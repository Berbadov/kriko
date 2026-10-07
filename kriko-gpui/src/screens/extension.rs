//! Browser extension: put it on disk, show where, open a browser, and say
//! plainly whether the extension has been seen. There is no pairing: the
//! engine trusts the extension's own origin.

use gpui::{div, prelude::*, px, rgb, ClickEvent, Context, Div, Styled, Window};

use crate::app::{Field, Kriko};
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

pub fn extension(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let k = &app.live.knowledge;
    let Some(e) = &k.ext else {
        return div().child(empty_note(
            "Waiting for Kriko's engine. The extension's state appears here as soon as it answers.",
        ));
    };

    let port_input = app.input_field(
        Field::ExtensionPort, "ext-port-input", "8787", None, window, cx,
    );
    let act = |action: &'static str| {
        cx.listener(move |this, _: &ClickEvent, _w, cx| this.extension_action(action, cx))
    };
    let check = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_extension(cx));
    let save_port = cx.listener(|this, _: &ClickEvent, _w, cx| this.save_extension_port(cx));

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
            "Open a browser with the extension loaded, or use Load unpacked on the page below and choose the folder.",
            e.available.then(|| ghost("ext-launch", "Open a browser").on_click(act("launch")).into_any_element()),
        ));
    if !e.browsers.is_empty() {
        let mut list = div().mt(px(8.0)).flex().flex_col().gap(px(4.0));
        for b in &e.browsers {
            list = list.child(mono(&format!("{}: {}", b.name, b.url), DIM));
        }
        steps_card = steps_card.child(list);
    }
    if let Some(n) = &k.ext_notice {
        steps_card = steps_card.child(div().mt(px(12.0)).child(mono(n, MUTED)));
    }

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
                .child(ghost("ext-check", "Check again").on_click(check))
                .child(row_desc("The extension is trusted by its own origin; there is nothing to pair.")),
        );

    div()
        .flex()
        .gap(px(24.0))
        .items_start()
        .child(div().flex_1().min_w(px(0.0)).child(steps_card))
        .child(div().flex_1().min_w(px(0.0)).child(status))
}
