//! The live actions dock: the right-hand bar where the running agents are
//! watched and answered. Every tab sits beside it; the reply field at the
//! bottom posts straight into the feed.

use gpui::{
    div, prelude::*, px, rgb, rgba, Animation, AnimationExt, Context, Div, FontWeight, Styled,
    Window,
};

use crate::app::{DockFeedEntry, Field, Kriko};
use crate::data;
use crate::screens::{mono, row_desc};
use crate::marks::{mark_glyph, mark_tile, phase_beat, Phase};
use crate::theme::*;

pub fn dock(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> gpui::Stateful<Div> {
    let motion = !app.reduce_motion;

    let send = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        let text = this.dock_reply.value.trim().to_string();
        if !text.is_empty() {
            this.dock_reply.value.clear();
            this.dock_feed
                .push(DockFeedEntry::now(format!("You: {text}"), TagState::Done));
            // answering feeds the lane it names, so the bar visibly moves
            this.dock_lane_bump = (this.dock_lane_bump + 1) % data::DOCK_LANES.len();
            this.dock_reply_sent += 1;
        }
        // the drawer closes once you have answered
        this.dock_reply_open = false;
        cx.notify();
    });

    // ---- the requests: only while an agent is asking ----
    let mut requests: Vec<gpui::Stateful<Div>> = Vec::new();
    for (i, request) in data::DOCK_REQUESTS.iter().enumerate() {
        if !app.dock_request_active[i] || app.dock_resolved.contains(&i) {
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
        // a click anywhere on the request re-opens the reply drawer, in
        // case it was collapsed while the agent is still asking
        let open_reply = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.dock_reply_open = true;
            cx.notify();
        });
        requests.push(
            well()
                .id(("dock-request", i))
                .p(px(12.0))
                .flex()
                .flex_col()
                .gap(px(10.0))
                .cursor_pointer()
                .on_click(open_reply)
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(10.0))
                        .child(mark_tile(&format!("dock-req-{i}"), agent.mark, Phase::Waiting, 40.0, motion))
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
                        .child(mark_glyph(
                            &format!("dock-lane-tile-{i}"), agent.mark, lane.phase, 34.0, false,
                        ))
                        .child(
                            div()
                                .flex_1()
                                .min_w(px(0.0))
                                .flex()
                                .flex_col()
                                .gap(px(1.0))
                                .child(
                                    div()
                                        .flex()
                                        .items_center()
                                        .justify_between()
                                        .gap(px(8.0))
                                        .child(
                                            div()
                                                .font_family(SANS)
                                                .font_weight(FontWeight::SEMIBOLD)
                                                .text_size(px(13.0))
                                                .text_color(rgb(INK))
                                                .child(agent.name.to_string()),
                                        )
                                        .child(phase_beat(&format!("dock-lane-beat-{i}"), lane.phase, motion)),
                                )
                                .child(mono(lane.task, MUTED)),
                        ),
                )
                // The phase lights above are the lane's single activity
                // signal. Progress stays readable without a second blink.
                .child(meter(progress, 12)),
        );
    }

    // ---- the feed: what just happened in the dock itself ----
    let mut feed_rows: Vec<Div> = Vec::new();
    for (ri, entry) in app.dock_feed.iter().rev().take(6).enumerate() {
        feed_rows.push(
            div()
                .py(px(8.0))
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(tag(format!("dock-feed-{ri}"), entry.state, "", motion))
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

    // ---- the reply drawer: it only exists while you are answering ----
    let reply_drawer: Option<gpui::AnyElement> = if app.dock_reply_open {
        // the field is built only now that the drawer is open
        let reply = app.input_field(Field::DockReply, "dock-reply", "Answer the agent...", Some("agents"), window, cx);
        let collapse = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.dock_reply_open = false;
            cx.notify();
        });
        let block = div()
            .flex()
            .flex_col()
            .flex_none()
            .gap(px(8.0))
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(eyebrow("Reply"))
                    .child(div().flex_1())
                    .child(
                        div()
                            .id("dock-reply-collapse")
                            .size(px(24.0))
                            .flex()
                            .items_center()
                            .justify_center()
                            .rounded(px(6.0))
                            .cursor_pointer()
                            .child(icon("collapse", 12.0).text_color(rgb(DIM)))
                            .hover(|s| s.bg(rgba(GLASS_1)))
                            .on_click(collapse),
                    ),
            )
            .child(div().flex().gap(px(8.0)).child(reply))
            .child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap(px(8.0))
                    .child(key("dock-send", "Send").on_click(send))
                    .child(row_desc("or press Enter")),
            );
        let block: gpui::AnyElement = if motion {
            block
                .with_animation(
                    gpui::ElementId::NamedInteger(
                        gpui::SharedString::from("dock-reply-drawer"),
                        1,
                    ),
                    Animation::new(std::time::Duration::from_millis(260)),
                    |el, t| el.opacity(t),
                )
                .into_any_element()
        } else {
            block.into_any_element()
        };
        Some(block)
    } else {
        // closed: the drawer does not exist at all. It opens by itself when
        // an agent asks, and a click on a request re-opens it.
        None
    };

    // The dock: a pinned head, a scrolling middle, a pinned reply drawer.
    // The head never scrolls away and the drawer is always in reach; only
    // the requests, lanes and feed move.
    div()
        .id("dock-scroll")
        .w(px(300.0))
        .flex_none()
        .bg(rgb(SURFACE_1))
        .border_l_1()
        .border_color(rgba(HAIRLINE))
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
                .child(tag("dock-live", TagState::Live, "Live", motion).flex_none()),
        )
        .when(!requests.is_empty(), |d| {
            // The block pops in when an agent starts asking: the count rides
            // the id, so a new question remounts it and the fade replays.
            let count = requests.len();
            let block = div()
                .flex()
                .flex_col()
                .flex_none()
                .gap(px(12.0))
                .child(eyebrow(&format!("Needs you ({count})")))
                .children(requests);
            let block: gpui::AnyElement = if motion {
                block
                    .with_animation(
                        gpui::ElementId::NamedInteger(
                            gpui::SharedString::from("dock-requests"),
                            count as u64,
                        ),
                        Animation::new(std::time::Duration::from_millis(360)),
                        |el, t| el.opacity(t),
                    )
                    .into_any_element()
            } else {
                block.into_any_element()
            };
            d.child(block)
        })
        // the scrolling middle: only the sections move, the head and the
        // reply drawer stay put
        .child(
            div()
                .id("dock-sections-scroll")
                .flex()
                .flex_1()
                .min_h(px(0.0))
                .flex_col()
                .gap(px(16.0))
                .overflow_y_scroll()
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
                ),
        )
        .children(reply_drawer)
}
