//! Activity: what Kriko did, and what is waiting for you.
//! A needs-you callout on top (only while a job has put a question to you),
//! a filter under it, the feed in a glass card — the shape of the reference
//! screen. The feed is `/api/operations`, refreshed every five seconds while
//! this tab is open; the callout reads `attention` off `/api/jobs`.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::live::history::{ago, feed_kind, now_secs, Op};
use crate::screens::history::clip;
use crate::screens::{empty_note, mono, plate_s};
use crate::theme::*;

/// An operation's name as words: `pack_update` reads "Pack update".
fn words(name: &str) -> String {
    let flat = name.replace('_', " ");
    let mut chars = flat.chars();
    match chars.next() {
        Some(c) => c.to_uppercase().collect::<String>() + chars.as_str(),
        None => String::new(),
    }
}

/// The state tag an operation's state earns.
fn tag_state(state: &str) -> TagState {
    match state {
        "running" | "queued" => TagState::Live,
        "failed" | "error" => TagState::Block,
        "ok" | "done" => TagState::Done,
        _ => TagState::Queue,
    }
}

/// How long an operation took, said short; nothing when it was not measured.
fn took(ms: Option<f64>) -> String {
    match ms {
        None => String::new(),
        Some(ms) if ms < 1000.0 => format!(" · {} ms", ms as i64),
        Some(ms) => format!(" · {:.1} s", ms / 1000.0),
    }
}

/// What one operation says about itself, read as a sentence.
fn op_text(op: &Op) -> String {
    let mut text = format!("{} {}", words(&op.name), op.state);
    if !op.note.is_empty() {
        text.push_str(&format!(": {}", clip(&op.note, 110)));
    }
    if !op.harness.is_empty() {
        text.push_str(&format!(" · with {}", op.harness));
    }
    if !op.model.is_empty() {
        text.push_str(&format!(" · model {}", op.model));
    }
    text.push_str(&took(op.ms));
    text
}

/// The job log an expanded row unfolds into, newest line last.
fn op_log_block(app: &Kriko, op: &Op) -> Div {
    let mut block = well().mt(px(6.0)).p(px(12.0)).flex().flex_col().gap(px(6.0));
    let Some(lines) = app.live.history.op_logs.get(&op.op_id) else {
        return block.child(mono("Reading the log.", MUTED));
    };
    if lines.is_empty() {
        return block.child(mono("This job left no log.", MUTED));
    }
    block = block.child(mono(&format!("{} lines", lines.len()), DIM));
    let mut list = div().id("activity-log-lines").max_h(px(280.0)).overflow_y_scroll().flex().flex_col();
    for line in lines {
        list = list.child(
            div()
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(if line.kind == "problem" { 0xffb86b } else { INK_2 }))
                .child(line.text.clone()),
        );
    }
    block.child(list)
}

pub fn activity(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    // ---- the needs-you callout: only while a job has put a question ----
    let callout = app.live.history.attention.clone().map(|say| {
        let open_run = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.tab = Tab::Run;
            cx.notify();
        });
        callout()
            .child(
                div()
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(tag("activity-need", TagState::Need, "Needs you", motion))
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(16.0))
                            .text_color(rgb(INK))
                            .child(say),
                    ),
            )
            .child(key("open-run", "Open run").on_click(open_run))
    });

    // ---- the filter ----
    let filter = app.input_field(
        Field::ActivityFilter,
        "activity-filter",
        "Filter activity",
        Some("search"),
        window,
        cx,
    );

    // ---- the feed card ----
    let query = app.activity_filter.value.to_lowercase();
    let now = now_secs();
    let h = &app.live.history;
    let open = h.op_open;
    let shown: Vec<&Op> = h
        .ops
        .iter()
        .filter(|op| {
            if query.is_empty() {
                return true;
            }
            let text = op_text(op);
            text.to_lowercase().contains(&query) || feed_kind(op).contains(&query)
        })
        .collect();

    let mut feed = card();
    feed = feed.child(div().mb(px(14.0)).child(eyebrow("Recent")));

    if !h.ops_loaded {
        feed = feed.child(empty_note("Reading the activity from the engine."));
    } else if shown.is_empty() {
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
                        .child(if h.ops.is_empty() {
                            "Nothing has happened yet."
                        } else {
                            "Nothing in the feed matches."
                        }),
                ),
        );
    }

    let count = shown.len();
    for (ri, op) in shown.into_iter().enumerate() {
        let when = ago(op.ts, now);
        let text = op_text(op);
        let kind = feed_kind(op);
        let state = tag_state(&op.state);
        let mut row = div()
            .flex()
            .items_center()
            .gap(px(16.0))
            .py(px(14.0))
            .hover(|s| s.bg(rgba(GLASS_1)))
            .child(
                div()
                    .w(px(90.0))
                    .flex_none()
                    .text_align(gpui::TextAlign::Right)
                    .child(mono(&when, MUTED)),
            )
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .font_family(SANS)
                    .text_size(px(15.0))
                    .text_color(rgb(INK))
                    .child(text),
            )
            .child(tag(format!("activity-feed-{ri}"), state, kind, motion));
        if !op.job_id.is_empty() {
            let (op_id, job_id) = (op.op_id, op.job_id.clone());
            let unfold = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.open_op_log(op_id, job_id.clone(), cx);
            });
            row = row.child(
                plate_s(
                    gpui::ElementId::named_usize("activity-log", ri),
                    if open == Some(op.op_id) { "Hide log" } else { "Log" },
                )
                .on_click(unfold),
            );
        }
        let mut block = div().flex().flex_col().child(row);
        if open == Some(op.op_id) && !op.job_id.is_empty() {
            block = block.child(op_log_block(app, op));
        }
        feed = feed.child(block);
        if ri + 1 < count {
            feed = feed.child(hairline());
        }
    }
    if h.ops_has_older {
        let older = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.load_older_activity(cx);
            cx.notify();
        });
        feed = feed.child(
            div()
                .pt(px(14.0))
                .flex()
                .justify_center()
                .child(plate_s(
                    "activity-older",
                    if h.ops_older_inflight { "Loading" } else { "Load older activity" },
                ).on_click(older)),
        );
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .children(callout)
        .child(div().flex().child(filter))
        .child(feed)
}
