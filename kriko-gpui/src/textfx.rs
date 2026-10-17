//! Text motion: words that arrive, and a status line that scrolls like a
//! cylinder. Both are one-shot and bounded; both rest when motion is off.

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::time::Duration;

use gpui::{
    div, prelude::*, px, Animation, AnimationExt, AnyElement, ElementId, SharedString,
};

use crate::theme::*;

/// One line's height in the cylinder windows.
const LINE_H: f32 = 18.0;

/// How long one word's rise takes before the reader's motion profile scales it.
const WORD_MS: u64 = 340;

/// A stable key for text that must replay when it changes: the same words in
/// the same place keep one key, new words remount and play once.
fn text_key(text: &str) -> u64 {
    let mut hasher = DefaultHasher::new();
    text.hash(&mut hasher);
    hasher.finish()
}

/// The text appears word by word, each word rising a few pixels as it lands.
/// The whole sentence is laid out from the first frame, so the words hold the
/// places a still line would; the stagger is a fraction of one short
/// animation, so a long sentence still settles in well under a second. `id`
/// and the text make the key: new text replays once, the same text does not.
/// Under Reduce motion it is the finished line, still.
pub fn words_reveal(text: &str, id: &str, motion: bool) -> gpui::AnyElement {
    let words: Vec<&str> = text.split_whitespace().collect();
    if words.is_empty() {
        return div().into_any_element();
    }
    let key = text_key(text);
    let count = words.len();
    let mut line = div()
        .flex()
        .flex_wrap()
        .items_center()
        .gap(px(4.0))
        .min_w(px(0.0));
    for (index, word) in words.iter().enumerate() {
        // The style rides on every word, so the line reads the same as the
        // static text it settles into whatever the parent inherits.
        let span = div()
            .font_family(SANS)
            .text_size(px(14.0))
            .line_height(px(20.0))
            // An answer is primary text. It was MUTED, which read as a
            // description of an answer rather than the answer.
            .text_color(paint(INK))
            .child(word.to_string());
        let span: AnyElement = if motion {
            // The last word starts at the midpoint of one animation, so the
            // whole reveal is a single bounded beat however long the sentence.
            let delay = 0.5 * index as f32 / (count.max(2) - 1) as f32;
            span.with_animation(
                ElementId::Name(SharedString::from(format!("{id}-word-{key}-{index}"))),
                Animation::new(Duration::from_millis(tempo_ms(WORD_MS))).with_easing(|t| t),
                move |el, t| {
                    let u = ((t - delay) / (1.0 - delay).max(0.01)).clamp(0.0, 1.0);
                    let e = ease_mech(u);
                    el.opacity(u).relative().top(px((1.0 - e) * amp(6.0)))
                },
            )
            .into_any_element()
        } else {
            span.into_any_element()
        };
        line = line.child(span);
    }
    line.into_any_element()
}

/// One line inside the cylinder window: mono and dim, one row high, cut off
/// rather than wrapped so the window never changes size.
fn cylinder_line(text: &str) -> gpui::Div {
    div()
        .absolute()
        .top_0()
        .left_0()
        .w_full()
        .font_family(MONO)
        .text_size(px(12.0))
        .line_height(px(LINE_H))
        .text_color(paint(DIM))
        .whitespace_nowrap()
        .truncate()
        .child(text.to_string())
}

/// A fixed-height window over one line. When the line changes the old one
/// leaves upward while the new one rises from below, like a cylinder turning.
/// The state keeps the line it last showed, so a change replays once and the
/// same text never moves; the element requests frames only while a turn is in
/// flight, so an idle window draws nothing.
struct Cylinder {
    id: ElementId,
    line: String,
    motion: bool,
}

struct CylinderState {
    shown: String,
    prev: String,
    start: std::time::Instant,
}

impl gpui::IntoElement for Cylinder {
    type Element = Self;
    fn into_element(self) -> Self {
        self
    }
}

impl gpui::Element for Cylinder {
    type RequestLayoutState = AnyElement;
    type PrepaintState = ();
    fn id(&self) -> Option<ElementId> {
        Some(self.id.clone())
    }
    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> {
        None
    }
    fn request_layout(
        &mut self,
        id: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        window: &mut gpui::Window,
        cx: &mut gpui::App,
    ) -> (gpui::LayoutId, Self::RequestLayoutState) {
        window.with_element_state(id.unwrap(), |state: Option<CylinderState>, window| {
            let now = std::time::Instant::now();
            let mut state = state.unwrap_or_else(|| CylinderState {
                shown: self.line.clone(),
                prev: String::new(),
                start: now,
            });
            if state.shown != self.line {
                state.prev = std::mem::replace(&mut state.shown, self.line.clone());
                state.start = now;
            }
            let progress = (state.start.elapsed().as_secs_f32() / 0.30).clamp(0.0, 1.0);
            let turning = self.motion && !state.prev.is_empty() && progress < 1.0;
            if turning {
                window.request_animation_frame();
            }
            let mut window_box = div().relative().h(px(LINE_H)).w_full().overflow_hidden();
            if turning {
                let e = ease_mech(progress);
                window_box = window_box
                    .child(
                        cylinder_line(&state.prev)
                            .top(px(-LINE_H * e))
                            .opacity(1.0 - progress),
                    )
                    .child(
                        cylinder_line(&self.line)
                            .top(px(LINE_H * (1.0 - e)))
                            .opacity(progress),
                    );
            } else {
                if !self.motion {
                    state.prev.clear();
                }
                window_box = window_box.child(cylinder_line(&self.line));
            }
            let mut child = window_box.into_any_element();
            ((child.request_layout(window, cx), child), state)
        })
    }
    fn prepaint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: gpui::Bounds<gpui::Pixels>,
        child: &mut Self::RequestLayoutState,
        window: &mut gpui::Window,
        cx: &mut gpui::App,
    ) {
        child.prepaint(window, cx);
    }
    fn paint(
        &mut self,
        _: Option<&gpui::GlobalElementId>,
        _: Option<&gpui::InspectorElementId>,
        _: gpui::Bounds<gpui::Pixels>,
        child: &mut Self::RequestLayoutState,
        _: &mut (),
        window: &mut gpui::Window,
        cx: &mut gpui::App,
    ) {
        child.paint(window, cx);
    }
}

/// The run's current stage or status, as a cylinder window: a change slides
/// the old line up and the new one in from below, keyed on the text so a
/// change replays once and identical text is still. `id` names the window.
pub fn cylinder_status(id: &str, line: &str, motion: bool) -> gpui::AnyElement {
    Cylinder {
        id: ElementId::Name(SharedString::from(format!("{id}-cylinder"))),
        line: line.to_string(),
        motion,
    }
    .into_any_element()
}

/// A short, fixed-height trace of the newest lines. A new line slides the
/// block up by one row so the newest arrives from below, the same turn the
/// status window makes; the last few lines stay in view and it settles. Still
/// under Reduce motion.
#[allow(dead_code)] // a multi-line trace builder, kept for the next caller that needs one
pub fn cylinder_trace(id: &str, lines: &[String], motion: bool) -> gpui::AnyElement {
    const VISIBLE: usize = 3;
    if lines.is_empty() {
        return div().into_any_element();
    }
    let mut column = div().flex().flex_col().w_full();
    for line in &lines[lines.len().saturating_sub(VISIBLE)..] {
        column = column.child(
            div()
                .w_full()
                .font_family(MONO)
                .text_size(px(12.0))
                .line_height(px(LINE_H))
                .text_color(paint(DIM))
                .whitespace_nowrap()
                .truncate()
                .child(line.clone()),
        );
    }
    let column: AnyElement = if motion {
        let key = text_key(lines.last().map(String::as_str).unwrap_or_default());
        column
            .with_animation(
                ElementId::NamedInteger(SharedString::from(format!("{id}-trace")), key),
                Animation::new(Duration::from_millis(tempo_ms(320))).with_easing(|t| t),
                move |el, t| el.relative().top(px(LINE_H * (1.0 - ease_mech(t)))),
            )
            .into_any_element()
    } else {
        column.into_any_element()
    };
    div()
        .relative()
        .h(px(LINE_H * VISIBLE as f32))
        .w_full()
        .overflow_hidden()
        .child(column)
        .into_any_element()
}
