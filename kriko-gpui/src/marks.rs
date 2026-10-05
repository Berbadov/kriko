//! Agent and runtime marks, drawn in the app's own dot language, and the
//! motion a working agent's tile makes.
//!
//! A mark is a small LED matrix: each character of a row is one dot, `.` is
//! unlit and a digit `1`..`5` lights it in that slot of the mark's palette.
//! The brand colour survives, the drawing is ours: every tile reads as the
//! same hardware as the tags and meters around it.
//!
//! The tile's motion says what the agent is doing, one phase each, and each
//! phase moves differently so they can be told apart without reading:
//! thinking orbits, reading scans, writing types, waiting breathes.

use gpui::{
    div, point, prelude::*, px, rgb, Animation, AnimationExt, BoxShadow, Div, SharedString,
};

use crate::theme::*;

pub struct Mark {
    pub rows: &'static [&'static str],
    pub palette: &'static [u32],
}

// ---- the agents ----

pub const CLAUDE: Mark = Mark {
    rows: &[
        "....1....",
        ".1..1..1.",
        "..1.1.1..",
        "...111...",
        "111111111",
        "...111...",
        "..1.1.1..",
        ".1..1..1.",
        "....1....",
    ],
    palette: &[0xe0805e],
};

pub const CLAUDE_DESKTOP: Mark = Mark {
    rows: &[
        "222222222",
        "2.......2",
        "2.1.1.1.2",
        "2..111..2",
        "2.11111.2",
        "2..111..2",
        "2.1.1.1.2",
        "2.......2",
        "222222222",
    ],
    palette: &[0xe0805e, LED_DIM],
};

pub const OPENCODE: Mark = Mark {
    // The official mark (opencode, simple-icons): a tall block frame with
    // thick walls; the app icon fills the lower half of the opening grey.
    rows: &[
        "111111111",
        "111111111",
        "11.....11",
        "11.....11",
        "11.....11",
        "11.....11",
        "112222211",
        "112222211",
        "112222211",
        "111111111",
        "111111111",
    ],
    palette: &[0xf1ecec, 0x6f6c6c],
};

pub const ANTIGRAVITY: Mark = Mark {
    // The published curved arch and its colour bands, sampled to LEDs.
    rows: &[
        ".....2.....",
        "....122....",
        "...35222...",
        "...35552...",
        "..5444555..",
        "..4444455..",
        "..444..44..",
        ".444...444.",
        ".44.....44.",
        "44.......44",
        "4.........4",
    ],
    palette: &[0xfbbc04, 0xfc413d, 0x00b95c, 0x3186ff, 0x749bff],
};

/// One dot per block of the official mark (Mistral AI logo, 2025): a 7x5
/// grid, five bands from yellow to red, the feet stepping outward.
pub const MISTRAL: Mark = Mark {
    rows: &[
        ".1...1.",
        ".22.22.",
        ".33333.",
        ".4.4.4.",
        "555.555",
    ],
    palette: &[0xffd800, 0xffaf00, 0xff8205, 0xfa500f, 0xe10500],
};

pub const COPILOT: Mark = Mark {
    rows: &[
        ".111.111.",
        "1...1...1",
        "1...1...1",
        ".111.111.",
        ".1.....1.",
        "1..2.2..1",
        "1..2.2..1",
        "1.......1",
        ".1111111.",
    ],
    palette: &[INK, ICE],
};

pub const CURSOR: Mark = Mark {
    // Rasterised from the official mark (Cursor, 2025, simple-icons): the
    // cube seen corner-on, its top and left faces lit, the cursor's
    // arrowhead cut into the front as the darker face.
    rows: &[
        ".....1.....",
        "...11111...",
        ".111111111.",
        ".233333331.",
        ".222333331.",
        ".222233311.",
        ".222223311.",
        ".222223111.",
        ".222223111.",
        "...22211...",
        ".....2.....",
    ],
    palette: &[0xedecec, 0x9a9a9e, 0x4a4e60],
};

// ---- the local runtimes ----

/// Kriko's own runtime: the K in dots, in the brand blue.
pub const BUILTIN: Mark = Mark {
    rows: &[
        "11....11",
        "11...11.",
        "11..11..",
        "11111...",
        "11111...",
        "11..11..",
        "11...11.",
        "11....11",
    ],
    palette: &[BRAND_BRIGHT],
};

pub const OLLAMA: Mark = Mark {
    rows: &[
        ".1....1.",
        ".1....1.",
        ".111111.",
        "11....11",
        "1.2..2.1",
        "1..11..1",
        "1......1",
        ".111111.",
    ],
    palette: &[INK, ICE],
};

pub const LMSTUDIO: Mark = Mark {
    rows: &[
        "11111...",
        "........",
        ".2222222",
        "........",
        "111111..",
        "........",
        "..222222",
        "........",
    ],
    palette: &[0x8f7cff, ICE],
};

pub const LLAMACPP: Mark = Mark {
    rows: &[
        "1..1....",
        "1..1....",
        "1..1....",
        "1..1.222",
        "1..1.2..",
        "1..1.2..",
        "11.11222",
        "........",
    ],
    palette: &[INK, ICE],
};

pub const JAN: Mark = Mark {
    rows: &[
        "....11..",
        ".....1..",
        ".....1..",
        ".....1..",
        "1....1..",
        "1....1..",
        ".1111...",
        "........",
    ],
    palette: &[ICE],
};

/// What an agent is doing right now. Each one has its own motion.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    /// Connected, not on anything: the mark sits lit and still.
    Idle,
    /// Weighing an answer: a comet orbits the tile, light shimmers across.
    Thinking,
    /// Reading a page: a scan bar sweeps across the mark.
    Reading,
    /// Writing claims: the mark types itself in, dot by dot.
    Writing,
    /// Holding a question for you: the mark breathes, the corners blink.
    Waiting,
    /// Not found or not allowed: the mark unlit, its colours dimmed.
    Off,
}

impl Phase {
    pub fn label(self) -> &'static str {
        match self {
            Phase::Idle => "Idle",
            Phase::Thinking => "Thinking",
            Phase::Reading => "Reading",
            Phase::Writing => "Writing",
            Phase::Waiting => "Needs you",
            Phase::Off => "Off",
        }
    }
}

fn glow(color: u32, blur: f32) -> Vec<BoxShadow> {
    vec![BoxShadow {
        color: hsla(color),
        offset: point(px(0.0), px(0.0)),
        blur_radius: px(blur),
        spread_radius: px(0.0),
    }]
}

fn mark_dims(mark: &Mark) -> (usize, usize) {
    let h = mark.rows.len();
    let w = mark.rows.iter().map(|r| r.len()).max().unwrap_or(0);
    (w, h)
}

/// One lit dot's brightness at time `t` (0..1 through the cycle) for a phase.
/// `x`, `y` are the dot's position in the mark, 0..1 each; `order` is its
/// reading-order rank among the lit dots, 0..1.
fn level(phase: Phase, t: f32, x: f32, y: f32, order: f32) -> f32 {
    match phase {
        Phase::Thinking => {
            // a soft diagonal shimmer rolling across the mark
            let d = (x + y) * 0.5;
            let k = (t - d).rem_euclid(1.0);
            0.45 + 0.55 * (1.0 - (k * 3.0).min(1.0)).powf(1.5)
        }
        Phase::Reading => {
            // a bright vertical bar sweeping left to right, dim behind it
            let bar = t * 1.3 - 0.15;
            if (x - bar).abs() < 0.12 {
                1.0
            } else {
                0.35
            }
        }
        Phase::Writing => {
            // typed in, reading order, then held, then cleared
            let fill = (t / 0.75).min(1.0);
            if order <= fill {
                1.0
            } else {
                0.12
            }
        }
        Phase::Waiting => {
            // a slow breath, the whole mark together
            let s = (t * std::f32::consts::TAU).sin();
            0.55 + 0.45 * (0.5 + 0.5 * s)
        }
        Phase::Idle | Phase::Off => 1.0,
    }
}

fn cycle_ms(phase: Phase) -> u64 {
    match phase {
        Phase::Thinking => 1800,
        Phase::Reading => 1400,
        Phase::Writing => 2600,
        Phase::Waiting => 2200,
        Phase::Idle | Phase::Off => 1000,
    }
}

/// The mark as an LED matrix, animated for its phase.
pub fn mark_matrix(id: &str, mark: &Mark, phase: Phase, dot: f32, gap: f32, motion: bool) -> Div {
    mark_dots(id, mark, phase, dot, gap, motion, true)
}

/// The mark's dots; `unlit` draws the dark dots between them, as a tile's
/// panel does, or leaves them out so the mark stands on its own.
fn mark_dots(
    id: &str,
    mark: &Mark,
    phase: Phase,
    dot: f32,
    gap: f32,
    motion: bool,
    unlit: bool,
) -> Div {
    let (w, h) = mark_dims(mark);
    let lit_total = mark
        .rows
        .iter()
        .flat_map(|r| r.chars())
        .filter(|c| c.is_ascii_digit())
        .count()
        .max(1);
    let animated = motion && !matches!(phase, Phase::Idle | Phase::Off);
    let mut grid = div().flex().flex_col().gap(px(gap)).flex_none();
    let mut rank = 0usize;
    for (ry, row) in mark.rows.iter().enumerate() {
        let mut line = div().flex().gap(px(gap));
        for (rx, ch) in row.chars().enumerate() {
            let base = div().size(px(dot)).rounded(px((dot * 0.35).round().max(1.0)));
            let slot = ch.to_digit(10).map(|d| d as usize);
            let cell: gpui::AnyElement = match slot {
                Some(s) if s >= 1 => {
                    // Off keeps the brand colours, dimmed and unlit, so a
                    // missing agent is still recognisable by its mark
                    let color = mark.palette[(s - 1).min(mark.palette.len() - 1)];
                    let lit = base.bg(rgb(color)).shadow(if phase == Phase::Off {
                        Vec::new()
                    } else {
                        glow(color, dot * 1.6)
                    });
                    let x = rx as f32 / (w.max(2) - 1) as f32;
                    let y = ry as f32 / (h.max(2) - 1) as f32;
                    let order = rank as f32 / lit_total as f32;
                    rank += 1;
                    if animated {
                        lit.with_animation(
                            gpui::ElementId::Name(SharedString::from(format!(
                                "{id}-{}-{rx}-{ry}",
                                phase.label()
                            ))),
                            Animation::new(std::time::Duration::from_millis(cycle_ms(phase)))
                                .repeat()
                                .with_easing(|t| t),
                            move |el, t| el.opacity(level(phase, t, x, y, order)),
                        )
                        .into_any_element()
                    } else {
                        lit.opacity(if phase == Phase::Off { 0.32 } else { 1.0 })
                            .into_any_element()
                    }
                }
                _ if unlit => base.bg(rgb(LED_OFF)).opacity(0.55).into_any_element(),
                _ => base.into_any_element(),
            };
            line = line.child(cell);
        }
        grid = grid.child(line);
    }
    grid
}

/// The ring of dots inside a tile's edge: a comet for Thinking, blinking
/// corners for Waiting, nothing otherwise.
fn tile_ring(id: &str, size: f32, phase: Phase, motion: bool) -> Option<gpui::AnyElement> {
    if !motion || !matches!(phase, Phase::Thinking | Phase::Waiting) {
        return None;
    }
    let inset = 3.0;
    let dot = (size / 20.0).round().max(2.0);
    let span = size - inset * 2.0 - dot;
    let per_side = 7usize;
    let slots = per_side * 4;
    let mut ring = div().absolute().top_0().left_0().size(px(size));
    for i in 0..slots {
        let side = i / per_side;
        let k = (i % per_side) as f32 / per_side as f32;
        // clockwise from the top-left corner
        let (x, y) = match side {
            0 => (k * span, 0.0),
            1 => (span, k * span),
            2 => (span - k * span, span),
            _ => (0.0, span - k * span),
        };
        let (x, y) = (x.round(), y.round());
        let corner = i % per_side == 0;
        if phase == Phase::Waiting && !corner {
            continue;
        }
        let color = if phase == Phase::Waiting { 0xffffff } else { ICE };
        let pos = i as f32 / slots as f32;
        let d = div()
            .absolute()
            .left(px(inset + x))
            .top(px(inset + y))
            .size(px(dot))
            .rounded(px(dot * 0.5))
            .bg(rgb(color))
            .shadow(glow(color, dot * 2.5));
        ring = ring.child(
            d.with_animation(
                gpui::ElementId::Name(SharedString::from(format!(
                    "{id}-ring-{}-{i}",
                    phase.label()
                ))),
                Animation::new(std::time::Duration::from_millis(if phase == Phase::Waiting {
                    1100
                } else {
                    1500
                }))
                .repeat()
                .with_easing(|t| t),
                move |el, t| {
                    if phase == Phase::Waiting {
                        el.opacity(if t < 0.5 { 1.0 } else { 0.0 })
                    } else {
                        // the comet's head at t, a fading tail behind it
                        let behind = (t - pos).rem_euclid(1.0);
                        let tail = 0.28;
                        el.opacity(if behind < tail {
                            (1.0 - behind / tail).powf(1.6)
                        } else {
                            0.0
                        })
                    }
                },
            ),
        );
    }
    Some(ring.into_any_element())
}

/// An agent's tile: a recessed well holding its mark, moving for its phase.
/// `size` is the tile's side; 40 in lanes and lists, larger on detail cards.
pub fn mark_tile(id: &str, mark: &Mark, phase: Phase, size: f32, motion: bool) -> Div {
    let (w, h) = mark_dims(mark);
    let cells = w.max(h) as f32;
    // Whole pixels only: a fractional dot or gap lands on the pixel grid
    // differently from its neighbour and the matrix reads as uneven. The
    // mark takes the largest whole dot that keeps it within the tile.
    let gap = if size >= 56.0 { 2.0 } else { 1.0 };
    let room = (size * 0.86).floor();
    let dot = ((room - gap * (cells - 1.0)) / cells).floor().max(1.0);
    let edge = match phase {
        Phase::Thinking | Phase::Reading | Phase::Writing => rgb(BRAND_LOW),
        Phase::Waiting => rgb(LED_DIM),
        _ => rgb(BEZEL_EDGE),
    };
    let mut tile = well()
        .relative()
        .size(px(size))
        .flex_none()
        .flex()
        .items_center()
        .justify_center()
        .border_color(edge)
        .child(mark_matrix(id, mark, phase, dot, gap, motion));
    if matches!(phase, Phase::Thinking | Phase::Reading | Phase::Writing) {
        tile = tile.shadow(glow(BRAND, 10.0));
    }
    if let Some(ring) = tile_ring(id, size, phase, motion) {
        tile = tile.child(ring);
    }
    tile
}

/// The mark on its own, no well and no unlit dots: for lanes, where a row of
/// boxed tiles read as a column of grey squares. It still moves for its
/// phase; a working phase lights a soft brand halo under it.
pub fn mark_glyph(id: &str, mark: &Mark, phase: Phase, size: f32, motion: bool) -> Div {
    let (w, h) = mark_dims(mark);
    let cells = w.max(h) as f32;
    let gap = 1.0;
    let dot = ((size - gap * (cells - 1.0)) / cells).floor().max(1.0);
    let mut holder = div()
        .relative()
        .size(px(size))
        .flex_none()
        .flex()
        .items_center()
        .justify_center();
    if matches!(phase, Phase::Thinking | Phase::Reading | Phase::Writing) {
        holder = holder.child(
            div()
                .absolute()
                .top(px(size * 0.2))
                .left(px(size * 0.2))
                .size(px(size * 0.6))
                .rounded(px(size))
                .bg(gpui::rgba(BRAND_WASH))
                .shadow(glow(BRAND, size * 0.6)),
        );
    }
    holder.child(mark_dots(id, mark, phase, dot, gap, motion, false))
}

/// The phase beside the same recessed LED matrix as the app's status tags.
/// Whole-pixel bulbs hold their positions while the phase moves their light.
pub fn phase_beat(id: &str, phase: Phase, motion: bool) -> Div {
    let rows: &'static [&'static str] = match phase {
        // Open book, a scan passing over the recorded page.
        Phase::Reading => &["11.11", "1.1.1", "1.1.1", "1.1.1", "11.11"],
        // Pencil, lit in sequence along the diagonal stroke.
        Phase::Writing => &["....1", "...11", "..11.", ".11..", "11..."],
        // A ring and centre light, gently shimmering while thinking.
        Phase::Thinking => &[".111.", "1...1", "1.1.1", "1...1", ".111."],
        Phase::Waiting => &["..1..", "..1..", "..1..", ".....", "..1.."],
        Phase::Idle => &[".....", ".....", "1.1.1", ".....", "....."],
        Phase::Off => &["1...1", ".1.1.", "..1..", ".1.1.", "1...1"],
    };
    let palette: &'static [u32] = match phase {
        Phase::Thinking | Phase::Reading | Phase::Writing => &[ICE],
        Phase::Waiting => &[INK],
        Phase::Idle => &[INK_2],
        Phase::Off => &[LED_DIM],
    };
    let glyph = Mark { rows, palette };
    let indicator = well()
        .size(px(25.0))
        .rounded(px(5.0))
        .flex_none()
        .flex()
        .items_center()
        .justify_center()
        .child(mark_matrix(id, &glyph, phase, 3.0, 1.0, motion));
    div()
        .flex()
        .items_center()
        .gap(px(6.0))
        .child(indicator)
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(palette[0]))
                .child(phase.label().to_uppercase()),
        )
}
