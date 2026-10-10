//! KRIKO theme for GPUI. One file: colours, shadows and the small builders
//! (key, plate, well, LED matrix, tag, meter, switch, agent tile, hero, frost).
//! Everything here uses only primitives GPUI has: fills, gradients, 1px borders,
//! outer box shadows, images. There is no backdrop blur and no inset shadow, so
//! "wells" are a darker fill plus a hairline ring, and "frost" is a translucent
//! fill over the dithered sky image.

use gpui::{
    div, img, linear_color_stop, linear_gradient, point, px, rgb, rgba, BoxShadow, Div, Hsla,
    InteractiveElement, ObjectFit, ParentElement, SharedString, Stateful,
    StatefulInteractiveElement, Styled, StyledImage,
};

// ---- colour tokens (match tokens.json) ----
pub const GROUND: u32 = 0x05070f;
pub const SURFACE_1: u32 = 0x090e1b;
pub const SURFACE_2: u32 = 0x0d1427;
pub const BRAND: u32 = 0x1f4fff;
pub const BRAND_HOVER: u32 = 0x3a64ff;
pub const BRAND_LOW: u32 = 0x1739c2;
pub const BRAND_DEEP: u32 = 0x0a1a66;
pub const BRAND_BRIGHT: u32 = 0x86a3ff;
pub const ICE: u32 = 0xbfe4ff;
pub const INK: u32 = 0xf2f5ff;
pub const INK_2: u32 = 0xc9d1ea;
pub const MUTED: u32 = 0x98a3c2;
pub const DIM: u32 = 0x8893b2;
pub const DANGER: u32 = 0xff6b5e;
pub const WELL: u32 = 0x080b16;
pub const LED_OFF: u32 = 0x161d36;
pub const LED_DIM: u32 = 0x6b7799;
pub const BEZEL_HI: u32 = 0x3a4156;
pub const BEZEL_LO: u32 = 0x181c2a;
pub const BEZEL_EDGE: u32 = 0x06080f;
// translucent: 0xRRGGBBAA
pub const GLASS_1: u32 = 0xffffff0d;
pub const GLASS_2: u32 = 0xffffff14;
pub const HAIRLINE: u32 = 0xffffff1a;
pub const BORDER_CONTROL: u32 = 0xffffff59;
pub const BRAND_WASH: u32 = 0x1f4fff29;
pub const DANGER_WASH: u32 = 0xff6b5e24;
pub const FROST: u32 = 0xecf1ffeb; // pale frosted card over the sky

// ---- font families (register the .ttf files at startup, see register_fonts) ----
pub const DISPLAY: &str = "Barlow Condensed";
pub const SANS: &str = "DM Sans";
pub const MONO: &str = "JetBrains Mono";

pub fn register_fonts(cx: &mut gpui::App, fonts: Vec<std::borrow::Cow<'static, [u8]>>) {
    cx.text_system().add_fonts(fonts).expect("fonts");
}

fn hsla(hex: u32) -> Hsla {
    rgb(hex).into()
}

fn shadow(hex_rgba: u32, dx: f32, dy: f32, blur: f32, spread: f32) -> BoxShadow {
    BoxShadow {
        color: rgba(hex_rgba).into(),
        offset: point(px(dx), px(dy)),
        blur_radius: px(blur),
        spread_radius: px(spread),
    }
}

// ---- surfaces ----

/// Glass card: flat translucent fill, no shadow.
pub fn card() -> Div {
    div().bg(rgba(GLASS_1)).rounded(px(20.0)).p(px(24.0))
}

/// Recessed well: darker fill and a hairline ring. Used for rails, tracks, tags and LED tiles.
pub fn well() -> Div {
    div()
        .bg(rgb(WELL))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .rounded(px(10.0))
}

/// Pale frosted card that floats over a hero image (the one light surface).
pub fn frost() -> Div {
    div()
        .bg(rgba(FROST))
        .rounded(px(20.0))
        .p(px(16.0))
        .shadow(vec![shadow(0x02061773, 0.0, 24.0, 60.0, 0.0)])
}

/// Hero: the dithered sky PNG fills the box, the dither itself fades into GROUND,
/// so no gradient overlay is needed. Add children after calling.
pub fn hero(sky_path: impl Into<SharedString>, height: f32) -> Div {
    let sky: SharedString = sky_path.into();
    div()
        .relative()
        .w_full()
        .h(px(height))
        .bg(rgb(GROUND))
        .child(
            img(sky)
                .absolute()
                .top_0()
                .left_0()
                .size_full()
                .object_fit(ObjectFit::Cover),
        )
}

// ---- controls ----

/// Primary action: flat blue key. Solid `brand`, lighter on hover, darker while pressed.
pub fn key(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .h(px(44.0))
        .px(px(24.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(12.0))
        .font_family(DISPLAY)
        .text_color(rgb(0xffffff))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(rgb(BRAND))
        .hover(|s| s.bg(rgb(BRAND_HOVER)))
        .active(|s| s.bg(rgb(BRAND_LOW)))
        .child(label.to_uppercase())
}

/// Secondary action: flat graphite plate with a 1px edge.
pub fn plate(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .h(px(44.0))
        .px(px(24.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(12.0))
        .font_family(DISPLAY)
        .text_color(rgb(INK_2))
        .text_size(px(15.0))
        .cursor_pointer()
        .border_1()
        .border_color(rgb(BEZEL_EDGE))
        .bg(rgb(BEZEL_LO))
        .hover(|s| s.bg(rgb(BEZEL_HI)).text_color(rgb(INK)))
        .active(|s| s.bg(rgb(WELL)))
        .child(label.to_uppercase())
}

/// A dot-matrix: rows of equal-length strings, '#' is lit. Each lit dot glows.
pub fn led_matrix(rows: &[&str], color: u32, dot: f32, gap: f32) -> Div {
    let mut grid = div().flex().flex_col().gap(px(gap));
    for r in rows {
        let mut line = div().flex().gap(px(gap));
        for ch in r.chars() {
            let lit = ch == '#';
            let mut d = div().size(px(dot)).rounded(px(1.5));
            d = if lit {
                d.bg(rgb(color)).shadow(vec![BoxShadow {
                    color: hsla(color),
                    offset: point(px(0.0), px(0.0)),
                    blur_radius: px(5.0),
                    spread_radius: px(0.0),
                }])
            } else {
                d.bg(rgb(LED_OFF))
            };
            line = line.child(d);
        }
        grid = grid.child(line);
    }
    grid
}

pub const BANG5: [&str; 5] = ["..#..", "..#..", "..#..", ".....", "..#.."];
pub const CHECK5: [&str; 5] = ["....#", "...#.", "#.#..", ".#...", "....."];
pub const X5: [&str; 5] = ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"];
pub const QUEUE5: [&str; 5] = [".....", ".....", "#.#.#", ".....", "....."];

#[derive(Clone, Copy)]
pub enum TagState {
    Live,
    Need,
    Queue,
    Done,
    Block,
}

/// State tag: LED glyph plus a word, always both.
pub fn tag(state: TagState, label: &str) -> Div {
    let (glyph, led, fg): (&[&str], u32, u32) = match state {
        TagState::Live => (&BANG5, ICE, ICE),
        TagState::Need => (&BANG5, 0xffffff, 0xffffff),
        TagState::Queue => (&QUEUE5, LED_DIM, MUTED),
        TagState::Done => (&CHECK5, INK_2, INK_2),
        TagState::Block => (&X5, DANGER, DANGER),
    };
    let base = div()
        .h(px(28.0))
        .px(px(10.0))
        .flex()
        .items_center()
        .gap(px(8.0))
        .rounded(px(8.0))
        .font_family(MONO)
        .text_size(px(11.0))
        .text_color(rgb(fg))
        .border_1()
        .border_color(rgba(HAIRLINE));
    let base = match state {
        TagState::Need => base.bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BRAND_HOVER), 0.0),
            linear_color_stop(hsla(BRAND), 1.0),
        )),
        TagState::Block => base.bg(rgba(DANGER_WASH)),
        _ => base.bg(rgb(WELL)),
    };
    base.child(led_matrix(glyph, led, 3.0, 1.0)).child(label.to_uppercase())
}

/// Segment meter, `segments` squares, `value` 0..=100.
pub fn meter(value: f32, segments: usize) -> Div {
    let lit = ((segments as f32) * value.clamp(0.0, 100.0) / 100.0).round() as usize;
    let mut track = well().p(px(6.0)).flex().gap(px(3.0));
    for i in 0..segments {
        let seg = div().flex_1().h(px(14.0)).rounded(px(1.5));
        track = track.child(if i < lit {
            seg.bg(rgb(ICE)).shadow(vec![BoxShadow {
                color: hsla(ICE),
                offset: point(px(0.0), px(0.0)),
                blur_radius: px(6.0),
                spread_radius: px(0.0),
            }])
        } else {
            seg.bg(rgb(LED_OFF))
        });
    }
    track
}

/// Hardware switch. The knob is a bezel gradient, the slit lights when on.
pub fn switch(id: impl Into<gpui::ElementId>, on: bool) -> Stateful<Div> {
    let knob = div()
        .w(px(26.0))
        .h(px(24.0))
        .rounded(px(12.0))
        .border_1()
        .border_color(rgb(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BEZEL_HI), 0.0),
            linear_color_stop(hsla(BEZEL_LO), 1.0),
        ))
        .flex()
        .items_center()
        .justify_center()
        .child(div().w(px(8.0)).h(px(4.0)).rounded(px(2.0)).bg(rgb(if on { ICE } else { LED_OFF })));
    let track = div()
        .id(id)
        .w(px(56.0))
        .h(px(30.0))
        .p(px(3.0))
        .rounded(px(15.0))
        .bg(rgb(WELL))
        .border_1()
        .border_color(rgba(BORDER_CONTROL))
        .cursor_pointer()
        .flex();
    if on { track.justify_end().child(knob) } else { track.child(knob) }
}

/// Agent tile: 40px well. Pass the official icon path, or None for the LED monogram.
pub fn agent_tile(letter_rows: &[&str], icon: Option<SharedString>) -> Div {
    let t = well().size(px(40.0)).flex().items_center().justify_center();
    match icon {
        Some(p) => t.child(img(p).size(px(24.0))),
        None => t.child(led_matrix(letter_rows, BRAND_BRIGHT, 3.0, 1.0)),
    }
}

/// Sidebar item. `current` draws the recessed well with ice text.
pub fn nav_item(id: impl Into<gpui::ElementId>, label: &str, current: bool) -> Stateful<Div> {
    let base = div()
        .id(id)
        .h(px(36.0))
        .px(px(12.0))
        .flex()
        .items_center()
        .gap(px(12.0))
        .rounded(px(12.0))
        .font_family(SANS)
        .text_size(px(14.0))
        .cursor_pointer();
    if current {
        base.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE)).text_color(rgb(ICE))
    } else {
        base.text_color(rgb(MUTED)).hover(|s| s.bg(rgba(GLASS_1)).text_color(rgb(INK)))
    }
    .child(label.to_string())
}
