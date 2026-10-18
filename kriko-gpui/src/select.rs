//! Selectable rich text.
//!
//! GPUI 0.2 has no selectable static text: an input owns the selection, and a
//! `div().child(string)` is a picture of words. An answer on the Chat screen is
//! the one place a reader most wants to take words out of the app — a part
//! number, a viscosity, a quotation — and it was the one place that could not
//! be selected.
//!
//! This element draws a run of styled pieces on a canvas, wraps them into
//! lines itself, and keeps a selection over the whole run. A drag selects
//! across pieces and across lines; the selection is painted behind the text;
//! Ctrl+C copies it. Nothing here knows about markdown: the caller hands it
//! pieces, and it draws them.
//!
//! The layout is a greedy wrap over *fragments*. A fragment is one piece's
//! shaped text, so it carries one face and one colour. A line is a run of
//! fragments laid end to end; it breaks where the next fragment would pass the
//! width, or inside a fragment at the last space that still fits.

use std::ops::Range;

use gpui::{
    div, fill, font, point, prelude::*, px, size, App, Bounds, ContentMask, CursorStyle, Div,
    ElementId, FontStyle, FontWeight, GlobalElementId, Hitbox, HitboxBehavior, InspectorElementId,
    IntoElement, LayoutId, MouseButton, MouseDownEvent, MouseMoveEvent, MouseUpEvent, Pixels, Point,
    SharedString, Stateful, Style, TextAlign, TextRun, Window, WrappedLine,
};

use crate::theme::*;

/// One styled piece of the run.
#[derive(Clone, Debug, PartialEq)]
pub struct Piece {
    pub text: String,
    pub colour: u32,
    pub size: f32,
    pub weight: FontWeight,
    pub italic: bool,
    pub family: &'static str,
    /// The address this piece opens, if it is a link. Empty otherwise.
    pub url: String,
}

impl Piece {
    pub fn new(text: impl Into<String>, colour: u32, size: f32) -> Piece {
        Piece {
            text: text.into(),
            colour,
            size,
            weight: FontWeight::NORMAL,
            italic: false,
            family: SANS,
            url: String::new(),
        }
    }

    pub fn bold(mut self) -> Piece {
        self.weight = FontWeight::SEMIBOLD;
        self
    }

    pub fn weight(mut self, weight: FontWeight) -> Piece {
        self.weight = weight;
        self
    }

    pub fn italic(mut self) -> Piece {
        self.italic = true;
        self
    }

    pub fn family(mut self, family: &'static str) -> Piece {
        self.family = family;
        self
    }


    pub fn link(mut self, url: impl Into<String>) -> Piece {
        self.url = url.into();
        self
    }


}

/// A piece's shaped text, laid at a place on a line.
struct Fragment {
    layout: WrappedLine,
    /// Where this fragment's first character sits in the whole run.
    offset: usize,
    /// The x the fragment starts at, from the line's left edge.
    x: Pixels,
    url: String,
}

/// One laid-out line.
struct Line {
    fragments: Vec<Fragment>,
    top: Pixels,
    height: Pixels,
}

impl Line {
    /// The character index nearest an x on this line.
    fn index_at(&self, x: Pixels) -> usize {
        let mut best: Option<(Pixels, usize)> = None;
        for fragment in &self.fragments {
            let local = (x - fragment.x).max(px(0.0));
            let glyphs = &fragment.layout.unwrapped_layout;
            let byte = glyphs.closest_index_for_x(local);
            let at = fragment.offset
                + fragment.layout.text[..byte.min(fragment.layout.text.len())]
                    .chars()
                    .count();
            let anchor = fragment.x + glyphs.x_for_index(byte);
            let distance = (x - anchor).abs();
            if best.map_or(true, |(d, _)| distance < d) {
                best = Some((distance, at));
            }
        }
        best.map(|(_, at)| at).unwrap_or(0)
    }


}

/// The one selection the transcript holds.
///
/// One place rather than one per paragraph: a drag that starts in a bullet and
/// ends in the paragraph under it is a selection, not two. `run` names the
/// element the range belongs to, so only that element paints the highlight.
#[derive(Default)]
pub struct Selection {
    /// The element the range belongs to, as its id's own words.
    pub run: String,
    pub anchor: usize,
    pub head: usize,
    pub dragging: bool,
    /// The words themselves, written when the drag ends.
    ///
    /// The range is what the highlight needs and it is deliberately tiny: it
    /// is written on every mouse move and read on every paint. But a copy
    /// happens later, from the window's key handler, where no run is being
    /// drawn and there is nothing to ask. So the run resolves its own range to
    /// text once, at the moment the reader lets go, and leaves the answer here
    /// for Ctrl+C to take.
    pub text: String,
}

impl Selection {
    pub fn range(&self) -> Range<usize> {
        self.anchor.min(self.head)..self.anchor.max(self.head)
    }


}

/// What the element keeps between frames: the laid-out lines and the run's own
/// text, so a hit test needs no second pass over the pieces. Public because the
/// caller owns one per run; the fields are this module's own.
#[derive(Default)]
pub struct State {
    lines: Vec<Line>,
    bounds: Option<Bounds<Pixels>>,
    text: String,
}

impl State {
    /// The character index nearest a point inside this element. A point inside
    /// a line always beats a point above or below every line.
    fn index_at(&self, position: Point<Pixels>) -> usize {
        let Some(bounds) = self.bounds else { return 0 };
        let y = position.y - bounds.top();
        let x = position.x - bounds.left();
        let mut best: Option<(Pixels, usize)> = None;
        for line in &self.lines {
            let outside = if y < line.top {
                line.top - y
            } else if y > line.top + line.height {
                y - (line.top + line.height)
            } else {
                px(-1.0)
            };
            let at = line.index_at(x);
            if best.map_or(true, |(d, _)| outside < d) {
                best = Some((outside, at));
            }
        }
        best.map(|(_, at)| at)
            .unwrap_or_else(|| self.text.chars().count())
    }

    /// The address of the link under a point, or "" when the point is not on
    /// one. A link is a target, not a word: a press on it opens the page, and
    /// only a press beside it starts a selection.
    fn url_at(&self, position: Point<Pixels>) -> String {
        let Some(bounds) = self.bounds else { return String::new() };
        let y = position.y - bounds.top();
        let x = position.x - bounds.left();
        for line in &self.lines {
            if y < line.top || y > line.top + line.height {
                continue;
            }
            for fragment in &line.fragments {
                if fragment.url.is_empty() {
                    continue;
                }
                if x >= fragment.x && x <= fragment.x + fragment.layout.width() {
                    return fragment.url.clone();
                }
            }
        }
        String::new()
    }

    /// The selected characters of this run, ready for the clipboard.
    ///
    /// The range is in characters and a Rust string is indexed in bytes, so
    /// the two are not the same number the moment an answer holds a Turkish
    /// dotted capital or an emoji — which is the ordinary case here, not the
    /// exotic one. Slicing on a character index would panic on a byte
    /// boundary; this converts first.
    pub fn selected(&self, range: &Range<usize>) -> String {
        if range.is_empty() {
            return String::new();
        }
        let bytes = byte_range(&self.text, range.clone());
        self.text[bytes].to_string()
    }
}

/// A character range as a byte range, clamped to the string's boundaries.
///
/// A range that names one past the end of the text is normal rather than a
/// bug: a hit test on the trailing edge of a line reports the index after its
/// last character, and that is a caret position a reader can legitimately
/// select to.
fn byte_range(text: &str, chars: Range<usize>) -> Range<usize> {
    let total = text.chars().count();
    let start_at = chars.start.min(total);
    let end_at = chars.end.min(total);
    let mut start = text.len();
    let mut end = text.len();
    for (count, (byte, _)) in text.char_indices().enumerate() {
        if count == start_at {
            start = byte;
        }
        if count == end_at {
            end = byte;
            break;
        }
    }
    if end_at >= total {
        end = text.len();
    }
    start.min(text.len())..end.max(start)
}

/// One run of styled text that a reader can select and copy.
///
/// The element owns an [`Entity<State>`] rather than its own GPUI element
/// state. That is deliberate: a hit test during a mouse event has to read the
/// laid-out lines, and a mouse event is not a layout pass, so there is no
/// `with_element_state` to reach through. One entity, written at prepaint and
/// read at paint and at the event, is the whole mechanism.
pub struct Selectable {
    id: ElementId,
    pieces: Vec<Piece>,
    leading: f32,
    width: Option<f32>,
    selection: gpui::Entity<Selection>,
    layout: gpui::Entity<State>,
    /// The lines `request_layout` measured, handed to `prepaint` so the run is
    /// shaped once per frame rather than twice.
    cache: std::rc::Rc<std::cell::RefCell<Option<Vec<Line>>>>,
}

impl Selectable {
    /// A run, with its own layout state. The caller keeps the selection; this
    /// makes the layout entity itself, so a screen writes one call per run.
    pub fn new(
        id: impl Into<ElementId>,
        pieces: Vec<Piece>,
        leading: f32,
        selection: gpui::Entity<Selection>,
        cx: &mut App,
    ) -> Selectable {
        Selectable {
            id: id.into(),
            pieces,
            leading,
            width: None,
            selection,
            layout: cx.new(|_| State::default()),
            cache: std::rc::Rc::new(std::cell::RefCell::new(None)),
        }
    }

    /// The run as one string, in reading order.
    fn text(&self) -> String {
        self.pieces.iter().map(|p| p.text.as_str()).collect()
    }

}

/// The face one piece is shaped with.
fn run_for(piece: &Piece) -> TextRun {
    let mut face = font(piece.family);
    face.weight = piece.weight;
    face.style = if piece.italic { FontStyle::Italic } else { FontStyle::Normal };
    TextRun {
        len: piece.text.len(),
        font: face,
        color: paint(piece.colour).into(),
        background_color: None,
        underline: None,
        strikethrough: None,
    }
}

/// Shape one piece's text, unwrapped. The wrap is this module's own, so a
/// break can fall inside a piece and still be one line here.
fn shape(text: &str, piece: &Piece, window: &mut Window) -> Option<WrappedLine> {
    if text.is_empty() {
        return None;
    }
    let run = TextRun { len: text.len(), ..run_for(piece) };
    window
        .text_system()
        .shape_text(SharedString::from(text.to_string()), px(piece.size), &[run], None, None)
        .ok()
        .and_then(|mut lines| lines.pop())
}

/// Where to break a piece's text so its head fits in `room`: the last space
/// whose left part fits. `None` when no space fits, so an unbreakable word
/// overflows the line rather than being cut.
fn split(text: &str, piece: &Piece, room: Pixels, window: &mut Window) -> Option<(String, String)> {
    let mut best: Option<usize> = None;
    for (byte, c) in text.char_indices() {
        if c != ' ' || byte == 0 {
            continue;
        }
        let head = &text[..byte];
        let width = shape(head, piece, window).map(|l| l.width())?;
        if width <= room {
            best = Some(byte);
        } else {
            break;
        }
    }
    let byte = best?;
    Some((text[..byte].to_string(), text[byte..].trim_start_matches(' ').to_string()))
}

/// Lay pieces out inside `width`, greedily.
///
/// A free function rather than a method because `request_layout` measures the
/// run inside a `'static` closure, where `&self` cannot be borrowed.
fn measure(pieces: &[Piece], width: Pixels, leading: f32, window: &mut Window) -> Vec<Line> {
    let leading = px(leading);
    let mut lines: Vec<Line> = Vec::new();
    let mut current: Vec<Fragment> = Vec::new();
    let mut used = px(0.0);
    let mut offset = 0usize;

    for piece in pieces {
        if piece.text.is_empty() {
            continue;
        }
        let Some(shaped) = shape(&piece.text, piece, window) else {
            continue;
        };
        let mut text = shaped.text.to_string();
        let mut line_offset = offset;
        offset += text.chars().count();

        loop {
            if current.is_empty() {
                break;
            }
            let room = width - used;
            if room <= px(0.0) {
                lines.push(finish(std::mem::take(&mut current), leading));
                used = px(0.0);
                continue;
            }
            let Some(shaped_now) = shape(&text, piece, window) else {
                break;
            };
            if shaped_now.width() <= room {
                break;
            }
            let Some((head, tail)) = split(&text, piece, room, window) else {
                break;
            };
            let Some(head_line) = shape(&head, piece, window) else {
                break;
            };
            current.push(Fragment {
                layout: head_line,
                offset: line_offset,
                x: used,
                url: piece.url.clone(),
            });
            lines.push(finish(std::mem::take(&mut current), leading));
            used = px(0.0);
            line_offset += head.chars().count();
            text = tail;
        }

        let Some(last) = shape(&text, piece, window) else {
            continue;
        };
        if used + last.width() > width && !current.is_empty() {
            lines.push(finish(std::mem::take(&mut current), leading));
            used = px(0.0);
        }
        let at = used;
        used += last.width();
        current.push(Fragment {
            layout: last,
            offset: line_offset,
            x: at,
            url: piece.url.clone(),
        });
    }
    if !current.is_empty() {
        lines.push(finish(current, leading));
    }
    lines
}

/// The width a laid-out line actually occupies.
fn line_width(line: &Line) -> Pixels {
    line.fragments
        .iter()
        .map(|f| f.x + f.layout.width())
        .fold(px(0.0), |a, b| if a > b { a } else { b })
}

fn finish(fragments: Vec<Fragment>, leading: Pixels) -> Line {
    let height = fragments
        .iter()
        .map(|f| f.layout.size(leading).height)
        .fold(leading, |a, b| if a > b { a } else { b });
    Line { fragments, top: px(0.0), height }
}

impl IntoElement for Selectable {
    type Element = Self;
    fn into_element(self) -> Self::Element {
        self
    }
}

impl gpui::Element for Selectable {
    type RequestLayoutState = ();
    type PrepaintState = Option<Hitbox>;

    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }

    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }

    /// The run's height is *measured*, not declared.
    ///
    /// This element draws on a canvas, so nothing else in the tree knows how
    /// tall it is. Declaring `height: relative(1.0)` — which is what the first
    /// version did — asks the parent for the whole of its own height, and a
    /// column with no fixed height answers zero: every answer on the Chat
    /// screen laid out at no height at all and painted nothing. `request_
    /// measured_layout` is the toolkit's own door for exactly this: it hands
    /// back the space available, so the text can be shaped at the width it
    /// will actually be drawn at and the result reported as the element's
    /// size.
    fn request_layout(
        &mut self,
        _id: Option<&GlobalElementId>,
        _inspector: Option<&InspectorElementId>,
        window: &mut Window,
        cx: &mut App,
    ) -> (LayoutId, Self::RequestLayoutState) {
        let pieces = self.pieces.clone();
        let leading = self.leading;
        let fixed = self.width;
        let cache = self.cache.clone();
        let layout_id = window.request_measured_layout(Style::default(), move |known, available, window, _cx| {
            let width = match fixed {
                Some(w) => px(w),
                None => known
                    .width
                    .or(match available.width {
                        gpui::AvailableSpace::Definite(w) => Some(w),
                        _ => None,
                    })
                    .unwrap_or(px(600.0)),
            }
            .max(px(20.0));
            let lines = measure(&pieces, width, leading, window);
            let height = lines.iter().fold(px(0.0), |sum, line| sum + line.height);
            *cache.borrow_mut() = Some(lines);
            gpui::size(width, height)
        });
        (layout_id, ())
    }

    fn prepaint(
        &mut self,
        _id: Option<&GlobalElementId>,
        _inspector: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _child: &mut Self::RequestLayoutState,
        window: &mut Window,
        cx: &mut App,
    ) -> Self::PrepaintState {
        let width = bounds.size.width.max(px(20.0));
        // The measured pass shaped at the width the layout was given, which is
        // the width it is drawn at. Re-shape only when they differ, which is
        // the case where the parent had no definite width to offer.
        let mut lines = match self.cache.borrow_mut().take() {
            Some(lines) if lines.iter().fold(px(0.0), |w, l| w.max(line_width(l))).eq(&width) => lines,
            _ => measure(&self.pieces, width, self.leading, window),
        };
        let mut top = px(0.0);
        for line in lines.iter_mut() {
            line.top = top;
            top += line.height;
        }
        let text = self.text();
        self.layout.update(cx, |state, _| {
            state.lines = lines;
            state.text = text;
            state.bounds = Some(bounds);
        });
        Some(window.insert_hitbox(bounds, HitboxBehavior::Normal))
    }

    fn paint(
        &mut self,
        _id: Option<&GlobalElementId>,
        _inspector: Option<&InspectorElementId>,
        bounds: Bounds<Pixels>,
        _child: &mut Self::RequestLayoutState,
        hitbox: &mut Self::PrepaintState,
        window: &mut Window,
        cx: &mut App,
    ) {
        let run = self.id.to_string();
        let selected = self.selection.read(cx).range();
        let highlighted = self.selection.read(cx).run == run && !selected.is_empty();
        let lines = std::mem::take(&mut self.layout.update(cx, |state, _| std::mem::take(&mut state.lines)));

        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            for line in lines.iter() {
                let origin = point(bounds.left(), bounds.top() + line.top);
                if highlighted {
                    paint_selection(line, origin, &selected, bounds, window);
                }
                for fragment in &line.fragments {
                    let at = point(origin.x + fragment.x, origin.y);
                    let _ =
                        fragment
                            .layout
                            .paint(at, line.height, TextAlign::Left, None, window, cx);
                    if !fragment.url.is_empty() {
                        // A link is underlined by a rule under its own
                        // fragment: the shaped run carries no underline here.
                        let y = origin.y + line.height - px(2.0);
                        window.paint_quad(fill(
                            Bounds::new(point(at.x, y), size(fragment.layout.width(), px(1.0))),
                            paint_a(BRAND_BRIGHT),
                        ));
                    }
                }
            }
        });

        // Put the lines back: the next event's hit test reads them.
        self.layout.update(cx, |state, _| state.lines = lines);

        if let Some(hitbox) = hitbox.as_ref() {
            window.set_cursor_style(CursorStyle::IBeam, hitbox);
        }
    }
}

/// The highlight behind one line's selected characters.
fn paint_selection(
    line: &Line,
    origin: Point<Pixels>,
    selected: &Range<usize>,
    bounds: Bounds<Pixels>,
    window: &mut Window,
) {
    for fragment in &line.fragments {
        for (byte, ch) in fragment.layout.text.char_indices() {
            let index = fragment.offset + fragment.layout.text[..byte].chars().count();
            if index < selected.start || index >= selected.end {
                continue;
            }
            let Some(start) = fragment.layout.position_for_index(byte, line.height) else {
                continue;
            };
            let end = fragment
                .layout
                .position_for_index(byte + ch.len_utf8(), line.height)
                .unwrap_or(start + point(px(7.0), px(0.0)));
            let width = if end.y == start.y {
                (end.x - start.x).max(px(2.0))
            } else {
                (bounds.size.width - fragment.x - start.x).max(px(2.0))
            };
            window.paint_quad(fill(
                Bounds::new(
                    point(origin.x + fragment.x + start.x, origin.y),
                    size(width, line.height),
                ),
                paint_a(0x86a3ff4d),
            ));
        }
    }
}

impl Selectable {
    /// Wrap the run in a pointer surface: a press starts a selection, a drag
    /// extends it, and a release ends it. The copy itself is bound to Ctrl+C
    /// on the window, because the transcript is not a focusable field.
    pub fn interactive(self, selection: gpui::Entity<Selection>) -> Stateful<Div> {
        let run = self.id.to_string();
        let layout_down = self.layout.clone();
        let layout_move = self.layout.clone();
        let layout_up = self.layout.clone();
        let down = selection.clone();
        let down_run = run.clone();
        let moved = selection.clone();
        let moved_run = run.clone();
        let up = selection.clone();
        div()
            .id(ElementId::Name(SharedString::from(format!("sel-{run}"))))
            .w_full()
            .min_w(px(0.0))
            .child(self)
            .on_mouse_down(MouseButton::Left, move |event: &MouseDownEvent, _window, cx| {
                let url = layout_down.read(cx).url_at(event.position);
                if !url.is_empty() {
                    cx.open_url(&url);
                    return;
                }
                let at = layout_down.read(cx).index_at(event.position);
                down.update(cx, |sel, cx| {
                    sel.run = down_run.clone();
                    sel.anchor = at;
                    sel.head = at;
                    sel.text.clear();
                    sel.dragging = true;
                    cx.notify();
                });
            })
            .on_mouse_move(move |event: &MouseMoveEvent, _window, cx| {
                if !moved.read(cx).dragging || moved.read(cx).run != moved_run {
                    return;
                }
                let at = layout_move.read(cx).index_at(event.position);
                moved.update(cx, |sel, cx| {
                    sel.head = at;
                    cx.notify();
                });
            })
            .on_mouse_up(MouseButton::Left, move |_: &MouseUpEvent, _window, cx| {
                let range = up.read(cx).range();
                let words = layout_up.read(cx).selected(&range);
                up.update(cx, |sel, cx| {
                    sel.dragging = false;
                    sel.text = words;
                    cx.notify();
                });
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn state(text: &str) -> State {
        State { lines: Vec::new(), bounds: None, text: text.to_string() }
    }

    #[test]
    fn a_selection_reports_its_range_in_order_whichever_way_the_drag_went() {
        // A drag to the left reports a head below its anchor, and the range is
        // still the words between them rather than nothing.
        let mut selection = Selection::default();
        selection.anchor = 9;
        selection.head = 3;
        assert_eq!(selection.range(), 3..9);
        selection.anchor = 3;
        selection.head = 9;
        assert_eq!(selection.range(), 3..9);
        // A press that never moved is an empty range, which is what stops a
        // stray click from painting a highlight or filling the clipboard.
        selection.head = 3;
        assert!(selection.range().is_empty());
    }

    #[test]
    fn a_selected_run_comes_back_as_the_words_the_reader_dragged_over() {
        let run = state("the oil filter is here");
        assert_eq!(run.selected(&(4..14)), "oil filter");
    }

    #[test]
    fn a_selection_over_a_turkish_letter_or_an_emoji_does_not_split_a_character() {
        // The range is in characters and a Rust string is indexed in bytes, so
        // these two are not the same number the moment an answer holds a
        // dotted capital or an emoji — which is the ordinary case here. A
        // slice on a character index would panic on a byte boundary.
        let run = state("Şımart 🤖 K9K");
        assert_eq!(run.selected(&(0..6)), "Şımart");
        assert_eq!(run.selected(&(7..8)), "🤖");
        assert_eq!(run.selected(&(9..12)), "K9K");
    }

    #[test]
    fn a_range_that_names_past_the_end_is_clamped_rather_than_panicking() {
        // A hit test on the trailing edge of a line reports the index after
        // its last character, and that is a caret position a reader can
        // legitimately select to.
        let run = state("short");
        assert_eq!(run.selected(&(2..99)), "ort");
        assert_eq!(run.selected(&(99..120)), "");
        assert_eq!(run.selected(&(0..0)), "");
    }

    #[test]
    fn a_piece_carries_the_link_it_was_given_and_nothing_when_it_was_not() {
        let link = Piece::new("the manual", 0xffffff, 14.0).link("https://example.com/a.pdf");
        assert_eq!(link.url, "https://example.com/a.pdf");
        assert!(Piece::new("plain", 0xffffff, 14.0).url.is_empty());
    }

    /// The bug this element shipped with, pinned so it cannot come back.
    ///
    /// The first version declared its own height as `relative(1.0)`, which asks
    /// the parent for the whole of the parent's height — and a column with no
    /// fixed height answers zero. Every answer on the Chat screen laid out at
    /// no height at all and painted nothing, while the compile, the unit tests
    /// and every gate stayed green: a canvas draws itself, so nothing else in
    /// the tree knows how tall it is.
    ///
    /// There is no way to assert the toolkit's measured-layout call from here,
    /// so this pins the two facts that make the mistake detectable by reading:
    /// the element measures through `request_measured_layout`, and the height
    /// it reports is the sum of the lines it laid out rather than a fraction of
    /// its parent.
    #[test]
    fn the_element_measures_its_own_height_rather_than_asking_the_parent_for_it() {
        let source = include_str!("select.rs");
        let request = source
            .split("fn request_layout")
            .nth(1)
            .expect("request_layout is still the door the element measures through");
        let body = request.split("fn prepaint").next().unwrap_or(request);
        assert!(
            body.contains("request_measured_layout"),
            "the run must measure itself: a declared height of relative(1.0) \
             resolves to zero in a column that has no fixed height, and the \
             whole answer paints nothing"
        );
        assert!(
            !body.contains("relative(1.0)"),
            "requesting the parent's whole height is the defect this test exists for"
        );
        // And the measured height is the lines' own, summed.
        assert!(
            body.contains("sum") || body.contains("height"),
            "the measured height must come from the laid-out lines"
        );
    }
}
