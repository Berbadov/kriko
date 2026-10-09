//! Benchmark: how the agents and planes do on the engine's fixed test set,
//! on this machine. The machine and the run key; the headline numbers with
//! their change since the benchmark before; each agent side by side; the
//! history of benchmarks; and the latest one, run by run. Everything is a
//! row the engine measured (`GET /api/bench`); a number it did not measure
//! reads "n/a", never zero.

use gpui::{div, point, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::live::local::{batches, change, BenchPhase, BenchRun, Batch, Machine};
use crate::marks::{self, mark_glyph, Mark, Phase};
use crate::screens::local::pill;
use crate::screens::{empty_note, mono, plate_s, row_desc, row_title, th};
use crate::theme::*;

fn setup(app: &Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let b = &app.live.local.bench;
    let mut result = card().flex().flex_col().gap(px(12.0)).child(eyebrow("Run setup"))
        .child(row_desc("Each case asks for product risks, searches and reads evidence, then scores the answer against the versioned expected findings and forbidden claims. Generation controls below apply to local inference; other agents use their own supported defaults."));
    for (name, key, values, current) in [
        ("First cases (or choose below)", "cases", vec![1, 3, 5, 10], b.case_count),
        ("Pages per case", "documents", vec![1, 3, 5, 10, 20], b.documents),
        ("Repetitions", "repeats", vec![1, 2, 3, 5, 10], b.repeats),
        ("Timeout seconds per inference / agent call", "timeout", vec![60, 120, 240, 600, 1200], b.timeout),
        ("Local reply tokens", "tokens", vec![512, 1024, 2048, 4096], b.max_tokens),
    ] {
        let mut row = div().flex().flex_wrap().items_center().gap(px(8.0)).child(row_desc(name));
        for (i, value) in values.into_iter().enumerate() {
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                let b = &mut this.live.local.bench;
                if matches!(b.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
                match key { "cases" => { b.case_count = value; b.case_ids.clear(); }, "documents" => b.documents = value,
                    "repeats" => b.repeats = value, "timeout" => b.timeout = value, _ => b.max_tokens = value }
                b.phase = BenchPhase::Idle; cx.notify();
            });
            row = row.child(pill(gpui::ElementId::named_usize(format!("bench-setup-{key}"), i), &value.to_string(), current == value).on_click(pick));
        }
        result = result.child(row);
    }
    let mut temp = div().flex().gap(px(8.0)).child(row_desc("Local temperature"));
    for (i, value) in [0.0, 0.2, 0.5, 1.0].into_iter().enumerate() {
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            if matches!(this.live.local.bench.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
            this.live.local.bench.temperature = value; this.live.local.bench.phase = BenchPhase::Idle; cx.notify();
        });
        temp = temp.child(pill(("bench-temperature", i), &value.to_string(), b.temperature == value).on_click(pick));
    }
    result = result.child(temp).child(hairline()).child(eyebrow("Agents and served models"));
    result = result.child(app.input_field(Field::BenchModelSearch, "bench-model-search", "Search this agent's models", Some("search"), window, cx));
    for (i, entry) in app.live.run.agent_entries().iter().enumerate() {
        let Some(h) = &entry.harness else { continue };
        if !matches!(h.state, crate::live::run::RunState::Ready) { continue; }
        let id = entry.id.clone();
        let select_agent = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            let b = &mut this.live.local.bench;
            if matches!(b.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
            b.harness = id.clone(); b.models.clear();
            b.picked = vec![if id == "local" { "local" } else if id.ends_with("-api") { "api" } else { "harness" }.to_string()];
            b.phase = BenchPhase::Idle; cx.notify();
        });
        let row = div().flex().flex_wrap().gap(px(8.0))
            .child(plate_s(("bench-agent-pick", i), &entry.label).on_click(select_agent))
            .child(row_desc(&format!("{} · {}", entry.id, if h.llm.is_empty() { "agent default" } else { &h.llm })));
        result = result.child(row);
        if b.harness != entry.id { continue; }
        let query = app.bench_model_search.value.trim().to_lowercase();
        let mut row = div().id("bench-model-options").h(px(180.0)).overflow_y_scroll().occlude().on_scroll_wheel(|_,_,cx| cx.stop_propagation())
            .flex().flex_col().gap(px(6.0));
        for (n, model) in h.llms.iter().enumerate().filter(|(_,m)| query.is_empty() || m.to_lowercase().contains(&query)) {
            let chosen = model.clone(); let agent = entry.id.clone();
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                let b = &mut this.live.local.bench;
                if matches!(b.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
                if b.harness != agent { b.models.clear(); }
                b.harness = agent.clone(); b.picked = vec![if agent == "local" { "local" } else if agent.ends_with("-api") { "api" } else { "harness" }.to_string()];
                if b.models.contains(&chosen) { b.models.retain(|m| m != &chosen); } else { b.models.push(chosen.clone()); }
                b.phase = BenchPhase::Idle; cx.notify();
            });
            row = row.child(pill(gpui::ElementId::named_usize(format!("bench-served-{i}"), n), model, b.models.contains(model)).on_click(pick));
        }
        result = result.child(row);
    }
    result = result.child(hairline()).child(eyebrow("Test cases and expected answers"));
    for (i, case) in b.cases.iter().enumerate() {
        let id = crate::api::s(case, "id"); let selected = b.case_ids.contains(&id) || (b.case_ids.is_empty() && i < b.case_count);
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            let b = &mut this.live.local.bench;
            if matches!(b.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
            if b.case_ids.is_empty() { b.case_ids = b.cases.iter().take(b.case_count).map(|c| crate::api::s(c, "id")).collect(); }
            if b.case_ids.contains(&id) { if b.case_ids.len() == 1 { return; } b.case_ids.retain(|x| x != &id); } else { b.case_ids.push(id.clone()); }
            b.phase = BenchPhase::Idle; cx.notify();
        });
        result = result.child(div().flex().flex_col().gap(px(4.0))
            .child(pill(("bench-case-pick", i), &crate::api::s(case, "product"), selected).on_click(pick))
            .child(row_desc(&format!("Expected: {} · forbidden: {}",
                case_words(case, "must_find"), case_words(case, "must_not_find")))));
    }
    result.child(row_desc("Correctness: expected findings matched / expected findings. Unsupported rate: unsupported findings / produced findings. Source coverage and accuracy are not independently measured by this test set. Task token rate includes input and output over total task time; it is not inference speed. n/a means not measured."))
}

fn glow(color: u32, blur: f32) -> Vec<gpui::BoxShadow> {
    vec![gpui::BoxShadow {
        color: hsla(color),
        offset: point(px(0.0), px(0.0)),
        blur_radius: px(blur),
        spread_radius: px(0.0),
    }]
}

/// A horizontal LED bar: `value` 0..=100 of `segments` lit.
fn led_bar(value: f32, segments: usize, color: u32) -> Div {
    let lit = ((value.clamp(0.0, 100.0) / 100.0) * segments as f32).round() as usize;
    let mut bar = div().flex().gap(px(2.0));
    for i in 0..segments {
        let d = div().w(px(8.0)).h(px(14.0)).rounded(px(1.5));
        bar = bar.child(if i < lit {
            d.bg(rgb(color)).shadow(glow(color, 5.0))
        } else {
            d.bg(rgb(LED_OFF))
        });
    }
    bar
}

/// "m:ss" for a number of seconds.
fn clock(secs: f64) -> String {
    let s = secs.max(0.0).round() as u32;
    format!("{}:{:02}", s / 60, s % 60)
}

fn seconds(ms: Option<f64>) -> String {
    ms.map(|m| format!("{:.1} s", m / 1000.0)).unwrap_or_else(|| "n/a".to_string())
}

/// The change since the benchmark before: an LED arrow and the percent, in
/// ice when it got better and the danger ink when it got worse. `None` says
/// there is nothing to compare with.
fn delta(pct: Option<i8>, higher_better: bool) -> Div {
    let Some(pct) = pct else {
        return mono("no earlier benchmark", DIM);
    };
    let better = if higher_better { pct > 0 } else { pct < 0 };
    let color = if pct == 0 {
        MUTED
    } else if better {
        ICE
    } else {
        DANGER
    };
    const UP: [&str; 3] = ["..#..", ".###.", "#####"];
    const DOWN: [&str; 3] = ["#####", ".###.", "..#.."];
    let arrow = if pct >= 0 { &UP } else { &DOWN };
    div()
        .flex()
        .items_center()
        .gap(px(6.0))
        .child(led_matrix(arrow, color, 2.0, 1.0))
        .child(mono(&format!("{}{}%", if pct > 0 { "+" } else { "" }, pct), color))
}

/// One headline number: label, the figure in display type, its unit, the
/// change, and a strip of the benchmarks before it.
fn headline(label: &str, value: &str, unit: &str, pct: Option<i8>, higher_better: bool, series: &[Option<f64>]) -> Div {
    let mut spark = div().flex().items_end().gap(px(2.0)).h(px(22.0));
    let known: Vec<f64> = series.iter().flatten().copied().collect();
    let lo = known.iter().copied().fold(f64::MAX, f64::min);
    let hi = known.iter().copied().fold(f64::MIN, f64::max);
    for (k, v) in series.iter().enumerate() {
        let last = k + 1 == series.len();
        let h = match v {
            Some(v) => 4.0 + 18.0 * ((v - lo) / (hi - lo).max(f64::MIN_POSITIVE)).clamp(0.0, 1.0),
            None => 3.0,
        };
        spark = spark.child(
            div()
                .w(px(5.0))
                .h(px(h.round() as f32))
                .rounded(px(1.0))
                .bg(rgb(if v.is_none() { LED_OFF } else if last { ICE } else { LED_DIM }))
                .when(last && v.is_some(), |d| d.shadow(glow(ICE, 5.0))),
        );
    }
    card()
        .flex_1()
        .min_w(px(180.0))
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(mono(&label.to_uppercase(), DIM))
        .child(
            div()
                .flex()
                .items_end()
                .gap(px(8.0))
                .child(
                    div()
                        .font_family(DISPLAY)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(40.0))
                        .line_height(px(40.0))
                        .text_color(rgb(INK))
                        .child(value.to_string()),
                )
                .child(div().pb(px(4.0)).child(mono(unit, MUTED))),
        )
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(delta(pct, higher_better))
                .child(spark),
        )
}

/// The mark an agent wears, by the id the engine gives it.
fn mark_for(plane: &str, llm: &str, local_server: &str) -> &'static Mark {
    let id = llm.to_lowercase();
    for (needle, mark) in [
        ("claude", &marks::CLAUDE),
        ("codex", &marks::CODEX),
        ("opencode", &marks::OPENCODE),
        ("antigravity", &marks::ANTIGRAVITY),
        ("agy", &marks::ANTIGRAVITY),
        ("mistral", &marks::MISTRAL),
        ("copilot", &marks::COPILOT),
        ("cursor", &marks::CURSOR),
    ] {
        if id.contains(needle) {
            return mark;
        }
    }
    if plane == "local" {
        return match local_server {
            "Ollama" => &marks::OLLAMA,
            "LM Studio" => &marks::LMSTUDIO,
            "llama-server" => &marks::LLAMACPP,
            _ => &marks::BUILTIN,
        };
    }
    &marks::BUILTIN
}

fn machine_cells(m: Option<&Machine>) -> Vec<(&'static str, String)> {
    let na = || "n/a".to_string();
    let Some(m) = m else {
        return vec![("Machine", "reading".to_string())];
    };
    vec![
        (
            "CPU",
            match (&m.cpu, m.cores) {
                (Some(n), Some(c)) => format!("{n} · {c:.0} threads"),
                (Some(n), None) => n.clone(),
                _ => na(),
            },
        ),
        ("GPU", m.gpu.clone().unwrap_or_else(na)),
        (
            "VRAM",
            m.vram_total_mb.map(|v| format!("{:.1} GB", v / 1024.0)).unwrap_or_else(na),
        ),
        ("Memory", m.ram_mb.map(|v| format!("{:.1} GB", v / 1024.0)).unwrap_or_else(na)),
    ]
}

pub fn benchmark(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let bench = app.live.local.bench.clone();
    let b = &bench;
    if !b.loaded {
        return div().child(empty_note("Asking Kriko's engine for its benchmark results."));
    }
    let server = app
        .live
        .local
        .plane
        .as_ref()
        .map(|p| p.name.clone())
        .unwrap_or_default();
    let press = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.bench_press(cx));
    let all = batches(&b.runs);
    let running = matches!(b.phase, BenchPhase::Running { .. });
    let setup_panel = setup(app, window, cx);
    let mut progress_panel = card().flex().flex_col().gap(px(12.0)).child(eyebrow("Live progress"));
    let jobs: Vec<_> = app.live.run.jobs.iter().filter(|j| j.kind == "bench").take(5).cloned().collect();
    if jobs.is_empty() { progress_panel = progress_panel.child(empty_note("No benchmark task yet.")); }
    for job in &jobs { progress_panel = progress_panel.child(crate::screens::logs::job_logs(app, job, cx)); }
    let export = b.snapshot.to_string();
    let copy = cx.listener(move |_this, _: &gpui::ClickEvent, _w, cx| cx.write_to_clipboard(gpui::ClipboardItem::new_string(export.clone())));
    let source = cx.listener(|_this, _: &gpui::ClickEvent, _w, cx| { cx.open_url("https://github.com/Berbadov/kriko/blob/main/src/app/bench.py"); });
    let runtime_settings = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::Settings; this.refresh_local(cx); cx.notify();
    });
    let runtime = app.live.local.plane.as_ref().map(|p| p.runtime.clone()).unwrap_or(crate::api::Value::Null);
    progress_panel = progress_panel.child(row_desc(&format!("Local runtime: {} · model {} · active device {} · {}",
        crate::api::s(&runtime, "runtime"), crate::api::s(&runtime, "model"),
        crate::api::s(&runtime, "device"), crate::api::s(&runtime, "reason"))));
    progress_panel = progress_panel.child(div().flex().flex_wrap().gap(px(10.0))
        .child(plate_s("bench-export", "Copy detailed results JSON").on_click(copy))
        .child(plate_s("bench-source", "Open benchmark source").on_click(source))
        .child(plate_s("bench-runtime-settings", "Local runtime settings").on_click(runtime_settings)));

    // ---- the machine and the run key ----
    let mut machine = div().flex().flex_wrap().gap(px(8.0));
    for (label, value) in machine_cells(app.live.local.machine.as_ref()) {
        machine = machine.child(
            well()
                .px(px(12.0))
                .py(px(8.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(mono(&label.to_uppercase(), DIM))
                .child(mono(&value, INK_2)),
        );
    }
    let (status, key_label) = match &b.phase {
        BenchPhase::Idle => (tag("bench-idle", TagState::Done, "Idle", motion), "Run benchmark"),
        BenchPhase::Estimating => (tag("bench-est", TagState::Live, "Pricing the grid", motion), "Pricing"),
        BenchPhase::Confirm(e) => (
            tag(
                "bench-confirm",
                TagState::Need,
                &format!(
                    "{} measurement{}, {}. Press again to run",
                    e.runs,
                    if e.runs == 1 { "" } else { "s" },
                    match e.usd {
                        Some(u) if u > 0.0 => format!("about ${u:.2}"),
                        Some(_) => "nothing to spend".to_string(),
                        None => "cost not yet measured here".to_string(),
                    }
                ),
                motion,
            ),
            "Confirm and run",
        ),
        BenchPhase::Running { progress, message, .. } => (
            tag(
                "bench-running",
                TagState::Live,
                &format!("Running · {:.0}% · {message}", progress.min(100.0)),
                motion,
            ),
            "Stop benchmark",
        ),
        BenchPhase::Failed(why) => (tag("bench-failed", TagState::Block, why, motion), "Run benchmark"),
    };
    let mut planes = div().flex().items_center().gap(px(6.0)).flex_wrap();
    for (i, (plane, _meaning)) in b.planes.iter().enumerate() {
        let name = plane.clone();
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.bench_toggle_plane(&name, cx);
        });
        planes = planes.child(
            pill(("bench-plane", i), plane, b.picked.contains(plane)).on_click(toggle),
        );
    }
    let start_panel = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(24.0))
                .child(plate_wide("bench-run", key_label).on_click(press))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_desc(
                            "Runs the engine's fixed test set on the planes picked below and records time, tokens, \
                             cost and how many claims were accepted. The first press prices it; a second spends.",
                        ))
                        .child(mono(
                            &format!(
                                "{} · {} run{} on record",
                                if b.set_label.trim() == "· 0 cases" { "test set" } else { &b.set_label },
                                b.runs.len(),
                                if b.runs.len() == 1 { "" } else { "s" }
                            ),
                            DIM,
                        )),
                ),
        )
        .child(div().flex().items_center().gap(px(16.0)).flex_wrap().child(status).child(planes))
        .children(b.last.clone().map(|l| mono(&l, MUTED)))
        .child(div().pt(px(4.0)).child(eyebrow("Measured on")))
        .child(machine);

    if b.runs.is_empty() {
        return div()
            .flex()
            .flex_col()
            .gap(px(24.0))
            .child(start_panel)
            .child(setup_panel)
            .child(progress_panel)
            .child(empty_note("Nothing has been benchmarked here yet. Run one to see how an agent does."));
    }

    // ---- the headline numbers: the latest benchmark against the one before ----
    let latest = all.first().cloned().unwrap_or_default();
    let before = all.get(1).cloned();
    let take = |f: fn(&Batch) -> Option<f64>| -> Vec<Option<f64>> {
        let mut v: Vec<Option<f64>> = all.iter().take(12).map(f).collect();
        v.reverse();
        v
    };
    let ms = |x: &Batch| x.median_ms;
    let tokens = |x: &Batch| x.median_tokens;
    let usd = |x: &Batch| x.median_usd;
    let accept = |x: &Batch| x.acceptance;
    let heads = div()
        .flex()
        .flex_wrap()
        .gap(px(16.0))
        .child(headline(
            "Median answer",
            &latest.median_ms.map(|m| format!("{:.1}", m / 1000.0)).unwrap_or_else(|| "n/a".into()),
            "s",
            change(latest.median_ms, before.as_ref().and_then(ms)),
            false,
            &take(|x| x.median_ms),
        ))
        .child(headline(
            "Tokens per run",
            &latest.median_tokens.map(|t| format!("{:.0}", t)).unwrap_or_else(|| "n/a".into()),
            "tokens",
            change(latest.median_tokens, before.as_ref().and_then(tokens)),
            false,
            &take(|x| x.median_tokens),
        ))
        .child(headline(
            "Cost per run",
            &latest.median_usd.map(|u| format!("{u:.3}")).unwrap_or_else(|| "n/a".into()),
            if latest.median_usd.is_some() { "USD" } else { "not measured" },
            change(latest.median_usd, before.as_ref().and_then(usd)),
            false,
            &take(|x| x.median_usd),
        ))
        .child(headline(
            "Evidence kept",
            &latest.acceptance.map(|a| format!("{:.0}", a * 100.0)).unwrap_or_else(|| "n/a".into()),
            "%",
            change(latest.acceptance, before.as_ref().and_then(accept)),
            true,
            &take(|x| x.acceptance),
        ));

    let mine: Vec<&BenchRun> = b.runs.iter().filter(|r| r.batch_id == latest.id).collect();
    // ---- the agents, side by side ----
    let mut agents = card()
        .flex()
        .flex_col()
        .child(div().mb(px(12.0)).child(eyebrow("All recorded runs by agent")))
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().min_w(px(170.0)).child(th("Agent")))
                .child(div().w(px(84.0)).child(th("Answer")))
                .child(div().w(px(180.0)).child(th("Task tokens / s")))
                .child(div().w(px(112.0)).child(th("Claims / run")))
                .child(div().w(px(84.0)).child(th("Finished")))
                .child(div().w(px(96.0)).child(th("Trap claims"))),
        )
        .child(hairline());
    let speeds: Vec<Option<f64>> = b
        .summary
        .iter()
        .map(|r| match (r.tokens, r.ms) {
            (Some(t), Some(ms)) if ms > 0.0 && r.runs > 0.0 => Some(t * 1000.0 / r.runs / ms),
            _ => None,
        })
        .collect();
    let fastest = speeds.iter().flatten().copied().fold(0.0f64, f64::max);
    for (k, row) in b.summary.iter().enumerate() {
        let name = if row.llm.is_empty() { row.plane.clone() } else { row.llm.clone() };
        let finished = if row.runs > 0.0 { Some((row.runs - row.failures) / row.runs * 100.0) } else { None };
        let ungrounded = b
            .scored
            .iter()
            .find(|g| g.plane == row.plane && g.llm == row.llm)
            .and_then(|g| g.hallucination);
        let tps = speeds[k];
        agents = agents.child(
            div()
                .py(px(10.0))
                .flex()
                .items_center()
                .child(
                    div()
                        .flex_1()
                        .min_w(px(170.0))
                        .flex()
                        .items_center()
                        .gap(px(12.0))
                        .child(mark_glyph(
                            &format!("bench-agent-{k}"),
                            mark_for(&row.plane, &row.llm, &server),
                            if running { Phase::Thinking } else { Phase::Idle },
                            30.0,
                            motion,
                        ))
                        .child(
                            div()
                                .flex()
                                .flex_col()
                                .child(
                                    div()
                                        .font_family(SANS)
                                        .font_weight(FontWeight::SEMIBOLD)
                                        .text_size(px(14.0))
                                        .text_color(rgb(INK))
                                        .child(name),
                                )
                                .child(mono(&format!("{} · {} · {:.0} runs", row.plane, row.protocol, row.runs), DIM)),
                        ),
                )
                .child(div().w(px(84.0)).child(mono(&seconds(row.ms), INK_2)))
                .child(
                    div().w(px(180.0)).flex().items_center().gap(px(10.0)).child(match tps {
                        Some(t) => div()
                            .flex()
                            .items_center()
                            .gap(px(10.0))
                            .child(led_bar(
                                if fastest > 0.0 { (t / fastest * 100.0) as f32 } else { 0.0 },
                                10,
                                if t >= fastest { ICE } else { LED_DIM },
                            ))
                            .child(mono(&format!("{t:.0}"), INK_2)),
                        None => div().child(mono("n/a", DIM)),
                    }),
                )
                .child(
                    div()
                        .w(px(112.0))
                        .child(mono(&if row.runs > 0.0 { format!("{:.1}", row.accepted / row.runs) } else { "n/a".into() }, INK_2)),
                )
                .child(div().w(px(84.0)).child(match finished {
                    Some(f) => mono(&format!("{f:.0}%"), if f >= 95.0 { ICE } else { INK_2 }),
                    None => mono("n/a", DIM),
                }))
                .child(div().w(px(96.0)).child(match ungrounded {
                    Some(h) => mono(&format!("{:.0}%", h * 100.0), if h > 0.0 { DANGER } else { ICE }),
                    None => mono("not scored", DIM),
                })),
        );
        if k + 1 < b.summary.len() {
            agents = agents.child(hairline());
        }
    }

    // ---- the history of benchmarks ----
    let mut series: Vec<&Batch> = all.iter().filter(|x| x.median_ms.is_some()).take(10).collect();
    series.reverse();
    let vals: Vec<f64> = series.iter().filter_map(|x| x.median_ms).collect();
    let lo = vals.iter().copied().fold(f64::MAX, f64::min);
    let hi = vals.iter().copied().fold(f64::MIN, f64::max);
    let rows = 10usize;
    let mut columns = div().flex().items_end().justify_between().gap(px(6.0));
    for (k, x) in series.iter().enumerate() {
        let v = x.median_ms.unwrap_or(0.0);
        let lit = (2.0 + (v - lo) / (hi - lo).max(1.0) * (rows as f64 - 2.0)).round() as usize;
        let last = k + 1 == series.len();
        let best = v == lo;
        let color = if last { ICE } else if best { INK_2 } else { MUTED };
        let mut col = div().flex().flex_col().gap(px(2.0)).items_center();
        for r in 0..rows {
            let d = div().w(px(18.0)).h(px(6.0)).rounded(px(1.5));
            col = col.child(if rows - r <= lit {
                d.bg(rgb(color)).opacity(if last { 1.0 } else { 0.7 }).when(last, |d| d.shadow(glow(ICE, 5.0)))
            } else {
                d.bg(rgb(LED_OFF))
            });
        }
        columns = columns.child(
            div()
                .flex()
                .flex_col()
                .items_center()
                .gap(px(6.0))
                .child(mono(&clock(v / 1000.0), if last { ICE } else if best { INK_2 } else { DIM }))
                .child(col),
        );
    }
    let date = |x: &Batch| x.at.chars().take(10).collect::<String>();
    let history = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(eyebrow("Typical answer, benchmark by benchmark"))
                .child(delta(
                    change(series.last().and_then(|x| x.median_ms), series.first().and_then(|x| x.median_ms)),
                    false,
                )),
        )
        .child(row_desc(&match (series.first(), series.last()) {
            (Some(a), Some(z)) if series.len() > 1 => format!(
                "Shorter is faster. The median answer went from {} to {} between {} and {}.",
                seconds(a.median_ms),
                seconds(z.median_ms),
                date(a),
                date(z)
            ),
            _ => "Shorter is faster. One benchmark is on record; the next one draws the line.".to_string(),
        }))
        .child(columns)
        .children(match (series.first(), series.last()) {
            (Some(a), Some(z)) => Some(
                div().flex().justify_between().child(mono(&date(a), DIM)).child(mono(&date(z), DIM)),
            ),
            _ => None,
        });

    // ---- the latest benchmark, run by run ----

    let mut variation = card().flex().flex_col().gap(px(8.0)).child(eyebrow("Repeated case variation"))
        .child(row_desc("Elapsed range includes the entire task. Compare repeated samples of the same case and agent; these are not inference-speed measurements."));
    let mut groups = std::collections::BTreeMap::<(String, String, String), Vec<&BenchRun>>::new();
    for run in &mine { groups.entry((run.plane.clone(), run.llm.clone(), run.subject.clone())).or_default().push(run); }
    for ((plane, llm, subject), runs) in groups {
        let times: Vec<f64> = runs.iter().filter_map(|r| r.ms).collect();
        let failed = runs.iter().filter(|r| !r.error.is_empty()).count();
        let range = if times.len() < 2 { "Variation unavailable: fewer than two timed samples".into() } else {
            format!("task range {:.2}–{:.2} s", times.iter().copied().fold(f64::INFINITY, f64::min) / 1000.0,
                times.iter().copied().fold(f64::NEG_INFINITY, f64::max) / 1000.0)
        };
        variation = variation.child(row_desc(&format!("{subject} · {plane} / {llm} · n={} · failures {failed}/{} · {range}", runs.len(), runs.len())));
    }
    variation = variation.child(row_desc("Expected findings = the known issues this case should report. Traps = deliberately forbidden or known-absent claims. Rejected = candidates the evidence gate removed, not proven hallucinations. A finished run can still find none of the expected issues."));
    let slowest = mine.iter().filter_map(|r| r.ms).fold(1.0f64, f64::max);
    let mut bars = card().flex().flex_col();
    bars = bars.child(div().mb(px(12.0)).child(eyebrow("Latest benchmark, run by run")));
    for (i, r) in mine.iter().enumerate() {
        let detail = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.local.bench.detail = if this.live.local.bench.detail == Some(i) { None } else { Some(i) }; cx.notify();
        });
        let failed = !r.error.is_empty();
        bars = bars.child(
            div()
                .py(px(12.0))
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(16.0))
                        .child(
                            div()
                                .flex_1()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .text_color(rgb(INK_2))
                                .child(format!(
                                    "{} · {}",
                                    r.subject,
                                    if r.llm.is_empty() { &r.plane } else { &r.llm }
                                )),
                        )
                        .child(mono(
                            &if failed { format!("failed: {}", r.error) } else { format!("{:.0} accepted, {:.0} refused", r.accepted, r.refused) },
                            if failed { DANGER } else { DIM },
                        ))
                        .child(div().w(px(72.0)).flex().justify_end().child(mono(&seconds(r.ms), INK))),
                )
                .child(mono("Elapsed time relative to the slowest case in this batch", DIM))
                .child(led_bar(
                    r.ms.map(|m| (m / slowest * 100.0) as f32).unwrap_or(0.0),
                    28,
                    if failed { DANGER } else if i == 0 { ICE } else { LED_DIM },
                ))
                .child(plate_s(("bench-case-detail", i), "View answer and score").on_click(detail))
                .child(reveal(run_detail(r, i, cx), format!("bench-answer-{i}"), b.detail == Some(i), 650.0, motion)),
        );
        if i + 1 < mine.len() {
            bars = bars.child(crate::theme::hairline());
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(start_panel)
        .child(setup_panel)
        .child(progress_panel)
        .child(row_title("Results"))
        .child(latest_score(&mine))
        .child(heads)
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .items_start()
                .child(div().id("bench-agent-table-scroll").flex_1().min_w(px(560.0)).overflow_x_scroll().occlude().child(agents.min_w(px(880.0))))
                .child(div().flex_1().min_w(px(360.0)).child(history)),
        )
        .child(bars)
        .child(variation)
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(div().size(px(6.0)).rounded(px(1.5)).bg(rgba(0xbfe4ff99)))
                .child(mono("Ice is better than the benchmark before, red is worse. n/a means the engine did not measure it.", DIM)),
        )
}

fn case_words(case: &crate::api::Value, key: &str) -> String {
    let words: Vec<String> = crate::api::arr(case,key).iter().map(|v| if let Some(s)=v.as_str() { s.to_string() } else { crate::api::s(v,"claim") }).filter(|s| !s.is_empty()).collect();
    if words.is_empty() { "none specified".into() } else { words.join("; ") }
}

fn score_words(raw: &crate::api::Value) -> String {
    let Some(gold) = raw.get("gold").filter(|g| !g.is_null()) else { return "This older run was not scored against expected answers.".into(); };
    let found = crate::api::arr(gold,"found").len(); let missed=crate::api::arr(gold,"missed").len();
    let traps = crate::api::arr(gold,"hallucinated").len();
    format!("Expected issues found: {found}/{} · missed: {missed} · forbidden claims in the final answer: {traps}", found+missed)
}

fn latest_score(runs: &[&BenchRun]) -> Div {
    let completed = runs.iter().filter(|r| r.error.is_empty()).count();
    let mut passed=0;
    let mut found=0; let mut wanted=0; let mut traps=0; let mut attempted=0; let mut attempted_scored=0; let mut scored=0;
    let mut tokens=0.0; let mut measured=0;
    for run in runs {
        if let Some(g)=run.raw.get("gold").filter(|g| !g.is_null()) {
            if run.error.is_empty() && crate::api::arr(g,"missed").is_empty() && crate::api::arr(g,"hallucinated").is_empty() { passed+=1; }
            scored+=1; found+=crate::api::arr(g,"found").len(); wanted+=crate::api::arr(g,"found").len()+crate::api::arr(g,"missed").len(); traps+=crate::api::arr(g,"hallucinated").len();
        }
        if let Some(g)=run.raw.get("attempted_gold").filter(|g| !g.is_null()) { attempted_scored+=1; attempted+=crate::api::arr(g,"hallucinated").len(); }
        if let Some(t)=run.tokens { tokens+=t; measured+=1; }
    }
    card().flex().flex_col().gap(px(10.0)).child(eyebrow("Benchmark score explained"))
        .child(row_desc(&format!("Completed {completed}/{} runs. {}", runs.len(), if wanted>0 { format!("Found {found}/{wanted} expected issues ({:.0}%).", found as f64/wanted as f64*100.0) } else { "Expected-answer success rate was not measured.".into() })))
        .child(row_desc(&format!("Passed all expected-answer checks: {passed}/{scored} scored runs. A pass requires no missing expected issue and no forbidden claim.")))
        .child(row_desc(&format!("Forbidden claims in scored answers: {traps} ({scored} scored runs). {}", if attempted_scored>0 { format!("Final candidates contained {attempted} forbidden claims before filtering, across {attempted_scored} measured runs.") } else { "Attempts before filtering were not recorded in these older runs.".into() })))
        .child(row_desc(&format!("Tokens burned: {}. Counts include input and output; missing usage is not zero.", if measured>0 { format!("{tokens:.0} across {measured}/{} measured runs",runs.len()) } else { "not reported by this agent".into() })))
        .child(row_desc("Evidence kept measures quote checks. It does not mean the answer is complete or correct. Trap scoring compares wording against the versioned case list; it is not an independent accuracy audit."))
}

fn run_detail(r: &BenchRun, i: usize, _cx: &mut Context<Kriko>) -> gpui::Stateful<Div> {
    let detail=r.raw.get("detail").cloned().unwrap_or(crate::api::Value::Null);
    let answer=detail.get("answer").cloned().unwrap_or(crate::api::Value::Null);
    let mut d=well().id(("bench-answer-scroll",i)).h(px(400.0)).overflow_y_scroll().occlude().on_scroll_wheel(|_,_,cx|cx.stop_propagation())
        .p(px(16.0)).flex().flex_col().gap(px(12.0))
        .child(row_desc(&score_words(&r.raw)).flex_none())
        .child(row_desc(&format!("{} · tokens: {} · {} risks backed by evidence · {} candidates rejected", seconds(r.ms), r.tokens.map(|v|format!("{v:.0}")).unwrap_or_else(||"not reported".into()),r.accepted,r.refused)));
    if !r.error.is_empty() { d=d.child(row_desc(&r.error)); }
    if let Some(g)=r.raw.get("gold") {
        for (key,label) in [("found","Found"),("missed","Missed"),("hallucinated","Forbidden claim"),("unlisted","Additional finding")] {
            for item in crate::api::arr(g,key) { d=d.child(row_desc(&format!("{label}: {}",item.as_str().unwrap_or("unreported"))).flex_none()); }
        }
    }
    let risks=crate::api::arr(&answer,"risks");
    if risks.is_empty() && r.error.is_empty() { d=d.child(row_desc("No risk passed the evidence checks. This is not proof that the product has no problems.")); }
    for (risk_index, risk) in risks.iter().enumerate() {
        d=d.child(hairline()).child(row_title(&crate::api::s(risk,"title")).flex_none()).child(row_desc(&crate::api::s(risk,"body")).flex_none());
        for source in crate::api::arr(risk,"sources") {
            let url=crate::api::s(source,"url"); let link=url.clone();
            d=d.child(mono(&crate::api::s(source,"quote"),INK_2).flex_none())
                .child(div().id(gpui::ElementId::named_usize(format!("bench-source-{i}-{risk_index}-{url}"),0)).cursor_pointer().child(mono(&url,ICE)).on_click(move |_,_,cx|cx.open_url(&link)));
        }
    }
    d=d.child(hairline()).child(row_desc(&format!("Settings used: {}", detail.get("settings").map(|s| format!("{} pages · {} reply tokens · {} s timeout · agent {}",crate::api::n(s,"max_documents").map(|v|v.to_string()).unwrap_or_else(||"run default".into()),crate::api::n(s,"max_tokens").map(|v|v.to_string()).unwrap_or_else(||"default".into()),crate::api::n(s,"timeout_seconds").map(|v|v.to_string()).unwrap_or_else(||"default".into()),crate::api::s(s,"harness"))).unwrap_or_else(||"not recorded".into()))).flex_none());
    let copy=r.raw.to_string();
    d.child(plate_s(("bench-copy-record",i),"Copy full technical record").on_click(move |_,_,cx|cx.write_to_clipboard(gpui::ClipboardItem::new_string(copy.clone()))).flex_none())
}
