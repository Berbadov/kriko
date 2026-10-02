//! The live actions dock: the right-hand bar where the running agents are
//! watched and answered. Every tab sits beside it; the reply field at the
//! bottom posts straight into the feed.

use gpui::{
    div, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Styled, Window,
};

use crate::app::{DockFeedEntry, Field, Kriko};
use crate::data;
use crate::screens::{mono, row_desc};
use crate::theme::*;

pub fn dock(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> gpui::Stateful<Div> {
    let motion = !app.reduce_motion;

    // ---- the reply field: answer the agents directly from here ----
    let reply = app.input_field(Field::DockReply, "dock-reply", "Answer the agent...", Some("agents"), window, cx);
    let send = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        let text = this.dock_reply.value.trim().to_string();
        if !text.is_empty() {
            this.dock_reply.value.clear();
            this.dock_feed
                .push(DockFeedEntry::now(format!("You: {text}"), TagState::Done));
            // answering feeds the lane it names, so the bar visibly moves
            this.dock_lane_bump = (this.dock_lane_bump + 1) % data::DOCK_LANES.len();
            cx.notify();
        }
    });

    // ---- the requests: one well each, with the answering key on it ----
    let mut requests: Vec<Div> = Vec::new();
    for (i, request) in data::DOCK_REQUESTS.iter().enumerate() {
        if app.dock_resolved.contains(&i) {
            continue;
        }
        let agent = &data::AGENTS[request.agent];
        let answer = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.dock_resolved.push(i);
            let agent = &data::AGENTS[data::DOCK_REQUESTS[i].agent];
            this.dock_feed.push(DockFeedEntry::now(
                format!("{}: allowed", agent.name),
                TagState::Done,
            ));
            cx.notify();
        });
        let skip = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.dock_resolved.push(i);
            let agent = &data::AGENTS[data::DOCK_REQUESTS[i].agent];
            this.dock_feed.push(DockFeedEntry::now(
                format!("{}: skipped by you", agent.name),
                TagState::Block,
            ));
            cx.notify();
        });
        requests.push(
            well()
                .p(px(12.0))
                .flex()
                .flex_col()
                .gap(px(10.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(10.0))
                        .child(agent_tile(letter_rows(agent.monogram), None))
                        .child(
                            div()
                                .flex()
                                .flex_col()
                                .gap(px(1.0))
                                .child(
                                    div()
                                        .font_family(SANS)
                                        .font_weight(FontWeight::SEMIBOLD)
                                        .text_size(px(13.0))
                                        .text_color(rgb(INK))
                                        .child(agent.name.to_string()),
                                )
                                .child(mono(request.text, MUTED)),
                        ),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(key(("dock-answer", i), request.answer).on_click(answer))
                        .child(ghost(("dock-skip", i), "Skip").on_click(skip)),
                ),
        );
    }

    // ---- the lanes: who is working, on what, how far ----
    let mut lanes: Vec<Div> = Vec::new();
    for (i, lane) in data::DOCK_LANES.iter().enumerate() {
        let agent = &data::AGENTS[lane.agent];
        let progress = (lane.progress as f32
            + if i == app.dock_lane_bump && app.dock_reply_sent > 0 {
                20.0
            } else {
                0.0
            })
        .min(96.0);
        lanes.push(
            div()
                .py(px(10.0))
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(10.0))
                        .child(agent_tile(letter_rows(agent.monogram), None))
                        .child(
                            div()
                                .flex_1()
                                .min_w(px(0.0))
                                .flex()
                                .flex_col()
                                .gap(px(1.0))
                                .child(
                                    div()
                                        .font_family(SANS)
                                        .font_weight(FontWeight::SEMIBOLD)
                                        .text_size(px(13.0))
                                        .text_color(rgb(INK))
                                        .child(agent.name.to_string()),
                                )
                                .child(mono(lane.task, MUTED)),
                        ),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(meter_live(progress, 12, true, motion))
                        .child(tag(TagState::Live, "Live", motion)),
                ),
        );
    }

    // ---- the feed: what just happened in the dock itself ----
    let mut feed_rows: Vec<Div> = Vec::new();
    for entry in app.dock_feed.iter().rev().take(6) {
        feed_rows.push(
            div()
                .py(px(8.0))
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(tag(entry.state, "", motion))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .font_family(SANS)
                        .text_size(px(12.0))
                        .text_color(rgb(INK_2))
                        .child(entry.text.clone()),
                )
                .child(mono("now", DIM)),
        );
    }

    div()
        .id("dock-scroll")
        .w(px(300.0))
        .flex_none()
        .bg(rgb(SURFACE_1))
        .border_l_1()
        .border_color(rgba(HAIRLINE))
        .overflow_y_scroll()
        .flex()
        .flex_col()
        .p(px(16.0))
        .gap(px(16.0))
        .child(
            div()
                .flex()
                .flex_none()
                .items_center()
                .justify_between()
                .child(eyebrow("Live actions"))
                .child(tag(TagState::Live, "Live", motion)),
        )
        .when(!requests.is_empty(), |d| {
            d.child(
                div()
                    .flex()
                    .flex_col()
                    .flex_none()
                    .gap(px(12.0))
                    .child(eyebrow(&format!("Needs you ({})", requests.len())))
                    .children(requests),
            )
        })
        .child(
            div()
                .flex()
                .flex_col()
                .flex_none()
                .gap(px(0.0))
                .child(eyebrow("Working now"))
                .children(lanes),
        )
        .child(
            div()
                .flex()
                .flex_col()
                .flex_none()
                .gap(px(0.0))
                .child(eyebrow("Feed"))
                .children(feed_rows),
        )
        .child(
            div()
                .flex()
                .flex_col()
                .flex_none()
                .gap(px(8.0))
                .child(eyebrow("Reply"))
                .child(div().flex().gap(px(8.0)).child(reply))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .justify_between()
                        .gap(px(8.0))
                        .child(key("dock-send", "Send").on_click(send))
                        .child(row_desc("or press Enter")),
                ),
        )
}
