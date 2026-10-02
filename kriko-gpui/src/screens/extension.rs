//! Browser extension: send pages from the browser into Kriko's knowledge.
//! Numbered steps, a pairing code block, and the two switches.

use gpui::{div, prelude::*, px, rgb, Context, Div, Styled, Window};

use crate::app::{Kriko, Tab};
use crate::screens::{row_desc, row_title};
use crate::theme::*;

pub fn extension(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let pair = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.extension_linked = true;
        cx.notify();
    });
    let toggle_hover = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.extension_hover = !this.extension_hover;
        cx.notify();
    });

    // ---- steps ----
    let steps = [("Install the extension", "From the browser's store: search for Kriko, or use the packed file in dist/."),
                  ("Open Kriko on this machine", "The extension talks to the local engine over a loopback port; nothing leaves the machine."),
                  ("Enter the pairing code", "The code below is shown once and rotates when you re-pair.")];
    let mut steps_card = card().flex().flex_col();
    steps_card = steps_card.child(div().mb(px(12.0)).child(eyebrow("Three steps")));
    for (i, (title, desc)) in steps.iter().enumerate() {
        steps_card = steps_card.child(
            div()
                .py(px(12.0))
                .flex()
                .items_start()
                .gap(px(14.0))
                .child(
                    well()
                        .size(px(32.0))
                        .flex()
                        .items_center()
                        .justify_center()
                        .font_family(MONO)
                        .text_size(px(13.0))
                        .text_color(rgb(ICE))
                        .child(format!("{}", i + 1)),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title(title))
                        .child(row_desc(desc)),
                ),
        );
        if i + 1 < steps.len() {
            steps_card = steps_card.child(hairline());
        }
    }

    // ---- pairing ----
    let pairing = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(eyebrow("Pairing code"))
        .child(if app.extension_linked {
            div()
                .flex()
                .flex_col()
                .gap(px(10.0))
                .child(tag(TagState::Live, "Linked", motion))
                .child(row_desc("The browser extension is paired with this install. Pages you send land in Knowledge."))
                .into_any_element()
        } else {
            div()
                .flex()
                .flex_col()
                .gap(px(14.0))
                .child(
                    well()
                        .h(px(72.0))
                        .flex()
                        .items_center()
                        .justify_center()
                        .font_family(MONO)
                        .text_size(px(28.0))
                        .text_color(rgb(ICE))
                        .child("K7 4F2 9QD"),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(12.0))
                        .child(key("ext-pair", "Pair now").on_click(pair))
                        .child(row_desc("Then click the Kriko icon on any product page.")),
                )
                .into_any_element()
        })
        .child(hairline())
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(24.0))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title("Send pages on hover"))
                        .child(row_desc("Kriko reads a page when the cursor rests on its link.")),
                )
                .child(switch_anim("ext-hover", app.extension_hover, motion).on_click(toggle_hover)),
        );

    // ---- where the pages go ----
    let open_browse = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::Browse;
        cx.notify();
    });
    let destination = card()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title("Where pages go"))
                .child(row_desc("Sent pages are stored as drafts until a run grounds them.")),
        )
        .child(ghost("ext-open-browse", "Open Browse").on_click(open_browse));

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .items_start()
                .child(div().flex_1().min_w(px(0.0)).child(steps_card))
                .child(div().flex_1().min_w(px(0.0)).child(pairing)),
        )
        .child(destination)
}
