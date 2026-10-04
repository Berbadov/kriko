//! Run: one check, from question to stored claims. The subject banner holds
//! the question and the phase stepper; the agent lanes are the same lanes
//! the dock watches; the feed grows as the run moves. No verdicts anywhere:
//! when the run ends, the claims are simply stored.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, Animation, AnimationExt,
    Context, Div, FontWeight, Styled, Window,
};

use crate::app::Kriko;
use crate::data;
use crate::screens::{mono, plate_s, row_title};
use crate::marks::{mark_tile, phase_beat, Phase};
use crate::theme::*;

/// The run's phases, in order. `Kriko` advances `run_phase` through them
/// while the Run tab is on screen; Run draws whatever step it has reached.
pub const PHASES: [&str; 4] = ["READ", "GROUND", "SETTLE", "STORED"];

pub fn run(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let replay = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.run_phase = 0;
        cx.notify();
    });
    let phase = app.run_phase.min(PHASES.len());
    let stored = phase >= PHASES.len();

    // ---- the stepper: READ - GROUND - SETTLE - STORED ----
    let mut stepper = div().flex().items_center().gap(px(8.0));
    for (i, name) in PHASES.iter().enumerate() {
        let done = phase > i;
        let live = phase == i;
        let mut seg = well()
            .h(px(36.0))
            .flex()
            .items_center()
            .px(px(14.0))
            .gap(px(10.0))
            .when(live, |s| {
                s.bg(linear_gradient(
                    180.0,
                    linear_color_stop(hsla(BRAND_HOVER), 0.0),
                    linear_color_stop(hsla(BRAND_LOW), 1.0),
                ))
                .border_color(rgba(0xffffff40))
                .shadow(vec![shadow(0x0f2a9c99, 0.0, 2.0, 8.0, 0.0)])
            });
        // done phases carry their check, the live phase broadcasts with the
        // same ripple the dock lanes use, pending ones stay dim
        let glyph = if live {
            led_ripple(&format!("run-phase-{i}"), motion)
        } else if done {
            led_matrix(&CHECK5, INK_2, 3.0, 1.0)
        } else {
            led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0)
        };
        seg = seg.child(glyph);
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
    stepper = stepper.child(plate_s("run-replay", "Replay").on_click(replay));

    // ---- the subject: the question this run is answering ----
    let subject = card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(eyebrow("Run 14 · from the browser extension"))
        .child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::BOLD)
                .text_size(px(20.0))
                .text_color(rgb(INK))
                .child("Samsung Galaxy Buds2 Pro — what does the measured evidence say?"),
        )
        .child(mono(
            "started just now · 3 claims to ground · rtings.com + 2 packs",
            DIM,
        ))
        .child(div().mt(px(8.0)).child(stepper));

    // ---- agent lanes: the same lanes the dock watches, at reading size ----
    let mut lanes = card().flex().flex_col().gap(px(0.0));
    lanes = lanes.child(div().mb(px(12.0)).child(eyebrow("Agent lanes")));
    for (i, lane) in data::DOCK_LANES.iter().enumerate() {
        let agent = &data::AGENTS[lane.agent];
        // the bars move with the run: each phase adds a push
        let progress = (lane.progress as f32 + phase as f32 * 9.0).min(96.0);
        // what the agent is doing moves on with the run: read, think, write,
        // in turn, each lane a step apart; a stored run leaves them idle
        let lane_phase = if stored {
            Phase::Idle
        } else {
            let cycle = [Phase::Reading, Phase::Thinking, Phase::Writing];
            let start = cycle.iter().position(|p| *p == lane.phase).unwrap_or(0);
            cycle[(start + phase as usize) % cycle.len()]
        };
        lanes = lanes.child(
            div()
                .py(px(14.0))
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(14.0))
                        .child(mark_tile(&format!("run-lane-tile-{i}"), agent.mark, lane_phase, 48.0, motion))
                        .child(
                            div()
                                .flex_1()
                                .min_w(px(0.0))
                                .flex()
                                .flex_col()
                                .gap(px(2.0))
                                .child(
                                    div()
                                        .flex()
                                        .items_center()
                                        .justify_between()
                                        .gap(px(12.0))
                                        .child(row_title(agent.name))
                                        .child(phase_beat(&format!("run-lane-beat-{i}"), lane_phase, motion)),
                                )
                                .child(mono(lane.task, MUTED)),
                        ),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(12.0))
                        .child(
                            meter_live(
                                format!("run-lane-meter-{i}"),
                                progress,
                                28,
                                !stored,
                                motion,
                            )
                            .flex_1(),
                        )
                        // a stored run leaves its lanes quiet, with checks
                        .child(if stored {
                            led_matrix(&CHECK5, INK_2, 3.0, 1.0)
                        } else {
                            led_ripple(&format!("run-lane-{i}"), motion)
                        }),
                ),
        );
    }

    // ---- the feed: one line per step, growing as the run moves ----
    let steps: [(usize, &str); PHASES.len()] = [
        (1, "Reading rtings.com/samsung/buds2-pro"),
        (2, "Grounding 3 claims against stored evidence"),
        (3, "Settling the battery dispute with the pack"),
        (4, "Stored 12 claims to the samsung.headphones pack"),
    ];
    let mut rows: Vec<(TagState, &str)> = Vec::new();
    for (j, text) in steps.iter().rev() {
        if phase >= *j {
            let state = if phase == *j && !stored {
                TagState::Live
            } else {
                TagState::Done
            };
            rows.push((state, *text));
        }
    }
    rows.push((TagState::Done, "Run 14 started from the browser extension"));

    let mut feed = card().flex().flex_col();
    feed = feed.child(div().mb(px(12.0)).child(eyebrow("Live feed")));
    for (i, (state, text)) in rows.iter().enumerate() {
        let line = div()
            .py(px(10.0))
            .flex()
            .items_center()
            .gap(px(14.0))
            .child(tag(format!("run-feed-{i}"), *state, "", motion))
            .child(
                div()
                    .flex_1()
                    .font_family(SANS)
                    .text_size(px(14.0))
                    .text_color(rgb(INK_2))
                    .child(text.to_string()),
            );
        // the newest line fades in as it lands; the id carries the phase
        // so each new line mounts its own fade
        let line: gpui::AnyElement = if motion && i == 0 && phase > 0 {
            line.with_animation(
                gpui::ElementId::named_usize("run-feed-in", phase),
                Animation::new(std::time::Duration::from_millis(450)).with_easing(|t| t * t),
                |el, v| el.opacity(v),
            )
            .into_any_element()
        } else {
            line.into_any_element()
        };
        feed = feed.child(line);
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(subject)
        .child(lanes)
        .child(feed)
}
