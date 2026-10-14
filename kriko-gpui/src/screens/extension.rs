//! Browser extension: put it on disk, show where, open a browser, and say
//! plainly whether the extension has been seen. There is no pairing: the
//! engine trusts the extension's own origin.

use gpui::{div, prelude::*, px, rgb, ClickEvent, Context, Div, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::live::knowledge::{ago_seconds, ExtStatus};
use crate::screens::{guidance, mono, row_desc, row_title};
use crate::theme::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ExtensionNext {
    UseRunScreen,
    OpenBrowser,
    None,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ExtensionReadState {
    Checking,
    Waiting,
    Failed,
    Stale,
    Ready,
}

fn extension_read_state(has_status: bool, checking: bool, failed: bool) -> ExtensionReadState {
    if checking {
        return if has_status { ExtensionReadState::Ready } else { ExtensionReadState::Checking };
    }
    match (has_status, failed) {
        (true, true) => ExtensionReadState::Stale,
        (true, false) => ExtensionReadState::Ready,
        (false, true) => ExtensionReadState::Failed,
        (false, false) => ExtensionReadState::Waiting,
    }
}

fn next_for_extension(e: &ExtStatus) -> ExtensionNext {
    if !e.available {
        ExtensionNext::UseRunScreen
    } else if e.connected {
        ExtensionNext::None
    } else {
        ExtensionNext::OpenBrowser
    }
}

/// One numbered step: the number in a well, a title, a line, and its key.
fn step(n: usize, title: &str, desc: &str, control: Option<gpui::AnyElement>) -> Div {
    div()
        .py(px(12.0))
        .flex()
        .items_start()
        .gap(px(SPACE_CARD))
        .child(
            well()
                .size(px(32.0))
                .flex_none()
                .flex()
                .items_center()
                .justify_center()
                .font_family(MONO)
                .text_size(px(13.0))
                .text_color(rgb(ICE))
                .child(format!("{n}")),
        )
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(title))
                .child(row_desc(desc))
                .children(control),
        )
}

fn seen_line(e: &ExtStatus) -> (TagState, &'static str, String) {
    if e.connected {
        let when = e.seconds_since_seen.map(ago_seconds).unwrap_or_else(|| "just now".into());
        (
            TagState::Live,
            "Connected",
            format!("The extension asked this engine {when}. It has made {} requests in all.", e.hits),
        )
    } else if e.ever_connected {
        let when = e.seconds_since_seen.map(ago_seconds).unwrap_or_else(|| "a while ago".into());
        (
            TagState::Queue,
            "Seen before",
            format!("Last seen {when}, {} requests in all. Open a page in the browser and it checks in.", e.hits),
        )
    } else {
        (TagState::Queue, "Never seen", "No extension has reached this engine yet.".into())
    }
}

pub fn extension(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    let k = &app.live.knowledge;
    let Some(e) = &k.ext else {
        let read_state = extension_read_state(false, k.ext_checking, k.ext_error.is_some());
        let (title, detail, label) = match read_state {
            ExtensionReadState::Checking => (
                "Checking extension status",
                "The engine is reading the extension status now.",
                "Checking…",
            ),
            ExtensionReadState::Failed => (
                "Could not read extension status",
                k.ext_error.as_deref().unwrap_or("The status request failed. Check again to retry."),
                "Check again",
            ),
            ExtensionReadState::Waiting => (
                "Waiting for extension status",
                "The engine has not answered this screen yet. Check again to retry the status request.",
                "Check again",
            ),
            ExtensionReadState::Stale | ExtensionReadState::Ready => unreachable!("no status cannot be stale or ready"),
        };
        let action = if read_state == ExtensionReadState::Checking {
            ghost("ext-status-retry", label).into_any_element()
        } else {
            let check = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_extension(cx));
            ghost("ext-status-retry", label).on_click(check).into_any_element()
        };
        return div().child(guidance::next_step("extension-status-waiting", title, detail, action, motion));
    };

    let port_input = app.input_field(
        Field::ExtensionPort, "ext-port-input", "8787", None, window, cx,
    );
    let act = |action: &'static str| {
        cx.listener(move |this, _: &ClickEvent, _w, cx| this.extension_action(action, cx))
    };
    let check = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_extension(cx));
    let stale_check = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_extension(cx));
    let save_port = cx.listener(|this, _: &ClickEvent, _w, cx| this.save_extension_port(cx));
    let stale_notice = if extension_read_state(true, k.ext_checking, k.ext_error.is_some()) == ExtensionReadState::Stale {
        let error = k.ext_error.as_deref().unwrap_or("The status request failed.");
        Some(guidance::next_step(
            "extension-status-stale",
            "Extension status may be out of date",
            &format!("{error} The last-known status is shown below. Check again to refresh it."),
            ghost("ext-status-retry", "Check again").on_click(stale_check).into_any_element(),
            motion,
        ))
    } else { None };
    let next = next_for_extension(e);
    let next_step = match next {
        ExtensionNext::UseRunScreen => Some(guidance::next_step(
            "extension-unavailable",
            "Check a product in Kriko",
            "This build does not carry the browser extension. You can still run checks from Run; browser checks need a build that includes the extension.",
            key("ext-unavailable-run", "Open Run")
                .on_click(cx.listener(|this, _: &ClickEvent, _w, cx| {
                    this.tab = Tab::Run;
                    this.refresh_jobs(cx);
                    this.refresh_agents(cx);
                    cx.notify();
                }))
                .into_any_element(),
            motion,
        )),
        ExtensionNext::OpenBrowser => Some(guidance::next_step(
            "extension-open-browser",
            "Open a readable listing",
            "This action stages the extension and opens a page Kriko can read. The status turns Connected only after the extension reaches this engine; if it stays unseen, use the steps below.",
            key("ext-open-with-extension", "Open browser with extension")
                .on_click(act("launch"))
                .into_any_element(),
            motion,
        )),
        ExtensionNext::None => None,
    };

    // ---- steps ----
    let staged_line = if !e.available {
        "This build does not carry the extension.".to_string()
    } else if e.staged {
        format!("Version {} is on disk at {}.", e.staged_version, e.path)
    } else {
        format!("Version {} is ready to put in {}.", e.version, e.path)
    };
    let mut steps_card = card().flex().flex_col();
    steps_card = steps_card.child(div().mb(px(12.0)).child(eyebrow("Three steps")));
    steps_card = steps_card
        .child(step(
            1,
            "Put it on disk",
            &staged_line,
            e.available.then(|| {
                key("ext-stage", if e.staged { "Refresh" } else { "Stage" })
                    .on_click(act("stage"))
                    .into_any_element()
            }),
        ))
        .child(hairline())
        .child(step(
            2,
            "Show the folder",
            "Opens it in the file manager, so the browser can be pointed at it.",
            e.staged.then(|| ghost("ext-reveal", "Show folder").on_click(act("reveal")).into_any_element()),
        ))
        .child(hairline())
        .child(step(
            3,
            "Load it in a browser",
            "Use Open browser with extension above, or in Chrome open chrome://extensions, turn on Developer mode, choose Load unpacked, and choose the folder shown here.",
            e.available.then(|| ghost("ext-launch", "Open browser with extension").on_click(act("launch")).into_any_element()),
        ));
    if !e.browsers.is_empty() {
        let mut list = div().mt(px(8.0)).flex().flex_col().gap(px(4.0));
        for b in e.browsers.iter().filter(|b| b.name != "Firefox") {
            list = list.child(mono(&format!("{}: {}", b.name, b.url), DIM));
        }
        steps_card = steps_card.child(list);
    }
    if let Some(n) = &k.ext_notice {
        steps_card = steps_card.child(div().mt(px(12.0)).child(mono(n, MUTED)));
    }

    let firefox_path = e.firefox_path.clone();
    let firefox = card().flex().flex_col().gap(px(10.0))
        .child(eyebrow("Firefox"))
        .child(row_desc("Firefox 140 or newer. Prepare the add-on, then open about:debugging#/runtime/this-firefox and choose Load Temporary Add-on. Choose manifest.json below."))
        .child(mono(&e.firefox_path, MUTED))
        .child(div().flex().flex_wrap().gap(px(8.0))
            .when(e.available, |d| d.child(key("firefox-stage", "Prepare Firefox").on_click(act("firefox/stage"))))
            .when(e.firefox_staged, |d| d
                .child(ghost("firefox-reveal", "Show files").on_click(act("firefox/reveal")))
                .child(ghost("firefox-copy", "Copy path").on_click(cx.listener(move |_this, _: &ClickEvent, _w, cx| {
                    cx.write_to_clipboard(gpui::ClipboardItem::new_string(firefox_path.clone()));
                })))))
        .child(row_desc("Temporary add-ons are removed when Firefox restarts. Permanent installation needs a Mozilla-signed XPI. Preparing also creates an unsigned XPI beside the folder."))
        .child(row_desc("The add-on sends page URLs and product details to Kriko on this computer. Research uses the provider you configure in Kriko."));

    // ---- what the engine has seen ----
    let (state, label, said) = if k.ext_error.is_some() {
        let (_, _, last_known) = seen_line(e);
        (TagState::Need, "Stale status", format!("Last known: {last_known}"))
    } else {
        seen_line(e)
    };
    let mut status = card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(eyebrow("Has it been seen"))
        .child(tag("extension-seen", state, label, motion))
        .child(row_desc(&said));
    if !e.compat_state.is_empty() {
        let line = if e.compat_detail.is_empty() {
            format!("Extension version: {}", e.compat_state)
        } else {
            format!("Extension version: {}. {}", e.compat_state, e.compat_detail)
        };
        status = status.child(row_desc(&line));
    }
    status = status
        .child(hairline())
        .child(mono(
            &format!(
                "engine port {}{}",
                e.port,
                if e.port_is_ours { "" } else { ", not this engine's own" }
            ),
            DIM,
        ))
        .child(hairline())
        .child(eyebrow("Connection port"))
        .child(row_desc("Choose a free local port, then use the same address in the browser extension's settings."))
        .child(port_input)
        .child(ghost("ext-save-port", "Save port and restart engine").on_click(save_port))
        .child(mono(&format!("Extension address: http://127.0.0.1:{}", e.port), DIM))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
        .child(ghost("ext-check", if k.ext_checking { "Checking…" } else { "Check again" }).flex_none().on_click(check))
                // flex_1 and min_w(0) so the sentence wraps inside the card.
                .child(div().flex_1().min_w(px(0.0)).child(row_desc(
                    "The extension is trusted by its own origin; there is nothing to pair.",
                ))),
        );

    div()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .children(stale_notice)
        .children(next_step)
        // The steps most browsers take come first; Firefox's own path, which
        // is a temporary add-on, follows them.
        .child(grid(app.content_w, 320.0, vec![steps_card, status]))
        .child(firefox)
}

#[cfg(test)]
mod guidance_tests {
    use super::{extension_read_state, next_for_extension, ExtensionNext, ExtensionReadState};
    use crate::live::knowledge::ExtStatus;

    #[test]
    fn unavailable_build_keeps_a_direct_check_path() {
        assert_eq!(next_for_extension(&ExtStatus::default()), ExtensionNext::UseRunScreen);
    }

    #[test]
    fn disconnected_extension_offers_the_staging_and_launch_action() {
        let available = ExtStatus { available: true, staged: true, ..Default::default() };
        assert_eq!(next_for_extension(&available), ExtensionNext::OpenBrowser);
    }

    #[test]
    fn a_connected_extension_does_not_keep_showing_setup_as_the_next_step() {
        let connected = ExtStatus { available: true, connected: true, ever_connected: true, ..Default::default() };
        assert_eq!(next_for_extension(&connected), ExtensionNext::None);
    }

    #[test]
    fn failed_refresh_marks_a_connected_snapshot_stale_and_keeps_first_read_retryable() {
        assert_eq!(extension_read_state(false, true, false), ExtensionReadState::Checking);
        assert_eq!(extension_read_state(false, false, true), ExtensionReadState::Failed);
        assert_eq!(extension_read_state(true, false, true), ExtensionReadState::Stale);
        assert_eq!(extension_read_state(true, false, false), ExtensionReadState::Ready);
    }
}
