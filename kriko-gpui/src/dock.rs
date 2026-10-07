//! The live actions dock: the right-hand bar where the running jobs are
//! watched and answered. Every tab sits beside it. What it shows is the
//! engine's own jobs (`live::run`): one lane per running job, the questions
//! a job put to you, the last lines of its feed, and a reply field that says
//! a line to the running job.

use gpui::{
    div, prelude::*, px, rgb, rgba, Animation, AnimationExt, Context, Div, FontWeight, Styled,
    Window,
};

use crate::app::{Field, Kriko};
use crate::live::run::mark_for;
use crate::marks::{mark_glyph, mark_tile, Phase};
use crate::screens::run::option_chip;
use crate::screens::{empty_note, mono, row_desc};
use crate::theme::*;

pub fn dock(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> gpui::Stateful<Div> {
    let motion = !app.reduce_motion;

    let send = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.send_reply(cx);
        cx.notify();
    });
    let toggle_logs = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.dock_logs_open = !this.dock_logs_open;
        cx.notify();
    });
    let close_logs = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.dock_logs_open = false;
        cx.notify();
    });

    // ---- the requests: jobs that put a question to you ----
    let mut requests: Vec<Div> = Vec::new();
    for (i, job) in app.live.run.needs_you().into_iter().enumerate() {
        let Some(att) = &job.attention else { continue };
        let mut block = well()
            .p(px(12.0))
            .flex()
            .flex_col()
            .gap(px(10.0))
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(10.0))
                    .child(mark_tile(
                        &format!("dock-req-{i}"),
                        mark_for(&job.harness),
                        Phase::Waiting,
                        40.0,
                        motion,
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
                                    .font_family(SANS)
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .text_size(px(13.0))
                                    .text_color(rgb(INK))
                                    .child(app.live.run.task(job)),
                            )
                            .child(mono(&format!("{} question(s)", att.questions.len()), MUTED)),
                    ),
            )
            .child(row_desc(&att.say));
        for (qi, q) in att.questions.iter().enumerate() {
            let chosen = app
                .live
                .run
                .answers
                .get(&q.id)
                .cloned()
                .unwrap_or_else(|| q.default.clone());
            let mut options = div().flex().flex_wrap().gap(px(6.0));
            for (oi, opt) in q.options.iter().enumerate() {
                let (qid, o) = (q.id.clone(), opt.clone());
                let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    this.pick_answer(qid.clone(), o.clone());
                    cx.notify();
                });
                options = options.child(
                    option_chip(("dock-opt", (i * 8 + qi) * 16 + oi), opt, *opt == chosen)
                        .on_click(pick),
                );
            }
            block = block.child(
                div()
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(12.0))
                            .text_color(rgb(INK_2))
                            .child(q.ask.clone()),
                    )
                    .child(options),
            );
        }
        if job.done {
            let id = job.id.clone();
            let answer = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.answer_job(id.clone(), cx);
                cx.notify();
            });
            block = block.child(key(("dock-answer", i), "Run again with answers").on_click(answer));
        } else {
            block = block.child(row_desc("Answers go into the next run."));
        }
        requests.push(block);
    }

    // ---- the lanes: who is working, on what, how far ----
    let mut lanes: Vec<Div> = Vec::new();
    for (i, job) in app.live.run.running().enumerate() {
        let phase = job.lane_phase();
        let agent = mark_for(&job.harness);
        let status = if job.message.is_empty() { job.state.clone() } else { job.message.clone() };
        let stop: gpui::AnyElement = if job.state == "cancelling" {
            row_desc("Stopping…").into_any_element()
        } else {
            let id = job.id.clone();
            let cancel = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.stop_job(id.clone(), cx);
                cx.notify();
            });
            danger_s(("dock-lane-stop", i), "Stop")
                .on_click(cancel)
                .into_any_element()
        };
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
                            &format!("dock-lane-tile-{i}"),
                            agent,
                            phase,
                            34.0,
                            motion,
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
                                        .min_w(px(0.0))
                                        .child(
                                            div()
                                                .min_w(px(0.0))
                                                .truncate()
                                                .font_family(SANS)
                                                .font_weight(FontWeight::SEMIBOLD)
                                                .text_size(px(13.0))
                                                .text_color(rgb(INK))
                                                .child(app.live.run.task(job)),
                                        )
                                        .child(stop),
                                )
                                .child(div().truncate().child(mono(&status, MUTED))),
                        ),
                ),
        );
    }

    // ---- the feed: the last lines of running jobs, then finished-job notices ----
    let mut lines: Vec<(TagState, String)> = Vec::new();
    for entry in app.dock_feed.iter().rev().take(3) {
        lines.push((entry.state, entry.text.clone()));
    }
    for job in app.live.run.running() {
        for line in job.feed.iter().rev().take(2) {
            let state = if line.kind == "problem" { TagState::Block } else { TagState::Live };
            lines.push((state, line.text.clone()));
        }
    }
    lines.extend(app.live.run.notices());
    let mut feed_rows: Vec<Div> = Vec::new();
    for (ri, (state, text)) in lines.into_iter().take(8).enumerate() {
        feed_rows.push(
            div()
                .py(px(8.0))
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(tag(format!("dock-feed-{ri}"), state, "", motion))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .font_family(SANS)
                        .text_size(px(12.0))
                        .text_color(rgb(INK_2))
                        .child(text),
                ),
        );
    }

    let mut log_rows: Vec<gpui::AnyElement> = app
        .live
        .run
        .running()
        .enumerate()
        .map(|(i, job)| {
            let task = app.live.run.task(job);
            let log = if job.log.trim().is_empty() {
                job.message.clone()
            } else {
                job.log.clone()
            };
            div()
                .id(("dock-log-job", i))
                .flex()
                .flex_col()
                .flex_none()
                .gap(px(4.0))
                .child(mono(&task, ICE))
                .child(
                    div()
                        .id(("dock-log-text", i))
                        .min_h(px(0.0))
                        .max_h(px(180.0))
                        .overflow_y_scroll()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(MUTED))
                        .child(if log.is_empty() {
                            "Waiting for agent output.".to_string()
                        } else {
                            log
                        }),
                )
                .into_any_element()
        })
        .collect();
    if log_rows.is_empty() {
        log_rows.push(empty_note("No agent is running.").into_any_element());
    }
    let log_drawer = div()
        .id("dock-log-drawer")
        .flex()
        .flex_none()
        .flex_col()
        .max_h(px(280.0))
        .gap(px(8.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(eyebrow("Agent logs"))
                .child(key("dock-logs-close", "Close").on_click(close_logs)),
        )
        .child(
            div()
                .id("dock-log-list")
                .flex()
                .flex_1()
                .min_h(px(0.0))
                .flex_col()
                .gap(px(10.0))
                .overflow_y_scroll()
                .children(log_rows),
        );

    // ---- the reply: to the running job, disabled when none ----
    let target = app.live.run.reply_target().map(|j| app.live.run.task(j));
    // Conditional: with nothing running there is nobody to answer, so the
    // section is not drawn at all rather than standing there empty.
    let reply_drawer: Option<gpui::AnyElement> = match (&target, app.dock_reply_open) {
        (None, _) => None,
        (Some(task), false) => {
            let open = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                this.dock_reply_open = true;
                cx.notify();
            });
            Some(
                ghost("dock-reply-open", &format!("Reply to {task}"))
                    .w_full()
                    .min_w(px(0.0))
                    .overflow_x_hidden()
                    .truncate()
                    .on_click(open)
                    .into_any_element(),
            )
        }
        (Some(task), true) => {
            // the field is built only now that the drawer is open
            let reply = app.input_field(
                Field::DockReply,
                "dock-reply",
                "Say it to the agent...",
                Some("agents"),
                window,
                cx,
            );
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
                        .min_w(px(0.0))
                        .w_full()
                        .gap(px(8.0))
                        .child(eyebrow("Reply").flex_none())
                        .child(
                            div()
                                .flex_1()
                                .min_w(px(0.0))
                                .overflow_x_hidden()
                                .truncate()
                                .child(mono(task, DIM)),
                        )
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
                .child(
                    div()
                        .flex()
                        .min_w(px(0.0))
                        .gap(px(8.0))
                        .child(reply.flex_1().min_w(px(0.0))),
                )
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
        }
    };

    // The dock: a pinned head, a scrolling middle, a pinned reply drawer.
    // The head never scrolls away and the drawer is always in reach; only
    // the requests, lanes and feed move.
    let nothing_running = lanes.is_empty();
    let loaded = app.live.run.jobs_loaded;
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
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(6.0))
                        .child(
                            key(
                                "dock-logs-toggle",
                                if app.dock_logs_open { "Hide logs" } else { "Logs" },
                            )
                            .on_click(toggle_logs),
                        )
                        .child(tag("dock-live", TagState::Live, "Live", motion).flex_none()),
                ),
        )
        .when(app.dock_logs_open, |d| d.child(log_drawer))
        .when(!requests.is_empty(), |d| {
            // The block pops in when a job starts asking: the count rides
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
                        .when(nothing_running, |d| {
                            d.child(div().mt(px(8.0)).child(empty_note(if loaded {
                                "No agent is working."
                            } else {
                                "Waiting for the engine."
                            })))
                        })
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
