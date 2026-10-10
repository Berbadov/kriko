//! Benchmark: how the agents and planes do on the engine's fixed test set,
//! on this machine. The machine and the run key; the headline numbers with
//! their change since the benchmark before; each agent side by side; the
//! history of benchmarks; and the latest one, run by run. Everything is a
//! row the engine measured (`GET /api/bench`); a number it did not measure
//! reads "n/a", never zero.

use gpui::{div, point, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Styled, Window};

use crate::app::Kriko;
use crate::api::{self, Value};
use crate::live::local::{batches, change, BenchPhase, BenchRun, Batch, Machine};
use crate::marks::{self, mark_glyph, Mark, Phase};
use crate::screens::history::{drawer_ctrl, drawer_option};
use crate::screens::local::pill;
use crate::screens::{empty_note, mono, row_desc, th};
use crate::theme::*;

fn glow(color: u32, blur: f32) -> Vec<gpui::BoxShadow> {
    vec![gpui::BoxShadow {
        color: hsla(color),
        offset: point(px(0.0), px(0.0)),
        blur_radius: px(blur),
        spread_radius: px(0.0),
    }]
}

fn csv_cell(value: impl AsRef<str>) -> String {
    let value = value.as_ref();
    let safe = if value.starts_with(['=', '+', '-', '@']) {
        format!("'{value}")
    } else {
        value.to_string()
    };
    format!("\"{}\"", safe.replace('"', "\"\""))
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
/// change, a strip of the benchmarks before it, and what the number means.
fn headline(label: &str, value: &str, unit: &str, desc: &str, pct: Option<i8>, higher_better: bool, series: &[Option<f64>]) -> Div {
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
        .child(row_desc(desc))
}

/// The mark an agent wears, by the id the engine gives it.
fn mark_for(plane: &str, llm: &str, local_server: &str) -> &'static Mark {
    let id = llm.to_lowercase();
    for (needle, mark) in [
        ("claude", &marks::CLAUDE),
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

pub fn benchmark(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let b = &app.live.local.bench;
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
        if !b.controlled() && plane == "api" { continue; }
        let name = plane.clone();
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.bench_toggle_plane(&name, cx);
        });
        planes = planes.child(
            pill(("bench-plane", i), plane, b.picked.contains(plane)).on_click(toggle),
        );
    }
    let meanings: Vec<String> = b
        .planes
        .iter()
        .filter(|(p, _)| b.picked.contains(p))
        .map(|(p, m)| format!("{p}: {m}"))
        .collect();

    // ---- the grid's knobs, each a drawer ----
    let knob = |name: &'static str, label: &str, word: String, open: bool| {
        drawer_ctrl(gpui::ElementId::Name(name.into()), label, &word, open)
    };
    let mut grid_row = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (name, label, word) in [
        ("suite", "SUITE", b.suites.iter().find(|s| s.id == b.suite).map(|s| s.label.clone()).unwrap_or_else(|| "Configuration accuracy".into())),
        ("cases", "CASES", format!("{}", b.cases)),
        ("docs", "DOCS", format!("{}", b.docs)),
        ("reps", "REPS", format!("{}", b.reps)),
        ("budget", "SPEND", format!("${:.2}", b.budget)),
        (
            "models",
            "MODELS",
            if b.models.is_empty() {
                "EACH PLANE'S OWN".to_string()
            } else {
                format!("{}", b.models.len())
            },
        ),
    ] {
        if b.controlled() && name == "docs" { continue; }
        let open = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.bench_open_drawer(name, cx);
        });
        grid_row = grid_row.child(knob(name, label, word, b.drawer == Some(name)).on_click(open));
    }
    let mut grid_panel = div().flex().flex_col().gap(px(8.0)).child(grid_row);
    match b.drawer {
        Some("suite") => {
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(4.0));
            for (i, suite) in b.suites.iter().enumerate() {
                let id = suite.id.clone();
                let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    this.bench_pick_suite(id.clone(), cx);
                });
                panel = panel.child(drawer_option(gpui::ElementId::named_usize("bench-suite", i),
                    &suite.label, b.suite == suite.id).on_click(pick)).child(row_desc(&suite.description));
            }
            grid_panel = grid_panel.child(panel);
        }
        Some("models") => {
            let choices = app.bench_model_choices();
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(2.0));
            panel = panel.child(mono(
                "Picked ones are swept; none picked means whichever model each plane would run.",
                MUTED,
            ));
            if choices.is_empty() {
                panel = panel.child(mono("No provider on this machine lists its models yet.", MUTED));
            }
            for (mi, m) in choices.iter().enumerate() {
                let want = m.clone();
                let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    this.bench_pick_model(want.clone(), cx);
                });
                panel = panel.child(
                    drawer_option(gpui::ElementId::named_usize("bench-model-opt", mi), m, b.models.contains(m))
                        .on_click(pick),
                );
            }
            grid_panel = grid_panel.child(panel);
        }
        Some(name @ ("cases" | "docs" | "reps" | "budget")) => {
            let (values, fmt): (Vec<f64>, fn(f64) -> String) = match name {
                "cases" if b.controlled() => (vec![1.0, 3.0, 5.0, 9.0], |v| format!("{v:.0}")),
                "cases" | "docs" => (vec![1.0, 3.0, 5.0, 10.0, 20.0], |v| format!("{v:.0}")),
                "reps" => (vec![1.0, 2.0, 3.0, 5.0], |v| format!("{v:.0}x")),
                _ => (vec![0.0, 0.10, 0.20, 0.50, 1.0, 2.0], |v| format!("${v:.2}")),
            };
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(2.0));
            for (vi, v) in values.iter().enumerate() {
                let word = fmt(*v);
                let val = *v;
                let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    this.bench_set_knob(name, val, cx);
                });
                let chosen = match name {
                    "cases" => b.cases as f64 == *v,
                    "docs" => b.docs as f64 == *v,
                    "reps" => b.reps as f64 == *v,
                    _ => (b.budget - *v).abs() < 0.005,
                };
                panel = panel.child(
                    drawer_option(gpui::ElementId::named_usize("bench-knob-opt", vi), &word, chosen)
                        .on_click(pick),
                );
            }
            grid_panel = grid_panel.child(panel);
        }
        _ => {}
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
                            "Measure time, input and output tokens, unsupported claims, missed facts, \
                             exact specifications and correct abstention on each picked plane.",
                        ))
                        .child(mono(
                            &format!(
                                "{} · {} run{} on record",
                                if !b.controlled() { "Live web research" } else if b.set_label.trim() == "· 0 cases" { "test set" } else { &b.set_label },
                                b.runs.len(),
                                if b.runs.len() == 1 { "" } else { "s" }
                            ),
                            DIM,
                        )),
                ),
        )
        .child(
            well()
                .p(px(12.0))
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(eyebrow("This run will bench"))
                .child(mono(&app.bench_grid_word(), INK_2))
                .when(!meanings.is_empty(), |d| d.child(mono(&meanings.join("  ·  "), DIM))),
        )
        .child(div().flex().items_center().gap(px(16.0)).flex_wrap().child(status).child(planes))
        .when(running, |d| {
            let progress = match &b.phase {
                BenchPhase::Running { progress, .. } => *progress,
                _ => 0.0,
            };
            d.child(meter_live("bench-progress", progress, 28, true, motion))
        })
        .when(
            matches!(b.phase, BenchPhase::Confirm(_)),
            |d| d.children(b.last.clone().map(|l| mono(&l, MUTED))),
        )
        .children(b.last.clone().filter(|_| !matches!(b.phase, BenchPhase::Confirm(_))).map(|l| mono(&l, MUTED)))
        .child(grid_panel)
        .child(row_desc(if b.controlled() {
            "Fictional products, identical supplied documents, no search. Scores inspect the raw answer before source filtering. This small development suite does not establish real-world coverage."
        } else {
            "Live search changes over time. Legacy answer keys need auditing; quoted text alone does not prove configuration accuracy."
        }))
        .child(row_desc("Local runs plan and extract evidence; hosted runs use direct completions. The measured protocol is shown with each result. Missing usage or prices remain unmeasured."))
        .child(div().pt(px(4.0)).child(eyebrow("Measured on")))
        .child(machine);

    if b.runs.is_empty() {
        return div()
            .flex()
            .flex_col()
            .gap(px(24.0))
            .child(start_panel)
            .child(empty_note("Nothing has been benchmarked here yet. Run one to see how an agent does."));
    }

    // ---- the headline numbers: the latest benchmark against the one before ----
    let latest = all.first().cloned().unwrap_or_default();
    let comparable: Vec<&Batch> = all.iter().filter(|x| x.configuration == latest.configuration).collect();
    let before = comparable.get(1).map(|x| (*x).clone());
    let take = |f: fn(&Batch) -> Option<f64>| -> Vec<Option<f64>> {
        let mut v: Vec<Option<f64>> = comparable.iter().take(12).map(|x| f(x)).collect();
        v.reverse();
        v
    };
    let ms = |x: &Batch| x.median_ms;
    let tokens = |x: &Batch| x.median_tokens;
    let usd = |x: &Batch| x.median_usd;
    let hallucination = |x: &Batch| x.hallucination;
    let mut csv = String::from("plane,model,protocol,case_set,search,runs,failures,median_ms,p95_ms,tokens_per_run,input_tokens,output_tokens,recall,spec_recall,hallucination,abstention,cost_per_claim\r\n");
    for row in &b.summary {
        let values = [
            row.plane.clone(), row.llm.clone(), row.protocol.clone(), row.set_label.clone(),
            row.search.clone(), format!("{:.0}", row.runs), format!("{:.0}", row.failures),
            row.ms.map(|v| format!("{v:.0}")).unwrap_or_default(),
            row.p95_ms.map(|v| format!("{v:.0}")).unwrap_or_default(),
            row.tokens.map(|v| format!("{v:.0}")).unwrap_or_default(),
            row.tokens_in.map(|v| format!("{v:.0}")).unwrap_or_default(),
            row.tokens_out.map(|v| format!("{v:.0}")).unwrap_or_default(),
            row.recall.map(|v| format!("{v:.6}")).unwrap_or_default(),
            row.spec_recall.map(|v| format!("{v:.6}")).unwrap_or_default(),
            row.hallucination.map(|v| format!("{v:.6}")).unwrap_or_default(),
            row.abstention.map(|v| format!("{v:.6}")).unwrap_or_default(),
            row.cost_per_claim.map(|v| format!("{v:.6}")).unwrap_or_default(),
        ];
        csv.push_str(&values.iter().map(csv_cell).collect::<Vec<_>>().join(","));
        csv.push_str("\r\n");
    }
    let export = cx.listener(move |_, _: &gpui::ClickEvent, _w, cx| {
        cx.write_to_clipboard(gpui::ClipboardItem::new_string(csv.clone()));
    });
    let export_card = card()
        .flex()
        .items_center()
        .gap(px(16.0))
        .child(div().flex_1().min_w(px(0.0)).flex().flex_col().gap(px(3.0))
            .child(eyebrow("Report"))
            .child(row_desc("Copy the benchmark summary as CSV for a spreadsheet or release report.")))
        .child(crate::screens::plate_s("bench-export-csv", "Copy CSV").on_click(export));
    let heads = div()
        .flex()
        .flex_wrap()
        .gap(px(16.0))
        .child(headline(
            "Median answer",
            &latest.median_ms.map(|m| format!("{:.1}", m / 1000.0)).unwrap_or_else(|| "n/a".into()),
            "s",
            "Half the attempts finished sooner; failed attempts are included.",
            change(latest.median_ms, before.as_ref().and_then(ms)),
            false,
            &take(|x| x.median_ms),
        ))
        .child(headline(
            "Tokens per run",
            &latest.median_tokens.map(|t| format!("{:.0}", t)).unwrap_or_else(|| "n/a".into()),
            "tokens",
            "The middle run's spend in tokens, reading included.",
            change(latest.median_tokens, before.as_ref().and_then(tokens)),
            false,
            &take(|x| x.median_tokens),
        ))
        .child(headline(
            "Cost per run",
            &latest.median_usd.map(|u| format!("{u:.3}")).unwrap_or_else(|| "n/a".into()),
            if latest.median_usd.is_some() { "USD" } else { "not measured" },
            "What the middle run cost on the planes that bill per token.",
            change(latest.median_usd, before.as_ref().and_then(usd)),
            false,
            &take(|x| x.median_usd),
        ))
        .child(headline(
            "Unsupported claims",
            &latest.hallucination.map(|a| format!("{:.0}", a * 100.0)).unwrap_or_else(|| "n/a".into()),
            "%",
            "Raw claims unsupported by the case's configuration and evidence.",
            change(latest.hallucination, before.as_ref().and_then(hallucination)),
            false,
            &take(|x| x.hallucination),
        ));

    // ---- the agents, side by side ----
    let mut agents = card()
        .min_w(px(850.0))
        .flex()
        .flex_col()
        .child(div().mb(px(12.0)).child(eyebrow("Agents on this machine")))
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().min_w(px(170.0)).child(th("Agent")))
                .child(div().w(px(116.0)).child(th("p50 / p95")))
                .child(div().w(px(100.0)).child(th("Tokens / run")))
                .child(div().w(px(80.0)).child(th("Recall")))
                .child(div().w(px(80.0)).child(th("Specs")))
                .child(div().w(px(96.0)).child(th("Hallucination")))
                .child(div().w(px(80.0)).child(th("Abstention"))),
        )
        .child(hairline());
    for (k, row) in b.summary.iter().enumerate() {
        let name = if row.llm.is_empty() { row.plane.clone() } else { row.llm.clone() };
        let percent = |value: Option<f64>| value.map(|v| format!("{:.0}%", v * 100.0)).unwrap_or_else(|| "n/a".into());
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
                                .child(mono(&format!("{} · {} · {:.0} runs · {:.0} failed", row.plane, row.protocol, row.runs, row.failures), DIM))
                                .child(mono(&format!("{} · {}", row.set_label, row.search), DIM))
                                .child(mono(&format!("tokens: {:.0}/{:.0} runs · $/claim: {}", row.counted_runs, row.runs,
                                    row.cost_per_claim.map(|v| format!("{v:.4}")).unwrap_or_else(|| "unmeasured".into())), DIM)),
                        ),
                )
                .child(div().w(px(116.0)).child(mono(&format!("{} / {}", seconds(row.ms), seconds(row.p95_ms)), INK_2)))
                .child(
                    div().w(px(100.0)).child(match row.tokens {
                        Some(t) => div().child(mono(&format!("{t:.0}"), INK_2)),
                        None => div().child(mono("n/a", DIM)),
                    }),
                )
                .child(
                    div()
                        .w(px(80.0))
                        .child(mono(&percent(row.recall), INK_2)),
                )
                .child(div().w(px(80.0)).child(mono(&percent(row.spec_recall), INK_2)))
                .child(div().w(px(96.0)).child(match row.hallucination {
                    Some(h) => mono(&format!("{:.0}%", h * 100.0), if h > 0.0 { DANGER } else { ICE }),
                    None => mono("not scored", DIM),
                }))
                .child(div().w(px(80.0)).child(mono(&percent(row.abstention), INK_2))),
        );
        let number = |v: Option<f64>| v.map(|x| format!("{x:.0}")).unwrap_or_else(|| "unmeasured".into());
        agents = agents.child(row_desc(&format!("Input {} · output {} tokens total · {:.0} incomplete counts · {:.0}/{:.0} cases passed · {:.0} raw claims · {:.0} wrong specifications",
            number(row.tokens_in), number(row.tokens_out), row.partial_runs, row.passed, row.graded, row.raw_produced, row.spec_errors)));
        if k + 1 < b.summary.len() {
            agents = agents.child(hairline());
        }
    }

    // ---- the history of benchmarks ----
    let mut series: Vec<&Batch> = comparable.iter().copied().filter(|x| x.median_ms.is_some()).take(10).collect();
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
                .child(eyebrow("Attempt time, same grid over time"))
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
    let mine: Vec<&BenchRun> = b.runs.iter().filter(|r| r.batch_id == latest.id).collect();
    let slowest = mine.iter().filter_map(|r| r.ms).fold(1.0f64, f64::max);
    let mut bars = card().flex().flex_col();
    bars = bars.child(div().mb(px(12.0)).child(eyebrow("Latest benchmark, run by run")));
    for (i, r) in mine.iter().enumerate() {
        let failed = !r.error.is_empty();
        let id = r.id.clone();
        let open = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.bench_open_run(id.clone(), cx);
        });
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
                .child(led_bar(
                    r.ms.map(|m| (m / slowest * 100.0) as f32).unwrap_or(0.0),
                    28,
                    if failed { DANGER } else if i == 0 { ICE } else { LED_DIM },
                ))
                .child(row_desc(&r.configuration))
                .child(mono(&format!("Tokens {} · input {} · output {}{}",
                    r.tokens.map(|v| format!("{v:.0}")).unwrap_or_else(|| "unmeasured".into()),
                    r.tokens_in.map(|v| format!("{v:.0}")).unwrap_or_else(|| "unmeasured".into()),
                    r.tokens_out.map(|v| format!("{v:.0}")).unwrap_or_else(|| "unmeasured".into()),
                    if r.usage_complete { "" } else { " · incomplete usage" }), DIM))
                .child(drawer_ctrl(gpui::ElementId::named_usize("bench-details", i), "EVIDENCE", "RAW ANSWER AND STAGES", b.open_run.as_ref() == Some(&r.id)).on_click(open))
                .when(b.open_run.as_ref() == Some(&r.id), |d| {
                    let mut detail = well().p(px(12.0)).flex().flex_col().gap(px(6.0));
                    for stage in &r.stages {
                        detail = detail.child(mono(&format!("{} · {} · {} tokens{}", api::s(stage, "stage"),
                            seconds(stage.get("ms").and_then(Value::as_f64)),
                            stage.get("tokens_used").and_then(Value::as_i64).map(|v| v.to_string()).unwrap_or_else(|| "unmeasured".into()),
                            if stage.get("failed").and_then(Value::as_bool) == Some(true) { " · failed" } else { "" }), MUTED));
                    }
                    if r.score.is_object() {
                        detail = detail.child(mono("Raw answer, missed facts and grading errors", INK_2));
                        let score = serde_json::json!({
                            "case": r.score.get("case"), "pass": r.score.get("pass"),
                            "proposed_risks": r.score.get("proposed_risks"),
                            "proposed_specs": r.score.get("proposed_specs"),
                            "errors": r.score.get("errors"), "missed": r.score.get("missed"),
                            "spec_errors": r.score.get("spec_errors"), "spec_missed": r.score.get("spec_missed"),
                            "abstention_correct": r.score.get("abstention_correct"),
                        });
                        for line in serde_json::to_string_pretty(&score).unwrap_or_default().lines() {
                            detail = detail.child(row_desc(line));
                        }
                    } else {
                        detail = detail.child(row_desc("No ground-truth score is available for this run."));
                    }
                    d.child(detail)
                }),
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
        .child(export_card)
        .child(heads)
        .child(div().id("bench-agents-scroll").overflow_x_scroll().child(agents))
        .child(history)
        .child(bars)
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(div().size(px(6.0)).rounded(px(1.5)).bg(rgba(0xbfe4ff99)))
                .child(mono("Ice is better than the benchmark before, red is worse. n/a means the engine did not measure it.", DIM)),
        )
}
