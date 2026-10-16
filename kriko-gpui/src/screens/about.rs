//! About: Kriko, local product knowledge. The wordmark over the hero, and
//! the key-value rows that say what this install is.

use gpui::{div, prelude::*, px, rgb, Context, Div, FontWeight, Styled, Window};

use crate::app::Kriko;
use crate::screens::mono;
use crate::theme::*;

fn section_title(label: &str) -> Div {
    div()
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(18.0))
        .text_color(rgb(BRAND_BRIGHT))
        .child(label.to_string())
}

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
    "Installing update · Kriko will restart".to_string()
}

#[cfg(not(windows))]
fn update_busy_message() -> String {
    "Preparing update information".to_string()
}

#[cfg(windows)]
fn update_available_message(version: &str) -> String {
    format!("Version {version} ready to install")
}

#[cfg(not(windows))]
fn update_available_message(version: &str) -> String {
    format!("Version {version} available · download from Releases")
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
        (Some(u), _) if !u.error.is_empty() => (
            format!("Check failed · {}", u.error),
            Some(check("Check again", cx)),
        ),
        (Some(_), _) => (
            "This is the newest version.".to_string(),
            Some(check("Check again", cx)),
        ),
        (None, _) => (
            "Not checked yet.".to_string(),
            Some(check("Check for updates", cx)),
        ),
    };
    #[cfg(windows)]
    let action = if k.app_update.as_ref().is_some_and(|u| u.newer) && !k.app_update_busy {
        Some(
            key("app-update-install", "Install and restart")
                .on_click(
                    cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.install_app_update(cx)),
                )
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
    let mut row = div()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(8.0))
        .child(mono(&line, INK_2).min_w(px(0.0)));
    if k.app_update_busy || k.app_update_note.as_deref() == Some("Checking for updates.") {
        row = row.child(spinner("app-update-spinner", 16.0, app.motion));
    }
    if let Some(button) = action {
        row = row.child(button);
    }
    let mut panel = card()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(section_title("Updates"))
        .child(row);
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
    let schema = if h.loaded {
        h.schema_version.to_string()
    } else {
        "not reported yet".to_string()
    };
    let mut facts = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(section_title("This install")))
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

    let brand = div().flex().flex_col().gap(px(8.0)).py(px(12.0))
        .child(section_title("About Kriko"))
        .child(crate::screens::row_desc(&format!("Local product knowledge · v{}", env!("CARGO_PKG_VERSION"))));

    let blurb = card()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(section_title("Local by design"))
        .child(
            div()
                .font_family(SANS)
                .text_size(px(16.0))
                .line_height(px(24.0))
                .text_color(rgb(INK_2))
                .child(
                    "Kriko keeps product claims with their sources. Saved knowledge, checks, and chats stay on this device.",
                ),
        )
        .child(
            div()
                .font_family(SANS)
                .text_size(px(13.0))
                .line_height(px(20.0))
                .text_color(rgb(MUTED))
                .child(
                    "Web runs send the question and reading context to their providers. Local inference stays here; web search still contacts its provider.",
                ),
        );

    div()
        .flex()
        .flex_col()
        .gap(px(SPACE_SECTION))
        .child(brand)
        .child(updates)
        .child(blurb)
        .child(facts)
}
