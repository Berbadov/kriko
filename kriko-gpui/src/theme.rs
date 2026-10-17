//! KRIKO theme for GPUI. One file: colours, shadows, and the small builders
//! (key, plate, well, LED matrix, tag, meter, switch, agent tile, hero, frost,
//! input, verdict, keycap, badge), plus `tracked`, the one way to set the wide
//! mechanical capitals. Everything uses only primitives GPUI has: fills,
//! gradients, 1px borders, outer box shadows, images, SVG alpha masks.
//! There is no backdrop blur and no inset shadow, so "wells" are a darker fill
//! plus a hairline ring, and "frost" is a translucent fill over the hero.

use gpui::{
    div, img, linear_color_stop, linear_gradient, percentage, point, px, rgb, rgba, relative, svg,
    prelude::*, Animation, AnimationExt, BoxShadow, Div, FontWeight, Hsla, ObjectFit, Rgba,
    SharedString, Stateful, Styled, Svg, TextAlign, Transformation,
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
/// The three quiet inks were nudged up from `0xc9d1ea / 0x98a3c2 / 0x8893b2`:
/// on the near-black ground the old values left a 12px label grey rather than
/// readable. They stay ordered (INK > INK_2 > MUTED > DIM) and every light
/// value below is a shade that still clears 7:1 on the white page.
pub const INK_2: u32 = 0xd3daf0;
pub const MUTED: u32 = 0xa5b0cd;
pub const DIM: u32 = 0x949fbb;
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
/// The live dock's panel: the ground colour at 94% so the page behind it
/// reads as a faint shape, never as text competing with the dock's own.
pub const DOCK_GLASS: u32 = 0x090e1bf0;
/// The live dock's width. The page reserves this much room while it is open,
/// so controls and text do not disappear beneath the floating panel.
pub const DOCK_WIDTH: f32 = 320.0;
pub const HAIRLINE: u32 = 0xffffff1a;
pub const BORDER_CONTROL: u32 = 0xffffff59;
pub const BRAND_WASH: u32 = 0x1f4fff29;
pub const DANGER_WASH: u32 = 0xff6b5e24;
pub const DANGER_EDGE: u32 = 0xff6b5e59;
/// The caution tone: a thing that needs attention, not the red line. It is a
/// named token so the white theme can darken it; a raw amber stayed bright on
/// white and the severity word washed out.
pub const WARN: u32 = 0xffb86b;
pub const WARN_WASH: u32 = 0xffb86b1f;
pub const FROST: u32 = 0xecf1ffeb;

// ---- light theme ----
//
// The app keeps one palette of names and swaps the values. Every builder and
// every screen paints through `paint`/`paint_a`, so a light frame cannot leave
// half a page dark. `fixed` is the escape hatch for colours that are not part
// of the surface: the measured sky ink and the words on the brand blue.
//
// The values below are chosen against a near-white ground: body text holds at
// least 4.5:1, and the muted pair stays above 6:1 so a 12px label is still
// readable. The brand stays blue; only the surfaces and ink change.

use std::sync::atomic::{AtomicBool, Ordering};

static LIGHT: AtomicBool = AtomicBool::new(false);

pub fn set_light(on: bool) {
    LIGHT.store(on, Ordering::Relaxed);
}

pub fn light() -> bool {
    LIGHT.load(Ordering::Relaxed)
}

/// The light value of one opaque token.
pub(crate) fn light_colour(hex: u32) -> u32 {
    match hex {
        0x05070f => 0xfbfcff, // GROUND
        0x090e1b => 0xffffff, // SURFACE_1
        0x1f4fff => 0x1f4fff, // BRAND
        0x3a64ff => 0x2b53e6, // BRAND_HOVER
        0x1739c2 => 0x1739c2, // BRAND_LOW
        0x86a3ff => 0x2447d8, // BRAND_BRIGHT
        0xbfe4ff => 0x1d43c8, // ICE
        0xf2f5ff => 0x0b1020, // INK
        0xc9d1ea => 0x1e2740, // INK_2 (the pre-nudge value, still mapped for old call sites)
        0x98a3c2 => 0x46506b, // MUTED (the pre-nudge value)
        0x8893b2 => 0x566079, // DIM (the pre-nudge value)
        0xd3daf0 => 0x1a2136, // INK_2
        0xa5b0cd => 0x3d4760, // MUTED
        0x949fbb => 0x4a5470, // DIM
        0xff6b5e => 0xc62d1f, // DANGER
        0xffb86b => 0x8a4a00, // WARN
        0x080b16 => 0xeef2f9, // WELL
        0x161d36 => 0xd7deec, // LED_OFF
        0x6b7799 => 0x7c86a0, // LED_DIM
        0x3a4156 => 0xe7ecf5, // BEZEL_HI
        0x181c2a => 0xf7f9fd, // BEZEL_LO
        0x06080f => 0xc9d2e2, // BEZEL_EDGE
        0xffffff => 0xffffff, // on-brand words stay white
        _ => hex,
    }
}

/// A light value for the translucent tokens and the few raw glazes used by the
/// builders. Dark glazes become a low black; light glass over the dark ground
/// becomes a low black over the light ground.
pub(crate) fn light_alpha(hex: u32) -> u32 {
    let ink = hex >> 8;
    let alpha = hex & 0xff;
    match hex {
        0xffffff0d => 0x0b10200a, // GLASS_1
        0xffffff14 => 0x0b102010, // GLASS_2
        0xffffff1a => 0x0b102016, // HAIRLINE
        0xffffff1b => 0x0b102009, // card's top glaze
        0xffffff20 => 0x0b10201a,
        0xffffff26 => 0x0b102018, // card edge
        0xffffff40 => 0x0b102030,
        0xffffff59 => 0x0b102050, // BORDER_CONTROL
        0xffffff8a => 0x0b102080,
        0xffffff90 => 0x0b102090,
        0xffffffb0 => 0x0b1020b0,
        0xffffff00 => 0x00000000,
        0x1f4fff29 => 0x1f4fff14, // BRAND_WASH
        0xff6b5e24 => 0xc62d1f12, // DANGER_WASH
        0xff6b5e59 => 0xc62d1f55, // DANGER_EDGE
        _ if ink == 0x000000 => {
            // Shadows: softer on a light ground so a card does not wear a bruise.
            let soft = (alpha / 3).max(6);
            (0x0b1020 << 8) | soft
        }
        _ => (light_colour(ink) << 8) | alpha,
    }
}

/// One opaque colour, mapped for the current theme.
pub fn paint(hex: u32) -> Rgba {
    if light() {
        rgb(light_colour(hex))
    } else {
        rgb(hex)
    }
}

/// One colour with alpha in its low byte, mapped for the current theme.
pub fn paint_a(hex: u32) -> Rgba {
    if light() {
        rgba(light_alpha(hex))
    } else {
        rgba(hex)
    }
}

/// A colour that must not follow the theme: sky ink, the words on brand.
pub fn fixed(hex: u32) -> Rgba {
    rgb(hex)
}

pub fn fixed_a(hex: u32) -> Rgba {
    rgba(hex)
}

// ---- font families (registered at startup from the embedded .ttf files) ----
pub const DISPLAY: &str = "Kriko Display";
pub const SANS: &str = "Kriko Sans";
/// What used to be set in a fixed-width face (eyebrows, crumbs, counts, paths)
/// wears the body face: the reader did not like the mono, "appears on
/// technical places". The name stays so a call site says what the text *is*
/// (a label, a figure) and the face stays one decision, here.
pub const MONO: &str = SANS;
/// The one place a fixed-width face is still right: text that is code, such
/// as a run's log, where the columns line up. The machine's own, so nothing
/// is shipped for it.
pub const CODE: &str = "Consolas";

pub fn register_fonts(cx: &mut gpui::App, fonts: Vec<std::borrow::Cow<'static, [u8]>>) {
    cx.text_system().add_fonts(fonts).expect("fonts");
}

/// Raw sRGB, never theme-mapped. The sky and the measured ink on it are the
/// same sky in both themes; only the page around them changes.
pub fn hsla(hex: u32) -> Hsla {
    rgb(hex).into()
}

pub fn shadow(hex_rgba: u32, dx: f32, dy: f32, blur: f32, spread: f32) -> BoxShadow {
    BoxShadow {
        color: paint_a(hex_rgba).into(),
        offset: point(px(dx), px(dy)),
        blur_radius: px(blur),
        spread_radius: px(spread),
    }
}

/// The soft drop shadow a glass card casts over the ground.
#[allow(dead_code)]
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
pub(crate) fn ease_mech(t: f32) -> f32 {
    let c1 = 1.70158;
    let c3 = c1 + 1.0;
    let x = t - 1.0;
    1.0 + c3 * x * x * x + c1 * x * x
}

// ---- how much motion the reader asked for ----
//
// Three profiles over one vocabulary. `Calm` is the quiet instrument, `Vivid`
// leans into the spring; `Standard` is the house setting. The profile scales
// distance, size and duration in one place, so every animation in the app
// responds to it without a second decision per call site. Reduce motion is
// still the hard switch: it is checked first and skips the profile entirely.

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum MotionProfile {
    Calm,
    Standard,
    Vivid,
}

impl MotionProfile {
    pub fn key(self) -> &'static str {
        match self {
            Self::Calm => "calm",
            Self::Standard => "standard",
            Self::Vivid => "vivid",
        }
    }

    pub fn from_key(key: &str) -> Self {
        match key.trim().to_ascii_lowercase().as_str() {
            "calm" => Self::Calm,
            "vivid" => Self::Vivid,
            _ => Self::Standard,
        }
    }

    /// Distance, size and overshoot multiplier.
    fn energy(self) -> f32 {
        match self {
            Self::Calm => 0.62,
            Self::Standard => 1.0,
            Self::Vivid => 1.55,
        }
    }

    /// Duration multiplier: vivid is not only bigger, it is slower to settle.
    fn tempo(self) -> f32 {
        match self {
            Self::Calm => 0.78,
            Self::Standard => 1.0,
            Self::Vivid => 1.28,
        }
    }
}

static PROFILE: std::sync::atomic::AtomicU8 = std::sync::atomic::AtomicU8::new(1);

/// The window's own motion switch, published once per frame. Most builders
/// take `motion` as an argument; the ones that cannot (a helper called from
/// everywhere) read this instead. Set nowhere but `render`.
static MOTION: AtomicBool = AtomicBool::new(false);

pub fn set_motion(on: bool) {
    MOTION.store(on, Ordering::Relaxed);
}

pub fn motion_on() -> bool {
    MOTION.load(Ordering::Relaxed)
}

pub fn set_profile(profile: MotionProfile) {
    PROFILE.store(match profile {
        MotionProfile::Calm => 0,
        MotionProfile::Standard => 1,
        MotionProfile::Vivid => 2,
    }, std::sync::atomic::Ordering::Relaxed);
}

pub fn profile() -> MotionProfile {
    match PROFILE.load(std::sync::atomic::Ordering::Relaxed) {
        0 => MotionProfile::Calm,
        2 => MotionProfile::Vivid,
        _ => MotionProfile::Standard,
    }
}

/// A distance or size, scaled by the reader's profile.
pub fn amp(base: f32) -> f32 {
    base * profile().energy()
}

/// A duration in milliseconds, scaled by the reader's profile and floored so
/// a frame always covers it.
pub fn tempo_ms(base: u64) -> u64 {
    ((base as f32) * profile().tempo()).max(60.0) as u64
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

// ---- rhythm: the one place for every gap and inset a screen uses ----
//
// One 4px scale. A screen names a step, it does not invent a pixel value, so
// two cards in one row cannot disagree by two pixels. The older names below
// are now steps on this scale: the off-scale values (6, 10, 20) were the
// drift, and a card inset of 10 beside a gutter of 6 read as two systems.

pub const SPACE_XS: f32 = 4.0;
pub const SPACE_S: f32 = 8.0;
pub const SPACE_M: f32 = 12.0;
pub const SPACE_L: f32 = 16.0;
pub const SPACE_XL: f32 = 24.0;
pub const SPACE_2XL: f32 = 32.0;

/// There are two control heights, not a private one per builder: a button is
/// 40 whatever its fill, and a pill is 24 whatever it counts. A 44px key beside
/// a 40px ghost was the same control drawn at two sizes.
pub const CONTROL_H: f32 = 40.0;
pub const PILL_H: f32 = SPACE_XL;

/// Line boxes for the small sizes, one step each: 11/14, 12/16, 13/18, 14/20.
/// A label, a row and its note then share a vertical rhythm instead of each
/// taking the font's default leading.
pub const LINE_11: f32 = 14.0;
pub const LINE_12: f32 = 16.0;
pub const LINE_13: f32 = 18.0;
pub const LINE_14: f32 = 20.0;

/// The page column's side gutter, below the hero. The page head uses it too,
/// so the title and the content share one left edge.
pub const PAGE_PAD: f32 = SPACE_L;
/// Between two sections of one page.
pub const SPACE_SECTION: f32 = SPACE_L;
/// Between cards that sit side by side or stacked within a section.
pub const SPACE_CARD: f32 = SPACE_M;
/// Between a section's title and what it holds. One step: a title closer than
/// this to its body and further than this from the next card reads as a
/// heading with two owners.
pub const SPACE_TITLE: f32 = SPACE_S;
/// Inside a card.
pub const PAD_CARD: f32 = SPACE_M;
/// Inside a dense card: a list of rows, a table, a settings group.
pub const PAD_CARD_TIGHT: f32 = SPACE_S;

// ---- surfaces ----

/// Flat glass card from the current design reference. One inset on all four
/// sides, so a card's title and its body share the left edge.
pub fn card() -> Div {
    div()
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint_a(0xffffff1b), 0.0),
            linear_color_stop(paint_a(GLASS_1), 1.0),
        ))
        .border_1()
        .border_color(paint_a(0xffffff26))
        .rounded(px(10.0))
        .p(px(PAD_CARD))
        .shadow(vec![shadow(0x00000045, 0.0, 6.0, 16.0, 0.0)])
}

/// A titled section: the eyebrow title over its body, at one distance on
/// every screen. Cards inside keep their own inset.
#[allow(dead_code)] // the shared builder for the next screen that titles a group
pub fn section(title: &str, body: impl IntoElement) -> Div {
    div()
        .flex()
        .flex_col()
        .gap(px(SPACE_TITLE))
        .child(eyebrow(title))
        .child(body)
}

/// How many columns of at least `min_w` fit in `width`, `SPACE_CARD` apart,
/// never more than `max` and never fewer than one. A width that is too
/// narrow for two columns gives one, so cards stack instead of squeezing.
pub fn column_count(width: f32, min_w: f32, max: usize) -> usize {
    if width <= 0.0 || min_w <= 0.0 || max <= 1 {
        return 1;
    }
    let fit = ((width + SPACE_CARD) / (min_w + SPACE_CARD)).floor();
    (fit.max(1.0) as usize).min(max)
}

/// Sibling cards laid out in rows of `column_count` equal columns. Cards in one
/// row share a height; a short last row keeps its columns, so the grid never
/// leaves a gap of unused width. `width` is the page's content width.
pub fn grid<E: IntoElement + Styled>(width: f32, min_w: f32, items: Vec<E>) -> Div {
    let per_row = column_count(width, min_w, items.len());
    let mut rows = div().flex().flex_col().gap(px(SPACE_CARD)).w_full();
    let mut items = items.into_iter().peekable();
    while items.peek().is_some() {
        // a row is a flex row: its children stretch to the tallest one
        let mut row = div().flex().gap(px(SPACE_CARD));
        for item in items.by_ref().take(per_row) {
            row = row.child(item.flex_1().min_w(px(0.0)));
        }
        rows = rows.child(row);
    }
    rows
}

/// Recessed well: darker fill and a hairline ring.
pub fn well() -> Div {
    div()
        .bg(paint(WELL))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .rounded(px(10.0))
}

/// Pale frosted card that floats over a hero image (the one light surface).
#[allow(dead_code)] // a design-system surface, kept for the next hero that needs it
pub fn frost() -> Div {
    div()
        .bg(paint_a(FROST))
        .rounded(px(20.0))
        .p(px(SPACE_L))
        .shadow(vec![shadow(0x02061773, 0.0, 24.0, 60.0, 0.0)])
}

/// Brand-wash callout panel, full width: tag and lines left, a key right.
pub fn callout() -> Div {
    div()
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint_a(0x527bff34), 0.0),
            linear_color_stop(paint_a(BRAND_WASH), 1.0),
        ))
        .border_1()
        .border_color(paint_a(0x86a3ff48))
        .rounded(px(10.0))
        .p(px(PAD_CARD))
        .flex()
        .flex_wrap()
        .items_center()
        .justify_between()
        .gap(px(SPACE_M))
}

/// One horizontal hairline separator.
pub fn hairline() -> Div {
    div().w_full().h(px(1.0)).bg(paint_a(HAIRLINE))
}

/// Sideways tables consume horizontal wheels while vertical wheels reach the
/// surrounding page. Occluding this hitbox would block both axes.
pub fn horizontal_wheel<T: Styled + gpui::InteractiveElement>(mut element: T) -> T {
    element.style().restrict_scroll_to_axis = Some(true);
    element.on_scroll_wheel(|event, window, cx| {
        let delta = event.delta.pixel_delta(window.line_height());
        if delta.x.abs() > delta.y.abs() {
            cx.stop_propagation();
        }
    })
}

/// The wide mechanical capitals of the design system.
///
/// GPUI 0.2 has no letter-spacing, so tracking is layout: one span per glyph
/// in a flex row, `gap` px apart. That is why this returns a row rather than a
/// styled string, and why every glyph carries its face, weight, size, line box
/// and colour itself.
///
/// Text style *is* inherited here: `Div::request_layout`/`paint` push the
/// element's `text` refinement onto the window's style stack
/// (`window.with_text_style`), and a child text element composes that stack.
/// But inheritance is exactly what a label must not depend on: a card that
/// re-colours its children would tint an eyebrow, and an animation that sets a
/// size would resize it. So each glyph is explicit.
///
/// A space becomes a fixed spacer of `0.3 * size`: a text space between two
/// flex items collapses to the gap alone, which would make a two-word label
/// read as two tracked words run together.
pub fn tracked(label: &str, size: f32, gap: f32, colour: u32, weight: FontWeight) -> Div {
    let line = size * 1.2;
    let mut row = div()
        .flex()
        .items_center()
        .flex_none()
        .gap(px(gap))
        // The row holds the label's line box even when the label is empty, so
        // a caller's baseline does not move when a count reads "".
        .h(px(line));
    for ch in label.chars() {
        let glyph = if ch == ' ' {
            div().flex_none().w(px(size * 0.3)).h(px(line))
        } else {
            // A single-character String is the smallest child GPUI takes;
            // `char` itself is not an element in 0.2.
            div()
                .flex_none()
                .font_family(MONO)
                .font_weight(weight)
                .text_size(px(size))
                .line_height(px(line))
                .text_color(paint(colour))
                .child(ch.to_string())
        };
        row = row.child(glyph);
    }
    row
}

/// Mono eyebrow label: 12px capitals in MUTED, tracked 0.9px so the capitals
/// read as a label rather than as a block of grey. The weight carries the rest.
pub fn eyebrow(label: &str) -> Div {
    tracked(&label.to_uppercase(), 12.0, 0.9, MUTED, FontWeight::SEMIBOLD)
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
#[allow(dead_code)] // the un-scrolled form, kept for a caller with no page scroll
pub fn hero(sky: Sky, height: f32, motion: bool) -> Div {
    hero_scrolled(sky, height, motion, 0.0, "")
}

/// The hero with the page's scroll offset: the sky drifts a fraction of the
/// scroll, so the band reads as a window rather than as a sticker on the page.
/// Scroll-linked, not looping: it only changes while `step_scroll` is asking
/// for frames, so an idle window still draws nothing (#184).
///
/// `key` names the page (the tab): the sky's own awakening (`sky_aurora`) is
/// keyed on it, so arriving on a page replays it once and a plain redraw does
/// not. The page head is added as a child after this returns, so the text
/// always paints above the moving light.
pub fn hero_scrolled(sky: Sky, height: f32, motion: bool, scroll: f32, key: &str) -> Div {
    let (top, bottom) = sky.base();
    // `scroll` is zero at the top and negative further down; the sky lags it.
    let drift = if motion { -scroll * amp(0.22) } else { 0.0 };
    let mut hero = div()
        .relative()
        .w_full()
        .h(px(height))
        .overflow_hidden()
        .bg(paint(GROUND))
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
                .top(px(drift))
                .left_0()
                .w_full()
                .h(px(height + amp(48.0)))
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
                    linear_color_stop(Hsla { a: 0.0, ..Hsla::from(paint(ICE)) }, 0.0),
                    linear_color_stop(Hsla { a: sky.glow(), ..Hsla::from(paint(ICE)) }, 1.0),
                )),
        );
    // The sky's awakening, over the still image and under the page head.
    for layer in sky_aurora(sky, key, height, motion) {
        hero = hero.child(layer);
    }
    hero.child(sky_veil(motion)).child(
        div()
            .absolute()
            .bottom_0()
            .left_0()
            .w_full()
            .h(px((height * 0.5).min(150.0)))
            .bg(linear_gradient(
                180.0,
                linear_color_stop(Hsla { a: 0.0, ..paint(GROUND).into() }, 0.0),
                linear_color_stop(paint(GROUND), 1.0),
            )),
    )
}

/// The hero's awakening: three soft light-fields that drift across the band
/// and settle over ~2.4 s when a page arrives. One-shot and keyed on the page,
/// so a switch replays it and a redraw does not; gone under Reduce motion. The
/// alpha stays low and each field fades across the band, so the page head
/// painted above it stays readable (`Sky::ink` was measured for this).
fn sky_aurora(sky: Sky, key: &str, height: f32, motion: bool) -> Vec<gpui::AnyElement> {
    if !motion {
        return Vec::new();
    }
    // (gradient angle, colour, peak alpha, drift-x fraction, drift-y px, delay)
    let fields: [(f32, u32, f32, f32, f32, f32); 3] = match sky {
        Sky::Bright => [
            (112.0, 0x86a3ff, 0.16, -0.12, 12.0, 0.00),
            (86.0, 0xbfe4ff, 0.12, 0.14, 7.0, 0.16),
            (132.0, 0x6f5bff, 0.10, 0.04, -9.0, 0.32),
        ],
        Sky::Dim => [
            (112.0, 0x86a3ff, 0.14, -0.10, 9.0, 0.00),
            (86.0, 0xbfe4ff, 0.10, 0.12, 5.0, 0.16),
            (132.0, 0x5f6bff, 0.09, 0.03, -7.0, 0.32),
        ],
        Sky::Wide => [
            (108.0, 0x86a3ff, 0.12, -0.08, 8.0, 0.00),
            (84.0, 0xbfe4ff, 0.09, 0.10, 5.0, 0.14),
            (126.0, 0x5f7bff, 0.08, 0.02, -6.0, 0.28),
        ],
    };
    fields
        .iter()
        .enumerate()
        .map(|(i, &(angle, hue, alpha, dx, dy, delay))| {
            // One edge of the band brightens and fades toward the other, so
            // the field reads as light rather than as paint.
            let base = div()
                .absolute()
                .top_0()
                .left_0()
                .w_full()
                .h(px(height))
                .bg(linear_gradient(
                    angle,
                    linear_color_stop(Hsla { a: 0.0, ..hsla(hue) }, 0.0),
                    linear_color_stop(Hsla { a: alpha, ..hsla(hue) }, 1.0),
                ));
            base.with_animation(
                gpui::ElementId::Name(format!("aurora-{key}-{i}").into()),
                Animation::new(std::time::Duration::from_millis(tempo_ms(2400)))
                    .with_easing(|t| t),
                move |d, t| {
                    // Each field wakes after the one before it and is settled
                    // where it belongs for good at t == 1.
                    let u = ((t - delay) / (1.0 - delay).max(0.01)).clamp(0.0, 1.0);
                    let e = ease_mech(u);
                    d.opacity(u)
                        .left(px(amp(150.0) * dx * (1.0 - e)))
                        .top(px(dy * (1.0 - e)))
                },
            )
            .into_any_element()
        })
        .collect()
}

/// A translucent brand wash over the sky. It used to breathe on a 14 s loop,
/// which redrew the whole window every frame on every screen for a movement
/// nobody could see (#184); the wash now holds the breath's middle.
fn sky_veil(_motion: bool) -> gpui::AnyElement {
    div().absolute().top_0().left_0().size_full().bg(linear_gradient(
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
    ))
    .opacity(0.6)
    .into_any_element()
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
pub fn page_head(sky: Sky, crumb: &str, title: &str, lead: &str, motion: bool) -> Div {
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
                .px(px(PAGE_PAD))
                // The floating titlebar is CONTROL_H tall; the crumb starts one
                // step below it rather than two pixels below it.
                .pt(px(CONTROL_H + SPACE_XS))
                .flex()
                .flex_col()
                .child(
                    // One line over the title: where you are, and what the
                    // page is for, cut off rather than wrapped.
                    div()
                        .flex()
                        .items_center()
                        .gap(px(SPACE_S))
                        .font_family(MONO)
                        .text_size(px(13.5))
                        .line_height(px(LINE_14))
                        .child(div().flex_none().text_color(fixed(accent)).child("kriko /"))
                        .child(div().flex_none().text_color(fixed(plan.ink)).opacity(0.9).child(crumb.to_uppercase()))
                        .when(!lead.is_empty(), |d| {
                            d.child(
                                div()
                                    .flex_1()
                                    .min_w(px(0.0))
                                    .overflow_hidden()
                                    .whitespace_nowrap()
                                    .text_ellipsis()
                                    .text_color(fixed(plan.ink))
                                    .opacity(0.86)
                                    .child(format!("\u{00b7}  {lead}")),
                            )
                        }),
                )
                .child(
                    title_wipe(title, plan.ink, motion),
                ),
        )
}

fn title_wipe(title: &str, ink: u32, motion: bool) -> gpui::AnyElement {
    let text = div().font_family(DISPLAY).font_weight(FontWeight::BOLD)
        .text_size(px(27.0)).line_height(px(32.0)).text_color(fixed(ink))
        .whitespace_nowrap().child(title.to_uppercase());
    let clip = div().mt(px(SPACE_XS)).h(px(32.0)).w_full().overflow_hidden().child(text);
    if motion {
        clip.with_animation(gpui::ElementId::Name(format!("title-{title}").into()),
            Animation::new(std::time::Duration::from_millis(420)),
            |d, t| d.w(relative((t * 14.0).floor() / 14.0)),
        ).into_any_element()
    } else { clip.into_any_element() }
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
        .w(px(CONTROL_H))
        .h(px(SPACE_2XL))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.0))
        .cursor_pointer()
        .bg(paint_a(GLASS_1))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .child(icon(icon_name, 14.0).text_color(paint(INK_2)))
        .hover(|s| {
            s.bg(if close {
                paint_a(DANGER_WASH)
            } else {
                paint_a(GLASS_2)
            })
            .text_color(paint(if close { DANGER } else { INK }))
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
        .h(px(CONTROL_H))
        .flex()
        .items_center()
        .px(px(SPACE_M))
        .gap(px(SPACE_M))
}

// ---- controls ----

/// Flat primary action; a press changes its fill without moving the layout.
pub fn key(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(CONTROL_H))
        .px(px(SPACE_XL))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(10.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(fixed(0xffffff))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint(BRAND_HOVER), 0.0),
            linear_color_stop(hsla(BRAND), 1.0),
        ))
        .border_1()
        .border_color(fixed_a(0xffffff59))
        .shadow(vec![shadow(0x102b9c80, 0.0, 3.0, 12.0, 0.0)])
        .hover(|s| s.bg(paint(BRAND_HOVER)).border_color(fixed_a(0xffffff90)).relative().top(px(-1.0)))
        .active(|s| s.bg(paint(BRAND_LOW)))
        .child(label.to_string())
}

/// Ghost button: translucent fill, control-coloured ring.
pub fn ghost(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(CONTROL_H))
        .px(px(SPACE_L))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(10.0))
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(paint(INK_2))
        .text_size(px(14.0))
        .line_height(px(LINE_14))
        .cursor_pointer()
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint_a(GLASS_2), 0.0),
            linear_color_stop(paint_a(GLASS_1), 1.0),
        ))
        .border_1()
        .border_color(paint_a(BORDER_CONTROL))
        .shadow(vec![shadow(0x00000035, 0.0, 2.0, 8.0, 0.0)])
        .hover(|s| s.bg(paint_a(0xffffff20)).border_color(paint_a(0xffffff8a)).relative().top(px(-1.0)))
        .active(|s| s.bg(paint_a(0xffffff0a)))
        .child(label.to_string())
}

/// A compact danger key for a row that already carries its own label: the
/// dock's per-lane Stop, which at full key size outweighed the task it stops.
pub fn danger_s(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(SPACE_2XL))
        .px(px(SPACE_M))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(6.0))
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(paint(DANGER))
        .text_size(px(12.0))
        .line_height(px(LINE_12))
        .cursor_pointer()
        .bg(paint_a(DANGER_WASH))
        .border_1()
        .border_color(paint_a(DANGER_EDGE))
        .hover(|s| s.bg(paint_a(0xff6b5e3d)))
        .active(|s| s.opacity(0.85))
        .child(label.to_string())
}

/// Danger button: danger wash fill, danger text.
pub fn danger(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(CONTROL_H))
        .px(px(SPACE_XL))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(10.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(paint(0xffd0ca))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint_a(0xff6b5e35), 0.0),
            linear_color_stop(paint_a(DANGER_WASH), 1.0),
        ))
        .border_1()
        .border_color(paint_a(DANGER_EDGE))
        .hover(|s| s.bg(paint_a(0xff6b5e3d)))
        .active(|s| s.opacity(0.85))
        .child(label.to_string())
}

/// Wide benchmark run plate: 72px, leading play glyph, big label. The 9px
/// inset is half of (72 - 54): it centres the well, so it is geometry, not a
/// spacing step.
pub fn plate_wide(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .min_w(px(340.0))
        .h(px(CONTROL_H + SPACE_2XL))
        .flex()
        .items_center()
        .gap(px(SPACE_XL))
        .px(px(9.0))
        .pr(px(SPACE_XL))
        .rounded(px(10.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(paint(INK_2))
        .cursor_pointer()
        .border_1()
        .border_color(paint(BEZEL_EDGE))
        .bg(paint(BEZEL_LO))
        .hover(|s| s.bg(paint(BEZEL_HI)).text_color(paint(INK)))
        .active(|s| s.bg(paint(WELL)))
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
        .h(px(PILL_H))
        .px(px(SPACE_S))
        .flex()
        .items_center()
        .font_family(MONO)
        .text_size(px(11.0))
        .line_height(px(LINE_11))
        .text_color(paint(INK_2))
        .child(text.to_string())
}

/// Keyboard keycap chip. The face is a small mechanical capital, so it is
/// tracked like a label; the bezel, not a private height, sets its size.
pub fn keycap(text: &str) -> Div {
    div()
        .min_w(px(SPACE_2XL))
        .h(px(PILL_H))
        .px(px(SPACE_S))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.0))
        .border_1()
        .border_color(paint(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint(BEZEL_HI), 0.0),
            linear_color_stop(paint(BEZEL_LO), 1.0),
        ))
        .shadow(vec![shadow(0x00000066, 0.0, 2.0, 4.0, 0.0)])
        .child(tracked(
            &text.to_uppercase(),
            12.0,
            0.5,
            INK_2,
            FontWeight::NORMAL,
        ))
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
    let columns = rows.iter().map(|r| r.len()).max().unwrap_or(0);
    let width = columns as f32 * dot + columns.saturating_sub(1) as f32 * gap;
    let height = rows.len() as f32 * dot + rows.len().saturating_sub(1) as f32 * gap;
    let mut grid = div().w(px(width)).h(px(height)).flex_none().flex().flex_col().gap(px(gap));
    let mut index = 0usize;
    for r in rows {
        let mut line = div().w(px(width)).h(px(dot)).flex_none().flex().gap(px(gap));
        for ch in r.chars() {
            let lit = ch == '#';
            let d = div().size(px(dot)).flex_none().rounded(px(1.5));
            let d: gpui::AnyElement = if lit {
                let base = d.bg(paint(color)).shadow(vec![BoxShadow {
                    color: paint(color).into(),
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
                    // another, so the sign never goes dark all at once. It
                    // runs BLINKS rounds when the tag appears, then rests lit:
                    // a question can wait for days, and a loop would redraw
                    // the whole window every frame for all of them (#184).
                    let phase = index as f32 / lit_dots as f32;
                    base.with_animation(
                        gpui::ElementId::named_usize(format!("{id}-blink"), index),
                        Animation::new(std::time::Duration::from_millis(1200 * BLINKS as u64))
                            .with_easing(|t| t),
                        move |el, t| {
                            let k = (t * BLINKS as f32 + phase).fract();
                            el.opacity(if t >= 1.0 || k < 0.6 { 1.0 } else { 0.25 })
                        },
                    )
                    .into_any_element()
                } else {
                    base.into_any_element()
                };
                index += 1;
                cell
            } else {
                d.bg(paint(LED_OFF)).into_any_element()
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

/// How many marquee rounds a needs-you tag runs before it rests lit.
const BLINKS: u32 = 3;

/// State tag: LED glyph plus a word, always both. The LED animates the way
/// the CSS does: NEEDS YOU blinks a few rounds, LIVE boots once on mount. `motion ==
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
        .h(px(PILL_H))
        .px(px(SPACE_S))
        .flex()
        .items_center()
        .gap(px(SPACE_S))
        .rounded(px(8.0))
        .border_1()
        .border_color(paint_a(HAIRLINE));
    let base = match state {
        TagState::Need => base
            .bg(linear_gradient(
                180.0,
                linear_color_stop(paint(BRAND_HOVER), 0.0),
                linear_color_stop(hsla(BRAND), 1.0),
            ))
            .border_color(fixed_a(0xffffff40)),
        TagState::Block => base.bg(paint_a(DANGER_WASH)),
        _ => base.bg(paint(WELL)),
    };
    // The state is part of the animation's id: a tag that changes from Queue
    // to Live remounts its LED matrix, so the boot flicker replays and the
    // change is seen, not just read.
    let state_key = match state {
        TagState::Live => 1,
        TagState::Need => 2,
        TagState::Queue => 3,
        TagState::Done => 4,
        TagState::Block => 5,
    };
    base.child(led_matrix_anim(
        &format!("{id}-{state_key}"),
        glyph,
        led,
        3.0,
        1.0,
        anim,
        motion,
    ))
    // The state word is the tag's label, so it is tracked; an empty label
    // leaves the glyph alone rather than trailing the row's gap.
    .when(!label.is_empty(), |d| {
        d.child(tracked(
            &label.to_uppercase(),
            11.0,
            0.5,
            fg,
            FontWeight::NORMAL,
        ))
    })
}

/// Segment meter, `segments` squares, `value` 0..=100. When `live`, the
/// leading lit segment blinks (`.k-meter i.head`); `motion == false` freezes it.
pub fn meter(value: f32, segments: usize) -> Div {
    // The global switch is set from `app.motion` once per frame. A hard `true`
    // here animated the GPU memory meter under Reduce motion.
    meter_live("meter", value, segments, false, motion_on())
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
        .bg(paint(ICE));
    if motion {
        let sheen = div()
            .absolute()
            .top_0()
            .h_full()
            .w(relative(0.35))
            .bg(linear_gradient(
                90.0,
                linear_color_stop(fixed_a(0xffffff00), 0.0),
                linear_color_stop(fixed_a(0xffffffb0), 0.5),
            ))
            .with_animation(
                gpui::ElementId::Name(SharedString::from(format!("{id}-sheen"))),
                Animation::new(std::time::Duration::from_millis(1400))
                    .repeat()
                    .with_easing(|t| t),
                // from just off the left edge to just off the right
                |el, t| el.left(relative(-0.35 + 1.35 * t)),
            );
        // A soft head at the leading edge: the bar is alive even when the
        // value has not moved, and the eye lands on where it has reached.
        let head = div()
            .absolute()
            .top(px(-2.0))
            .right(px(-2.0))
            .size(px(8.0))
            .rounded_full()
            .bg(paint(ICE))
            .shadow(vec![BoxShadow {
                color: gpui::Hsla { a: 0.7, ..Hsla::from(paint(ICE)) },
                offset: point(px(0.0), px(0.0)),
                blur_radius: px(6.0),
                spread_radius: px(0.0),
            }])
            .with_animation(
                gpui::ElementId::Name(SharedString::from(format!("{id}-head"))),
                Animation::new(std::time::Duration::from_millis(1100))
                    .repeat()
                    .with_easing(|t| t),
                |el, t| el.opacity(0.6 + 0.4 * (1.0 - t)),
            );
        fill = fill.child(sheen).child(head);
    }
    div()
        .h(px(4.0))
        .w_full()
        .rounded(px(2.0))
        .overflow_hidden()
        .bg(paint_a(GLASS_2))
        .child(fill)
}

/// A working indicator: three round LEDs breathing in turn, left to right,
/// like a carrier signal. Round and soft, so it reads as "alive" beside a
/// segment meter without becoming a second grid. Still, it rests with the
/// middle LED lit and the outer two dim.
pub fn led_ripple(id: &str, motion: bool) -> gpui::AnyElement {
    fn lit(el: Div, level: f32) -> Div {
        let alpha = (36.0 + 219.0 * level) as u32;
        el.bg(paint_a((ICE << 8) | alpha.min(255))).shadow(vec![BoxShadow {
            color: gpui::Hsla { a: 0.55 * level, ..Hsla::from(paint(ICE)) },
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
            let cell = seg.bg(paint(ICE)).shadow(vec![BoxShadow {
                color: paint(ICE).into(),
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
            } else if motion {
                // Each new lit segment drops in after the one before it, so a
                // meter that steps forward reads as filling rather than as a
                // number that changed. Keyed on the count, so it replays only
                // when the value actually moves.
                let delay = (i.min(10) as f32) * 0.05;
                cell.with_animation(
                    gpui::ElementId::named_usize(format!("{head_id}-led"), i * 64 + lit),
                    Animation::new(std::time::Duration::from_millis(tempo_ms(320)))
                        .with_easing(|t| t),
                    move |el, t| {
                        let u = ((t - delay) / (1.0 - delay).max(0.01)).clamp(0.0, 1.0);
                        let e = ease_mech(u);
                        el.opacity(0.25 + 0.75 * e)
                            .relative()
                            .top(px((1.0 - e) * amp(4.0)))
                    },
                )
                .into_any_element()
            } else {
                cell.into_any_element()
            }
        } else {
            seg.bg(paint(LED_OFF)).into_any_element()
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
            seg.bg(paint(ICE)).shadow(vec![BoxShadow {
                color: paint(ICE).into(),
                offset: point(px(0.0), px(0.0)),
                blur_radius: px(5.0),
                spread_radius: px(0.0),
            }])
        } else {
            seg.bg(paint(LED_OFF))
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
        .bg(paint(if on { ICE } else { LED_OFF }));
    let knob_base = div()
        .absolute()
        .top(px(2.0))
        .w(px(24.0))
        .h(px(24.0))
        .rounded(px(12.0))
        .border_1()
        .border_color(paint(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint(BEZEL_HI), 0.0),
            linear_color_stop(paint(BEZEL_LO), 1.0),
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
                    // a 2px margin to the track wall on both sides
                    let x = 2.0 + if on { travel * m } else { travel * (1.0 - m) };
                    el.left(px(x))
                },
            )
            .into_any_element()
    } else {
        knob_base
            .left(px(2.0 + if on { travel } else { 0.0 }))
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
        .bg(paint(WELL))
        .border_1()
        .border_color(paint_a(BORDER_CONTROL))
        .cursor_pointer()
        .child(knob)
}

/// The k-seg thumb: the bezel square that slides to the picked cell.
/// `from`/`to` are cell indexes; the slide plays once when the id changes.
pub fn segmented_thumb(id_key: u64, from: usize, to: usize, motion: bool) -> gpui::AnyElement {
    let thumb = div()
        .absolute()
        .top(px(SPACE_XS))
        .h(px(CONTROL_H))
        .w(px(SEG_CELL_W))
        .rounded(px(10.0))
        .border_1()
        .border_color(paint(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(paint(BEZEL_HI), 0.0),
            linear_color_stop(paint(BEZEL_LO), 1.0),
        ))
        .shadow(vec![
            shadow(0xffffff14, 0.0, 0.0, 0.0, 0.0),
            shadow(0x0000008c, 0.0, 6.0, 16.0, 0.0),
        ]);
    if motion {
        let start = SPACE_XS + SEG_STEP * from as f32;
        let end = SPACE_XS + SEG_STEP * to as f32;
        thumb
            .with_animation(
                gpui::ElementId::NamedInteger(SharedString::from("seg-thumb"), id_key),
                Animation::new(std::time::Duration::from_millis(260)),
                move |el, t| el.left(px(start + (end - start) * ease_mech(t))),
            )
            .into_any_element()
    } else {
        thumb
            .left(px(SPACE_XS + SEG_STEP * to as f32))
            .into_any_element()
    }
}

/// One k-seg cell's width, and the step between two cells: the track's gap.
/// The thumb's travel is `SEG_STEP`, so the two cannot drift apart.
const SEG_CELL_W: f32 = 56.0;
const SEG_STEP: f32 = SEG_CELL_W + SPACE_XS;

/// The k-seg track: a well holding the thumb and the LED cells. The cells are
/// built by the caller (they carry the click listeners).
pub fn segmented_track() -> Div {
    well()
        .relative()
        .p(px(SPACE_XS))
        .flex()
        .gap(px(SPACE_XS))
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
        .w(px(SEG_CELL_W))
        .h(px(CONTROL_H))
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
        .flex_none()
}

/// One section's own glyph in a small well, then the eyebrow title. Every
/// card wears one, so a screen is read by shapes before it is read by words.
/// The glyph wakes once when the card appears and then rests; looping it would
/// redraw the window for as long as the page is open (#184).
pub fn icon_alive(
    name: &str,
    size: f32,
    key: &str,
    index: usize,
    motion: bool,
) -> gpui::AnyElement {
    let base = div()
        .flex_none()
        .rounded(px(6.0))
        .bg(paint_a(GLASS_1))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .flex()
        .items_center()
        .justify_center()
        .child(icon(name, size).text_color(paint(ICE)));
    if motion {
        let full = size + 9.0;
        let delay = (index.min(8) as f32) * 0.055;
        base.with_animation(
            gpui::ElementId::Name(format!("alive-{key}-{index}").into()),
            Animation::new(std::time::Duration::from_millis(tempo_ms(560))).with_easing(|t| t),
            move |d, t| {
                let u = ((t - delay) / (1.0 - delay).max(0.01)).clamp(0.0, 1.0);
                let e = ease_mech(u);
                let s = full * (1.0 - (1.0 - e).max(0.0) * amp(0.55).min(0.9));
                d.size(px(s))
                    .opacity(u)
                    .relative()
                    .top(px((1.0 - e) * amp(5.0)))
            },
        )
        .into_any_element()
    } else {
        base.size(px(size + 9.0)).into_any_element()
    }
}

/// A card header: its glyph and its name, at one distance on every screen.
pub fn card_head(icon_name: &str, label: &str, motion: bool) -> Div {
    card_head_row(icon_name, label, None, motion)
}

/// A card header with a control on the right (a refresh, a count, a toggle).
pub fn card_head_row(
    icon_name: &str,
    label: &str,
    control: Option<gpui::AnyElement>,
    motion: bool,
) -> Div {
    div()
        // The head sits one small step above its body. A card that also sets
        // its own gap gets that step twice, which is why the card's gap and
        // this one are both on the scale rather than eyeballed.
        .mb(px(SPACE_XS))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(SPACE_S))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(SPACE_S))
                .child(icon_alive(icon_name, 14.0, label, 0, motion))
                .child(eyebrow(label)),
        )
        .children(control.map(|c| div().flex_none().child(c)))
}

/// A loading mark: the loader arc turning while the engine answers. It stays
/// still under reduced motion, so the wait is still shown without movement.
pub fn spinner(id: impl Into<SharedString>, size: f32, motion: bool) -> gpui::AnyElement {
    let base = icon("loader", size).text_color(paint(ICE));
    if motion {
        base.with_animation(
            gpui::ElementId::Name(id.into()),
            Animation::new(std::time::Duration::from_millis(900)).repeat(),
            |mark, t| mark.with_transformation(Transformation::rotate(percentage(t))),
        )
        .into_any_element()
    } else {
        base.into_any_element()
    }
}

/// One line of the sidebar rail: a lit glyph well, the label, and the engine's
/// count. The active row wears a brand wash with a lit left edge; a hovered
/// row glides up a hair. Collapsed (`label` empty) the row is only its well.
/// `count` is a quiet pill (Browse 760); `badge` is the brand needs-you pill
/// (Activity).
pub fn nav_item(
    id: impl Into<gpui::ElementId>,
    icon_name: &str,
    label: &str,
    current: bool,
    count: Option<&str>,
    badge: Option<&str>,
) -> Stateful<Div> {
    let collapsed = label.is_empty();
    // The glyph's own well lights when the row is the one on screen, so the
    // rail reads by shape before it reads by word.
    let glyph = div()
        .flex_none()
        // One step under the row: the well centres in 44 with room above and
        // below, and lands on the 4px scale rather than at an eyeballed 30.
        .size(px(SPACE_XL + SPACE_XS))
        .rounded(px(8.0))
        .flex()
        .items_center()
        .justify_center()
        .bg(paint_a(if current { 0x1f4fff3d } else { GLASS_1 }))
        .border_1()
        .border_color(paint_a(if current { 0x86a3ff48 } else { HAIRLINE }))
        .child(icon(icon_name, 18.0).text_color(paint(if current { ICE } else { MUTED })));
    let mut row = div()
        .id(id)
        .relative()
        // A rail row is a control plus one step: 44, taller than a button so
        // the glyph well and the label share a centre.
        .h(px(CONTROL_H + SPACE_XS))
        .flex_none()
        .flex()
        .items_center()
        .rounded(px(10.0))
        .font_family(SANS)
        .text_size(px(14.0))
        .line_height(px(LINE_14))
        .cursor_pointer()
        .gap(px(if collapsed { 0.0 } else { SPACE_M }))
        .px(px(if collapsed { 0.0 } else { SPACE_S }))
        .when(collapsed, |d| d.justify_center())
        .when(current, |d| {
            d.bg(paint_a(BRAND_WASH))
                .text_color(paint(INK))
                .font_weight(FontWeight::SEMIBOLD)
                .hover(|h| h.relative().top(px(-1.0)))
        })
        .when(!current, |d| {
            d.text_color(paint(MUTED))
                .hover(|h| h.bg(paint_a(GLASS_1)).text_color(paint(INK)).relative().top(px(-1.0)))
        })
        .child(glyph);
    if !collapsed {
        row = row.child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .overflow_hidden()
                .whitespace_nowrap()
                .text_ellipsis()
                .child(label.to_string()),
        );
    }
    if let Some(c) = count {
        row = row.child(
            div()
                .flex_none()
                .h(px(PILL_H))
                .min_w(px(SPACE_XL))
                .px(px(SPACE_XS))
                .rounded_full()
                .flex()
                .items_center()
                .justify_center()
                .bg(paint_a(GLASS_1))
                .border_1()
                .border_color(paint_a(HAIRLINE))
                .font_family(MONO)
                .text_size(px(11.0))
                .line_height(px(LINE_11))
                .text_color(paint(if current { ICE } else { DIM }))
                .child(c.to_string()),
        );
    }
    if let Some(b) = badge {
        row = row.child(
            div()
                .flex_none()
                .h(px(PILL_H))
                .min_w(px(SPACE_XL))
                .px(px(SPACE_XS))
                .rounded_full()
                .flex()
                .items_center()
                .justify_center()
                .bg(paint(BRAND))
                .shadow(vec![shadow(0x0f2a9c99, 0.0, 2.0, 0.0, 0.0)])
                .font_family(MONO)
                .text_size(px(11.0))
                .line_height(px(LINE_11))
                .text_color(fixed(0xffffff))
                .child(b.to_string()),
        );
    }
    if current && !collapsed {
        // The lit left edge: the rail's own "you are here" light.
        row = row.child(
            div()
                .absolute()
                .left(px(0.0))
                .top(px(SPACE_S))
                .bottom(px(SPACE_S))
                .w(px(2.5))
                .rounded_full()
                .bg(paint(BRAND_BRIGHT)),
        );
    }
    row
}

/// The brand block on top of the sidebar: flat brand rectangle, white wordmark.
pub fn reveal(child: impl IntoElement, id: impl Into<SharedString>, open: bool, height: f32, motion: bool) -> gpui::AnyElement {
    Reveal { id: gpui::ElementId::Name(id.into()), child: Some(child.into_any_element()), open, height, motion }.into_any_element()
}

/// Page arrival keeps the natural layout while fading and rising twelve pixels.
/// Unlike a drawer, it never clips a long page through a changing max-height.
pub fn arrive(child: impl IntoElement, id: impl Into<SharedString>, motion: bool) -> gpui::AnyElement {
    // w_full: the page is as wide as its column. Without it a screen was sized
    // by its widest child's natural width, so a table could narrow the page.
    let base = div().relative().flex_none().w_full().child(child);
    if motion {
        base.with_animation(
            gpui::ElementId::Name(id.into()),
            Animation::new(std::time::Duration::from_millis(tempo_ms(260))),
            |d, t| {
                let t = t * t * (3.0 - 2.0 * t);
                d.opacity(t).top(px(amp(12.0) * (1.0 - t)))
            },
        ).into_any_element()
    } else { base.into_any_element() }
}

/// A page change slides: the arriving screen fades in while it travels from
/// the side it belongs on. `from_left` is true when the new tab sits earlier
/// in the rail, so the page comes in from the left and travels right, the way
/// the eye followed the click. Keyed on the tab, so it plays once per switch;
/// `motion == false` draws it still.
pub fn slide_page(
    child: impl IntoElement,
    key: &str,
    from_left: bool,
    motion: bool,
) -> gpui::AnyElement {
    // w_full: like `arrive`, the page keeps its column width while it slides,
    // so a wide table never drags the page narrow on the way in.
    let base = div().relative().flex_none().w_full().child(child);
    if motion {
        let start = if from_left { -amp(28.0) } else { amp(28.0) };
        base.with_animation(
            gpui::ElementId::Name(format!("slide-{key}").into()),
            Animation::new(std::time::Duration::from_millis(tempo_ms(300))),
            move |d, t| {
                let e = t * t * (3.0 - 2.0 * t);
                d.opacity(e).left(px(start * (1.0 - e)))
            },
        )
        .into_any_element()
    } else {
        base.into_any_element()
    }
}

/// One section of a page, rising once when the page arrives. `index` staggers
/// the sections, so a screen assembles rather than appearing whole: the title
/// first, then the cards under it. Full-width sections only (a grid item must
/// keep its `flex_1`); a one-shot, never a loop.
pub fn enter(
    child: impl IntoElement,
    key: &str,
    index: usize,
    motion: bool,
) -> gpui::AnyElement {
    let base = div().relative().flex_none().w_full().child(child);
    if motion {
        let delay = (index.min(10) as f32) * 0.055;
        base.with_animation(
            gpui::ElementId::Name(format!("enter-{key}-{index}").into()),
            Animation::new(std::time::Duration::from_millis(tempo_ms(460))).with_easing(|t| t),
            move |d, t| {
                let u = ((t - delay) / (1.0 - delay).max(0.01)).clamp(0.0, 1.0);
                let e = ease_mech(u);
                d.opacity(u).relative().top(px((1.0 - e) * amp(16.0)))
            },
        )
        .into_any_element()
    } else {
        base.into_any_element()
    }
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
        .bg(paint(BRAND))
        .px(px(SPACE_XL))
        .pt(px(SPACE_L))
        .pb(px(SPACE_L))
        .flex()
        .flex_col()
        .gap(px(SPACE_S))
        .child(
            div().flex().items_center().gap(px(SPACE_M)).child(svg()
                .path(SharedString::from(wordmark))
                .w(px(66.4))
                .h(px(22.0))
                .flex_none()
                .text_color(fixed(0xffffff))).child(div().flex_none().font_family(MONO).text_size(px(11.0)).text_color(fixed(ICE)).px(px(6.0)).py(px(3.0)).border_1().border_color(fixed_a(0xffffff59)).rounded(px(4.0)).child("BETA")),
        )
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(fixed(0xffffffd9))
                .child(tagline.to_string()),
        )
}

#[cfg(test)]
mod grid_tests {
    use super::*;

    /// The page's content width at a window width: the window less the
    /// expanded sidebar and the page gutter on both sides.
    fn content_at(window_w: f32) -> f32 {
        window_w - SIDEBAR_W - 2.0 * PAGE_PAD
    }

    #[test]
    fn the_smallest_window_keeps_two_columns_where_cards_are_wide_enough() {
        // 940x640 is the minimum window; its content is 644 px wide
        let w = content_at(940.0);
        assert_eq!(column_count(w, 300.0, 3), 2);
        assert_eq!(column_count(w, 200.0, 4), 3);
    }

    #[test]
    fn the_common_window_fits_three_cards_of_three_hundred() {
        // 1280x800: 984 px of content
        let w = content_at(1280.0);
        assert_eq!(column_count(w, 300.0, 3), 3);
        assert_eq!(column_count(w, 300.0, 2), 2, "the cap wins over the width");
    }

    #[test]
    fn a_narrow_column_stacks_instead_of_squeezing() {
        assert_eq!(column_count(300.0, 300.0, 3), 1);
        assert_eq!(column_count(200.0, 300.0, 3), 1);
        assert_eq!(column_count(0.0, 300.0, 3), 1);
    }

    #[test]
    fn the_gaps_between_columns_count_against_the_width() {
        // two of 300 need the gap between them as well, not just 600
        let need = 600.0 + SPACE_CARD;
        assert_eq!(column_count(need - 1.0, 300.0, 3), 1);
        assert_eq!(column_count(need, 300.0, 3), 2);
    }

    #[test]
    fn a_single_item_or_cap_never_asks_for_more_than_one_column() {
        assert_eq!(column_count(2000.0, 300.0, 1), 1);
        assert_eq!(column_count(2000.0, 300.0, 0), 1);
    }
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

#[cfg(test)]
mod palette_tests {
    use super::*;
    use crate::contrast::{luminance, ratio};

    /// Every colour used for body text in either theme, against the three
    /// grounds it can sit on. A token that passes on the page but not in a
    /// well is the kind of thing only a screenshot finds.
    #[test]
    fn light_body_text_clears_four_and_a_half_to_one() {
        let grounds = [0xfbfcffu32, 0xffffffff, 0xeef2f9];
        for token in [0xf2f5ffu32, 0xc9d1ea, 0x98a3c2, 0x8893b2, 0xbfe4ff, 0x86a3ff, 0xff6b5e, 0xffb86b] {
            let ink = light_colour(token);
            for ground in grounds {
                let got = ratio(luminance(ink), luminance(ground));
                assert!(
                    got >= 4.5,
                    "light {token:06x} -> {ink:06x} on {ground:06x} is {got:.2}:1"
                );
            }
        }
    }

    #[test]
    fn dark_body_text_clears_four_and_a_half_to_one() {
        for ink in [INK, INK_2, MUTED, DIM, ICE, BRAND_BRIGHT, DANGER] {
            let got = ratio(luminance(ink), luminance(GROUND));
            assert!(got >= 4.5, "dark {ink:06x} on ground is {got:.2}:1");
        }
    }

    /// The names the screens paint through. A new opaque surface token that
    /// forgets its light value would stay a dark island in the white theme.
    #[test]
    fn every_surface_token_has_a_light_value() {
        for token in [
            GROUND, SURFACE_1, BRAND_HOVER, BRAND_BRIGHT, ICE, INK, INK_2, MUTED, DIM,
            DANGER, WARN, WELL, LED_OFF, LED_DIM, BEZEL_HI, BEZEL_LO, BEZEL_EDGE,
        ] {
            assert_ne!(light_colour(token), token, "{token:06x} has no light value");
        }
        assert_eq!(light_colour(BRAND), BRAND, "the brand is the same blue in both themes");
        assert_eq!(light_colour(0xffffff), 0xffffff, "on-brand words stay white");
    }

    #[test]
    fn the_dark_palette_is_unchanged_by_the_light_mapping() {
        set_light(false);
        assert_eq!(paint(INK), rgb(INK));
        assert_eq!(paint_a(HAIRLINE), rgba(HAIRLINE));
    }
}
