//! Site marks and source rows: how a source is drawn and how it is opened.
//!
//! A source is a host, a page title and a URL. The row itself fetches nothing:
//! a mark is either the site's own icon, already fetched by `favicons` and
//! waiting in its cache, or a generated one from the host itself. Asking is a
//! set insert, so a redraw costs nothing while the icon is missing or gone.
//!
//! The generated mark mimics a favicon without one: a rounded tile with the
//! host's initial, its colour picked by hashing the host into a small set of
//! the theme's own inks. The same host always draws the same mark, in either
//! theme, and the row stays crisp down to the 16px a footer has room for.

use gpui::{div, img, prelude::*, px, AnyElement, FontWeight};

use crate::favicons;
use crate::theme::*;

/// One source as the app draws and opens it: the host it came from, the page
/// title, the URL a click opens, and whether anything stood behind it.
pub struct Source {
    pub host: String,
    pub title: String,
    pub url: String,
    /// `Some(true)` backed, `Some(false)` disputed, `None` nothing recorded.
    pub backed: Option<bool>,
}

/// The inks a site mark's initial may wear. All are theme names, so the mark
/// follows the light theme; the host's hash picks one, which is enough to tell
/// two sites apart without inventing a palette of raw colours.
const MARK_INKS: [u32; 5] = [ICE, BRAND_BRIGHT, INK_2, BRAND_HOVER, INK];

/// FNV-1a over the host: a small, stable number the mark and the row's
/// animation ids are built from.
fn host_hash(text: &str) -> u64 {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in text.as_bytes() {
        hash ^= *byte as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    hash
}

/// The principal label of a host, past a bare `www.`, and its first letter.
fn host_initial(host: &str) -> String {
    let label = host.trim().trim_start_matches("www.");
    label
        .chars()
        .find(|c| c.is_ascii_alphanumeric())
        .map(|c| c.to_ascii_uppercase().to_string())
        .unwrap_or_else(|| "\u{2022}".to_string())
}

/// The host a URL points at, lowercased and without `www.`; empty when the
/// URL carries nothing that reads as one.
pub fn host_of(url: &str) -> String {
    let rest = url.split_once("://").map(|(_, head)| head).unwrap_or(url);
    let authority = rest.split(['/', '?', '#']).next().unwrap_or(rest);
    let authority = authority.rsplit('@').next().unwrap_or(authority);
    let host = authority.split(':').next().unwrap_or(authority);
    host.trim_start_matches("www.").to_ascii_lowercase()
}

/// A one-line tail of a title, so a long page name does not push the row wide.
fn clip(text: &str, limit: usize) -> String {
    let clean = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if clean.chars().count() <= limit {
        return clean;
    }
    format!(
        "{}…",
        clean.chars().take(limit.saturating_sub(1)).collect::<String>()
    )
}

/// A site mark: the site's own icon once `favicons` has it, and a generated
/// tile in a recessed well until then. The monogram is not a placeholder with
/// an expiry — a site that declares no icon keeps it for good.
///
/// Asking is here rather than in `source_row` so both callers of a mark queue
/// the host, and the cache read is one lock with no network behind it.
pub fn site_mark(host: &str, size: f32) -> gpui::AnyElement {
    favicons::request(host);
    let radius = px((size * 0.24).round());
    if let Some(image) = favicons::cached(host) {
        // Drawn inside the same well as the monogram: a transparent PNG then
        // still reads against a light page instead of vanishing into it.
        return div()
            .flex_none()
            .size(px(size))
            .rounded(radius)
            .bg(paint(WELL))
            .border_1()
            .border_color(paint_a(HAIRLINE))
            .overflow_hidden()
            .child(
                img(gpui::ImageSource::Image(image))
                    .flex_none()
                    .size(px(size))
                    .rounded(radius),
            )
            .into_any_element();
    }
    let ink = MARK_INKS[(host_hash(host) % MARK_INKS.len() as u64) as usize];
    div()
        .flex_none()
        .size(px(size))
        .rounded(radius)
        .bg(paint(WELL))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .flex()
        .items_center()
        .justify_center()
        .font_family(DISPLAY)
        .font_weight(FontWeight::BOLD)
        .text_size(px((size * 0.56).round()))
        .line_height(px(size))
        .text_color(paint(ink))
        .child(host_initial(host))
        .into_any_element()
}

/// The small trust LED beside a source, mapping the same three states as
/// `screens::trust_icon`: a check when it was backed, a bang when it was
/// disputed, a queue when nothing was recorded. It wakes once when a row
/// appears and then rests lit.
fn trust_led(backed: Option<bool>, id: &str, motion: bool) -> AnyElement {
    let (glyph, colour): (&[&str], u32) = match backed {
        Some(true) => (&CHECK5, ICE),
        Some(false) => (&BANG5, WARN),
        None => (&QUEUE5, LED_DIM),
    };
    led_matrix_anim(id, glyph, colour, 3.0, 1.0, LedAnim::Boot, motion)
}

/// One source as a row: its mark, its host and its page title. The whole row
/// is the link — it lifts a pixel on hover and opens the URL in the reader's
/// own browser. A trust LED rides at the end when the source's backing is
/// known.
pub fn source_row(source: &Source, motion: bool) -> gpui::AnyElement {
    let key = host_hash(&source.url) ^ host_hash(&source.host) ^ host_hash(&source.title);
    let host = source.host.clone();
    let title = clip(&source.title, 56);
    let has_title = !title.is_empty();
    let backed = source.backed;
    let url = source.url.clone();
    // A source that is a tool's own name rather than a page — `web_search`,
    // `product_match` — has nothing to open. It used to be drawn as a link
    // anyway: the pointer changed, the row lifted on hover, and the press
    // called `open_url("")` and did nothing at all. A row that promises a page
    // and delivers silence is worse than one that says it is a name.
    let opens = !url.is_empty();
    div()
        .id(gpui::ElementId::NamedInteger(gpui::SharedString::from("source-row"), key))
        .flex()
        .items_center()
        .gap(px(8.0))
        .py(px(3.0))
        .px(px(6.0))
        .mx(px(-6.0))
        .rounded(px(8.0))
        .when(opens, |d| {
            d.cursor_pointer()
                .hover(|s| s.bg(paint_a(GLASS_1)).relative().top(px(-1.0)))
                .on_click(move |_, _, cx| cx.open_url(&url))
        })
        .child(site_mark(&source.host, 18.0))
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(1.0))
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(11.0))
                        .text_color(paint(if opens { ICE } else { MUTED }))
                        .truncate()
                        .child(host),
                )
                .when(has_title, |d| {
                    d.child(
                        div()
                            .font_family(SANS)
                            .text_size(px(13.0))
                            .text_color(paint(INK_2))
                            .truncate()
                            .child(title),
                    )
                }),
        )
        .when(backed.is_some(), |d| {
            d.child(trust_led(
                backed,
                &format!("source-led-{key}"),
                motion,
            ))
        })
        .into_any_element()
}

/// A wrapping row of source rows, for a card footer: the sources a card's
/// claim or answer read. Each row keeps its own mark and its own link.
pub fn source_strip(sources: &[Source], motion: bool) -> gpui::AnyElement {
    let mut strip = div().flex().flex_wrap().items_center().gap(px(4.0)).w_full();
    for (i, source) in sources.iter().enumerate() {
        // An indexed wrapper: identical sources stay distinct elements, so
        // two rows never share one hover or one animation.
        strip = strip.child(
            div()
                .id(("source-strip", i))
                .flex_none()
                .max_w(px(320.0))
                .child(source_row(source, motion)),
        );
    }
    strip.into_any_element()
}
