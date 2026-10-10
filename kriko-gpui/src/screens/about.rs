//! About: Kriko, local product knowledge. The wordmark over the hero, and
//! the key-value rows that say what this install is.

use gpui::{div, prelude::*, px, rgb, svg, Context, Div, SharedString, Styled, Window};

use crate::app::Kriko;
use crate::screens::mono;
use crate::theme::*;

fn kv(k: &str, v: &str) -> Div {
    div()
        .py(px(12.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(mono(k, DIM).flex_none())
        .child(mono(v, INK_2).min_w(px(0.0)))
}

pub fn about(app: &mut Kriko, _window: &mut Window, _cx: &mut Context<Kriko>) -> Div {
    let h = &app.live.health;
    let said = |v: &str| {
        if h.loaded && !v.is_empty() {
            v.to_string()
        } else {
            "not reported yet".to_string()
        }
    };
    let schema = if h.loaded { h.schema_version.to_string() } else { "not reported yet".to_string() };
    let mut facts = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("This install")))
        .child(hairline())
        .child(kv("Version", &said(&h.version)))
        .child(hairline())
        .child(kv("Schema version", &schema))
        .child(hairline())
        .child(kv("Knowledge store", &said(&h.store)))
        .child(hairline())
        .child(kv("App state", &said(&h.app_state)))
        .child(hairline())
        .child(kv("Log file", &said(&h.log_file)))
        .child(hairline())
        .child(kv("Releases", &said(&h.releases_url)));
    for (id, version) in &h.packs {
        facts = facts.child(hairline()).child(kv(id, version));
    }

    let brand = card()
        .flex()
        .items_center()
        .gap(px(20.0))
        .child(
            svg()
                .path(SharedString::from("kriko-mark-white.svg"))
                .size(px(64.0))
                .text_color(rgb(0xffffff)),
        )
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(
                    svg()
                        .path(SharedString::from("kriko-wordmark-white.svg"))
                        .w(px(160.0))
                        .h(px(52.0))
                        .text_color(rgb(0xffffff)),
                )
                .child(mono("local product knowledge", DIM)),
        );

    let blurb = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow("What it is"))
        .child(
            div()
                .font_family(SANS)
                .text_size(px(16.0))
                .line_height(px(24.0))
                .text_color(rgb(INK_2))
                .child(
                    "Kriko reads what the web says about a product, keeps every claim next to its source, and tells you what is actually known. Everything it stores stays on your machine.",
                ),
        )
        .child(
            div()
                .font_family(SANS)
                .text_size(px(13.0))
                .line_height(px(20.0))
                .text_color(rgb(MUTED))
                .child(
                    "Quick Look can run model inference on this device. Web searches still go to the configured search service. If you choose a hosted model provider, the product query and page text sent for analysis go to that provider. Saved claims and sources stay in this local store.",
                ),
        );

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(brand)
        .child(blurb)
        .child(facts)
}
