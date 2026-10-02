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
        .child(mono(k, DIM))
        .child(mono(v, INK_2))
}

pub fn about(_app: &mut Kriko, _window: &mut Window, _cx: &mut Context<Kriko>) -> Div {
    let facts = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("This install")))
        .child(hairline())
        .child(kv("Version", "0.11.0"))
        .child(hairline())
        .child(kv("Design system", "Kriko / Panel"))
        .child(hairline())
        .child(kv("Fonts", "Barlow Condensed · DM Sans · JetBrains Mono"))
        .child(hairline())
        .child(kv("Data location", "~/.kriko"))
        .child(hairline())
        .child(kv("Engine", "kriko-sidecar, local"))
        .child(hairline())
        .child(kv("Browser extension", "Chrome / Firefox, TypeScript"))
        .child(hairline())
        .child(kv("Licence", "See LICENSE in the repository"));

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
                    "A check runs locally: agents read, claims are grounded against the store, and the verdict names its evidence. Nothing is uploaded.",
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
