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
//! thinking orbits, searching radiates, reading scans, writing types, citing
//! drops a source in, waiting breathes.

use gpui::{
    div, point, prelude::*, px, Animation, AnimationExt, BoxShadow, Div, SharedString,
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

pub const CODEX: Mark = Mark {
    // Codex's app icon: the rounded cloud with a terminal prompt cut into it,
    // the `>` and the `_` in white on the blue-violet body.
    rows: &[
        "...11111...",
        ".111111111.",
        "11221111111",
        "11122111111",
        "11112211111",
        "11122111111",
        "11221122211",
        ".111111111.",
        "...11111...",
    ],
    palette: &[0x7b86ff, 0xffffff],
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

// no Local LLM runtime row draws it yet; kept with the other runtime marks
#[allow(dead_code)]
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
    /// Sifting sources: light radiates from the centre in rings.
    #[allow(dead_code)] // wired from the live run once its steps map to it
    Searching,
    /// Reading a page: a scan bar sweeps across the mark.
    Reading,
    /// Writing claims: the mark types itself in, dot by dot.
    Writing,
    /// Naming a source: a source dot drops in and settles with a bounce.
    #[allow(dead_code)] // wired from the live run once its steps map to it
    Citing,
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
            Phase::Searching => "Searching",
            Phase::Reading => "Reading",
            Phase::Writing => "Writing",
            Phase::Citing => "Citing",
            Phase::Waiting => "Needs you",
            Phase::Off => "Off",
        }
    }
}

fn glow(color: u32, blur: f32) -> Vec<BoxShadow> {
    vec![BoxShadow {
        color: paint(color).into(),
        offset: point(px(0.0), px(0.0)),
        blur_radius: px(blur),
        spread_radius: px(0.0),
    }]
}

/// Put one dot's look on its element: its light, its glow, and its nudge.
/// A dot's size never changes, so `dot` is the fixed pixel size that the
/// glow blur and the micro-offsets are measured against.
fn apply(el: Div, d: Dot, base: u32, dot: f32) -> Div {
    let mut el = el.opacity(d.opacity);
    if d.dx != 0.0 || d.dy != 0.0 {
        el = el.relative().left(px(d.dx * dot)).top(px(d.dy * dot));
    }
    if d.blur > 0.0 {
        el.shadow(glow(d.color.unwrap_or(base), dot * d.blur))
    } else {
        el.shadow(Vec::<BoxShadow>::new())
    }
}

fn mark_dims(mark: &Mark) -> (usize, usize) {
    let h = mark.rows.len();
    let w = mark.rows.iter().map(|r| r.len()).max().unwrap_or(0);
    (w, h)
}

/// How one lit dot looks at time `t`: its brightness, the glow around it and
/// any micro-offset from its slot. A dot's size is fixed by the layout, so the
/// motion is carried by light and a nudge, never by resizing the bulb.
#[derive(Clone, Copy)]
struct Dot {
    /// 0..1 alpha.
    opacity: f32,
    /// glow blur as a multiple of the dot's size (0 = no glow).
    blur: f32,
    /// the glow's colour token; `None` keeps the dot's own palette colour.
    color: Option<u32>,
    /// micro-offset from the slot, as a multiple of the dot's size.
    dx: f32,
    dy: f32,
}

impl Dot {
    /// A lit dot at rest, its own colour glowing softly.
    fn rest() -> Dot {
        Dot { opacity: 1.0, blur: 1.6, color: None, dx: 0.0, dy: 0.0 }
    }
}

const TAU: f32 = std::f32::consts::TAU;

/// A ball's fall: quick to land, then small bounces that die out.
fn ease_out_bounce(x: f32) -> f32 {
    let n = 7.5625;
    let d = 2.75;
    if x < 1.0 / d {
        n * x * x
    } else if x < 2.0 / d {
        let x = x - 1.5 / d;
        n * x * x + 0.75
    } else if x < 2.5 / d {
        let x = x - 2.25 / d;
        n * x * x + 0.9375
    } else {
        let x = x - 2.625 / d;
        n * x * x + 0.984375
    }
}

/// One lit dot's look at time `t` (0..1 through the cycle) for a phase.
/// `x`, `y` are the dot's position in the mark, 0..1 each; `order` is its
/// reading-order rank among the lit dots, 0..1; `step` is the spacing of that
/// order (`1 / lit dots`), which tells writing where its pen tip is.
fn level(phase: Phase, t: f32, x: f32, y: f32, order: f32, step: f32) -> Dot {
    match phase {
        Phase::Thinking => {
            // A comet orbits the mark: the dot on the orbit ring at angle `t`
            // is the head, and the dots the head has just swept are its tail.
            // A low brand breath runs under it, so the tile glows from within.
            let ang = t * TAU;
            let dx = x - 0.5;
            let dy = y - 0.5;
            let r = (dx * dx + dy * dy).sqrt();
            let behind = (ang - dy.atan2(dx)).rem_euclid(TAU);
            let head = (-behind * 1.5).exp();
            let ring = (-((r - 0.42) / 0.34).powi(2)).exp();
            let comet = head * ring;
            let breath = 0.5 + 0.5 * (t * TAU).sin();
            Dot {
                opacity: (0.17 + 0.10 * breath + 0.75 * comet).min(1.0),
                blur: 0.5 + 2.1 * comet,
                color: (comet > 0.55).then_some(BRAND),
                dx: 0.0,
                dy: 0.0,
            }
        }
        Phase::Searching => {
            // Light radiates from the centre in rings that travel outward.
            let dx = x - 0.5;
            let dy = y - 0.5;
            let r = (dx * dx + dy * dy).sqrt() / 0.707;
            let front = (r / 0.34 - t * 3.0).rem_euclid(1.0);
            let ring = (1.0 - (front * 2.0).min(1.0)).powi(2);
            let v = ring * (1.0 - 0.45 * r);
            Dot {
                opacity: (0.15 + 0.82 * v).min(1.0),
                blur: 0.5 + 2.3 * v,
                color: (v > 0.5).then_some(BRAND),
                dx: 0.0,
                dy: 0.0,
            }
        }
        Phase::Reading => {
            // An ICE scan beam sweeps left to right: a bright head with an
            // afterglow trailing behind it over the page it has already read.
            let bar = t * 1.3 - 0.15;
            let d = x - bar;
            let head = (-(d / 0.09).powi(2)).exp();
            let trail = if d < 0.0 { (d * 2.6).exp() } else { 0.0 };
            let v = head.max(trail * 0.85);
            Dot {
                opacity: (0.26 + 0.74 * v).min(1.0),
                blur: 0.5 + 2.2 * head + 0.9 * trail,
                color: if head > 0.5 {
                    Some(ICE)
                } else if trail > 0.4 {
                    Some(BRAND_BRIGHT)
                } else {
                    None
                },
                dx: 0.0,
                dy: 0.0,
            }
        }
        Phase::Writing => {
            // The mark types itself in reading order; the last dot written is
            // the pen tip, and it pulses and bobs like a caret while it holds.
            let fill = (t / 0.72).min(1.0);
            let gap = fill - order;
            if gap >= 0.0 && gap <= step {
                let pulse = 0.5 + 0.5 * (t * TAU * 3.0).sin();
                Dot {
                    opacity: 1.0,
                    blur: 0.7 + 1.6 * pulse,
                    color: Some(ICE),
                    dx: 0.0,
                    dy: 0.3 * pulse,
                }
            } else if gap > 0.0 {
                Dot { opacity: 0.9, blur: 0.6, color: None, dx: 0.0, dy: 0.0 }
            } else {
                Dot { opacity: 0.10, blur: 0.3, color: None, dx: 0.0, dy: 0.0 }
            }
        }
        Phase::Citing => {
            // A source dot drops in from above and settles with a small
            // bounce; the rest of the mark washes in behind the landing, then
            // fades out so the reset at the top of the loop is not a snap.
            let fall = ease_out_bounce((t / 0.62).min(1.0));
            let settle = ((t - 0.35) / 0.45).clamp(0.0, 1.0);
            let exit = ((t - 0.88) / 0.12).clamp(0.0, 1.0);
            if order <= 0.0 {
                Dot {
                    opacity: (1.0 - 0.75 * exit).min(1.0),
                    blur: 0.8 + 2.3 * (1.0 - fall),
                    color: Some(INK),
                    dx: 0.0,
                    dy: (fall - 1.0) * 3.0,
                }
            } else {
                Dot {
                    opacity: ((0.16 + 0.84 * settle) * (1.0 - 0.45 * exit)).min(1.0),
                    blur: 0.5 + 1.3 * settle,
                    color: None,
                    dx: 0.0,
                    dy: 0.0,
                }
            }
        }
        Phase::Waiting => {
            // A slow breath, the whole mark together; the caller stops it
            // after WAIT_BREATHS and leaves the mark resting lit.
            let breath = 0.5 + 0.5 * (t * TAU).sin();
            Dot {
                opacity: 0.55 + 0.45 * breath,
                blur: 1.1 + 0.7 * breath,
                color: None,
                dx: 0.0,
                dy: 0.0,
            }
        }
        Phase::Idle | Phase::Off => Dot::rest(),
    }
}

/// How many breaths a waiting mark takes before it rests lit.
const WAIT_BREATHS: u32 = 3;

fn cycle_ms(phase: Phase) -> u64 {
    match phase {
        Phase::Thinking => 1800,
        Phase::Searching => 1600,
        Phase::Reading => 1400,
        Phase::Writing => 2600,
        Phase::Citing => 2400,
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
    let step = 1.0 / lit_total as f32;
    let width = w as f32 * dot + w.saturating_sub(1) as f32 * gap;
    let height = h as f32 * dot + h.saturating_sub(1) as f32 * gap;
    let mut grid = div().w(px(width)).h(px(height)).flex().flex_col().gap(px(gap)).flex_none();
    let mut rank = 0usize;
    for (ry, row) in mark.rows.iter().enumerate() {
        let mut line = div().w(px(width)).h(px(dot)).flex_none().flex().gap(px(gap));
        for (rx, ch) in row.chars().enumerate() {
            let base = div().size(px(dot)).flex_none().rounded(px((dot * 0.35).round().max(1.0)));
            let slot = ch.to_digit(10).map(|d| d as usize);
            let cell: gpui::AnyElement = match slot {
                Some(s) if s >= 1 => {
                    // Off keeps the brand colours, dimmed and unlit, so a
                    // missing agent is still recognisable by its mark
                    let color = mark.palette[(s - 1).min(mark.palette.len() - 1)];
                    let lit = base.bg(paint(color)).shadow(if phase == Phase::Off {
                        Vec::new()
                    } else {
                        glow(color, dot * 1.6)
                    });
                    let x = rx as f32 / (w.max(2) - 1) as f32;
                    let y = ry as f32 / (h.max(2) - 1) as f32;
                    let order = rank as f32 / lit_total as f32;
                    rank += 1;
                    if animated && phase == Phase::Waiting {
                        // A question can wait for days, and a loop redraws the
                        // whole window every frame (#184): waiting breathes
                        // WAIT_BREATHS times when it starts, then rests lit.
                        lit.with_animation(
                            gpui::ElementId::Name(SharedString::from(format!(
                                "{id}-{}-{rx}-{ry}",
                                phase.label()
                            ))),
                            Animation::new(std::time::Duration::from_millis(
                                cycle_ms(phase) * WAIT_BREATHS as u64,
                            ))
                            .with_easing(|t| t),
                            move |el, t| {
                                if t >= 1.0 {
                                    el.opacity(1.0).shadow(glow(color, dot * 1.6))
                                } else {
                                    apply(
                                        el,
                                        level(
                                            phase,
                                            (t * WAIT_BREATHS as f32).fract(),
                                            x,
                                            y,
                                            order,
                                            step,
                                        ),
                                        color,
                                        dot,
                                    )
                                }
                            },
                        )
                        .into_any_element()
                    } else if animated {
                        lit.with_animation(
                            gpui::ElementId::Name(SharedString::from(format!(
                                "{id}-{}-{rx}-{ry}",
                                phase.label()
                            ))),
                            Animation::new(std::time::Duration::from_millis(cycle_ms(phase)))
                                .repeat()
                                .with_easing(|t| t),
                            move |el, t| apply(el, level(phase, t, x, y, order, step), color, dot),
                        )
                        .into_any_element()
                    } else {
                        lit.opacity(if phase == Phase::Off { 0.32 } else { 1.0 })
                            .into_any_element()
                    }
                }
                _ if unlit => base.bg(paint(LED_OFF)).opacity(0.55).into_any_element(),
                _ => base.into_any_element(),
            };
            line = line.child(cell);
        }
        grid = grid.child(line);
    }
    grid
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
        Phase::Thinking | Phase::Searching | Phase::Reading | Phase::Writing | Phase::Citing => {
            paint(BRAND_LOW)
        }
        Phase::Waiting => paint(LED_DIM),
        _ => paint(BEZEL_EDGE),
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
    if matches!(
        phase,
        Phase::Thinking | Phase::Searching | Phase::Reading | Phase::Writing | Phase::Citing
    ) {
        tile = tile.shadow(glow(BRAND, 10.0));
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
    if matches!(
        phase,
        Phase::Thinking | Phase::Searching | Phase::Reading | Phase::Writing | Phase::Citing
    ) {
        holder = holder.child(
            div()
                .absolute()
                .top(px(size * 0.2))
                .left(px(size * 0.2))
                .size(px(size * 0.6))
                .rounded(px(size))
                .bg(paint_a(BRAND_WASH))
                .shadow(glow(BRAND, size * 0.6)),
        );
    }
    holder.child(mark_dots(id, mark, phase, dot, gap, motion, false))
}

/// The phase beside the same recessed LED matrix as the app's status tags.
/// Whole-pixel bulbs hold their positions while the phase moves their light.
pub fn phase_beat(id: &str, phase: Phase, motion: bool) -> Div {
    let rows: &'static [&'static str] = match phase {
        // Rays leaving a centre: light radiated outward in rings.
        Phase::Searching => &["11111", "1...1", "1...1", "1...1", "11111"],
        // Open book, a scan passing over the recorded page.
        Phase::Reading => &["11.11", "1.1.1", "1.1.1", "1.1.1", "11.11"],
        // Pencil, lit in sequence along the diagonal stroke.
        Phase::Writing => &["....1", "...11", "..11.", ".11..", "11..."],
        // An arrow dropping onto a baseline: a citation landing.
        Phase::Citing => &["..1..", "..1..", ".111.", "..1..", "11111"],
        // A ring and centre light, gently shimmering while thinking.
        Phase::Thinking => &[".111.", "1...1", "1.1.1", "1...1", ".111."],
        Phase::Waiting => &["..1..", "..1..", "..1..", ".....", "..1.."],
        Phase::Idle => &[".....", ".....", "1.1.1", ".....", "....."],
        Phase::Off => &["1...1", ".1.1.", "..1..", ".1.1.", "1...1"],
    };
    let palette: &'static [u32] = match phase {
        Phase::Thinking | Phase::Searching | Phase::Reading | Phase::Writing | Phase::Citing => {
            &[ICE]
        }
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
                .text_color(paint(palette[0]))
                .child(phase.label().to_uppercase()),
        )
}
