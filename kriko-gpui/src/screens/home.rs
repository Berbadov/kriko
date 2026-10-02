//! Home: one place to start a check, see what is waiting and read the last
//! result. Totals in cards, one waiting callout, the latest runs in a table.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Styled, Window};

use crate::app::{Kriko, Tab};
use crate::data;
use crate::screens::{mono, plate_s, th};
use crate::theme::*;

/// The pale frost box that floats on the hero: the one way to start a check.
pub fn frost_start(cx: &mut Context<Kriko>) -> Div {
    let start = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::Run;
        cx.notify();
    });
    frost()
        .absolute()
        .bottom(px(24.0))
        .left(px(40.0))
        .min_w(px(380.0))
        .max_w(px(520.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(20.0))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(
                    div()
                        .font_family(DISPLAY)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(22.0))
                        .text_color(rgb(0x0a0e1a))
                        .child("START A CHECK"),
                )
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(0x3a4156))
                        .child("Pick a subject, or let an agent pick one."),
                ),
        )
        .child(key("home-start", "Start check").on_click(start))
}

fn total_card(label: &str, value: &str, note: &str) -> Div {
    card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(eyebrow(label))
        .child(
            div()
                .font_family(DISPLAY)
                .font_weight(FontWeight::SEMIBOLD)
                .text_size(px(64.0))
                .line_height(px(60.0))
                .text_color(rgb(INK))
                .child(value.to_string()),
        )
        .child(mono(note, MUTED))
}

pub fn home(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let open_history = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::History;
        cx.notify();
    });
    let open_activity = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::Activity;
        cx.notify();
    });

    let waiting = callout()
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(tag(TagState::Need, "Waiting", motion))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(16.0))
                        .text_color(rgb(INK))
                        .child("One run is waiting for you to pick a subject."),
                )
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(14.0))
                        .text_color(rgb(INK_2))
                        .child("It was started from the browser extension."),
                ),
        )
        .child(key("home-waiting", "Pick subject").on_click(open_activity));

    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().child(th("Latest checks")))
                .child(div().w(px(200.0)).child(th("Verdict")))
                .child(div().w(px(170.0)).child(th("Confidence")))
                .child(div().w(px(120.0)).child(th("Took"))),
        )
        .child(hairline());

    for (ri, check) in data::CHECKS.iter().take(3).enumerate() {
        let row = div()
            .flex()
            .items_center()
            .py(px(14.0))
            .hover(|s| s.bg(rgba(GLASS_1)))
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .flex()
                    .flex_col()
                    .gap(px(2.0))
                    .child(
                        div()
                            .font_family(SANS)
                            .font_weight(FontWeight::SEMIBOLD)
                            .text_size(px(15.0))
                            .text_color(rgb(INK))
                            .child(check.name.to_string()),
                    )
                    .child(mono(check.pack, MUTED)),
            )
            .child(
                div()
                    .w(px(200.0))
                    .flex()
                    .items_center()
                    .child(verdict_chip(check.verdict)),
            )
            .child(
                div()
                    .w(px(170.0))
                    .flex()
                    .items_center()
                    .gap(px(10.0))
                    .child(meter_slim(check.confidence as f32, 10))
                    .child(mono(&format!("{}%", check.confidence), INK_2)),
            )
            .child(div().w(px(120.0)).child(mono(check.took, INK_2)));
        table = table.child(row);
        if ri + 1 < data::CHECKS.len().min(3) {
            table = table.child(hairline());
        }
    }

    let all_history = plate_s("home-all", "All history").on_click(open_history);
    table = table.child(
        div()
            .mt(px(16.0))
            .pt(px(16.0))
            .flex()
            .items_center()
            .justify_end()
            .child(all_history),
    );

    let _ = app;

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .child(total_card("Checks run", "26", "last: 2 min ago"))
                .child(total_card("Claims backed", "1 214", "of 1 402 stored"))
                .child(total_card("Sources read", "388", "from 96 sites")),
        )
        .child(waiting)
        .child(
            div()
                .id("home-table-scroll")
                .overflow_x_scroll()
                .child(table.min_w(px(760.0))),
        )
}
