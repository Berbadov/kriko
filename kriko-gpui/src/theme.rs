//! KRIKO theme for GPUI. One file: colours, shadows, and the small builders
//! (key, plate, well, LED matrix, tag, meter, switch, agent tile, hero, frost,
//! input, verdict, keycap, badge). Everything uses only primitives GPUI has:
//! fills, gradients, 1px borders, outer box shadows, images, SVG alpha masks.
//! There is no backdrop blur and no inset shadow, so "wells" are a darker fill
//! plus a hairline ring, and "frost" is a translucent fill over the hero.

use gpui::{
    div, img, linear_color_stop, linear_gradient, point, px, rgb, rgba, relative, svg, prelude::*,
    Animation, AnimationExt, BoxShadow, Div, FontWeight, Hsla, ObjectFit, SharedString, Stateful,
    Styled, Svg, TextAlign,
};

// ---- colour tokens (match tokens.json / the screenshots) ----
pub const GROUND: u32 = 0x05070f;
pub const SURFACE_1: u32 = 0x090e1b;
pub const BRAND: u32 = 0x1f4fff;
pub const BRAND_HOVER: u32 = 0x3a64ff;
pub const BRAND_LOW: u32 = 0x1739c2;
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
pub const DANGER_EDGE: u32 = 0xff6b5e59;
pub const FROST: u32 = 0xecf1ffeb;


// ---- font families (registered at startup from the embedded .ttf files) ----
pub const DISPLAY: &str = "Kriko Display";
pub const SANS: &str = "Kriko Sans";
pub const MONO: &str = "Kriko Mono";

pub fn register_fonts(cx: &mut gpui::App, fonts: Vec<std::borrow::Cow<'static, [u8]>>) {
    cx.text_system().add_fonts(fonts).expect("fonts");
}

pub fn hsla(hex: u32) -> Hsla {
    rgb(hex).into()
}

pub fn shadow(hex_rgba: u32, dx: f32, dy: f32, blur: f32, spread: f32) -> BoxShadow {
    BoxShadow {
        color: rgba(hex_rgba).into(),
        offset: point(px(dx), px(dy)),
        blur_radius: px(blur),
        spread_radius: px(spread),
    }
}

/// The soft drop shadow a glass card casts over the ground.
pub fn card_shadow() -> Vec<BoxShadow> {
    vec![shadow(0x00000066, 0.0, 12.0, 32.0, 0.0)]
}

// ---- glyphs: 5x5 LED bitmaps, '#' is a lit square ----
pub const BANG5: [&str; 5] = ["..#..", "..#..", "..#..", ".....", "..#.."];
pub const CHECK5: [&str; 5] = ["....#", "...#.", "#.#..", ".#...", "....."];
pub const X5: [&str; 5] = ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"];
pub const QUEUE5: [&str; 5] = [".....", ".....", "#.#.#", ".....", "....."];
pub const PLAY5: [&str; 5] = ["..#..", "..##.", "..###", "..##.", "..#.."];
pub const COLS5: [&str; 5] = ["#.#.#", "#.#.#", "#.#.#", "#.#.#", "#.#.#"];
pub const LIST5: [&str; 5] = ["#####", ".....", "#####", ".....", "#####"];
pub const GRID5: [&str; 5] = ["#.#.#", ".....", "#.#.#", ".....", "#.#.#"];
pub const ONE5: [&str; 5] = ["..#..", ".##..", "..#..", "..#..", ".###."];
pub const TWO5: [&str; 5] = [".###.", "....#", "..##.", ".#...", "#####"];
pub const THREE5: [&str; 5] = ["####.", "....#", ".###.", "....#", "####."];
pub const FOUR5: [&str; 5] = ["#..#.", "#..#.", "#####", "...#.", "...#."];

// ---- motion ----
//
// The design system's four animations, rebuilt with the only tool GPUI
// offers: `with_animation` on a remounted element. The trick is the element
// id: it carries the state the animation depends on, so a change remounts
// the element and the animation replays. `motion == false` (Reduce motion
// in Settings) skips the wrapper entirely.

/// cubic-bezier(.3, 1.25, .5, 1): the --ease-mech overshoot of the hardware.
fn ease_mech(t: f32) -> f32 {
    let c1 = 1.70158;
    let c3 = c1 + 1.0;
    let x = t - 1.0;
    1.0 + c3 * x * x * x + c1 * x * x
}

/// The LED boot flicker (k-boot), one dot's slice of it. `index` staggers
/// the dots the way `--i * 9ms` does in the CSS.
fn boot_ease(index: usize) -> impl Fn(f32) -> f32 + 'static {
    move |t: f32| {
        // 600ms total, this dot wakes at index*9ms and flickers for 240ms.
        let local = (t * 600.0 - index as f32 * 9.0) / 240.0;
        if local <= 0.0 {
            return 0.1;
        }
        let u = local.min(1.0);
        // keyframes: 0% .1, 25% 1, 40% .15, 65% 1, 80% .3, 100% 1
        let stops = [0.0f32, 0.25, 0.40, 0.65, 0.80, 1.0];
        let vals = [0.1f32, 1.0, 0.15, 1.0, 0.3, 1.0];
        for w in 0..stops.len() - 1 {
            if u >= stops[w] && u <= stops[w + 1] {
                let k = (u - stops[w]) / (stops[w + 1] - stops[w]);
                return vals[w] + (vals[w + 1] - vals[w]) * k;
            }
        }
        1.0
    }
}

/// Which animation an LED matrix runs.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum LedAnim {
    None,
    /// The staggered wake-up flicker (live tags).
    Boot,
    /// The 1600ms on/off blink (needs-you tags, the live meter head).
    Blink,
}

// ---- surfaces ----

/// Glass card: translucent fill over the ground, soft shadow.
pub fn card() -> Div {
    div()
        .bg(rgba(GLASS_1))
        .rounded(px(20.0))
        .p(px(24.0))
        .shadow(card_shadow())
}

/// Recessed well: darker fill and a hairline ring.
pub fn well() -> Div {
    div()
        .bg(rgb(WELL))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .rounded(px(10.0))
}

/// Pale frosted card that floats over a hero image (the one light surface).
#[allow(dead_code)] // a design-system surface, kept for the next hero that needs it
pub fn frost() -> Div {
    div()
        .bg(rgba(FROST))
        .rounded(px(20.0))
        .p(px(16.0))
        .shadow(vec![shadow(0x02061773, 0.0, 24.0, 60.0, 0.0)])
}

/// Brand-wash callout panel, full width: tag and lines left, a key right.
pub fn callout() -> Div {
    div()
        .bg(rgba(BRAND_WASH))
        .rounded(px(20.0))
        .py(px(20.0))
        .px(px(24.0))
        .flex()
        .flex_wrap()
        .items_center()
        .justify_between()
        .gap(px(24.0))
}

/// One horizontal hairline separator.
pub fn hairline() -> Div {
    div().w_full().h(px(1.0)).bg(rgba(HAIRLINE))
}

/// Mono eyebrow label: 11px capitals in DIM.
pub fn eyebrow(label: &str) -> Div {
    div()
        .font_family(MONO)
        .text_size(px(11.0))
        .text_color(rgb(DIM))
        .child(label.to_uppercase())
}

// ---- the sky ----

/// The page head's colours on one sky. `build.rs` reads the sky image where
/// the words sit, picks the ink with the better contrast (light on a dark
/// sky, dark on a bright one) and the least shade of the other colour that
/// holds it at 7:1 over the brightest likely speck. A new sky image gets its
/// own answer by being there.
#[derive(Clone, Copy, Debug)]
pub struct SkyInk {
    pub ink: u32,
    pub shade: u32,
    pub shade_alpha: f32,
    #[allow(dead_code)] // reported, and asserted in the tests
    pub contrast: f32,
    /// Whether the brand accent still reads at 4.5:1 there; if not, the
    /// crumb wears the ink.
    pub accent_reads: bool,
}

include!("sky_ink.rs");

/// Which sky a hero carries. The dithered band is the identity; under it sits
/// a matching gradient, so the fades at both edges stay smooth and the
/// colour never runs out where the image ends.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Sky {
    /// Home and About: the full sky, brightest.
    Bright,
    /// Every working tab: the same sky in the evening.
    Dim,
    /// The Local LLM tab: wide and calm.
    Wide,
}

impl Sky {
    /// The vertical base of the sky, two stops of one gradient.
    fn base(self) -> (u32, u32) {
        match self {
            Sky::Bright => (0x0a1130, 0x2144bf),
            Sky::Dim => (0x060a1c, 0x11234e),
            Sky::Wide => (0x060a1c, 0x14264f),
        }
    }

    /// How much the horizon glows.
    fn glow(self) -> f32 {
        match self {
            Sky::Bright => 0.16,
            Sky::Dim => 0.07,
            Sky::Wide => 0.09,
        }
    }

    /// How the page head's words go on this sky: measured from the image at
    /// build time (`build.rs`), never chosen by eye.
    pub fn ink(self) -> SkyInk {
        SKY_INK[match self {
            Sky::Bright => 0,
            Sky::Dim => 1,
            Sky::Wide => 2,
        }]
    }

    /// The dithered sky band each hero carries.
    fn image(self) -> &'static str {
        match self {
            Sky::Bright => "sky-hero.png",
            Sky::Dim => "sky-dim.png",
            Sky::Wide => "sky-wide.png",
        }
    }
}

/// The hero band: the dithered sky image over its gradient base, dissolving
/// into the ground where the content begins. The sky runs to the top of the
/// window — the titlebar floats on it. Add children (the page head) after
/// calling.
pub fn hero(sky: Sky, height: f32, motion: bool) -> Div {
    let (top, bottom) = sky.base();
    div()
        .relative()
        .w_full()
        .h(px(height))
        .overflow_hidden()
        .bg(rgb(GROUND))
        .child(
            div().absolute().top_0().left_0().size_full().bg(linear_gradient(
                180.0,
                linear_color_stop(hsla(top), 0.0),
                linear_color_stop(hsla(bottom), 1.0),
            )),
        )
        .child(
            img(embedded(sky.image().into()))
                .absolute()
                .top_0()
                .left_0()
                .size_full()
                .object_fit(ObjectFit::Cover)
                .opacity(0.62),
        )
        .child(
            div()
                .absolute()
                .bottom_0()
                .left_0()
                .w_full()
                .h(relative(0.55))
                .bg(linear_gradient(
                    180.0,
                    linear_color_stop(Hsla { a: 0.0, ..hsla(ICE) }, 0.0),
                    linear_color_stop(Hsla { a: sky.glow(), ..hsla(ICE) }, 1.0),
                )),
        )
        .child(sky_veil(motion))
        .child(
            div()
                .absolute()
                .bottom_0()
                .left_0()
                .w_full()
                .h(px(150.0))
                .bg(linear_gradient(
                    180.0,
                    linear_color_stop(Hsla { a: 0.0, ..hsla(GROUND) }, 0.0),
                    linear_color_stop(hsla(GROUND), 1.0),
                )),
        )
}

/// A translucent brand wash over the sky that slowly breathes, so the hero
/// feels alive without anything moving in it. Still (dimmed) without motion.
fn sky_veil(motion: bool) -> gpui::AnyElement {
    let veil = div().absolute().top_0().left_0().size_full().bg(linear_gradient(
        90.0,
        linear_color_stop(
            Hsla {
                a: 0.00,
                ..hsla(BRAND)
            },
            0.0,
        ),
        linear_color_stop(
            Hsla {
                a: 0.10,
                ..hsla(BRAND)
            },
            1.0,
        ),
    ));
    if motion {
        veil.with_animation(
            "sky-breath",
            Animation::new(std::time::Duration::from_secs(14)).repeat(),
            |el, t| el.opacity(0.55 + 0.45 * (std::f32::consts::PI * t).sin()),
        )
        .into_any_element()
    } else {
        veil.opacity(0.6).into_any_element()
    }
}

/// The img source that reads from the embedded AssetSource. A bare string
/// would be parsed as a URI and the load would silently fail.
pub fn embedded(path: SharedString) -> gpui::ImageSource {
    gpui::ImageSource::Resource(gpui::Resource::Embedded(path))
}

/// Page head over the hero: mono crumb, display title, one lead line. It
/// starts below the floating titlebar, in the sky.
///
/// The sky stays whole and the words adapt to it (`Sky::ink`): their colour
/// is the one that contrasts with what is measured behind them, and a shade
/// of the opposite colour, only as dense as 7:1 needs, sits under the left
/// of the band and is gone by its middle, so the sky on the right is
/// untouched. The title names the page rather than filling it (the reader:
/// "page titles takes too much space, but i dont wanna lose the sky").
pub fn page_head(sky: Sky, crumb: &str, title: &str, lead: &str) -> Div {
    let plan = sky.ink();
    let shade = |a: f32| Hsla { a, ..hsla(plan.shade) };
    let accent = if plan.accent_reads { BRAND_BRIGHT } else { plan.ink };
    div()
        .absolute()
        .top_0()
        .left_0()
        .w_full()
        .h_full()
        .when(plan.shade_alpha > 0.0, |d| {
            d.child(
                div()
                    .absolute()
                    .top_0()
                    .left_0()
                    .size_full()
                    .bg(linear_gradient(
                        90.0,
                        linear_color_stop(shade(plan.shade_alpha), 0.38),
                        linear_color_stop(shade(0.0), 0.72),
                    )),
            )
        })
        .child(
            div()
                .relative()
                .px(px(40.0))
                .pt(px(60.0))
                .flex()
                .flex_col()
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .font_family(MONO)
                        .text_size(px(12.0))
                        .child(div().text_color(rgb(accent)).child("kriko /"))
                        .child(div().text_color(rgb(plan.ink)).opacity(0.8).child(crumb.to_uppercase())),
                )
                .child(
                    div()
                        .mt(px(6.0))
                        .font_family(DISPLAY)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(34.0))
                        .line_height(px(38.0))
                        .text_color(rgb(plan.ink))
                        .child(title.to_uppercase()),
                )
                .when(!lead.is_empty(), |d| {
                    d.child(
                        div()
                            .mt(px(10.0))
                            .max_w(px(560.0))
                            .font_family(SANS)
                            .text_size(px(15.0))
                            .line_height(px(22.0))
                            .text_color(rgb(plan.ink))
                            .opacity(0.88)
                            .child(lead.to_string()),
                    )
                }),
        )
}

// ---- the merged window top bar ----

/// The sidebar's width. The titlebar floats over everything to its right.
pub const SIDEBAR_W: f32 = 248.0;

/// One window-control button for the merged titlebar. `close` hovers red.
/// Resting state is a visible well; it is a control, not a ghost.
pub fn titlebar_button(
    id: impl Into<gpui::ElementId>,
    icon_name: &str,
    close: bool,
) -> Stateful<Div> {
    div()
        .id(id)
        .w(px(40.0))
        .h(px(28.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.0))
        .cursor_pointer()
        .bg(rgba(GLASS_1))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .child(icon(icon_name, 14.0).text_color(rgb(INK_2)))
        .hover(|s| {
            s.bg(if close {
                rgba(DANGER_WASH)
            } else {
                rgba(GLASS_2)
            })
            .text_color(rgb(if close { DANGER } else { INK }))
        })
}

/// The floating top bar: crumb and window controls over the sky, spanning the
/// content column. It paints nothing — the hero runs behind it, so the sky
/// is the bar.
pub fn titlebar() -> Stateful<Div> {
    div()
        .id("kriko-titlebar")
        .absolute()
        .top_0()
        .left_0()
        .right_0()
        .h(px(40.0))
        .flex()
        .items_center()
        .px(px(12.0))
        .gap(px(12.0))
}

// ---- controls ----

/// Primary action: blue key with a 3px lip that drops on press.
pub fn key(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(44.0))
        .px(px(24.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(12.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(rgb(0xffffff))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BRAND_HOVER), 0.0),
            linear_color_stop(hsla(BRAND_LOW), 1.0),
        ))
        .shadow(vec![
            shadow(0x0f2a9cff, 0.0, 3.0, 0.0, 0.0),
            shadow(0x00000080, 0.0, 10.0, 20.0, 0.0),
        ])
        .hover(|s| s.opacity(0.9))
        .active(|s| s.mt(px(3.0)).shadow(vec![shadow(0x00000080, 0.0, 2.0, 6.0, 0.0)]))
        .child(label.to_uppercase())
}

/// Ghost button: translucent fill, control-coloured ring.
pub fn ghost(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(44.0))
        .px(px(24.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(12.0))
        .font_family(MONO)
        .text_color(rgb(INK_2))
        .text_size(px(13.0))
        .cursor_pointer()
        .bg(rgba(GLASS_1))
        .border_1()
        .border_color(rgba(BORDER_CONTROL))
        .hover(|s| s.bg(rgba(GLASS_2)))
        .child(label.to_uppercase())
}

/// A compact danger key for a row that already carries its own label: the
/// dock's per-lane Stop, which at full key size outweighed the task it stops.
pub fn danger_s(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(22.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(6.0))
        .font_family(MONO)
        .text_color(rgb(DANGER))
        .text_size(px(10.0))
        .cursor_pointer()
        .bg(rgba(DANGER_WASH))
        .border_1()
        .border_color(rgba(DANGER_EDGE))
        .hover(|s| s.bg(rgba(0xff6b5e3d)))
        .active(|s| s.opacity(0.85))
        .child(label.to_uppercase())
}

/// Danger button: danger wash fill, danger text.
pub fn danger(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(44.0))
        .px(px(24.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(12.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(rgb(DANGER))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(rgba(DANGER_WASH))
        .border_1()
        .border_color(rgba(DANGER_EDGE))
        .hover(|s| s.bg(rgba(0xff6b5e3d)))
        .active(|s| s.opacity(0.85))
        .child(label.to_uppercase())
}

/// Wide benchmark run plate: 72px, leading play glyph, big label.
pub fn plate_wide(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .min_w(px(340.0))
        .h(px(72.0))
        .flex()
        .items_center()
        .gap(px(20.0))
        .px(px(9.0))
        .pr(px(28.0))
        .rounded(px(12.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(rgb(INK_2))
        .cursor_pointer()
        .border_1()
        .border_color(rgb(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BEZEL_HI), 0.0),
            linear_color_stop(hsla(BEZEL_LO), 1.0),
        ))
        .shadow(vec![shadow(0x00000099, 0.0, 6.0, 16.0, 0.0)])
        .hover(|s| s.text_color(rgb(INK)))
        .active(|s| s.mt(px(2.0)).shadow(vec![]))
        .child(
            well()
                .size(px(54.0))
                .rounded(px(10.0))
                .flex()
                .items_center()
                .justify_center()
                .child(led_matrix(&PLAY5, BRAND_BRIGHT, 4.0, 2.0)),
        )
        .child(
            div()
                .flex_1()
                .text_align(TextAlign::Center)
                .text_size(px(22.0))
                .child(label.to_uppercase()),
        )
}

/// Small well chip with mono text: paths, counts, codes.
pub fn chip(text: &str) -> Div {
    well()
        .h(px(28.0))
        .px(px(10.0))
        .flex()
        .items_center()
        .font_family(MONO)
        .text_size(px(11.0))
        .text_color(rgb(INK_2))
        .child(text.to_string())
}

/// Keyboard keycap chip.
pub fn keycap(text: &str) -> Div {
    div()
        .min_w(px(34.0))
        .h(px(30.0))
        .px(px(10.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .text_color(rgb(INK_2))
        .border_1()
        .border_color(rgb(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BEZEL_HI), 0.0),
            linear_color_stop(hsla(BEZEL_LO), 1.0),
        ))
        .shadow(vec![shadow(0x00000066, 0.0, 2.0, 4.0, 0.0)])
        .child(text.to_uppercase())
}

/// A dot-matrix: rows of equal-length strings, '#' is lit. Each lit dot glows.
pub fn led_matrix(rows: &[&str], color: u32, dot: f32, gap: f32) -> gpui::AnyElement {
    led_matrix_anim("", rows, color, dot, gap, LedAnim::None, true)
}

/// The LED matrix with its animation. `id` must be unique per matrix on the
/// screen: two LIVE tags sharing an id fight over one animation state and
/// one ends up half-lit. `motion == false` draws it static. Boot staggers
/// the lit dots' wake-up flicker; Blink is a marquee — each lit bulb takes
/// its turn going dim while the unlit dots hold steady.
pub fn led_matrix_anim(
    id: &str,
    rows: &[&str],
    color: u32,
    dot: f32,
    gap: f32,
    anim: LedAnim,
    motion: bool,
) -> gpui::AnyElement {
    let lit_dots = rows
        .iter()
        .flat_map(|r| r.chars())
        .filter(|c| *c == '#')
        .count();
    let mut grid = div().flex().flex_col().gap(px(gap));
    let mut index = 0usize;
    for r in rows {
        let mut line = div().flex().gap(px(gap));
        for ch in r.chars() {
            let lit = ch == '#';
            let d = div().size(px(dot)).rounded(px(1.5));
            let d: gpui::AnyElement = if lit {
                let base = d.bg(rgb(color)).shadow(vec![BoxShadow {
                    color: hsla(color),
                    offset: point(px(0.0), px(0.0)),
                    blur_radius: px(5.0),
                    spread_radius: px(0.0),
                }]);
                let cell = if motion && anim == LedAnim::Boot && lit_dots > 0 {
                    base.with_animation(
                        gpui::ElementId::named_usize(format!("{id}-led"), index),
                        Animation::new(std::time::Duration::from_millis(600))
                            .with_easing(boot_ease(index)),
                        |el, v| el.opacity(v),
                    )
                    .into_any_element()
                } else if motion && anim == LedAnim::Blink {
                    // the marquee: bulb `index` dims out of turn, one after
                    // another, so the sign never goes dark all at once
                    let phase = index as f32 / lit_dots as f32;
                    base.with_animation(
                        gpui::ElementId::named_usize(format!("{id}-blink"), index),
                        Animation::new(std::time::Duration::from_millis(1200))
                            .repeat()
                            .with_easing(|t| t),
                        move |el, t| {
                            let k = (t + phase).fract();
                            el.opacity(if k < 0.6 { 1.0 } else { 0.25 })
                        },
                    )
                    .into_any_element()
                } else {
                    base.into_any_element()
                };
                index += 1;
                cell
            } else {
                d.bg(rgb(LED_OFF)).into_any_element()
            };
            line = line.child(d);
        }
        grid = grid.child(line);
    }
    grid.into_any_element()
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum TagState {
    Live,
    Need,
    Queue,
    Done,
    Block,
}

/// State tag: LED glyph plus a word, always both. The LED animates the way
/// the CSS does: NEEDS YOU blinks, LIVE boots once on mount. `motion ==
/// false` (Reduce motion) keeps it static. `id` names the tag's animation:
/// unique per tag on the screen, or two tags half-light each other.
pub fn tag(id: impl Into<SharedString>, state: TagState, label: &str, motion: bool) -> Div {
    let id: SharedString = id.into();
    let (glyph, led, fg): (&[&str], u32, u32) = match state {
        TagState::Live => (&PLAY5, ICE, ICE),
        TagState::Need => (&BANG5, 0xffffff, 0xffffff),
        TagState::Queue => (&QUEUE5, LED_DIM, MUTED),
        TagState::Done => (&CHECK5, INK_2, INK_2),
        TagState::Block => (&X5, DANGER, DANGER),
    };
    let anim = match state {
        TagState::Live => LedAnim::Boot,
        TagState::Need => LedAnim::Blink,
        _ => LedAnim::None,
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
        TagState::Need => base
            .bg(linear_gradient(
                180.0,
                linear_color_stop(hsla(BRAND_HOVER), 0.0),
                linear_color_stop(hsla(BRAND), 1.0),
            ))
            .border_color(rgba(0xffffff40)),
        TagState::Block => base.bg(rgba(DANGER_WASH)),
        _ => base.bg(rgb(WELL)),
    };
    base.child(led_matrix_anim(&id, glyph, led, 3.0, 1.0, anim, motion))
        .child(label.to_uppercase())
}

/// Segment meter, `segments` squares, `value` 0..=100. When `live`, the
/// leading lit segment blinks (`.k-meter i.head`); `motion == false` freezes it.
pub fn meter(value: f32, segments: usize) -> Div {
    meter_live("meter", value, segments, false, true)
}

/// A thin progress bar for a job in flight: a track, a fill to the job's own
/// share, and a sheen that keeps sweeping across the fill so a run that sits
/// on one stage still reads as alive. Never a number beside it (#129: "Not
/// percentages but progress bars, animated"). Still under reduced motion.
pub fn progress_bar(id: &str, share: f32, motion: bool) -> Div {
    // a sliver even at zero, so a run that has just started is visibly on
    let share = share.clamp(0.0, 1.0).max(0.06);
    let mut fill = div()
        .relative()
        .h_full()
        .w(relative(share))
        .rounded(px(2.0))
        .overflow_hidden()
        .bg(rgb(ICE));
    if motion {
        let sheen = div()
            .absolute()
            .top_0()
            .h_full()
            .w(relative(0.35))
            .bg(linear_gradient(
                90.0,
                linear_color_stop(rgba(0xffffff00), 0.0),
                linear_color_stop(rgba(0xffffffb0), 0.5),
            ))
            .with_animation(
                gpui::ElementId::Name(SharedString::from(format!("{id}-sheen"))),
                Animation::new(std::time::Duration::from_millis(1400))
                    .repeat()
                    .with_easing(|t| t),
                // from just off the left edge to just off the right
                |el, t| el.left(relative(-0.35 + 1.35 * t)),
            );
        fill = fill.child(sheen);
    }
    div()
        .h(px(4.0))
        .w_full()
        .rounded(px(2.0))
        .overflow_hidden()
        .bg(rgba(GLASS_2))
        .child(fill)
}

/// A working indicator: three round LEDs breathing in turn, left to right,
/// like a carrier signal. Round and soft, so it reads as "alive" beside a
/// segment meter without becoming a second grid. Still, it rests with the
/// middle LED lit and the outer two dim.
pub fn led_ripple(id: &str, motion: bool) -> gpui::AnyElement {
    fn lit(el: Div, level: f32) -> Div {
        let alpha = (36.0 + 219.0 * level) as u32;
        el.bg(rgba((ICE << 8) | alpha.min(255))).shadow(vec![BoxShadow {
            color: gpui::Hsla { a: 0.55 * level, ..hsla(ICE) },
            offset: point(px(0.0), px(0.0)),
            blur_radius: px(2.0 + 6.0 * level),
            spread_radius: px(0.0),
        }])
    }
    let mut row = div().flex().items_center().gap(px(4.0)).flex_none().px(px(2.0));
    for i in 0..3u32 {
        let base = div().size(px(6.0)).rounded_full();
        let dot: gpui::AnyElement = if motion {
            let offset = i as f32 / 3.0;
            base.with_animation(
                gpui::ElementId::Name(gpui::SharedString::from(format!("{id}-breath-{i}"))),
                Animation::new(std::time::Duration::from_millis(1200))
                    .repeat()
                    .with_easing(|t| t),
                move |el, t| {
                    // one smooth swell per cycle, each LED a third behind
                    let phase = (t - offset).rem_euclid(1.0);
                    let level = 0.5 - 0.5 * (phase * std::f32::consts::TAU).cos();
                    lit(el, level * level)
                },
            )
            .into_any_element()
        } else {
            lit(base, if i == 1 { 1.0 } else { 0.15 }).into_any_element()
        };
        row = row.child(dot);
    }
    row.into_any_element()
}

/// Segment meter, `segments` squares, `value` 0..=100. When `live`, the
/// leading lit segment blinks; `id` names that blink, unique per meter.
pub fn meter_live(
    id: impl Into<SharedString>,
    value: f32,
    segments: usize,
    live: bool,
    motion: bool,
) -> Div {
    let head_id = gpui::SharedString::from(format!("{}-head", id.into()));
    let lit = ((segments as f32) * value.clamp(0.0, 100.0) / 100.0).round() as usize;
    let mut track = well().p(px(6.0)).flex().gap(px(3.0));
    for i in 0..segments {
        let seg = div().flex_1().h(px(14.0)).rounded(px(1.5));
        let head = motion && live && i == lit.saturating_sub(1);
        let seg: gpui::AnyElement = if i < lit {
            let cell = seg.bg(rgb(ICE)).shadow(vec![BoxShadow {
                color: hsla(ICE),
                offset: point(px(0.0), px(0.0)),
                blur_radius: px(6.0),
                spread_radius: px(0.0),
            }]);
            if head {
                cell.with_animation(
                    gpui::ElementId::Name(head_id.clone()),
                    Animation::new(std::time::Duration::from_millis(1600))
                        .repeat()
                        .with_easing(|t| t),
                    |el, t| el.opacity(if t < 0.5 { 1.0 } else { 0.2 }),
                )
                .into_any_element()
            } else {
                cell.into_any_element()
            }
        } else {
            seg.bg(rgb(LED_OFF)).into_any_element()
        };
        track = track.child(seg);
    }
    track
}

/// Slim confidence meter for table rows.
pub fn meter_slim(value: f32, segments: usize) -> Div {
    let lit = ((segments as f32) * value.clamp(0.0, 100.0) / 100.0).round() as usize;
    let mut track = well().p(px(4.0)).flex().gap(px(2.0)).min_w(px(96.0));
    for i in 0..segments {
        let seg = div().flex_1().h(px(8.0)).rounded(px(1.0));
        track = track.child(if i < lit {
            seg.bg(rgb(ICE)).shadow(vec![BoxShadow {
                color: hsla(ICE),
                offset: point(px(0.0), px(0.0)),
                blur_radius: px(5.0),
                spread_radius: px(0.0),
            }])
        } else {
            seg.bg(rgb(LED_OFF))
        });
    }
    track
}

/// Hardware switch. The knob is a bezel gradient that slides through the
/// --ease-mech overshoot (260ms in the CSS; 200ms reads the same here), the
/// slit inside it lights when on. `motion == false` snaps without the slide.
pub fn switch_anim(id: impl Into<gpui::ElementId>, on: bool, motion: bool) -> Stateful<Div> {
    let slit = div()
        .w(px(8.0))
        .h(px(4.0))
        .rounded(px(2.0))
        .bg(rgb(if on { ICE } else { LED_OFF }));
    let knob_base = div()
        .absolute()
        .top(px(3.0))
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
        .shadow(vec![shadow(0x00000099, 0.0, 4.0, 10.0, 0.0)])
        .flex()
        .items_center()
        .justify_center()
        .child(slit);
    let travel = 26.0;
    let knob: gpui::AnyElement = if motion {
        // The id carries the on-state: flipping the switch remounts the
        // knob and the slide replays from the other side.
        knob_base
            .with_animation(
                ("knob", on as usize),
                // linear here: the mech overshoot is applied inside the
                // animator, because an easing fn must stay within 0.0..=1.0
                Animation::new(std::time::Duration::from_millis(200)),
                move |el, t| {
                    let m = ease_mech(t);
                    let x = if on { travel * m } else { travel * (1.0 - m) };
                    el.left(px(x))
                },
            )
            .into_any_element()
    } else {
        knob_base
            .left(px(if on { travel } else { 0.0 }))
            .into_any_element()
    };
    // flex_none: in a narrow column the label beside it would otherwise
    // squeeze the switch into a sliver and push its knob outside the track
    div()
        .id(id)
        .relative()
        .flex_none()
        .w(px(56.0))
        .h(px(30.0))
        .rounded(px(15.0))
        .bg(rgb(WELL))
        .border_1()
        .border_color(rgba(BORDER_CONTROL))
        .cursor_pointer()
        .child(knob)
}

/// The k-seg thumb: the bezel square that slides to the picked cell.
/// `from`/`to` are cell indexes; the slide plays once when the id changes.
pub fn segmented_thumb(id_key: u64, from: usize, to: usize, motion: bool) -> gpui::AnyElement {
    let thumb = div()
        .absolute()
        .top(px(4.0))
        .h(px(40.0))
        .w(px(56.0))
        .rounded(px(10.0))
        .border_1()
        .border_color(rgb(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BEZEL_HI), 0.0),
            linear_color_stop(hsla(BEZEL_LO), 1.0),
        ))
        .shadow(vec![
            shadow(0xffffff14, 0.0, 0.0, 0.0, 0.0),
            shadow(0x0000008c, 0.0, 6.0, 16.0, 0.0),
        ]);
    if motion {
        let start = 4.0 + 58.0 * from as f32;
        let end = 4.0 + 58.0 * to as f32;
        thumb
            .with_animation(
                gpui::ElementId::NamedInteger(SharedString::from("seg-thumb"), id_key),
                Animation::new(std::time::Duration::from_millis(260)),
                move |el, t| el.left(px(start + (end - start) * ease_mech(t))),
            )
            .into_any_element()
    } else {
        thumb
            .left(px(4.0 + 58.0 * to as f32))
            .into_any_element()
    }
}

/// The k-seg track: a well holding the thumb and the LED cells. The cells are
/// built by the caller (they carry the click listeners).
pub fn segmented_track() -> Div {
    well()
        .relative()
        .p(px(4.0))
        .flex()
        .gap(px(2.0))
        .rounded(px(14.0))
}

/// One k-seg cell: the 56x40 radio with its LED glyph.
pub fn segmented_cell(
    id: impl Into<gpui::ElementId>,
    glyph: [&str; 5],
    picked: bool,
) -> Stateful<Div> {
    div()
        .id(id)
        .relative()
        .w(px(56.0))
        .h(px(40.0))
        .rounded(px(10.0))
        .flex()
        .items_center()
        .justify_center()
        .cursor_pointer()
        .child(led_matrix(
            &glyph,
            if picked { ICE } else { LED_DIM },
            4.0,
            2.0,
        ))
}

/// Sidebar / control icon from the embedded set, tinted with text_color.
pub fn icon(name: &str, size: f32) -> Svg {
    svg()
        .path(SharedString::from(format!("icons/{name}.svg")))
        .size(px(size))
}

/// Sidebar item. `current` draws the recessed well with ice text.
/// `count` is a plain mono count (Browse 760); `badge` is the brand
/// needs-you square (Activity).
pub fn nav_item(
    id: impl Into<gpui::ElementId>,
    icon_name: &str,
    label: &str,
    current: bool,
    count: Option<&str>,
    badge: Option<&str>,
) -> Stateful<Div> {
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
        .cursor_pointer()
        .when(current, |s| {
            s.bg(rgb(WELL))
                .border_1()
                .border_color(rgba(HAIRLINE))
                .text_color(rgb(ICE))
                .font_weight(FontWeight::SEMIBOLD)
        })
        .when(!current, |s| {
            s.text_color(rgb(MUTED))
                .hover(|h| h.bg(rgba(GLASS_1)).text_color(rgb(INK)))
        })
        .child(
            icon(icon_name, 18.0)
                .flex_none()
                .text_color(rgb(if current { ICE } else { MUTED })),
        )
        .child(div().child(label.to_string()))
        .child(div().flex_1());
    let base = match count {
        Some(c) => base.child(
            div()
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(if current { ICE } else { DIM }))
                .child(c.to_string()),
        ),
        None => base,
    };
    match badge {
        Some(b) => base.child(
            div()
                .h(px(20.0))
                .min_w(px(20.0))
                .px(px(5.0))
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(6.0))
                .bg(rgb(BRAND))
                .shadow(vec![shadow(0x0f2a9c99, 0.0, 2.0, 0.0, 0.0)])
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(0xffffff))
                .child(b.to_string()),
        ),
        None => base,
    }
}

/// The brand block on top of the sidebar: flat brand rectangle, white wordmark.
pub fn reveal(child: impl IntoElement, id: impl Into<SharedString>, open: bool, height: f32, motion: bool) -> gpui::AnyElement {
    Reveal { id: gpui::ElementId::Name(id.into()), child: Some(child.into_any_element()), open, height, motion }.into_any_element()
}

struct Reveal {
    id: gpui::ElementId,
    child: Option<gpui::AnyElement>,
    open: bool,
    height: f32,
    motion: bool,
}

struct RevealState {
    from: f32,
    target: f32,
    start: std::time::Instant,
}

impl gpui::IntoElement for Reveal {
    type Element = Self;
    fn into_element(self) -> Self { self }
}

impl gpui::Element for Reveal {
    type RequestLayoutState = gpui::AnyElement;
    type PrepaintState = ();
    fn id(&self) -> Option<gpui::ElementId> { Some(self.id.clone()) }
    fn source_location(&self) -> Option<&'static std::panic::Location<'static>> { None }
    fn request_layout(&mut self, id: Option<&gpui::GlobalElementId>, _: Option<&gpui::InspectorElementId>, window: &mut gpui::Window, cx: &mut gpui::App) -> (gpui::LayoutId, Self::RequestLayoutState) {
        window.with_element_state(id.unwrap(), |state: Option<RevealState>, window| {
            let target = if self.open { 1.0 } else { 0.0 };
            let mut state = state.unwrap_or(RevealState { from: 0.0, target, start: std::time::Instant::now() });
            let progress = (state.start.elapsed().as_secs_f32() / 0.26).min(1.0);
            let eased = progress * progress * (3.0 - 2.0 * progress);
            let current = state.from + (state.target - state.from) * eased;
            if target != state.target {
                state.from = current;
                state.target = target;
                state.start = std::time::Instant::now();
            }
            let value = if self.motion { current } else { target };
            if self.motion && (value - target).abs() > 0.001 { window.request_animation_frame(); }
            let mut child = div().flex().flex_col().flex_none().min_h(px(0.0)).overflow_hidden()
                .max_h(px(self.height * value)).opacity(value)
                // Clip a naturally sized child during the transition. Squeezing
                // its SVGs to zero makes GPUI reject their render requests.
                .child(div().flex_none().child(self.child.take().unwrap())).into_any_element();
            ((child.request_layout(window, cx), child), state)
        })
    }
    fn prepaint(&mut self, _: Option<&gpui::GlobalElementId>, _: Option<&gpui::InspectorElementId>, _: gpui::Bounds<gpui::Pixels>, child: &mut Self::RequestLayoutState, window: &mut gpui::Window, cx: &mut gpui::App) { child.prepaint(window, cx); }
    fn paint(&mut self, _: Option<&gpui::GlobalElementId>, _: Option<&gpui::InspectorElementId>, _: gpui::Bounds<gpui::Pixels>, child: &mut Self::RequestLayoutState, _: &mut (), window: &mut gpui::Window, cx: &mut gpui::App) { child.paint(window, cx); }
}

pub fn brand_block(wordmark: &'static str, tagline: &str) -> Div {
    div()
        .bg(rgb(BRAND))
        .px(px(20.0))
        .pt(px(16.0))
        .pb(px(16.0))
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(
            div().flex().items_center().gap(px(10.0)).child(svg()
                .path(SharedString::from(wordmark))
                .w(px(66.4))
                .h(px(22.0))
                .text_color(rgb(0xffffff))).child(div().font_family(MONO).text_size(px(10.0)).text_color(rgb(ICE)).px(px(6.0)).py(px(3.0)).border_1().border_color(rgba(0xffffff59)).rounded(px(4.0)).child("BETA")),
        )
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(0xffffffd9))
                .child(tagline.to_string()),
        )
}

#[cfg(test)]
mod sky_ink_tests {
    use super::*;

    #[test]
    fn every_sky_holds_its_words_at_seven_to_one() {
        for sky in [Sky::Bright, Sky::Dim, Sky::Wide] {
            let plan = sky.ink();
            assert!(plan.contrast >= 7.0, "{:?}", plan);
            assert!(plan.shade_alpha <= 0.85, "{:?}", plan);
        }
    }

    #[test]
    fn the_build_script_measures_with_the_themes_own_colours() {
        let script = include_str!("../build.rs");
        for (name, value) in [("INK", INK), ("GROUND", GROUND), ("ACCENT", BRAND_BRIGHT)] {
            assert!(
                script.contains(&format!("const {name}: u32 = 0x{value:06x};")),
                "build.rs's {name} is not theme.rs's"
            );
        }
    }
}
