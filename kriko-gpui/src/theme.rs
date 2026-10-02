//! KRIKO theme for GPUI. One file: colours, shadows, and the small builders
//! (key, plate, well, LED matrix, tag, meter, switch, agent tile, hero, frost,
//! input, verdict, keycap, badge). Everything uses only primitives GPUI has:
//! fills, gradients, 1px borders, outer box shadows, images, SVG alpha masks.
//! There is no backdrop blur and no inset shadow, so "wells" are a darker fill
//! plus a hairline ring, and "frost" is a translucent fill over the sky image.

use gpui::{
    div, img, linear_color_stop, linear_gradient, point, px, rgb, rgba, svg, prelude::*, Animation,
    AnimationExt, BoxShadow, Div, FontWeight, Hsla, ObjectFit, SharedString, Stateful, StyledImage,
    Svg, TextAlign,
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

/// Monogram letters for agents without an official icon (5x5).
pub const LETTERS: [(&str, [&str; 5]); 26] = [
    ("A", [".###.", "#...#", "#####", "#...#", "#...#"]),
    ("B", ["####.", "#...#", "####.", "#...#", "####."]),
    ("C", [".###.", "#....", "#....", "#....", ".###."]),
    ("D", ["####.", "#...#", "#...#", "#...#", "####."]),
    ("E", ["#####", "#....", "####.", "#....", "#####"]),
    ("F", ["#####", "#....", "####.", "#....", "#...."]),
    ("G", [".###.", "#....", "#.###", "#...#", ".###."]),
    ("H", ["#...#", "#...#", "#####", "#...#", "#...#"]),
    ("I", ["#####", "..#..", "..#..", "..#..", "#####"]),
    ("J", ["..###", "...#.", "...#.", "#..#.", ".##.."]),
    ("K", ["#..#.", "#.#..", "##...", "#.#..", "#..#."]),
    ("L", ["#....", "#....", "#....", "#....", "#####"]),
    ("M", ["#...#", "##.##", "#.#.#", "#...#", "#...#"]),
    ("N", ["#...#", "##..#", "#.#.#", "#..##", "#...#"]),
    ("O", [".###.", "#...#", "#...#", "#...#", ".###."]),
    ("P", ["####.", "#...#", "####.", "#....", "#...."]),
    ("Q", [".###.", "#...#", "#.#.#", "#..#.", ".##.#"]),
    ("R", ["####.", "#...#", "####.", "#.#..", "#..#."]),
    ("S", [".####", "#....", ".###.", "....#", "####."]),
    ("T", ["#####", "..#..", "..#..", "..#..", "..#.."]),
    ("U", ["#...#", "#...#", "#...#", "#...#", ".###."]),
    ("V", ["#...#", "#...#", "#...#", ".#.#.", "..#.."]),
    ("W", ["#...#", "#...#", "#.#.#", "##.##", "#...#"]),
    ("X", ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"]),
    ("Y", ["#...#", ".#.#.", "..#..", "..#..", "..#.."]),
    ("Z", ["#####", "...#.", "..#..", ".#...", "#####"]),
];

pub fn letter_rows(letter: char) -> [&'static str; 5] {
    let upper = letter.to_ascii_uppercase().to_string();
    for (name, rows) in LETTERS {
        if *name == upper {
            return rows;
        }
    }
    QUEUE5
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

/// The hero band: the dithered sky PNG fills the box and fades into GROUND.
/// Add children (the page head) after calling.
pub fn hero(sky_path: impl Into<SharedString>, height: f32) -> Div {
    let sky: SharedString = sky_path.into();
    div()
        .relative()
        .w_full()
        .h(px(height))
        .overflow_hidden()
        .bg(rgb(GROUND))
        .child(
            img(embedded(sky))
                .absolute()
                .top_0()
                .left_0()
                .size_full()
                .object_fit(ObjectFit::Cover),
        )
}

/// The img source that reads from the embedded AssetSource. A bare string
/// would be parsed as a URI and the load would silently fail.
pub fn embedded(path: SharedString) -> gpui::ImageSource {
    gpui::ImageSource::Resource(gpui::Resource::Embedded(path))
}

/// Page head over the hero: mono crumb, display title, one lead line.
pub fn page_head(crumb: &str, title: &str, lead: &str) -> Div {
    div()
        .absolute()
        .top_0()
        .left_0()
        .w_full()
        .h_full()
        .px(px(40.0))
        .pt(px(22.0))
        .flex()
        .flex_col()
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .font_family(MONO)
                .text_size(px(12.0))
                .child(div().text_color(rgb(BRAND_BRIGHT)).child("kriko /"))
                .child(div().text_color(rgb(INK_2)).child(crumb.to_uppercase())),
        )
        .child(
            div()
                .mt(px(8.0))
                .font_family(DISPLAY)
                .font_weight(FontWeight::SEMIBOLD)
                .text_size(px(56.0))
                .line_height(px(56.0))
                .text_color(rgb(INK))
                .child(title.to_uppercase()),
        )
        .when(!lead.is_empty(), |d| {
            d.child(
                div()
                    .mt(px(16.0))
                    .max_w(px(640.0))
                    .font_family(SANS)
                    .text_size(px(16.0))
                    .line_height(px(24.0))
                    .text_color(rgb(INK_2))
                    .child(lead.to_string()),
            )
        })
}

// ---- the merged window top bar ----

/// One window-control button for the merged titlebar. `close` hovers red.
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
        .child(icon(icon_name, 14.0).text_color(rgb(if close {
            DANGER
        } else {
            MUTED
        })))
        .hover(|s| s.bg(if close { rgba(DANGER_WASH) } else { rgba(GLASS_2) }))
}

/// The merged titlebar strip. The caller passes the maximized state (for the
/// restore/maximize icon) and appends nothing else: children are set inside.
pub fn titlebar() -> Stateful<Div> {
    div()
        .id("kriko-titlebar")
        .h(px(40.0))
        .flex_none()
        .flex()
        .items_center()
        .px(px(12.0))
        .gap(px(12.0))
        .bg(rgb(SURFACE_1))
        .border_b_1()
        .border_color(rgba(HAIRLINE))
}

// ---- controls ----

/// Primary action: blue key with a 3px lip that drops on press.
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

/// Danger button: danger wash fill, danger text.
pub fn danger(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
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
    led_matrix_anim(rows, color, dot, gap, LedAnim::None, true)
}

/// The LED matrix with its animation. `motion == false` draws it static.
/// Boot staggers the lit dots' flicker by index; blink pulses the whole
/// matrix, exactly as `.k-led` does in the CSS.
pub fn led_matrix_anim(
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
                    base
                        .with_animation(
                            ("boot", index),
                            Animation::new(std::time::Duration::from_millis(600))
                                .with_easing(boot_ease(index)),
                            |el, v| el.opacity(v),
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
    if motion && anim == LedAnim::Blink {
        grid.with_animation(
            "blink",
            Animation::new(std::time::Duration::from_millis(1600))
                .repeat()
                .with_easing(|t| t),
            |el, t| el.opacity(if t < 0.5 { 1.0 } else { 0.2 }),
        )
        .into_any_element()
    } else {
        grid.into_any_element()
    }
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
/// false` (Reduce motion) keeps it static.
pub fn tag(state: TagState, label: &str, motion: bool) -> Div {
    let (glyph, led, fg): (&[&str], u32, u32) = match state {
        TagState::Live => (&BANG5, ICE, ICE),
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
    base.child(led_matrix_anim(glyph, led, 3.0, 1.0, anim, motion))
        .child(label.to_uppercase())
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Verdict {
    Recommended,
    WeighUp,
    Avoid,
}

impl Verdict {
    pub fn word(&self) -> &'static str {
        match self {
            Verdict::Recommended => "RECOMMENDED",
            Verdict::WeighUp => "WEIGH UP",
            Verdict::Avoid => "AVOID",
        }
    }
}

/// Verdict chip: LED glyph plus the verdict word, in the verdict colour.
pub fn verdict_chip(verdict: Verdict) -> Div {
    let (glyph, fg, wash): (&[&str], u32, Option<u32>) = match verdict {
        Verdict::Recommended => (&CHECK5, ICE, None),
        Verdict::WeighUp => (&QUEUE5, INK_2, None),
        Verdict::Avoid => (&X5, DANGER, Some(DANGER_WASH)),
    };
    let base = div()
        .h(px(32.0))
        .px(px(12.0))
        .pl(px(8.0))
        .flex()
        .items_center()
        .gap(px(10.0))
        .rounded(px(8.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(15.0))
        .text_color(rgb(fg))
        .border_1()
        .border_color(rgba(HAIRLINE));
    let base = match wash {
        Some(w) => base.bg(rgba(w)),
        None => base.bg(rgb(WELL)),
    };
    base.child(led_matrix(glyph, fg, 3.0, 1.0))
        .child(verdict.word())
}

/// Segment meter, `segments` squares, `value` 0..=100. When `live`, the
/// leading lit segment blinks (`.k-meter i.head`); `motion == false` freezes it.
pub fn meter(value: f32, segments: usize) -> Div {
    meter_live(value, segments, false, true)
}

pub fn meter_live(value: f32, segments: usize, live: bool, motion: bool) -> Div {
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
                    "head",
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
    div()
        .id(id)
        .relative()
        .w(px(56.0))
        .h(px(30.0))
        .rounded(px(15.0))
        .bg(rgb(WELL))
        .border_1()
        .border_color(rgba(BORDER_CONTROL))
        .cursor_pointer()
        .child(knob)
}

/// Agent tile: 40px well. Pass the official icon path, or None for the LED monogram.
pub fn agent_tile(letter_rows: [&str; 5], icon: Option<SharedString>) -> Div {
    let t = well()
        .size(px(40.0))
        .flex()
        .items_center()
        .justify_center();
    match icon {
        Some(p) => t.child(img(embedded(p)).size(px(24.0))),
        None => t.child(led_matrix(&letter_rows, BRAND_BRIGHT, 3.0, 1.0)),
    }
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
            svg()
                .path(SharedString::from(wordmark))
                .w(px(66.4))
                .h(px(22.0))
                .text_color(rgb(0xffffff)),
        )
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(0xffffffd9))
                .child(tagline.to_string()),
        )
}

