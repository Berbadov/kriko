//! Browser extension: one click adds it to a browser Kriko opens for the
//! reader, and the screen says plainly whether the extension has been seen
//! since. There is no pairing: the engine trusts the extension's own origin.

use gpui::{div, prelude::*, px, ClickEvent, Context, Div, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::live::knowledge::{ago_seconds, ExtLaunch, ExtStatus};
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
                .text_color(paint(ICE))
                .child(format!("{n}")),
        )
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(SPACE_XS))
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

/// The plain outcome of the one click, in one line: where a window opened —
/// a separate profile is the thing readers notice — or the engine's own words
/// when none could be.
fn launch_line(o: &ExtLaunch) -> String {
    if o.launched {
        if o.profile.is_empty() {
            "Opened in the browser Kriko already lives in.".to_string()
        } else {
            "Opened in a new window with its own profile: your bookmarks and logins are not there.".to_string()
        }
    } else if o.error.is_empty() {
        "No browser was opened.".to_string()
    } else {
        o.error.clone()
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
    let add = cx.listener(|this, _: &ClickEvent, _w, cx| this.extension_launch(cx));
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

    let unavailable = next_for_extension(e) == ExtensionNext::UseRunScreen;
    // The one click was pressed and no window opened: a Firefox reader, most
    // often. That is when the manual install is the install, and not before.
    let show_manual = e.available && k.ext_launch.as_ref().is_some_and(|o| !o.launched);

    let next_step = unavailable.then(|| {
        guidance::next_step(
            "extension-unavailable",
            "This build has no browser extension",
            "Browser checks need a build that carries the extension. Every other check runs from Run.",
            key("ext-unavailable-run", "Open Run")
                .on_click(cx.listener(|this, _: &ClickEvent, _w, cx| {
                    this.tab = Tab::Run;
                    this.refresh_jobs(cx);
                    this.refresh_agents(cx);
                    cx.notify();
                }))
                .into_any_element(),
            motion,
        )
    });

    // ---- the one click ----
    let mut install = card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(row_title("Add Kriko to your browser"))
        .child(row_desc("Reads listings in a browser window Kriko opens for you."));
    if e.available {
        let label = if k.ext_launch_busy { "Adding…" } else { "Add to browser" };
        install = install.child(key("ext-add", label).on_click(add));
    }
    if let Some(o) = &k.ext_launch {
        install = install.child(row_desc(&launch_line(o)));
    }
    if e.staged && !show_manual {
        install = install.child(mono(&format!("Version {} is in {}", e.staged_version, e.path), DIM));
        install = install.child(ghost("ext-reveal", "Show folder").on_click(act("reveal")));
    }
    if let Some(n) = &k.ext_notice {
        install = install.child(mono(n, MUTED));
    }

    // ---- the manual install, only when the one click could not run ----
    let manual = show_manual.then(|| {
        let mut m = card()
            .flex()
            .flex_col()
            .child(card_head("list", "Install it yourself", motion));
        m = m.child(step(
            1,
            "Chrome, Edge or Brave",
            &format!(
                "Open the extensions page, turn on Developer mode, choose Load unpacked, and pick {}.",
                e.path
            ),
            Some(ghost("ext-reveal-manual", "Show folder").on_click(act("reveal")).into_any_element()),
        ));
        let firefox_control = if e.firefox_staged {
            ghost("firefox-reveal", "Show files").on_click(act("firefox/reveal"))
        } else {
            ghost("firefox-stage", "Prepare Firefox").on_click(act("firefox/stage"))
        };
        m = m.child(hairline()).child(step(
            2,
            "Firefox",
            &format!(
                "Open about:debugging#/runtime/this-firefox, choose Load Temporary Add-on, and pick {}.",
                e.firefox_path
            ),
            Some(firefox_control.into_any_element()),
        ));
        m
    });

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
        .child(card_head("check-circle", "Has it been seen", motion))
        .child(tag("extension-seen", state, label, motion))
        .child(row_desc(&said));
    // A browser running older files is worth one line; a current one is not.
    if matches!(e.compat_state.as_str(), "behind" | "too_old" | "stale_files") {
        let line = if e.compat_detail.is_empty() {
            format!("Extension version: {}", e.compat_state)
        } else {
            e.compat_detail.clone()
        };
        status = status.child(row_desc(&line));
    }
    status = status.child(ghost("ext-check", if k.ext_checking { "Checking…" } else { "Check again" }).on_click(check));
    if !e.port_is_ours {
        status = status
            .child(hairline())
            .child(mono(&format!("engine port {} — not this engine's own", e.port), DIM))
            .child(row_desc("Something else holds this port, so the extension cannot reach Kriko. Choose a free port, then restart the engine."))
            .child(port_input)
            .child(ghost("ext-save-port", "Save port and restart engine").on_click(save_port));
    }

    let columns: Vec<Div> = if unavailable { vec![status] } else { vec![install, status] };

    div()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .children(stale_notice)
        .children(next_step)
        .child(grid(app.content_w, 320.0, columns))
        .children(manual)
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
