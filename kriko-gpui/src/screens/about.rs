//! About: Kriko, local product knowledge. The wordmark over the hero, and
//! the key-value rows that say what this install is.

use gpui::{div, prelude::*, px, svg, Context, Div, SharedString, Styled, Window};

use crate::app::Kriko;
use crate::screens::{mono, row_desc};
use crate::theme::*;

fn kv(k: &str, v: &str) -> Div {
    div()
        .py(px(12.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(SPACE_SECTION))
        .child(mono(k, DIM).flex_none())
        .child(mono(v, INK_2).min_w(px(0.0)))
}

#[cfg(windows)]
fn update_busy_message() -> String {
    "Installing the update. Kriko will close and reopen.".to_string()
}

#[cfg(not(windows))]
fn update_busy_message() -> String {
    "Preparing the update information.".to_string()
}

#[cfg(windows)]
fn update_available_message(version: &str) -> String {
    format!("Version {version} is available. Installing keeps your catalogs and history.")
}

#[cfg(not(windows))]
fn update_available_message(version: &str) -> String {
    format!("Version {version} is available. Download it from Releases and install manually.")
}

fn updates_card(app: &Kriko, cx: &mut Context<Kriko>) -> Div {
    let k = &app.live.knowledge;
    let check = |label: &str, cx: &mut Context<Kriko>| {
        ghost("app-update-check", label)
            .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.check_app_update(cx)))
            .into_any_element()
    };
    let (line, action) = match (&k.app_update, k.app_update_busy) {
        (_, true) => (update_busy_message(), None),
        (Some(u), _) if u.newer => (update_available_message(&u.version), None),
        (Some(u), _) if !u.error.is_empty() => (format!("Could not check: {}.", u.error), Some(check("Check again", cx))),
        (Some(_), _) => ("This is the newest version.".to_string(), Some(check("Check again", cx))),
        (None, _) => ("Not checked yet.".to_string(), Some(check("Check for updates", cx))),
    };
    #[cfg(windows)]
    let action = if k.app_update.as_ref().is_some_and(|u| u.newer) && !k.app_update_busy {
        Some(
            key("app-update-install", "Install and restart")
                .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.install_app_update(cx)))
                .into_any_element(),
        )
    } else {
        action
    };
    #[cfg(not(windows))]
    let action = if k.app_update.as_ref().is_some_and(|u| u.newer) && !k.app_update_busy {
        let releases_url = if app.live.health.releases_url.is_empty() {
            "https://github.com/Berbadov/kriko/releases".to_string()
        } else {
            app.live.health.releases_url.clone()
        };
        Some(
            key("app-update-releases", "Open release downloads")
                .on_click(move |_, _, cx| cx.open_url(&releases_url))
                .into_any_element(),
        )
    } else {
        action
    };
    let mut row = div().flex().items_center().justify_between().gap(px(8.0)).child(mono(&line, INK_2).min_w(px(0.0)));
    if k.app_update_busy || k.app_update_note.as_deref() == Some("Checking for updates.") {
        row = row.child(spinner("app-update-spinner", 16.0, app.motion));
    }
    if let Some(button) = action {
        row = row.child(button);
    }
    let mut panel = card().flex().flex_col().gap(px(SPACE_S)).child(card_head("refresh", "Updates", app.motion)).child(row);
    if let Some(note) = &k.app_update_note {
        panel = panel.child(mono(note, DIM));
    }
    panel
}

pub fn about(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
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
        .child(card_head("database", "This install", app.motion))
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
        .gap(px(SPACE_SECTION))
        .bg(paint(BRAND))
        .child(
            svg()
                .path(SharedString::from("kriko-mark-white.svg"))
                .size(px(64.0))
                .text_color(fixed(0xffffff)),
        )
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(SPACE_XS))
                .child(
                    svg()
                        .path(SharedString::from("kriko-wordmark-white.svg"))
                        .w(px(160.0))
                        .h(px(52.0))
                        .text_color(fixed(0xffffff)),
                )
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(12.0))
                        .text_color(fixed_a(0xffffffcc))
                        .child("local product knowledge"),
                ),
        );

    let blurb = card()
        .flex()
        .flex_col()
        .gap(px(SPACE_S))
        .child(card_head("info", "What it is", app.motion))
        .child(
            div()
                .font_family(SANS)
                .text_size(px(16.0))
                .line_height(px(24.0))
                .text_color(paint(INK_2))
                .child(
                    "Kriko reads what the web says about a product, keeps every claim beside its source, and says what is actually known. Lookups, checks and conversations stay on your machine.",
                ),
        )
        .child(row_desc(
            "A web-backed run sends its question and reading context to the providers it uses. A local model keeps inference here; web search still contacts its search provider.",
        ));

    div()
        .flex()
        .flex_col()
        .gap(px(SPACE_SECTION))
        .child(enter(brand, "about-0", 0, motion))
        .child(enter(updates, "about-1", 1, motion))
        .child(enter(blurb, "about-2", 2, motion))
        .child(enter(facts, "about-3", 3, motion))
}
