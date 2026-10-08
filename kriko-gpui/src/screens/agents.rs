//! Agents: the coding agents on this machine, as the engine finds them. Two
//! facts per agent, each from its own endpoint: whether it can run a check
//! (`GET /api/prefs`: usable, needs sign-in, not installed) and whether it is
//! wired to Kriko's MCP server (`GET /api/agent-targets`). The detail card
//! acts on the picked one: use it for runs, connect it, refresh its skill.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Stateful, Styled, Window};

use crate::app::Kriko;
use crate::live::run::{mark_for, AgentEntry, Harness, RunState, Target};
use crate::marks::{mark_tile, phase_beat, Phase};
use crate::screens::run::option_chip;
use crate::screens::{empty_note, mono, row_desc, row_title, th};
use crate::theme::*;

/// How an agent stands as a runner of checks: the tag state and its word.
fn run_word(h: &RunState) -> (TagState, &'static str) {
    match h {
        RunState::Ready => (TagState::Live, "Ready"),
        RunState::Unusable(_) => (TagState::Need, "Needs sign-in"),
        RunState::Missing { .. } => (TagState::Queue, "Not installed"),
    }
}

/// How an agent stands as an MCP connection target.
fn mcp_word(t: &Target) -> (TagState, &'static str) {
    match t.state.as_str() {
        "connected" => (TagState::Live, "Connected"),
        "stale" => (TagState::Need, "Stale"),
        "unreadable" => (TagState::Block, "Unreadable"),
        _ => (TagState::Queue, "Not connected"),
    }
}

/// The tile's motion: what a running job of this agent is doing; otherwise
/// still when usable or connected, dark when it is not there, a held breath
/// when it needs you.
fn entry_phase(app: &Kriko, e: &AgentEntry) -> Phase {
    if let Some(job) = app.live.run.running().find(|j| j.harness == e.id) {
        return job.lane_phase();
    }
    match (&e.harness, &e.target) {
        (Some(h), _) => match h.state {
            RunState::Ready => Phase::Idle,
            RunState::Unusable(_) => Phase::Waiting,
            RunState::Missing { .. } => Phase::Off,
        },
        (None, Some(t)) if t.state == "connected" => Phase::Idle,
        _ => Phase::Off,
    }
}

pub fn agents(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Stateful<Div> {
    let motion = !app.reduce_motion;
    let entries = app.live.run.agent_entries();
    let loaded = app.live.run.prefs_loaded || app.live.run.targets_loaded;

    let body: Div = if entries.is_empty() {
        div().child(empty_note(if loaded {
            "No agent was found on this machine."
        } else {
            "Waiting for the engine to list the agents."
        }))
    } else {
        let selected = app.live.run.selected_agent().map(|e| e.id).unwrap_or_default();
        let picked = entries.iter().find(|e| e.id == selected).cloned();

        let mut table = card().flex().flex_col();
        table = table
            .child(
                div()
                    .flex()
                    .items_center()
                    .pb(px(10.0))
                    .child(div().flex_1().min_w(px(160.0)).child(th("Agent")))
                    .child(div().w(px(200.0)).child(th("Runs checks")))
                    .child(div().w(px(140.0)).child(th("MCP")))
                    .child(div().w(px(80.0)).child(th("Recent runs")))
                    .child(div().w(px(72.0)).child(th("Order"))),
            )
            .child(hairline());

        for (i, e) in entries.iter().enumerate() {
            let up_id = e.id.clone(); let down_id = e.id.clone();
            let up = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| this.order_agent(up_id.clone(), -1, cx));
            let down = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| this.order_agent(down_id.clone(), 1, cx));
            let is_selected = e.id == selected;
            let id = e.id.clone();
            let click = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.select_agent(id.clone());
                cx.notify();
            });
            let chosen = app.live.run.preferred == e.id;
            let runs_cell = match &e.harness {
                Some(h) => {
                    let (state, word) = run_word(&h.state);
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(tag(format!("agents-row-{i}"), state, word, motion))
                        .when(chosen, |d| d.child(chip("chosen")))
                }
                None => div().child(mono("-", DIM)),
            };
            let mcp_cell = match &e.target {
                Some(t) => {
                    let (state, word) = mcp_word(t);
                    div().flex().child(tag(format!("agents-mcp-{i}"), state, word, motion))
                }
                None => div().child(mono("-", DIM)),
            };
            let row = div()
                .id(("agent-row", i))
                .flex()
                .items_center()
                .py(px(12.0))
                .cursor_pointer()
                .hover(|s| s.bg(rgba(GLASS_1)))
                .when(is_selected, |s| {
                    s.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE))
                })
                .on_click(click)
                .child(
                    div()
                        .flex_1()
                        .min_w(px(160.0))
                        .flex()
                        .items_center()
                        .gap(px(12.0))
                        .child(mark_tile(
                            &format!("agents-row-tile-{i}"),
                            mark_for(&e.id),
                            entry_phase(app, e),
                            40.0,
                            motion,
                        ))
                        .child(
                            div()
                                .flex_1()
                                .min_w(px(0.0))
                                .pr(px(10.0))
                                .truncate()
                                .font_family(SANS)
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_size(px(15.0))
                                .text_color(rgb(if is_selected { ICE } else { INK }))
                                .child(e.label.clone()),
                        ),
                )
                .child(div().w(px(200.0)).flex_none().child(runs_cell))
                .child(div().w(px(140.0)).child(mcp_cell))
                .child(
                    div()
                        .w(px(80.0))
                        .child(mono(&app.live.run.runs_of(&e.id).to_string(), INK_2)),
                )
                .child(div().flex().gap(px(4.0))
                    .when(i > 0, |d| d.child(ghost(("agent-up", i), "Up").on_click(up)))
                    .when(i + 1 < entries.len(), |d| d.child(ghost(("agent-down", i), "Down").on_click(down))));
            table = table.child(row);
            if i + 1 < entries.len() {
                table = table.child(hairline());
            }
        }

        let detail = match picked {
            Some(e) => detail_card(app, &e, motion, cx),
            None => card(),
        };
        div()
            .flex()
            .gap(px(24.0))
            .items_start()
            .min_w(px(980.0))
            .child(div().flex_1().min_w(px(0.0)).child(table))
            .child(div().w(px(320.0)).flex_none().child(detail))
    };

    div()
        .id("agents-row-scroll")
        .overflow_x_scroll()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(body)
        .when(app.live.run.prefs_loaded, |d| d.child(research_card(app, cx)))
}

/// The source options every agent run reads: which kinds of source to go to
/// first, and how many sources at most. Stored by the engine, so a check
/// started from the app, the extension or Compare reads the same choice.
fn research_card(app: &Kriko, cx: &mut Context<Kriko>) -> Div {
    let run = &app.live.run;
    let mut kinds = div().flex().flex_wrap().gap(px(6.0));
    for (i, (id, words)) in run.source_kinds.iter().enumerate() {
        let on = run.research_kinds.contains(id);
        let kind = id.clone();
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.toggle_source_kind(kind.clone(), cx);
            cx.notify();
        });
        kinds = kinds.child(div().w(px(220.0)).min_w(px(0.0)).child(option_chip(("source-kind", i), words, on).h_auto().min_h(px(30.0)).py(px(8.0)).on_click(toggle)));
    }
    let mut counts = div().flex().flex_wrap().gap(px(6.0));
    for (i, n) in [0u32, 3, 5, 10, 20, 40].into_iter().enumerate() {
        let label = if n == 0 { "Run decides".to_string() } else { n.to_string() };
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.pick_source_count(n, cx);
            cx.notify();
        });
        counts = counts.child(
            option_chip(("source-count", i), &label, run.research_sources == n).on_click(pick),
        );
    }
    card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow("Research sources"))
        .child(row_desc(
            "Choose source types to read first. No types selected lets the agent choose. The limit caps pages read, not the number of findings included in the answer.",
        ))
        .child(kinds)
        .child(eyebrow("Sources per run"))
        .child(counts)
}

fn detail_card(app: &Kriko, e: &AgentEntry, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let phase = entry_phase(app, e);
    let mut c = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(16.0))
                .child(mark_tile(
                    &format!("agents-detail-tile-{}", e.id),
                    mark_for(&e.id),
                    phase,
                    72.0,
                    motion,
                ))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(4.0))
                        .child(row_title(&e.label))
                        .child(mono(&e.id, MUTED))
                        .child(phase_beat(&format!("agents-detail-beat-{}", e.id), phase, motion)),
                ),
        );

    // ---- runs checks ----
    if let Some(h) = &e.harness {
        let (state, word) = run_word(&h.state);
        let chosen = app.live.run.preferred == e.id;
        c = c
            .child(hairline())
            .child(eyebrow("Runs checks"))
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(10.0))
                    .child(tag("agents-detail-run", state, word, motion))
                    .when(chosen, |d| d.child(chip("used for runs"))),
            );
        match &h.state {
            RunState::Ready => {
                let runs = app.live.run.runs_of(&e.id);
                c = c.child(row_desc(&format!(
                    "{runs} of the engine's last 30 jobs ran with it."
                )));
                if !chosen {
                    let id = e.id.clone();
                    let use_it = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                        this.prefer_agent(id.clone(), cx);
                        cx.notify();
                    });
                    c = c.child(div().child(ghost("agent-use", "Use for runs").on_click(use_it)));
                }
                let models = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.open_agent_models(cx));
                c = c.child(ghost("agent-models-drawer", if app.live.run.model_drawer { "Close model and effort choices" } else { "Models and effort" }).on_click(models));
                if app.live.run.model_drawer { c = c.child(well().p(px(12.0)).child(dials(h, cx))); }
            }
            RunState::Unusable(why) => c = c.child(row_desc(why)),
            RunState::Missing { hint, url } => {
                c = c.child(row_desc(if hint.is_empty() { "Not found on this machine." } else { hint }));
                if !url.is_empty() {
                    c = c.child(mono(url, DIM));
                }
            }
        }
    }

    // ---- MCP connection ----
    if let Some(t) = &e.target {
        let (state, word) = mcp_word(t);
        let id = e.id.clone();
        let connect = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.connect_target(id.clone(), cx);
            cx.notify();
        });
        let label = if t.state == "absent" { "Connect" } else { "Reconnect" };
        c = c
            .child(hairline())
            .child(eyebrow("MCP connection"))
            .child(tag("agents-detail-mcp", state, word, motion))
            .child(mono(&t.path, DIM));
        if !t.detail.is_empty() {
            c = c.child(row_desc(&t.detail));
        }
        if t.skill_supported {
            let skill = if t.skill_stale {
                "The skill on disk is out of date."
            } else if t.skill_present {
                "The skill is on disk and current."
            } else {
                "No skill is written yet."
            };
            c = c.child(row_desc(skill));
        }
        let mut keys = div().flex().items_center().gap(px(10.0)).child(ghost("agent-connect", label).on_click(connect));
        if t.skill_supported {
            let id = e.id.clone();
            let refresh = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.refresh_skill(id.clone(), cx);
                cx.notify();
            });
            keys = keys.child(ghost("agent-skill", "Refresh skill").on_click(refresh));
        }
        c = c.child(keys);
    }

    if !app.live.run.agent_note.is_empty() {
        c = c.child(row_desc(&app.live.run.agent_note));
    }

    // ---- check connection: the engine starts its own MCP server and says
    // which step it passed ----
    let verify = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.verify_agents(cx);
        cx.notify();
    });
    c = c.child(hairline()).child(
        div()
            .flex()
            .items_center()
            .gap(px(10.0))
            .child(
                ghost(
                    "agent-verify",
                    if app.live.run.verifying { "Checking" } else { "Check connection" },
                )
                .on_click(verify),
            )
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .child(row_desc("Starts Kriko's MCP server and asks it who it is.")),
            ),
    );
    if app.live.run.verifying {
        c = c.child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(led_ripple("agent-verify-progress", motion))
                .child(row_desc("Checking the configured command and available tools…")),
        );
    }
    if let Some(v) = &app.live.run.verify {
        let mut steps = div().flex().flex_col().gap(px(6.0));
        for (i, (step, state)) in v.steps.iter().enumerate() {
            let (ts, word) = match state.as_str() {
                "ok" => (TagState::Done, "ok"),
                "failed" => (TagState::Block, "failed"),
                _ => (TagState::Queue, "skipped"),
            };
            steps = steps.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(10.0))
                    .child(tag(format!("agents-verify-{i}"), ts, word, motion))
                    .child(mono(step, INK_2)),
            );
        }
        c = c.child(steps);
        c = c.child(row_desc(&format!(
            "{} · {} ms",
            if v.ok { "Connection check passed" } else { "Connection check failed" },
            v.ms
        )));
        if !v.log.is_empty() {
            let toggle = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| { this.live.run.verify_log_open = !this.live.run.verify_log_open; cx.notify(); });
            let copied = v.log.clone();
            let copy = cx.listener(move |_this, _: &gpui::ClickEvent, _w, cx| cx.write_to_clipboard(gpui::ClipboardItem::new_string(copied.clone())));
            c = c.child(div().flex().gap(px(8.0))
                .child(ghost("agent-check-logs", if app.live.run.verify_log_open { "Hide logs" } else { "Show logs" }).on_click(toggle))
                .child(ghost("agent-check-copy", "Copy log").on_click(copy)));
            if app.live.run.verify_log_open { c = c.child(
                well()
                    .id("agent-check-log-scroll").overflow_y_scroll()
                    .max_h(px(220.0))
                    .p(px(12.0))
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(rgb(INK_2))
                    .child(v.log.clone()),
            ); }
        }
        if !v.ok && !v.detail.is_empty() {
            c = c.child(row_desc(&v.detail));
        }
    }
    c
}

/// The two dials a ready agent runs with: which model, and how hard it
/// thinks. Each lists what the engine found for this machine (the provider's
/// own model list, the CLI's own `--help` effort levels); "Default" leaves
/// the choice to the agent. A dial the agent does not have is not drawn.
fn dials(h: &Harness, cx: &mut Context<Kriko>) -> Div {
    let mut out = div().flex().flex_col().gap(px(10.0));
    if h.llm_selectable && (!h.llms.is_empty() || !h.llm.is_empty()) {
        let mut names: Vec<String> = h.llms.clone();
        if !h.llm.is_empty() && !names.contains(&h.llm) {
            names.insert(0, h.llm.clone());
        }
        let mut row = div().flex().flex_wrap().gap(px(6.0));
        // The local model has no "default" of its own: the server runs one.
        if h.id != "local" {
            let id = h.id.clone();
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.pick_agent_model(id.clone(), String::new(), cx);
                cx.notify();
            });
            row = row.child(option_chip("agent-model-default", "Default", h.llm.is_empty()).on_click(pick));
        }
        for (i, name) in names.iter().enumerate() {
            let (id, model) = (h.id.clone(), name.clone());
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.pick_agent_model(id.clone(), model.clone(), cx);
                cx.notify();
            });
            row = row.child(option_chip(("agent-model", i), name, *name == h.llm).on_click(pick));
        }
        out = out.child(hairline()).child(eyebrow("Model")).child(row);
        if !h.llms_note.is_empty() {
            out = out.child(row_desc(&h.llms_note));
        }
    }
    if !h.efforts.is_empty() {
        let mut row = div().flex().flex_wrap().gap(px(6.0));
        let id = h.id.clone();
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.pick_agent_effort(id.clone(), String::new(), cx);
            cx.notify();
        });
        row = row.child(option_chip("agent-effort-default", "Default", h.effort.is_empty()).on_click(pick));
        for (i, level) in h.efforts.iter().enumerate() {
            let (id, effort) = (h.id.clone(), level.clone());
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.pick_agent_effort(id.clone(), effort.clone(), cx);
                cx.notify();
            });
            row = row.child(option_chip(("agent-effort", i), level, *level == h.effort).on_click(pick));
        }
        out = out.child(hairline()).child(eyebrow("Effort")).child(row);
        if !h.effort_hint.is_empty() {
            out = out.child(row_desc(&h.effort_hint));
        }
    }
    out
}
