//! Activity: what Kriko did, and what is waiting for you.
//! A needs-you callout on top (only while a job has put a question to you),
//! a filter under it, the feed in a glass card — the shape of the reference
//! screen. The feed is `/api/operations`, refreshed every five seconds while
//! this tab is open; the callout reads `attention` off `/api/jobs`.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::live::history::{ago, feed_kind, now_secs};
use crate::live::run::kind_word;
use crate::screens::history::clip;
use crate::screens::{empty_note, mono};
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
    let entries: Vec<(String, String, &'static str, TagState)> = h
        .ops
        .iter()
        .map(|op| {
            let mut text = format!("{} {}", words(&op.name), op.state);
            if !op.note.is_empty() {
                text.push_str(&format!(": {}", clip(&op.note, 110)));
            }
            text.push_str(&took(op.ms));
            (ago(op.ts, now), text, feed_kind(op), tag_state(&op.state))
        })
        .filter(|(_, text, kind, _)| {
            query.is_empty() || text.to_lowercase().contains(&query) || kind.contains(&query)
        })
        .collect();

    let mut feed = card();
    feed = feed.child(div().mb(px(14.0)).child(eyebrow("Recent")));

    if !h.ops_loaded {
        feed = feed.child(empty_note("Reading the activity from the engine."));
    } else if entries.is_empty() {
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

    let count = entries.len();
    for (ri, (when, text, kind, state)) in entries.into_iter().enumerate() {
        let row = div()
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
        feed = feed.child(row);
        if ri + 1 < count {
            feed = feed.child(hairline());
        }
    }

    // Agent runs have a richer job record than the operations feed above:
    // name the agent/model and let the reader open the complete answer/log.
    let recent_jobs: Vec<_> = app.live.run.jobs.iter()
        .filter(|job| job.is_research_like() || job.kind == "compare_ask")
        .take(20)
        .collect();
    let mut runs = card().flex().flex_col().gap(px(10.0))
        .child(div().mb(px(4.0)).child(eyebrow("Agent runs")));
    if recent_jobs.is_empty() {
        runs = runs.child(empty_note(if app.live.run.jobs_loaded {
            "No agent runs yet."
        } else {
            "Reading completed and running agent jobs."
        }));
    }
    for (i, job) in recent_jobs.iter().enumerate() {
        if i > 0 { runs = runs.child(hairline()); }
        let id = job.id.clone();
        let open = app.live.run.activity_log_open.as_deref() == Some(job.id.as_str());
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.run.activity_log_open = if this.live.run.activity_log_open.as_deref() == Some(id.as_str()) {
                None
            } else {
                Some(id.clone())
            };
            cx.notify();
        });
        let agent = if job.harness.is_empty() { "Agent not reported" } else { &job.harness };
        let model = if job.model.is_empty() { "model not reported" } else { &job.model };
        let line = format!("{} · {} · {} · {}", kind_word(&job.kind), agent, model, job.state);
        runs = runs.child(
            div().flex().items_center().gap(px(12.0))
                .child(div().flex_1().min_w(px(0.0)).flex().flex_col().gap(px(3.0))
                    .child(row_title(&app.live.run.task(job)))
                    .child(row_desc(&line)))
                .child(ghost(format!("activity-run-{}", i), if open { "Hide details" } else { "View details" }).on_click(toggle)),
        );
        if open {
            if !job.answer.is_empty() {
                runs = runs.child(row_desc(&format!("Answer: {}", job.answer)));
            } else if job.done && !job.no_answer_why.is_empty() {
                runs = runs.child(row_desc(&format!("No answer: {}", job.no_answer_why)));
            }
            let log = if !job.log.is_empty() {
                job.log.clone()
            } else {
                job.feed.iter().map(|line| line.text.as_str()).collect::<Vec<_>>().join("\n")
            };
            runs = runs.child(well().p(px(12.0)).font_family(MONO).text_size(px(12.0))
                .text_color(rgb(INK_2)).child(if log.is_empty() { "This run left no log.".to_string() } else { log }));
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .children(callout)
        .child(runs)
        .child(div().flex().child(filter))
        .child(feed)
}
