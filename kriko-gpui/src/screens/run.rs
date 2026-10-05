//! Run: one check, from question to stored claims. The subject banner holds
//! the job the engine is running (or ran last) and the phase stepper driven
//! from it; the lane is that job's agent; the feed is the engine's own feed
//! for it. No verdicts anywhere: when the run ends, the claims are stored.
//!
//! Everything here is read from `live::run`; while that has not arrived, or
//! the engine has no job, a quiet note stands in.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, Animation, AnimationExt,
    Context, Div, FontWeight, Stateful, Styled, Window,
};

use crate::app::{Field, Kriko};
use crate::live::run::{ago, mark_for, Job, Stage};
use crate::marks::{mark_tile, phase_beat};
use crate::screens::{empty_note, mono, plate_s, row_desc, row_title};
use crate::theme::*;

/// The run's phases, in order, as the LEDs name them.
const PHASES: [&str; 4] = ["QUEUED", "READING", "GROUNDING", "STORED"];

/// A small choice chip: one answer to a question, one agent to pick. The
/// chosen one runs in the brand blue.
pub fn option_chip(id: impl Into<gpui::ElementId>, text: &str, chosen: bool) -> Stateful<Div> {
    let base = div()
        .id(id)
        .h(px(30.0))
        .px(px(12.0))
        .flex()
        .items_center()
        .rounded(px(8.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .cursor_pointer()
        .child(text.to_string());
    if chosen {
        base.text_color(rgb(0xffffff))
            .border_1()
            .border_color(rgba(0xffffff40))
            .bg(linear_gradient(
                180.0,
                linear_color_stop(hsla(BRAND_HOVER), 0.0),
                linear_color_stop(hsla(BRAND_LOW), 1.0),
            ))
    } else {
        base.text_color(rgb(INK_2))
            .border_1()
            .border_color(rgba(BORDER_CONTROL))
            .bg(rgba(GLASS_1))
            .hover(|s| s.bg(rgba(GLASS_2)))
    }
}

pub fn run(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let mut page = div().flex().flex_col().gap(px(24.0));

    let job = app.live.run.current().cloned();
    match (&job, app.live.run.jobs_loaded) {
        (Some(job), _) => {
            page = page.child(subject_card(app, job, motion, cx));
            if job.attention.is_some() {
                page = page.child(questions_card(app, job, cx));
            }
        }
        (None, loaded) => {
            page = page.child(
                card()
                    .flex()
                    .flex_col()
                    .gap(px(12.0))
                    .child(eyebrow("Run"))
                    .child(empty_note(if loaded {
                        "No check has run yet. Start one below."
                    } else {
                        "Waiting for the engine to answer."
                    })),
            );
        }
    }
    page = page.child(start_card(app, window, cx));
    if let Some(job) = &job {
        page = page.child(lane_card(app, job, motion));
        page = page.child(feed_card(job, motion));
    }
    page
}

fn subject_card(app: &Kriko, job: &Job, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let stage = job.stage();
    let terminal = matches!(stage, Stage::Stored | Stage::Failed | Stage::Cancelled);
    let at = stage.index();

    // ---- the stepper: QUEUED - READING - GROUNDING - STORED ----
    let mut stepper = div().flex().items_center().gap(px(8.0));
    for (i, name) in PHASES.iter().enumerate() {
        let ended_badly = matches!(stage, Stage::Failed | Stage::Cancelled) && i == 3;
        let name = if ended_badly {
            if stage == Stage::Failed { "FAILED" } else { "CANCELLED" }
        } else {
            name
        };
        let done = if terminal {
            stage == Stage::Stored && i <= 3
        } else {
            at > i
        };
        let live = !terminal && at == i;
        let lit = live || ended_badly;
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
        let glyph = if live {
            led_ripple(&format!("run-phase-{i}"), motion)
        } else if ended_badly {
            led_matrix(&BANG5, 0xffb86b, 3.0, 1.0)
        } else if done {
            led_matrix(&CHECK5, INK_2, 3.0, 1.0)
        } else {
            led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0)
        };
        seg = seg.child(glyph).child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(if live {
                    0xffffff
                } else if lit {
                    0xffb86b
                } else if done {
                    INK_2
                } else {
                    MUTED
                }))
                .child(name),
        );
        stepper = stepper.child(seg);
    }
    stepper = stepper.child(div().flex_1());
    if !job.done {
        let id = job.id.clone();
        let stop = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.stop_job(id.clone(), cx);
            cx.notify();
        });
        stepper = stepper.child(plate_s("run-stop", "Stop").on_click(stop));
    }

    let when = if job.done {
        format!("finished {}", ago(&job.finished_at))
    } else {
        format!("started {}", ago(&job.created_at))
    };
    let heading = if job.done { "Last run · finished" } else { "Running now" };
    let mut meta = vec![when];
    if !job.harness.is_empty() {
        meta.push(format!("with {}", job.harness));
    }
    if !job.done {
        meta.push(format!("{}%", (job.progress * 100.0).round() as i64));
    }

    card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(eyebrow(heading))
        .child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::BOLD)
                .text_size(px(20.0))
                .text_color(rgb(INK))
                .child(app.live.run.task(job)),
        )
        .child(mono(&meta.join(" · "), DIM))
        .when(!job.message.is_empty(), |c| c.child(row_desc(&job.message)))
        .child(div().mt(px(8.0)).child(stepper))
}

/// The questions a run put to the reader, with their options; answering is
/// a new run that carries them.
fn questions_card(app: &Kriko, job: &Job, cx: &mut Context<Kriko>) -> Div {
    let Some(att) = &job.attention else { return div() };
    let mut c = card().flex().flex_col().gap(px(12.0));
    c = c.child(eyebrow("Needs you")).child(row_desc(&att.say));
    for (qi, q) in att.questions.iter().enumerate() {
        let chosen = app
            .live
            .run
            .answers
            .get(&q.id)
            .cloned()
            .unwrap_or_else(|| q.default.clone());
        let mut options = div().flex().flex_wrap().gap(px(8.0));
        for (oi, opt) in q.options.iter().enumerate() {
            let (qid, o) = (q.id.clone(), opt.clone());
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.pick_answer(qid.clone(), o.clone());
                cx.notify();
            });
            options = options.child(
                option_chip(("run-opt", qi * 16 + oi), opt, *opt == chosen).on_click(pick),
            );
        }
        c = c.child(
            div()
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(row_title(&q.ask))
                .when(!q.because.is_empty(), |d| d.child(row_desc(&q.because)))
                .child(options),
        );
    }
    if job.done {
        let id = job.id.clone();
        let go = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.answer_job(id.clone(), cx);
            cx.notify();
        });
        c = c.child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(key("run-answer", "Run again with answers").on_click(go))
                .child(row_desc("A new run that carries these answers.")),
        );
    } else {
        c = c.child(row_desc("Your answers go into the next run; this one carries on with its own."));
    }
    c
}

/// Start a check: look a subject up, pick it, pick the agent, go.
fn start_card(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let open = app.live.run.start.open;
    let toggle = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        let s = &mut this.live.run.start;
        s.open = !s.open;
        cx.notify();
    });
    let mut c = card().flex().flex_col().gap(px(12.0)).child(
        div()
            .flex()
            .items_center()
            .child(eyebrow("Start a check"))
            .child(div().flex_1())
            .child(plate_s("run-start-toggle", if open { "Close" } else { "New" }).on_click(toggle)),
    );
    if !open {
        return c;
    }

    let search = app.input_field(Field::RunSearch, "run-search", "Find a product...", Some("search"), window, cx);
    let go = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.search_subjects(cx);
        cx.notify();
    });
    c = c.child(
        div()
            .flex()
            .items_center()
            .gap(px(8.0))
            .child(search)
            .child(key("run-search-go", if app.live.run.start.searching { "Looking" } else { "Search" }).on_click(go)),
    );

    let start = &app.live.run.start;
    if let Some(hit) = &start.picked {
        c = c.child(
            well()
                .p(px(12.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(&hit.label))
                .child(mono(&hit.pack_id, DIM)),
        );
        // the agent: the preferred one unless the reader picks another
        let chosen = app.live.run.start_harness();
        let mut agents = div().flex().flex_wrap().gap(px(8.0));
        for (i, h) in app.live.run.harnesses.iter().enumerate() {
            if !matches!(h.state, crate::live::run::RunState::Ready) {
                continue;
            }
            let id = h.id.clone();
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.run.start.harness = id.clone();
                cx.notify();
            });
            agents = agents.child(option_chip(("run-agent", i), &h.label, h.id == chosen).on_click(pick));
        }
        let begin = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.start_check(cx);
            cx.notify();
        });
        let back = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.live.run.start.picked = None;
            cx.notify();
        });
        c = c
            .child(mono("RUN WITH", DIM))
            .child(if app.live.run.harnesses.iter().any(|h| matches!(h.state, crate::live::run::RunState::Ready)) {
                agents
            } else {
                div().child(empty_note("No agent is ready to run a check. See the Agents tab."))
            })
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(key("run-begin", "Start").on_click(begin))
                    .child(ghost("run-back", "Back").on_click(back)),
            );
    } else if start.searched && start.hits.is_empty() && start.note.is_empty() {
        c = c.child(empty_note("Nothing in the installed catalogs matches that."));
    } else {
        for (i, hit) in start.hits.iter().enumerate() {
            let h = hit.clone();
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.run.start.picked = Some(h.clone());
                cx.notify();
            });
            c = c.child(
                well()
                    .id(("run-hit", i))
                    .p(px(12.0))
                    .flex()
                    .flex_col()
                    .gap(px(2.0))
                    .cursor_pointer()
                    .hover(|s| s.bg(rgba(GLASS_1)))
                    .on_click(pick)
                    .child(row_title(&hit.label))
                    .child(mono(
                        &format!("{} · {} claims", hit.identity, hit.claims),
                        DIM,
                    )),
            );
        }
    }
    if !start.note.is_empty() {
        c = c.child(row_desc(&start.note));
    }
    c
}

/// The agent doing the job: its mark, what it is doing, how far.
fn lane_card(app: &Kriko, job: &Job, motion: bool) -> Div {
    let agent = if job.harness.is_empty() { "agent" } else { job.harness.as_str() };
    let label = app
        .live
        .run
        .harnesses
        .iter()
        .find(|h| h.id == job.harness)
        .map(|h| h.label.clone())
        .unwrap_or_else(|| if job.harness.is_empty() { "Agent".to_string() } else { job.harness.clone() });
    let phase = job.lane_phase();
    let progress = if job.done { 100.0 } else { job.progress * 100.0 };
    card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Agent"))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(14.0))
                .child(mark_tile("run-lane-tile", mark_for(agent), phase, 48.0, motion))
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
                                .child(row_title(&label))
                                .child(phase_beat("run-lane-beat", phase, motion)),
                        )
                        .child(mono(&app.live.run.task(job), MUTED)),
                ),
        )
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(meter_live("run-lane-meter", progress, 28, !job.done, motion).flex_1())
                .child(if job.done {
                    led_matrix(&CHECK5, INK_2, 3.0, 1.0)
                } else {
                    led_ripple("run-lane", motion)
                }),
        )
}

/// The engine's feed for the job, newest first.
fn feed_card(job: &Job, motion: bool) -> Div {
    let mut feed = card().flex().flex_col();
    feed = feed.child(div().mb(px(12.0)).child(eyebrow(if job.done { "Log" } else { "Live feed" })));
    if job.feed.is_empty() {
        return feed.child(empty_note(if job.done {
            "This run left no log."
        } else {
            "Nothing yet. Lines land here as the agent reads and writes."
        }));
    }
    let count = job.feed.len();
    for (i, line) in job.feed.iter().rev().enumerate() {
        let state = if line.kind == "problem" {
            TagState::Block
        } else if i == 0 && !job.done {
            TagState::Live
        } else {
            TagState::Done
        };
        let row = div()
            .py(px(10.0))
            .flex()
            .items_center()
            .gap(px(14.0))
            .child(tag(format!("run-feed-{i}"), state, "", motion))
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .font_family(SANS)
                    .text_size(px(14.0))
                    .text_color(rgb(INK_2))
                    .child(line.text.clone()),
            );
        // the newest line fades in as it lands; the count rides the id so
        // each new line mounts its own fade
        let row: gpui::AnyElement = if motion && i == 0 && !job.done {
            row.with_animation(
                gpui::ElementId::named_usize("run-feed-in", count),
                Animation::new(std::time::Duration::from_millis(450)).with_easing(|t| t * t),
                |el, v| el.opacity(v),
            )
            .into_any_element()
        } else {
            row.into_any_element()
        };
        feed = feed.child(row);
    }
    feed
}
