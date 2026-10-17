//! KRIKO theme for GPUI. One file: colours, shadows, and the small builders
//! (key, plate, well, LED matrix, tag, meter, switch, agent tile, hero, frost,
//! input, verdict, keycap, badge). Everything uses only primitives GPUI has:
//! fills, gradients, 1px borders, outer box shadows, images, SVG alpha masks.
//! There is no backdrop blur and no inset shadow, so "wells" are a darker fill
//! plus a hairline ring, and "frost" is a translucent fill over the hero.

use gpui::{
    div, img, linear_color_stop, linear_gradient, percentage, point, prelude::*, px, relative, rgb,
    rgba, svg, Animation, AnimationExt, BoxShadow, Div, FontWeight, Hsla, ObjectFit, SharedString,
    Stateful, Styled, StyledImage, Svg, Transformation,
};

// ---- colour tokens (match new-design-16oct/tokens.json) ----
pub const GROUND: u32 = 0x03060f;
pub const SURFACE_1: u32 = 0x060b1a;
pub const SURFACE_2: u32 = 0x0a1226;
pub const BRAND: u32 = 0x2862ff;
pub const BRAND_HOVER: u32 = 0x4a80ff;
pub const BRAND_LOW: u32 = 0x1a48d8;
pub const BRAND_DEEP: u32 = 0x0a1c74;
pub const BRAND_BRIGHT: u32 = 0x9bb8ff;
pub const ICE: u32 = 0xcfe4ff;
pub const INK: u32 = 0xf4f7ff;
pub const INK_2: u32 = 0xd3dcf5;
pub const MUTED: u32 = 0xb3c0e2;
pub const DIM: u32 = 0x9aabd6;
pub const DANGER: u32 = 0xff6f63;
pub const WELL: u32 = 0x050a18;
pub const LED_OFF: u32 = 0x15203f;
pub const LED_DIM: u32 = 0x7086b8;
pub const BEZEL_HI: u32 = 0x27345c;
pub const BEZEL_LO: u32 = 0x111a33;
pub const BEZEL_EDGE: u32 = 0x050916;
// translucent: 0xRRGGBBAA
pub const GLASS_1: u32 = 0x5b8cff14;
pub const GLASS_2: u32 = 0x5b8cff20;
pub const GLASS_3: u32 = 0x5b8cff30;
/// The live dock's panel: the ground colour at 94% so the page behind it
/// reads as a faint shape, never as text competing with the dock's own.
pub const DOCK_GLASS: u32 = 0x060b1af5;
/// The live dock's width. The page reserves this much room while it is open,
/// so controls and text do not disappear beneath the floating panel.
pub const DOCK_WIDTH: f32 = 320.0;
pub const HAIRLINE: u32 = 0x6f95ff24;
pub const BORDER_CONTROL: u32 = 0x7f9cff66;
pub const BRAND_WASH: u32 = 0x2862ff2e;
pub const DANGER_WASH: u32 = 0xff6f6326;
pub const DANGER_EDGE: u32 = 0xff6f6359;
pub const FROST: u32 = 0xecf1ffeb;

// ---- font families (registered at startup from the embedded .ttf files) ----
// These are the family names inside the bundled fonts. The upstream names
// resolve to a system fallback on Windows because these files were renamed.
pub const DISPLAY: &str = "Kriko Display";
pub const SANS: &str = "Kriko Sans";
/// Fixed-width text is reserved for paths, counts, and identifiers.
pub const MONO: &str = "JetBrains Mono";
/// The one place a fixed-width face is still right: text that is code, such
/// as a run's log, where the columns line up. The machine's own, so nothing
/// is shipped for it.
pub const CODE: &str = "Consolas";

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

/// The page column's side gutter, below the hero. The page head uses it too,
/// so the title and the content share one left edge.
pub const PAGE_PAD: f32 = 20.0;
/// Between two sections of one page.
pub const SPACE_SECTION: f32 = 24.0;
/// Between cards that sit side by side or stacked within a section.
pub const SPACE_CARD: f32 = 16.0;
/// Between a section's title and what it holds.
pub const SPACE_TITLE: f32 = 12.0;
/// Inside a card.
pub const PAD_CARD: f32 = 10.0;
/// Inside a dense card: a list of rows, a table, a settings group.
pub const PAD_CARD_TIGHT: f32 = 6.0;

// ---- surfaces ----

/// Open content section. Controls may have an edge; content is not boxed.
pub fn card() -> Div {
    div()
        .border_b_1()
        .border_color(rgba(HAIRLINE))
        .py(px(20.0))
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
pub fn grid(width: f32, min_w: f32, items: Vec<Div>) -> Div {
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
        .bg(rgb(WELL))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .rounded(px(12.0))
}

/// Pale frosted card that floats over a hero image (the one light surface).
#[allow(dead_code)] // a design-system surface, kept for the next hero that needs it
pub fn frost() -> Div {
    div()
        .py(px(16.0))
        .border_b_1()
        .border_color(rgba(HAIRLINE))
}

/// Brand-wash callout panel, full width: tag and lines left, a key right.
pub fn callout() -> Div {
    div()
        .border_b_1()
        .border_color(rgba(HAIRLINE))
        .py(px(20.0))
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

/// Section label from the latest design draft: readable sans, sentence case.
pub fn eyebrow(label: &str) -> Div {
    div()
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(14.0))
        .line_height(px(20.0))
        .text_color(rgb(MUTED))
        .child(label.to_string())
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
    let _ = motion;
    div()
        .relative()
        .w_full()
        .h(px(height))
        .overflow_hidden()
        .bg(rgb(GROUND))
        .child(
            img(embedded(SharedString::from(sky.image())))
                .absolute()
                .bottom_0()
                .left_0()
                .w_full()
                .object_fit(ObjectFit::Cover),
        )
}

/// A translucent brand wash over the sky. It used to breathe on a 14 s loop,
/// which redrew the whole window every frame on every screen for a movement
/// nobody could see (#184); the wash now holds the breath's middle.
fn sky_veil(_motion: bool) -> gpui::AnyElement {
    div()
        .absolute()
        .top_0()
        .left_0()
        .size_full()
        .bg(linear_gradient(
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
pub fn page_head(
    _sky: Sky,
    crumb: &str,
    title: &str,
    lead: &str,
    page_pad: f32,
    motion: bool,
) -> Div {
    div().absolute().top_0().left_0().w_full().h_full().child(
        div()
            .relative()
            .px(px(page_pad))
            .pt(px(58.0))
            .flex()
            .flex_col()
            .gap(px(6.0))
            .child(
                div()
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(rgb(INK_2))
                    .child(crumb.to_string()),
            )
            .child(title_wipe(&title.to_uppercase(), INK, motion))
            .when(!lead.is_empty(), |d| {
                d.child(
                    div()
                        .font_family(SANS)
                        .text_size(px(15.0))
                        .text_color(rgb(INK_2))
                        .child(lead.to_string()),
                )
            }),
    )
}

fn title_wipe(title: &str, ink: u32, motion: bool) -> gpui::AnyElement {
    let text = div()
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(52.0))
        .line_height(px(56.0))
        .text_color(rgb(ink))
        .whitespace_nowrap()
        .child(title.to_string());
    let clip = div().h(px(56.0)).w_full().overflow_hidden().child(text);
    if motion {
        clip.with_animation(
            gpui::ElementId::Name(format!("title-{title}").into()),
            Animation::new(std::time::Duration::from_millis(420)),
            |d, t| d.w(relative((t * 14.0).floor() / 14.0)),
        )
        .into_any_element()
    } else {
        clip.into_any_element()
    }
}

// ---- the merged window top bar ----

/// The sidebar's width. The titlebar floats over everything to its right.
pub const SIDEBAR_W: f32 = 264.0;

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
        .h(px(32.0))
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
                rgba(GLASS_3)
            })
            .text_color(rgb(if close { DANGER } else { INK }))
        })
}

/// Quiet window controls above the section tabs.
pub fn titlebar() -> Stateful<Div> {
    div()
        .id("kriko-titlebar")
        .absolute()
        .top_0()
        .left_0()
        .right_0()
        .h(px(40.0))
        .bg(rgb(GROUND))
        .border_b_1()
        .border_color(rgba(HAIRLINE))
        .flex()
        .items_center()
        .px(px(12.0))
        .gap(px(12.0))
}

// ---- controls ----

/// Flat primary action; a press changes its fill without moving the layout.
pub fn key(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(42.0))
        .px(px(18.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(21.0))
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(rgb(0xffffff))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(rgb(BRAND))
        .hover(|s| s.bg(rgb(BRAND_HOVER)))
        .active(|s| s.bg(rgb(BRAND_LOW)))
        .map(fit_control)
        .child(label.to_string())
}

/// Ghost button: translucent fill, control-coloured ring.
pub fn ghost(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(40.0))
        .px(px(16.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(20.0))
        .font_family(SANS)
        .font_weight(FontWeight::MEDIUM)
        .text_color(rgb(INK_2))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(rgba(GLASS_1))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .hover(|s| s.bg(rgb(BEZEL_HI)))
        .active(|s| s.bg(rgb(WELL)))
        .map(fit_control)
        .child(label.to_string())
}

/// A compact danger key for a row that already carries its own label: the
/// dock's per-lane Stop, which at full key size outweighed the task it stops.
pub fn danger_s(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(32.0))
        .px(px(10.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(6.0))
        .font_family(SANS)
        .font_weight(FontWeight::MEDIUM)
        .text_color(rgb(DANGER))
        .text_size(px(12.0))
        .cursor_pointer()
        .bg(rgba(DANGER_WASH))
        .border_1()
        .border_color(rgba(DANGER_EDGE))
        .hover(|s| s.bg(rgba(DANGER_WASH)))
        .active(|s| s.opacity(0.85))
        .child(label.to_string())
}

/// Danger button: danger wash fill, danger text.
pub fn danger(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .flex_none()
        .h(px(44.0))
        .px(px(18.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(12.0))
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_color(rgb(0xffd0ca))
        .text_size(px(15.0))
        .cursor_pointer()
        .bg(rgba(DANGER_WASH))
        .border_1()
        .border_color(rgba(DANGER_EDGE))
        .hover(|s| s.bg(rgba(DANGER_WASH)))
        .active(|s| s.opacity(0.85))
        .child(label.to_uppercase())
}

/// Wide benchmark run plate: 72px, leading play glyph, big label.
pub fn plate_wide(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    key(id, label).child(icon("run", 18.0).text_color(rgb(0xffffff)))
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
    // The new identity uses the SVG icon set for status. Keep the pixel
    // matrices only for the few controls that are deliberately machine-like.
    let status = if rows == CHECK5.as_slice() {
        Some(("check", ICE))
    } else if rows == BANG5.as_slice() {
        Some(("alert", DANGER))
    } else if rows == X5.as_slice() {
        Some(("x", DANGER))
    } else if rows == QUEUE5.as_slice() {
        Some(("clock", MUTED))
    } else if rows == PLAY5.as_slice() {
        Some(("run", BRAND_BRIGHT))
    } else {
        None
    };
    if let Some((name, tint)) = status {
        return icon(name, (dot * 3.0 + gap * 2.0).max(14.0))
            .text_color(rgb(tint))
            .into_any_element();
    }
    let lit_dots = rows
        .iter()
        .flat_map(|r| r.chars())
        .filter(|c| *c == '#')
        .count();
    let columns = rows.iter().map(|r| r.len()).max().unwrap_or(0);
    let width = columns as f32 * dot + columns.saturating_sub(1) as f32 * gap;
    let height = rows.len() as f32 * dot + rows.len().saturating_sub(1) as f32 * gap;
    let mut grid = div()
        .w(px(width))
        .h(px(height))
        .flex_none()
        .flex()
        .flex_col()
        .gap(px(gap));
    let mut index = 0usize;
    for r in rows {
        let mut line = div()
            .w(px(width))
            .h(px(dot))
            .flex_none()
            .flex()
            .gap(px(gap));
        for ch in r.chars() {
            let lit = ch == '#';
            let d = div().size(px(dot)).flex_none().rounded(px(1.5));
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

/// How many marquee rounds a needs-you tag runs before it rests lit.
const BLINKS: u32 = 3;

/// State tag: an outline icon and a readable word. Only live work spins.
pub fn tag(id: impl Into<SharedString>, state: TagState, label: &str, motion: bool) -> Div {
    let id: SharedString = id.into();
    let (glyph, fg): (&str, u32) = match state {
        TagState::Live => ("loader", ICE),
        TagState::Need => ("alert", 0xffffff),
        TagState::Queue => ("clock", MUTED),
        TagState::Done => ("check", INK_2),
        TagState::Block => ("x", DANGER),
    };
    let base = div()
        .h(px(28.0))
        .px(px(10.0))
        .flex()
        .items_center()
        .gap(px(8.0))
        .rounded(px(8.0))
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(13.0))
        .text_color(rgb(fg))
        .border_1()
        .border_color(rgba(HAIRLINE));
    let base = match state {
        TagState::Need => base.bg(rgb(BRAND)).border_color(rgba(BRAND)),
        TagState::Block => base.bg(rgba(DANGER_WASH)),
        _ => base.bg(rgb(WELL)),
    };
    let resting = matches!(label.to_ascii_lowercase().as_str(), "ready" | "connected" | "in use" | "available");
    let state_icon = if matches!(state, TagState::Live) && !resting {
        spinner(id, 15.0, motion)
    } else {
        icon(if resting { "check" } else { glyph }, 15.0).text_color(rgb(fg)).into_any_element()
    };
    fit_control(base.flex_none().child(state_icon).child(label.to_uppercase()))
}

/// Content columns stretch sections, while controls keep their natural width.
fn fit_control<T: Styled>(mut element: T) -> T {
    element.style().align_self = Some(gpui::AlignSelf::FlexStart);
    element
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
        el.bg(rgba((ICE << 8) | alpha.min(255)))
            .shadow(vec![BoxShadow {
                color: gpui::Hsla {
                    a: 0.55 * level,
                    ..hsla(ICE)
                },
                offset: point(px(0.0), px(0.0)),
                blur_radius: px(2.0 + 6.0 * level),
                spread_radius: px(0.0),
            }])
    }
    let mut row = div()
        .flex()
        .items_center()
        .gap(px(4.0))
        .flex_none()
        .px(px(2.0));
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
    id: impl Into<SharedString>, value: f32, _segments: usize, live: bool, motion: bool,
) -> Div {
    if live { progress_bar(&id.into(), value / 100.0, motion) }
    else { flat_meter(value) }
}

fn flat_meter(value: f32) -> Div {
    let share = if value.is_finite() { value.clamp(0.0, 100.0) / 100.0 } else { 0.0 };
    div().h(px(4.0)).w_full().rounded(px(2.0)).overflow_hidden().bg(rgba(GLASS_2))
        .child(div().h_full().w(relative(share)).rounded(px(2.0)).bg(rgb(BRAND_BRIGHT)))
}

/// A quiet continuous meter for coverage rows.
pub fn meter_slim(value: f32, _segments: usize) -> Div {
    flat_meter(value).min_w(px(96.0))
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
        .top(px(2.0))
        .w(px(24.0))
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
        thumb.left(px(4.0 + 58.0 * to as f32)).into_any_element()
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

/// One segment: use the same outline icons as navigation and plain numerals.
pub fn segmented_cell(
    id: impl Into<gpui::ElementId>,
    glyph: [&str; 5],
    picked: bool,
) -> Stateful<Div> {
    let tint = if picked { ICE } else { MUTED };
    let mark = if glyph == LIST5 {
        icon("list", 20.0).text_color(rgb(tint)).into_any_element()
    } else if glyph == GRID5 {
        icon("grid", 20.0).text_color(rgb(tint)).into_any_element()
    } else if glyph == COLS5 {
        icon("compare", 20.0).text_color(rgb(tint)).into_any_element()
    } else if let Some(index) = [ONE5, TWO5, THREE5, FOUR5].iter().position(|g| *g == glyph) {
        div()
            .font_family(SANS)
            .font_weight(FontWeight::SEMIBOLD)
            .text_size(px(16.0))
            .text_color(rgb(tint))
            .child((index + 1).to_string())
            .into_any_element()
    } else {
        led_matrix(&glyph, tint, 4.0, 2.0)
    };
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
        .child(mark)
}

/// Sidebar / control icon from the embedded set, tinted with text_color.
pub fn icon(name: &str, size: f32) -> Svg {
    svg()
        .path(SharedString::from(format!("icons/{name}.svg")))
        .size(px(size))
        .flex_none()
}

/// A bundled brand logo, from the assets' `logos/` directory.
pub fn logo(name: &str, size: f32) -> Svg {
    svg()
        .path(SharedString::from(format!("logos/{name}.svg")))
        .size(px(size))
        .flex_none()
}

/// A loading mark: the loader arc turning while the engine answers. It stays
/// still under reduced motion, so the wait is still shown without movement.
pub fn spinner(id: impl Into<SharedString>, size: f32, motion: bool) -> gpui::AnyElement {
    let base = icon("loader", size).text_color(rgb(ICE));
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
        .h(px(50.0))
        .px(px(14.0))
        .flex()
        .items_center()
        .gap(px(12.0))
        .rounded(px(14.0))
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(16.0))
        .cursor_pointer()
        .when(current, |s| {
            s.bg(rgba(BRAND_WASH))
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
            icon(icon_name, 22.0)
                .flex_none()
                .text_color(rgb(if current { ICE } else { MUTED })),
        )
        .when(label.is_empty(), |d| {
            d.px(px(0.0)).gap(px(0.0)).justify_center()
        })
        .when(!label.is_empty(), |d| {
            d.child(div().child(label.to_string()))
                .child(div().flex_1())
        });
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
pub fn reveal(
    child: impl IntoElement,
    id: impl Into<SharedString>,
    open: bool,
    height: f32,
    motion: bool,
) -> gpui::AnyElement {
    Reveal {
        id: gpui::ElementId::Name(id.into()),
        child: Some(child.into_any_element()),
        open,
        height,
        motion,
    }
    .into_any_element()
}

/// A brief opacity transition keeps navigation calm without moving content.
/// Unlike a drawer, it never clips a long page through a changing max-height.
pub fn arrive(
    child: impl IntoElement,
    id: impl Into<SharedString>,
    motion: bool,
) -> gpui::AnyElement {
    // w_full: the page is as wide as its column. Without it a screen was sized
    // by its widest child's natural width, so a table could narrow the page.
    let base = div().relative().flex_none().w_full().child(child);
    if motion {
        base.with_animation(
            gpui::ElementId::Name(id.into()),
            Animation::new(std::time::Duration::from_millis(140)),
            |d, t| {
                let t = t * t * (3.0 - 2.0 * t);
                d.opacity(0.85 + 0.15 * t)
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
    fn into_element(self) -> Self {
        self
    }
}

impl gpui::Element for Reveal {
    type RequestLayoutState = gpui::AnyElement;
    type PrepaintState = ();
    fn id(&self) -> Option<gpui::ElementId> {
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
        window.with_element_state(id.unwrap(), |state: Option<RevealState>, window| {
            let target = if self.open { 1.0 } else { 0.0 };
            let mut state = state.unwrap_or(RevealState {
                from: 0.0,
                target,
                start: std::time::Instant::now(),
            });
            let progress = (state.start.elapsed().as_secs_f32() / 0.26).min(1.0);
            let eased = progress * progress * (3.0 - 2.0 * progress);
            let current = state.from + (state.target - state.from) * eased;
            if target != state.target {
                state.from = current;
                state.target = target;
                state.start = std::time::Instant::now();
            }
            let value = if self.motion { current } else { target };
            if self.motion && (value - target).abs() > 0.001 {
                window.request_animation_frame();
            }
            let mut child = div()
                .flex()
                .flex_col()
                .flex_none()
                .min_h(px(0.0))
                .overflow_hidden()
                .max_h(px(self.height * value))
                .opacity(value)
                // Clip a naturally sized child during the transition. Squeezing
                // its SVGs to zero makes GPUI reject their render requests.
                .child(div().flex_none().child(self.child.take().unwrap()))
                .into_any_element();
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

pub fn brand_block(wordmark: &'static str, _tagline: &str) -> Div {
    div()
        .px(px(10.0))
        .pt(px(8.0))
        .pb(px(20.0))
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(
                    svg()
                        .path(SharedString::from(wordmark))
                        .w(px(80.0))
                        .h(px(24.0))
                        .flex_none()
                        .text_color(rgb(0xffffff)),
                )
                .child(
                    div()
                        .px(px(7.0))
                        .py(px(2.0))
                        .rounded(px(6.0))
                        .border_1()
                        .border_color(rgba(0x9bb8ff80))
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(BRAND_BRIGHT))
                        .child("BETA"),
                ),
        )
        .child(
            div()
                .font_family(SANS)
                .text_size(px(13.0))
                .text_color(rgb(MUTED))
                .child("local product knowledge"),
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
