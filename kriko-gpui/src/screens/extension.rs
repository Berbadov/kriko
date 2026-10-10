//! Browser extension: put it on disk, show where, open a browser, and say
//! plainly whether the extension has been seen. There is no pairing: the
//! engine trusts the extension's own origin.

use gpui::{div, prelude::*, px, rgb, ClickEvent, Context, Div, Styled, Window};

use crate::app::Kriko;
use crate::live::knowledge::{ago_seconds, ExtStatus};
use crate::screens::{empty_note, mono, row_desc, row_title};
use crate::theme::*;

/// One numbered step: the number in a well, a title, a line, and its key.
fn step(n: usize, title: &str, desc: &str, control: Option<gpui::AnyElement>) -> Div {
    div()
        .py(px(12.0))
        .flex()
        .items_start()
        .gap(px(14.0))
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
                .child(row_desc(desc)),
        )
        .children(control)
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

pub fn extension(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let k = &app.live.knowledge;
    let Some(e) = &k.ext else {
        return div().child(empty_note(
            "Waiting for Kriko's engine. The extension's state appears here as soon as it answers.",
        ));
    };

    let act = |action: &'static str| {
        cx.listener(move |this, _: &ClickEvent, _w, cx| this.extension_action(action, cx))
    };
    let check = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_extension(cx));

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
            "Opens ~/.kriko in the file manager with the extension folder selected, so it can be dragged straight onto the browser's extensions page.",
            e.staged.then(|| ghost("ext-reveal", "Show Extension").on_click(act("reveal")).into_any_element()),
        ))
        .child(hairline())
        .child(step(
            3,
            "Load it in a browser",
            "Open a browser with the extension loaded, or use Load unpacked on the page below and choose the folder.",
            e.available.then(|| ghost("ext-launch", "Open a browser").on_click(act("launch")).into_any_element()),
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
        .child(row_desc("Firefox 140 or newer. Prepare the add-on, then open about:debugging#/runtime/this-firefox and choose Load Temporary Add-on. Select manifest.json below."))
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
    let (state, label, said) = seen_line(e);
    let mut status = card()
        .flex()
        .flex_col()
        .gap(px(14.0))
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
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(ghost("ext-check", "Check again").on_click(check))
                .child(row_desc("The extension is trusted by its own origin; there is nothing to pair.")),
        );

    div()
        .flex()
        .gap(px(24.0))
        .items_start()
        .child(div().flex_1().min_w(px(0.0)).flex().flex_col().gap(px(20.0)).child(steps_card).child(firefox))
        .child(div().flex_1().min_w(px(0.0)).child(status))
}
