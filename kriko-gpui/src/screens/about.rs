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

fn updates_card(app: &Kriko, cx: &mut Context<Kriko>) -> Div {
    let k = &app.live.knowledge;
    let check = |label: &str, cx: &mut Context<Kriko>| {
        ghost("app-update-check", label)
            .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.check_app_update(cx)))
            .into_any_element()
    };
    let (line, action) = match (&k.app_update, k.app_update_busy) {
        (_, true) => ("Installing the update. Kriko will close and reopen.".to_string(), None),
        (Some(u), _) if u.newer => (
            format!("Version {} is available. Installing keeps your catalogs and history.", u.version),
            Some(
                key("app-update-install", "Install and restart")
                    .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.install_app_update(cx)))
                    .into_any_element(),
            ),
        ),
        (Some(u), _) if !u.error.is_empty() => (format!("Could not check: {}.", u.error), Some(check("Check again", cx))),
        (Some(_), _) => ("This is the newest version.".to_string(), Some(check("Check again", cx))),
        (None, _) => ("Not checked yet.".to_string(), Some(check("Check for updates", cx))),
    };
    let mut row = div().flex().items_center().justify_between().gap(px(24.0)).child(mono(&line, INK_2).min_w(px(0.0)));
    if let Some(button) = action {
        row = row.child(button);
    }
    let mut panel = card().flex().flex_col().gap(px(10.0)).child(eyebrow("Updates")).child(row);
    if let Some(note) = &k.app_update_note {
        panel = panel.child(mono(note, DIM));
    }
    panel
}

pub fn about(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let updates = updates_card(app, cx);
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
                    "A check runs locally: agents read, claims are grounded against the store, and the verdict names its evidence. Nothing is uploaded.",
                ),
        );

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(brand)
        .child(updates)
        .child(blurb)
        .child(facts)
}
