//! Activity: what Kriko did today, and what is waiting for you.
//! A needs-you callout on top, a filter under it, the day's feed in a glass
//! card — the shape of the reference screen.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::data;
use crate::screens::mono;
use crate::theme::*;

pub fn activity(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    // ---- the needs-you callout ----
    let open_agents = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::Agents;
        cx.notify();
    });
    let callout = callout()
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(tag(TagState::Need, "Needs you", motion))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(16.0))
                        .text_color(rgb(INK))
                        .child("Antigravity CLI needs you to sign in."),
                )
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(14.0))
                        .text_color(rgb(INK_2))
                        .child("It will be skipped in Run until you do"),
                ),
        )
        .child(key("open-agents", "Open agents").on_click(open_agents));

    // ---- the filter ----
    let filter = app.input_field(Field::ActivityFilter, "activity-filter", "Filter activity", Some("search"), window, cx);

    // ---- the feed card ----
    let query = app.activity_filter.value.to_lowercase();
    let entries: Vec<&data::FeedEntry> = data::FEED
        .iter()
        .filter(|e| {
            query.is_empty()
                || e.text.to_lowercase().contains(&query)
                || e.kind.to_lowercase().contains(&query)
        })
        .collect();

    let mut feed = card();
    feed = feed.child(div().mb(px(14.0)).child(eyebrow("Today")));

    if entries.is_empty() {
        feed = feed.child(
            div()
                .py(px(40.0))
                .flex()
                .flex_col()
                .items_center()
                .gap(px(8.0))
                .child(led_matrix(&QUEUE5, LED_DIM, 4.0, 2.0))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(MUTED))
                        .child("Nothing in the feed matches."),
                ),
        );
    }

    for (ri, entry) in entries.iter().enumerate() {
        let row = div()
            .flex()
            .items_center()
            .gap(px(16.0))
            .py(px(14.0))
            .hover(|s| s.bg(rgba(GLASS_1)))
            .child(
                div()
                    .w(px(72.0))
                    .flex_none()
                    .text_align(gpui::TextAlign::Right)
                    .child(mono(entry.time, MUTED)),
            )
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .font_family(SANS)
                    .text_size(px(15.0))
                    .text_color(rgb(INK))
                    .child(entry.text.to_string()),
            )
            .child(tag(entry.state, entry.kind, motion));
        feed = feed.child(row);
        if ri + 1 < entries.len() {
            feed = feed.child(hairline());
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(callout)
        .child(div().flex().child(filter))
        .child(feed)
}
