//! Run: one check, from question to verdict. A phase stepper, the agent
//! lanes, the decision card, and the live feed underneath.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, Context, Div, Styled,
    Window,
};

use crate::app::{Kriko, Tab};
use crate::data;
use crate::screens::{mono, plate_s, row_desc, row_title};
use crate::theme::*;

const PHASES: [&str; 5] = ["READ", "GROUND", "SETTLE", "VERDICT", "STORED"];

pub fn run(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let step = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.run_phase = (this.run_phase + 1) % (PHASES.len() + 1);
        cx.notify();
    });
    let phase = app.run_phase;

    // ---- the stepper: READ - GROUND - SETTLE - VERDICT - STORED ----
    let mut stepper = div().flex().items_center().gap(px(8.0)).mb(px(24.0));
    for (i, name) in PHASES.iter().enumerate() {
        let done = phase > i;
        let live = phase == i;
        let mut seg = well()
            .h(px(36.0))
            .flex()
            .items_center()
            .px(px(14.0))
            .gap(px(8.0))
            .when(live, |s| {
                s.bg(linear_gradient(
                    180.0,
                    linear_color_stop(hsla(BRAND_HOVER), 0.0),
                    linear_color_stop(hsla(BRAND_LOW), 1.0),
                ))
                .border_color(rgba(0xffffff40))
                .shadow(vec![shadow(0x0f2a9c99, 0.0, 2.0, 8.0, 0.0)])
            });
        seg = seg.child(
            led_matrix(
                if done { &CHECK5 } else { &QUEUE5 },
                if done { INK_2 } else if live { 0xffffff } else { LED_DIM },
                3.0,
                1.0,
            ),
        );
        seg = seg.child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(if live {
                    0xffffff
                } else if done {
                    INK_2
                } else {
                    MUTED
                }))
                .child(*name),
        );
        stepper = stepper.child(seg);
    }
    stepper = stepper.child(div().flex_1());
    stepper = stepper.child(plate_s("run-step", "Step").on_click(step));

    // ---- agent lanes ----
    let mut lanes = card().flex().flex_col().gap(px(0.0));
    lanes = lanes.child(div().mb(px(12.0)).child(eyebrow("Agent lanes")));
    for agent in data::AGENTS.iter().take(4) {
        let active = agent.state == TagState::Live || agent.state == TagState::Need;
        lanes = lanes.child(
            div()
                .py(px(12.0))
                .flex()
                .items_center()
                .gap(px(14.0))
                .child(agent_tile(letter_rows(agent.monogram), None))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title(agent.name))
                        .child(mono(agent.latency, MUTED)),
                )
                .child(tag(agent.state, agent.state_label, motion))
                .when(active, |s| s.opacity(1.0))
                .when(!active, |s| s.opacity(0.5)),
        );
    }

    // ---- the decision card ----
    let decided = phase >= PHASES.len();
    let decision = card()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .when(!decided, |d| {
            d.child(
                div()
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(eyebrow("Decision"))
                    .child(row_desc(if phase == 0 {
                        "Nothing yet. Step through the run, or let the agents drive."
                    } else {
                        "Reading and grounding still in flight; the verdict lands at the end."
                    }))
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(10.0))
                            .child(mono("PROGRESS", DIM))
                            .child(
                                meter_live(
                                    phase as f32 / (PHASES.len() as f32) * 100.0,
                                    24,
                                    true,
                                    motion,
                                )
                                .max_w(px(240.0)),
                            ),
                    ),
            )
        })
        .when(decided, |d| {
            d.child(
                div()
                    .flex()
                    .flex_col()
                    .gap(px(10.0))
                    .child(eyebrow("Decision"))
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(16.0))
                            .child(verdict_chip(Verdict::Recommended))
                            .child(
                                div()
                                    .font_family(SANS)
                                    .text_size(px(15.0))
                                    .text_color(rgb(INK))
                                    .child("Samsung Galaxy Buds2 Pro, on measured noise cancelling and IPX7."),
                            ),
                    )
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(10.0))
                            .child(mono("CONFIDENCE", DIM))
                            .child(meter_live(82.0, 24, true, motion).max_w(px(240.0)))
                            .child(mono("82%", INK_2)),
                    ),
            )
        })
        .when(decided, |d| {
            d.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(tag(TagState::Done, "Stored", motion)),
            )
        });

    // ---- feed ----
    let feed_lines = [
        (TagState::Done, "Run 14 started from the browser extension", "just now"),
        (TagState::Live, "Reading rtings.com/samsung/buds2-pro", "2 s ago"),
        (TagState::Live, "Grounding 3 claims against stored evidence", "4 s ago"),
        (TagState::Queue, "Waiting for a verdict", "queued"),
    ];
    let mut feed = card().flex().flex_col();
    feed = feed.child(div().mb(px(12.0)).child(eyebrow("Live feed")));
    for (state, text, when) in feed_lines {
        let lit = match state {
            TagState::Live => true,
            _ => false,
        };
        let _ = lit;
        feed = feed.child(
            div()
                .py(px(10.0))
                .flex()
                .items_center()
                .gap(px(14.0))
                .child(tag(state, "", motion))
                .child(
                    div()
                        .flex_1()
                        .font_family(SANS)
                        .text_size(px(14.0))
                        .text_color(rgb(INK_2))
                        .child(text.to_string()),
                )
                .child(mono(when, DIM)),
        );
    }

    let _ = Tab::Home;

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(stepper)
        .child(
            div()
                .id("run-row-scroll")
                .overflow_x_scroll()
                .child(
                    div()
                        .flex()
                        .gap(px(24.0))
                        .items_start()
                        .min_w(px(904.0))
                        .child(div().flex_1().min_w(px(0.0)).child(lanes))
                        .child(div().w(px(420.0)).flex_none().child(decision)),
                ),
        )
        .child(feed)
}
