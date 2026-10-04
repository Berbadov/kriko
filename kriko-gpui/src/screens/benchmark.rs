//! Benchmark: how long the parts of a check take on this machine.
//! The machine it measured on and the run key; the headline numbers with
//! their change; where one check's time goes, stage by stage; how each
//! agent paces; the history of full checks; and the timed passes.

use gpui::{div, point, prelude::*, px, relative, rgb, rgba, Context, Div, FontWeight, Styled, Window};

use crate::app::Kriko;
use crate::data;
use crate::marks::{mark_glyph, Phase};
use crate::screens::{mono, row_desc, th};
use crate::theme::*;

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
fn clock(secs: f32) -> String {
    let s = secs.max(0.0).round() as u32;
    format!("{}:{:02}", s / 60, s % 60)
}

/// The change since the last benchmark: an LED arrow and the percent, in ice
/// when it got better and the danger ink when it got worse. `higher_better`
/// says which way better points for this number.
fn delta(pct: i8, higher_better: bool) -> Div {
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
/// change, and a strip of the full-check history under it.
fn headline(i: usize, label: &str, value: &str, unit: &str, pct: i8, higher_better: bool) -> Div {
    let mut spark = div().flex().items_end().gap(px(2.0)).h(px(22.0));
    // every headline has its own walk; the first is the real history
    let n = data::BENCH_HISTORY.len();
    let (lo, hi) = data::BENCH_HISTORY
        .iter()
        .fold((u16::MAX, 0u16), |(a, b), &v| (a.min(v), b.max(v)));
    for (k, v) in data::BENCH_HISTORY.iter().enumerate() {
        let wobble = ((k * 7 + i * 5) % 6) as f32 * 0.06;
        let mut f = (*v - lo) as f32 / (hi - lo).max(1) as f32;
        if higher_better {
            f = 1.0 - f; // fewer seconds, more throughput
        }
        let f = (0.25 + 0.75 * (f * 0.8 + wobble)).min(1.0);
        let last = k + 1 == n;
        spark = spark.child(
            div()
                .w(px(5.0))
                .h(px((22.0 * f).round().max(3.0)))
                .rounded(px(1.0))
                .bg(rgb(if last { ICE } else { LED_DIM }))
                .when(last, |d| d.shadow(glow(ICE, 5.0))),
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

pub fn benchmark(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let run = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.bench_start(cx);
    });
    let total: f32 = data::BENCH_STAGES.iter().map(|s| s.secs).sum();
    let progress = app.bench_progress;
    let at = progress.map(|p| p / 100.0 * total);

    // ---- the machine and the run key ----
    let mut machine = div().flex().flex_wrap().gap(px(8.0));
    for (label, value) in data::BENCH_MACHINE {
        machine = machine.child(
            well()
                .px(px(12.0))
                .py(px(8.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(mono(&label.to_uppercase(), DIM))
                .child(mono(value, INK_2)),
        );
    }
    let status = match at {
        Some(t) => {
            let stage = data::BENCH_STAGES
                .iter()
                .scan(0.0, |acc, s| {
                    *acc += s.secs;
                    Some((*acc, s.name))
                })
                .find(|(end, _)| t < *end)
                .map(|(_, n)| n)
                .unwrap_or("Settle");
            tag(
                "bench-running",
                TagState::Live,
                &format!("Running · {stage} · {} of {}", clock(t), clock(total)),
                motion,
            )
        }
        None => tag("bench-idle", TagState::Done, "Idle", motion),
    };
    let start_panel = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(24.0))
                .child(
                    plate_wide(
                        "bench-run",
                        if progress.is_some() { "Stop benchmark" } else { "Run benchmark" },
                    )
                    .on_click(run),
                )
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_desc(
                            "Times every stage of a check with the packs that are enabled now, on one saved listing, three subjects. Nothing is stored and no claim leaves this machine.",
                        ))
                        .child(mono(
                            &format!(
                                "Last benchmark: {} · {} on record",
                                if app.bench_done > 0 { "just now" } else { "2 min ago" },
                                data::BENCH_HISTORY.len() as u32 + app.bench_done
                            ),
                            DIM,
                        )),
                ),
        )
        .child(div().flex().child(status))
        .child(div().pt(px(4.0)).child(eyebrow("Measured on")))
        .child(machine);

    // ---- the headline numbers ----
    let mut heads = div().flex().flex_wrap().gap(px(16.0));
    for (i, (label, value, unit, pct, hb)) in data::BENCH_HEADLINE.iter().enumerate() {
        heads = heads.child(headline(i, label, value, unit, *pct, *hb));
    }

    // ---- where one check's time goes ----
    // one bar, each stage its share; while a benchmark runs the stages
    // light up in turn and the one under way fills
    let mut stacked = well().p(px(6.0)).flex().gap(px(3.0)).h(px(30.0));
    let mut legend = div().flex().flex_col();
    let mut start = 0.0f32;
    for (si, stage) in data::BENCH_STAGES.iter().enumerate() {
        let share = stage.secs / total;
        let end = start + stage.secs;
        let (fill, live) = match at {
            Some(t) if t >= end => (1.0, false),
            Some(t) if t >= start => ((t - start) / stage.secs, true),
            Some(_) => (0.0, false),
            None => (1.0, false),
        };
        stacked = stacked.child(
            div()
                .w(relative(share))
                .h_full()
                .rounded(px(3.0))
                .bg(rgb(LED_OFF))
                .overflow_hidden()
                .child(
                    div()
                        .w(relative(fill))
                        .h_full()
                        .rounded(px(3.0))
                        .bg(rgb(stage.color))
                        .shadow(glow(stage.color, if live { 10.0 } else { 4.0 })),
                ),
        );
        legend = legend
            .child(
                div()
                    .py(px(9.0))
                    .flex()
                    .items_center()
                    .gap(px(14.0))
                    .child(
                        div()
                            .size(px(10.0))
                            .flex_none()
                            .rounded(px(2.0))
                            .bg(rgb(stage.color))
                            .shadow(glow(stage.color, 5.0)),
                    )
                    .child(
                        div()
                            .w(px(140.0))
                            .flex_none()
                            .font_family(SANS)
                            .font_weight(FontWeight::SEMIBOLD)
                            .text_size(px(14.0))
                            .text_color(rgb(if live { ICE } else { INK }))
                            .child(stage.name),
                    )
                    .child(div().flex_1().min_w(px(0.0)).child(row_desc(stage.what)))
                    .child(
                        div()
                            .w(px(64.0))
                            .flex_none()
                            .flex()
                            .justify_end()
                            .child(mono(&format!("{:.0}%", share * 100.0), MUTED)),
                    )
                    .child(
                        div()
                            .w(px(64.0))
                            .flex_none()
                            .flex()
                            .justify_end()
                            .child(mono(&clock(stage.secs), if live { ICE } else { INK_2 })),
                    ),
            );
        if si + 1 < data::BENCH_STAGES.len() {
            legend = legend.child(hairline());
        }
        start = end;
    }
    let slowest = data::BENCH_STAGES
        .iter()
        .max_by(|a, b| a.secs.total_cmp(&b.secs))
        .map(|s| s.name)
        .unwrap_or("");
    let breakdown = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(eyebrow("Where one check's time goes"))
                .child(mono(&format!("{} total · 3 subjects", clock(total)), MUTED)),
        )
        .child(stacked)
        .child(row_desc(&format!(
            "{slowest} and fetching sources take most of a check. Pages already in the cache skip the fetch, so a second check of the same product is faster."
        )))
        .child(legend);

    // ---- the agents, side by side ----
    let fastest = data::BENCH_AGENTS
        .iter()
        .map(|a| a.2)
        .fold(1.0f32, f32::max);
    let mut agents = card()
        .flex()
        .flex_col()
        .child(div().mb(px(12.0)).child(eyebrow("Agents on this machine")))
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().min_w(px(170.0)).child(th("Agent")))
                .child(div().w(px(84.0)).child(th("Answer")))
                .child(div().w(px(180.0)).child(th("Tokens / s")))
                .child(div().w(px(112.0)).child(th("Claims / run")))
                .child(div().w(px(84.0)).child(th("Finished"))),
        )
        .child(hairline());
    for (k, (ai, answer, tps, claims, finished)) in data::BENCH_AGENTS.iter().enumerate() {
        let agent = &data::AGENTS[*ai];
        let running = progress.is_some();
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
                            agent.mark,
                            if running { Phase::Thinking } else { Phase::Idle },
                            30.0,
                            motion,
                        ))
                        .child(
                            div()
                                .font_family(SANS)
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_size(px(14.0))
                                .text_color(rgb(INK))
                                .child(agent.name),
                        ),
                )
                .child(div().w(px(84.0)).child(mono(answer, INK_2)))
                .child(
                    div()
                        .w(px(180.0))
                        .flex()
                        .items_center()
                        .gap(px(10.0))
                        .child(led_bar(tps / fastest * 100.0, 10, if *tps >= fastest { ICE } else { LED_DIM }))
                        .child(mono(&format!("{tps:.0}"), INK_2)),
                )
                .child(div().w(px(112.0)).child(mono(&format!("{claims:.1}"), INK_2)))
                .child(
                    div()
                        .w(px(84.0))
                        .child(mono(&format!("{finished}%"), if *finished >= 95 { ICE } else { INK_2 })),
                ),
        );
        if k + 1 < data::BENCH_AGENTS.len() {
            agents = agents.child(hairline());
        }
    }

    // ---- the history of full checks ----
    let (lo, hi) = data::BENCH_HISTORY
        .iter()
        .fold((u16::MAX, 0u16), |(a, b), &v| (a.min(v), b.max(v)));
    let n = data::BENCH_HISTORY.len();
    let rows = 10usize;
    let mut columns = div().flex().items_end().justify_between().gap(px(6.0));
    for (k, v) in data::BENCH_HISTORY.iter().enumerate() {
        let lit = (2.0 + (*v - lo + 10) as f32 / (hi - lo + 10) as f32 * (rows as f32 - 2.0)).round() as usize;
        let last = k + 1 == n;
        let best = *v == lo;
        let color = if last { ICE } else if best { INK_2 } else { MUTED };
        let mut col = div().flex().flex_col().gap(px(2.0)).items_center();
        for r in 0..rows {
            let on = rows - r <= lit;
            let d = div().w(px(18.0)).h(px(6.0)).rounded(px(1.5));
            col = col.child(if on {
                d.bg(rgb(color)).opacity(if last { 1.0 } else { 0.7 })
                    .when(last, |d| d.shadow(glow(ICE, 5.0)))
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
                .child(mono(&clock(*v as f32), if last { ICE } else if best { INK_2 } else { DIM }))
                .child(col),
        );
    }
    let first = *data::BENCH_HISTORY.first().unwrap_or(&1) as f32;
    let latest = *data::BENCH_HISTORY.last().unwrap_or(&1) as f32;
    let history = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(eyebrow("Full check, benchmark by benchmark"))
                .child(delta((((latest - first) / first) * 100.0).round() as i8, false)),
        )
        .child(row_desc(&format!(
            "Shorter is faster. From {} to {}, the full check went from {} to {}: the cache grew and the local model moved to the GPU.",
            data::BENCH_HISTORY_SPAN.0,
            data::BENCH_HISTORY_SPAN.1,
            clock(first),
            clock(latest)
        )))
        .child(columns)
        .child(
            div()
                .flex()
                .justify_between()
                .child(mono(data::BENCH_HISTORY_SPAN.0, DIM))
                .child(mono(data::BENCH_HISTORY_SPAN.1, DIM)),
        );

    // ---- the timed passes ----
    let mut bars = card().flex().flex_col();
    bars = bars.child(div().mb(px(12.0)).child(eyebrow("Timed passes")));
    for (i, entry) in data::BENCH_RUNS.iter().enumerate() {
        let color = if i == 0 { ICE } else { LED_DIM };
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
                                .child(entry.label.to_string()),
                        )
                        .child(mono(&format!("was {}", entry.before), DIM))
                        .child(div().w(px(64.0)).flex().justify_end().child(delta(entry.delta, false)))
                        .child(
                            div()
                                .w(px(72.0))
                                .flex()
                                .justify_end()
                                .child(mono(entry.took, INK)),
                        ),
                )
                .child(led_bar(entry.value as f32, 28, color)),
        );
        if i + 1 < data::BENCH_RUNS.len() {
            bars = bars.child(hairline());
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(start_panel)
        .child(heads)
        .child(breakdown)
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .items_start()
                .child(div().flex_1().min_w(px(560.0)).child(agents))
                .child(div().flex_1().min_w(px(360.0)).child(history)),
        )
        .child(bars)
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(div().size(px(6.0)).rounded(px(1.5)).bg(rgba(0xbfe4ff99)))
                .child(mono("Ice is better than last time, red is worse. Bars are against the fastest here.", DIM)),
        )
}
