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
    page = page.child(quicklook_card(app, window, cx));

    let job = app.live.run.current().cloned();
    match (&job, app.live.run.jobs_loaded) {
        (Some(job), _) if job.kind == "quick_look" => {
            page = page.child(quicklook_result_card(job, app, window, cx));
        }
        (Some(job), _) => {
            page = page.child(subject_card(app, job, motion, cx));
            if job.attention.is_some() {
                page = page.child(questions_card(app, job, cx));
            }
            if job.done {
                page = page.child(answer_card(job));
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
                        "No recent check. Start a Quick Look above, or a catalog check below."
                    } else {
                        "Waiting for the engine to answer."
                    })),
            );
        }
    }
    page = page.child(start_card(app, window, cx));
    if let Some(job) = &job {
        page = page.child(lane_card(app, job, motion));
        page = page.child(log_card(app, job, motion, cx));
    }
    page
}

/// The desktop's primary action: a sourced product brief, always on the
/// configured local model. The model setup remains available from this page
/// when the local plane is not ready.
fn quicklook_card(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let plane = app.live.local.plane.as_ref();
    let ready = plane.is_some_and(|p| p.ready);
    let busy = app.live.run.quicklook_starting;
    let model = plane.map(|p| p.model.as_str()).filter(|m| !m.is_empty()).unwrap_or("no model selected");
    let field = app.input_field(
        Field::QuickLookProduct,
        "quicklook-product",
        "Product, model, or exact variant…",
        Some("search"),
        window,
        cx,
    );
    let start = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.start_quick_look(cx);
        cx.notify();
    });
    let local = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = crate::app::Tab::Local;
        this.on_open_tab(cx);
        cx.notify();
    });
    let local_description = if ready {
        format!("{} · model inference stays on this device. Web searches use the configured search service.", model)
    } else {
        "Set up a local runtime and download a model to run Quick Looks with on-device inference.".to_string()
    };
    card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(eyebrow("Quick Look · local model"))
                .child(div().flex_1())
                .child(tag("quicklook-local", if ready { TagState::Live } else { TagState::Queue }, if ready { "On this device" } else { "Model setup needed" }, !app.reduce_motion)),
        )
        .child(row_desc(&local_description))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(field)
                .when(ready, |d| d.child(key("quicklook-start", if busy { "Starting" } else { "Quick Look" }).on_click(start)))
                .when(!ready, |d| d.child(plate_s("quicklook-setup", "Set up local model").on_click(local))),
        )
        .when(busy, |d| d.child(row_desc("Starting a local research job…")))
        .when(app.live.run.quicklook_note.is_some(), |d| {
            d.child(row_desc(app.live.run.quicklook_note.as_deref().unwrap_or_default()))
        })
}

fn quicklook_result_card(job: &Job, app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let state = if job.done {
        if job.failed() { "Quick Look failed" } else { "Quick Look complete" }
    } else if job.state == "queued" {
        "Quick Look queued"
    } else {
        "Quick Look in progress"
    };
    let model = if job.model.is_empty() {
        app.live.local.plane.as_ref().map(|p| p.model.as_str()).unwrap_or("local model")
    } else {
        job.model.as_str()
    };
    let plane_label = if job.backend == "local" {
        "On this device"
    } else if job.backend == "harness" {
        "Coding agent"
    } else {
        "Configured provider"
    };
    let mut card = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow(state))
        .child(row_title(&job.product))
        .child(mono(&format!("{plane_label} · {model} · {}", job.duration_word()), DIM));
    if !job.answer.is_empty() {
        card = card.child(row_desc(&job.answer));
    }
    if !job.quick_assumed.is_empty() {
        card = card.child(row_desc(&format!("Variant assumption: {}", job.quick_assumed)));
    }
    if !job.done {
        return card.child(meter_live("quicklook-progress", job.progress * 100.0, 28, true, true));
    }
    if !job.quick_risks.is_empty() {
        card = card.child(eyebrow("Documented risks"));
        for (i, risk) in job.quick_risks.iter().enumerate() {
            let mut detail = div()
                .flex()
                .flex_col()
                .gap(px(6.0))
                .p(px(12.0))
                .rounded(px(10.0))
                .bg(rgba(GLASS_1))
                .border_1()
                .border_color(rgba(HAIRLINE))
                .child(
                    div()
                        .flex()
                        .items_start()
                        .justify_between()
                        .gap(px(8.0))
                        .child(row_title(&risk.title))
                        .child(tag(format!("quick-risk-{i}"), if risk.severity == "high" { TagState::Need } else { TagState::Queue }, &risk.severity, false)),
                )
                .child(row_desc(&risk.why));
            if !risk.check.is_empty() {
                detail = detail.child(mono(&format!("Check: {}", risk.check), MUTED));
            }
            if !risk.quote.is_empty() {
                detail = detail.child(row_desc(&format!("“{}”", risk.quote)));
            }
            if !risk.domain.is_empty() || !risk.url.is_empty() {
                let url = risk.url.clone();
                let open = cx.listener(move |_, _: &gpui::ClickEvent, _w, cx| cx.open_url(&url));
                detail = detail.child(
                    div()
                        .id(("quick-risk-source", i))
                        .cursor_pointer()
                        .hover(|s| s.opacity(0.8))
                        .on_click(open)
                        .child(mono(if risk.domain.is_empty() { &risk.url } else { &risk.domain }, ICE)),
                );
            }
            card = card.child(detail);
        }
    }
    if !job.quick_specs.is_empty() {
        card = card.child(eyebrow("Specifications"));
        for (i, spec) in job.quick_specs.iter().enumerate() {
            let url = spec.url.clone();
            let open = cx.listener(move |_, _: &gpui::ClickEvent, _w, cx| cx.open_url(&url));
            card = card.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(div().flex_1().min_w(px(0.0)).child(row_title(&spec.name)))
                    .child(mono(&spec.value, INK_2))
                    .child(
                        div()
                            .id(("quick-spec-source", i))
                            .cursor_pointer()
                            .hover(|s| s.opacity(0.8))
                            .on_click(open)
                            .child(mono(if spec.domain.is_empty() { &spec.url } else { &spec.domain }, ICE)),
                    ),
            );
        }
    }
    if job.quick_risks.is_empty() && job.quick_specs.is_empty() {
        card = card.child(empty_note(if job.failed() {
            if job.no_answer_why.is_empty() { "The local model could not finish this check." } else { &job.no_answer_why }
        } else if job.no_answer_why.is_empty() {
            "No sourced risks or specifications were found in the pages read."
        } else {
            &job.no_answer_why
        }));
    }
    if job.done && !job.failed() {
        let asks = if app.live.run.quick_asks_for.as_deref() == Some(job.id.as_str()) {
            app.live.run.quick_asks.clone()
        } else {
            Vec::new()
        };
        let mut followups = crate::theme::card().flex().flex_col().gap(px(10.0)).child(eyebrow("Ask about this Quick Look"));
        followups = followups.child(row_desc("Answers use this check's findings and the same model plane; they do not start another web search."));
        for (i, ask) in asks.iter().enumerate() {
            followups = followups.child(
                well()
                    .p(px(12.0))
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(row_title(&ask.question))
                    .child(if ask.done {
                        row_desc(if ask.answer.is_empty() { "The model returned no answer." } else { &ask.answer })
                    } else {
                        mono(&format!("{}…", if ask.state.is_empty() { "Thinking" } else { &ask.state }), MUTED)
                    }),
            );
            if i + 1 < asks.len() {
                followups = followups.child(hairline());
            }
        }
        let field = app.input_field(
            Field::QuickLookQuestion,
            "quicklook-followup-question",
            "Ask about a risk, source, or specification…",
            Some("search"),
            window,
            cx,
        );
        let ask = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.start_quick_ask(cx);
            cx.notify();
        });
        followups = followups.child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(field)
                .child(key("quicklook-ask", if app.live.run.quick_asking { "Asking" } else { "Ask" }).on_click(ask)),
        );
        if let Some(note) = &app.live.run.quick_ask_note {
            followups = followups.child(row_desc(note));
        }
        card = card.child(followups);
    }
    card
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
    match job.backend.as_str() {
        "api" => meta.push("api plane".into()),
        "local" => meta.push("local plane".into()),
        "agent" => meta.push("agent plane".into()),
        _ => {}
    }
    if !job.model.is_empty() {
        meta.push(format!("model {}", job.model));
    }
    let took = job.duration_word();
    if !took.is_empty() {
        meta.push(took);
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

/// What the agent answered, once the run is done: its reply or outcome, or
/// an explicit no-answer with the reason, never a bare status word.
fn answer_card(job: &Job) -> Div {
    let mut c = card().flex().flex_col().gap(px(8.0)).child(eyebrow("The answer"));
    if job.answer.is_empty() {
        let why = if job.no_answer_why.is_empty() {
            job.message.clone()
        } else {
            job.no_answer_why.clone()
        };
        c = c.child(row_title("The agent returned no answer.")).when(
            !why.is_empty(),
            |c| c.child(row_desc(&why)),
        );
        return c;
    }
    let mut text = div()
        .font_family(SANS)
        .text_size(px(14.0))
        .text_color(rgb(INK_2))
        .max_w(px(720.0));
    for para in job.answer.split("\n\n") {
        text = text.child(
            div()
                .py(px(4.0))
                .text_color(rgb(INK_2))
                .child(para.trim().to_string()),
        );
    }
    c.child(text)
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
        let query = app.run_search.value.trim().to_string();
        let quick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.quicklook_product.value = query.clone();
            this.start_quick_look(cx);
            cx.notify();
        });
        c = c.child(
            div()
                .flex()
                .flex_col()
                .gap(px(10.0))
                .child(empty_note("No catalog subject matches that name. A Quick Look can still research it with the local model."))
                .child(plate_s("run-no-match-quicklook", "Quick Look this product").on_click(quick)),
        );
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

/// The run's log: every line the engine narrated, newest first, with a level
/// filter and a copy plate. Follows the live log while the run is going.
fn log_card(app: &Kriko, job: &Job, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let events = job.log_events();
    let level = app.live.run.log_level;
    let at = |k: &str| events.iter().filter(|e| e.kind == k).count();
    let mut card = card().flex().flex_col().gap(px(12.0));

    let words: [(&str, String); 5] = [
        ("ALL", format!("ALL {}", events.len())),
        ("SEARCH", format!("SEARCH {}", at("search"))),
        ("SOURCE", format!("SOURCES {}", at("source"))),
        ("FINDING", format!("FINDINGS {}", at("finding"))),
        ("PROBLEM", format!("PROBLEMS {}", at("problem"))),
    ];
    let mut chips = div().flex().flex_wrap().items_center().gap(px(8.0));
    for (li, (_, word)) in words.iter().enumerate() {
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.run.log_level = li;
            cx.notify();
        });
        chips = chips.child(
            option_chip(gpui::ElementId::named_usize("run-log-level", li), word, li == level)
                .on_click(pick),
        );
    }

    let copy_text = {
        let kept: Vec<&crate::live::run::FeedLine> = match level {
            1 => events.iter().filter(|e| e.kind == "search").collect(),
            2 => events.iter().filter(|e| e.kind == "source").collect(),
            3 => events.iter().filter(|e| e.kind == "finding").collect(),
            4 => events.iter().filter(|e| e.kind == "problem").collect(),
            _ => events.iter().collect(),
        };
        kept.iter().rev().map(|e| e.text.clone()).collect::<Vec<_>>().join("\n")
    };
    let copied = app
        .live
        .run
        .log_copied_at
        .map(|t| t.elapsed().as_secs() < 2)
        .unwrap_or(false);
    let copy = cx.listener(move |this, _: &gpui::ClickEvent, _, cx| {
        this.live.run.log_copied_at = Some(std::time::Instant::now());
        cx.write_to_clipboard(gpui::ClipboardItem::new_string(copy_text.clone()));
        cx.notify();
    });

    card = card.child(
        div()
            .flex()
            .items_center()
            .gap(px(12.0))
            .child(eyebrow(if job.done { "Log" } else { "Live log" }))
            .child(div().flex_1())
            .child(plate_s("run-log-copy", if copied { "Copied" } else { "Copy" }).on_click(copy)),
    );
    if events.is_empty() {
        return card.child(empty_note(if job.done {
            "This run left no log."
        } else {
            "Nothing yet. Lines land here as the agent reads and writes."
        }));
    }
    card = card.child(chips);

    let kept: Vec<&crate::live::run::FeedLine> = match level {
        1 => events.iter().filter(|e| e.kind == "search").collect(),
        2 => events.iter().filter(|e| e.kind == "source").collect(),
        3 => events.iter().filter(|e| e.kind == "finding").collect(),
        4 => events.iter().filter(|e| e.kind == "problem").collect(),
        _ => events.iter().collect(),
    };
    if kept.is_empty() {
        return card.child(empty_note("Nothing at this level."));
    }
    let hidden = kept.len().saturating_sub(200);
    let mut list = div().id("run-log-scroll").max_h(px(420.0)).overflow_y_scroll();
    if hidden > 0 {
        list = list.child(mono(&format!("{} earlier lines are folded", hidden), DIM));
    }
    let newest_first: Vec<&crate::live::run::FeedLine> = kept.iter().rev().take(200).copied().collect();
    let count = newest_first.len();
    for (i, line) in newest_first.iter().enumerate() {
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
            .child(tag(format!("run-log-{i}"), state, "", motion))
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(rgb(INK_2))
                    .child(line.text.clone()),
            );
        let row: gpui::AnyElement = if motion && i == 0 && !job.done {
            row.with_animation(
                gpui::ElementId::named_usize("run-log-in", count),
                Animation::new(std::time::Duration::from_millis(450)).with_easing(|t| t * t),
                |el, v| el.opacity(v),
            )
            .into_any_element()
        } else {
            row.into_any_element()
        };
        list = list.child(row);
    }
    card.child(list)
}
