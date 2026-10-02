//! Settings: where a preference lives, and the fact that it lives anywhere.
//! Four cards in a 2x2 grid: General, Privacy, Shortcuts, Danger zone —
//! the shape of the reference screen.

use gpui::{div, prelude::*, px, rgb, Context, Div, Stateful, Styled, Window};

use crate::app::{Kriko, Tab};
use crate::screens::{row_desc, row_title};
use crate::theme::*;

/// One row of a card: title + description left, a control right.
fn row(title: &str, desc: &str, control: gpui::AnyElement) -> Div {
    div()
        .py(px(14.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(title))
                .child(row_desc(desc)),
        )
        .child(control)
}

fn switch_row(
    id: &'static str,
    title: &str,
    desc: &str,
    on: bool,
    motion: bool,
    cx: &mut Context<Kriko>,
) -> Div {
    row(
        title,
        desc,
        switch_anim(id, on, motion)
            .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                match id {
                    "sw-launch" => this.launch_at_login = !this.launch_at_login,
                    "sw-menubar" => this.menu_bar_icon = !this.menu_bar_icon,
                    "sw-motion" => this.reduce_motion = !this.reduce_motion,
                    "sw-ask" => this.ask_before_reading = !this.ask_before_reading,
                    "sw-raw" => this.keep_raw_pages = !this.keep_raw_pages,
                    _ => {}
                }
                cx.notify();
            }))
            .into_any_element(),
    )
}

/// A shortcut row: label left, keycaps right.
fn shortcut_row(label: &str, note: Option<&str>, keys: &[&str]) -> Div {
    let mut caps = div().flex().items_center().gap(px(6.0));
    for (i, k) in keys.iter().enumerate() {
        if i > 0 {
            caps = caps.child(
                div()
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(rgb(DIM))
                    .child("+"),
            );
        }
        caps = caps.child(keycap(k));
    }
    div()
        .py(px(14.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(label))
                .when(note.is_some(), |d| d.children(note.map(row_desc))),
        )
        .child(caps)
}

pub fn settings(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Stateful<Div> {
    // ---- general ----
    let general = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("General")))
        .child(hairline())
        .child(switch_row("sw-launch", "Launch at login", "Start Kriko when you sign in", app.launch_at_login, !app.reduce_motion, cx))
        .child(hairline())
        .child(switch_row("sw-menubar", "Menu bar icon", "Show run state without opening the window", app.menu_bar_icon, !app.reduce_motion, cx))
        .child(hairline())
        .child(switch_row("sw-motion", "Reduce motion", "Turns off loops and flicker", app.reduce_motion, !app.reduce_motion, cx));

    // ---- privacy ----
    let privacy = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("Privacy")))
        .child(hairline())
        .child(switch_row("sw-ask", "Ask before reading new sites", "Pauses the run for your approval", app.ask_before_reading, !app.reduce_motion, cx))
        .child(hairline())
        .child(switch_row("sw-raw", "Keep raw pages", "Store page text next to claims", app.keep_raw_pages, !app.reduce_motion, cx))
        .child(hairline())
        .child(row(
            "Data location",
            "All data remains on this machine",
            chip("~/.kriko").into_any_element(),
        ));

    // ---- shortcuts ----
    let shortcuts = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("Shortcuts")))
        .child(hairline())
        .child(shortcut_row("New check", Some("Anywhere in Kriko"), &["ctrl", "N"]))
        .child(hairline())
        .child(shortcut_row("Search knowledge", None, &["ctrl", "K"]))
        .child(hairline())
        .child(shortcut_row("Jump to Browse", None, &["ctrl", "B"]));

    // ---- danger zone ----
    let danger_zone;
    if app.erased {
        let rebuild = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.tab = Tab::Browse;
            cx.notify();
        });
        danger_zone = card()
            .flex()
            .flex_col()
            .child(
                div()
                    .mb(px(4.0))
                    .child(
                        div()
                            .font_family(MONO)
                            .text_size(px(11.0))
                            .text_color(rgb(DANGER))
                            .child("DANGER ZONE"),
                    ),
            )
            .child(hairline())
            .child(
                div()
                    .py(px(14.0))
                    .flex()
                    .flex_col()
                    .gap(px(8.0))
                    .child(row_title("Every catalog removed"))
                    .child(row_desc("Packs, claims and evidence are gone. Rebuild them from Browse."))
                    .child(div().mt(px(4.0)).flex().child(ghost("rebuild", "Rebuild from Browse").on_click(rebuild))),
            );
    } else {
        let label = if app.erase_confirm {
            "Really erase everything?"
        } else {
            "Erase data"
        };
        let erase = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            if !this.erase_confirm {
                this.erase_confirm = true;
            } else {
                this.erased = true;
                this.erase_confirm = false;
            }
            cx.notify();
        });
        let cancel = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.erase_confirm = false;
            cx.notify();
        });
        danger_zone = card()
            .flex()
            .flex_col()
            .child(
                div()
                    .mb(px(4.0))
                    .child(
                        div()
                            .font_family(MONO)
                            .text_size(px(11.0))
                            .text_color(rgb(DANGER))
                            .child("DANGER ZONE"),
                    ),
            )
            .child(hairline())
            .child(row(
                "Erase local data",
                "Removes packs, claims, evidence and history",
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .when(app.erase_confirm, |d| {
                        d.child(ghost("erase-cancel", "Cancel").on_click(cancel))
                    })
                    .child(danger("erase", label).on_click(erase))
                    .into_any_element(),
            ));
    }

    div()
        .id("settings-scroll")
        .overflow_x_scroll()
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .items_start()
                .min_w(px(920.0))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(24.0))
                        .child(general)
                        .child(shortcuts),
                )
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(24.0))
                        .child(privacy)
                        .child(danger_zone),
                ),
        )
}
