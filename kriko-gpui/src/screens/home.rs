//! Home: what you were doing, what you saved, and the shape of the knowledge.
//! Recent work and drafts side by side, then the graphs. Information only —
//! no verdicts, no bare totals — and nothing asks you for anything here.
//! Everything comes from the engine: `/api/history`, `/api/compare-drafts`,
//! `/api/status` and `/api/packs`.

use gpui::{
    div, prelude::*, px, rgb, rgba, relative, ClickEvent, Context, Div, FontWeight, Stateful,
    Styled, Window,
};

use crate::app::{Kriko, Tab};
use crate::live::history::{ago, month_buckets, now_secs, Item};
use crate::screens::history::clip;
use crate::screens::{empty_note, mono, plate_s};
use crate::theme::*;

/// One recent check: what it was about, which catalog, when. Info, no verdict.
fn recent_row(cx: &mut Context<Kriko>, ri: usize, check: &Item, now: i64) -> Stateful<Div> {
    let open_history = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::History;
        this.page = 0;
        cx.notify();
    });
    div()
        .id(("home-recent", ri))
        .py(px(12.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .gap(px(16.0))
        .ml(px(-8.0))
        .mr(px(-8.0))
        .rounded(px(10.0))
        .cursor_pointer()
        .hover(|s| s.bg(rgba(GLASS_1)))
        .on_click(open_history)
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(
                    div()
                        .font_family(SANS)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(15.0))
                        .text_color(rgb(INK))
                        .child(check.label.clone()),
                )
                .child(mono(&clip(&check.pack_line(), 48), MUTED)),
        )
        .child(
            div()
                .w(px(110.0))
                .flex()
                .items_center()
                .justify_end()
                .child(mono(&ago(check.ts, now), DIM)),
        )
}

/// A saved comparison draft, openable straight into Compare. `subjects` are
/// the products' names, read from the history by lookup id.
fn draft_row(cx: &mut Context<Kriko>, i: usize, name: &str, subjects: &str) -> Stateful<Div> {
    // Compare loads its own drafts; Home only takes you there.
    let open_draft = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::Compare;
        cx.notify();
    });
    div()
        .id(("home-draft", i))
        .py(px(12.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .gap(px(16.0))
        .ml(px(-8.0))
        .mr(px(-8.0))
        .rounded(px(10.0))
        .cursor_pointer()
        .hover(|s| s.bg(rgba(GLASS_1)))
        .on_click(open_draft)
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(
                    div()
                        .font_family(SANS)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(15.0))
                        .text_color(rgb(INK))
                        .child(name.to_string()),
                )
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(MUTED))
                        .child(subjects.to_string()),
                ),
        )
        .child(icon("compare", 16.0).text_color(rgb(DIM)))
}

/// The activity graph: one column per month, the bar as tall as the count.
fn checks_graph(months: &[(String, u32)]) -> Div {
    let max = months.iter().map(|(_, v)| *v).max().unwrap_or(1).max(1) as f32;
    let mut cols = div().flex().items_end().gap(px(10.0));
    for (label, value) in months {
        let height = 10.0 + 110.0 * (*value as f32) / max;
        cols = cols.child(
            div()
                .flex_1()
                .flex()
                .flex_col()
                .items_center()
                .gap(px(8.0))
                .child(
                    div()
                        .w_full()
                        .max_w(px(28.0))
                        .flex()
                        .flex_col()
                        .justify_end()
                        .h(px(120.0))
                        .child(
                            div()
                                .w_full()
                                .h(px(if *value == 0 { 3.0 } else { height }))
                                .rounded(px(3.0))
                                .bg(rgb(ICE))
                                .opacity(if *value == 0 {
                                    0.15
                                } else {
                                    0.55 + 0.45 * (*value as f32) / max
                                })
                                .shadow(vec![shadow(0xbfe4ff40, 0.0, 0.0, 8.0, 0.0)]),
                        ),
                )
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(DIM))
                        .child(label.clone()),
                ),
        );
    }
    cols
}

/// Horizontal bars, longest on top: a label, a bar as long as its share of
/// the biggest value, and the figures at the right.
fn bar_rows(rows: &[(String, f32, String)]) -> Div {
    let max = rows.iter().map(|r| r.1).fold(0.0f32, f32::max).max(1.0);
    let mut graph = div().flex().flex_col().gap(px(12.0));
    for (label, value, figure) in rows {
        graph = graph.child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(
                    div()
                        .w(px(130.0))
                        .font_family(MONO)
                        .text_size(px(11.0))
                        .text_color(rgb(MUTED))
                        .child(label.clone()),
                )
                .child(
                    div()
                        .flex_1()
                        .h(px(10.0))
                        .rounded(px(2.0))
                        .bg(rgb(WELL))
                        .border_1()
                        .border_color(rgba(HAIRLINE))
                        .child(
                            div()
                                .h_full()
                                .w(relative(value / max))
                                .rounded(px(2.0))
                                .bg(rgb(ICE))
                                .opacity(0.8),
                        ),
                )
                .child(
                    div()
                        .w(px(70.0))
                        .flex()
                        .justify_end()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(DIM))
                        .child(figure.clone()),
                ),
        );
    }
    graph
}

pub fn home(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let open_history = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::History;
        this.page = 0;
        cx.notify();
    });
    let now = now_secs();
    let h = &app.live.history;

    // ---- recent work: the four newest checks ----
    let mut recent = card().flex().flex_col();
    recent = recent.child(div().mb(px(14.0)).child(eyebrow("Recent work")));
    if !h.loaded {
        recent = recent.child(empty_note("Reading your history from the engine."));
    } else if h.items.is_empty() {
        recent = recent.child(empty_note("No checks yet. The next one you run shows up here."));
    } else {
        let shown = h.items.len().min(4);
        for (ri, check) in h.items.iter().take(shown).enumerate() {
            recent = recent
                .child(recent_row(cx, ri, check, now))
                .when(ri + 1 < shown, |d| d.child(hairline()));
        }
        recent = recent.child(
            div()
                .mt(px(16.0))
                .flex()
                .items_center()
                .justify_end()
                .child(plate_s("home-all", "All history").on_click(open_history)),
        );
    }

    // ---- drafts: the saved comparisons ----
    let mut drafts = card().flex().flex_col();
    drafts = drafts.child(div().mb(px(14.0)).child(eyebrow("Drafts")));
    if !h.drafts_loaded {
        drafts = drafts.child(empty_note("Reading your drafts from the engine."));
    } else if h.drafts.is_empty() {
        drafts = drafts.child(empty_note("No saved comparisons yet."));
    } else {
        let n = h.drafts.len();
        let rows: Vec<(String, String)> = h
            .drafts
            .iter()
            .map(|d| {
                let names: Vec<&str> =
                    d.lookup_ids.iter().filter_map(|id| h.label_of(id)).collect();
                let line = if names.is_empty() {
                    format!("{} products", d.lookup_ids.len())
                } else {
                    names.join(" · ")
                };
                (d.name.clone(), line)
            })
            .collect();
        for (i, (name, line)) in rows.iter().enumerate() {
            drafts = drafts
                .child(draft_row(cx, i, name, line))
                .when(i + 1 < n, |d| d.child(hairline()));
        }
    }

    // ---- the graphs ----
    let checks_body: gpui::AnyElement = if h.loaded && !h.items.is_empty() {
        let months = month_buckets(h.items.iter().filter_map(|i| i.ts), now, 6);
        checks_graph(&months).into_any_element()
    } else {
        empty_note("No checks to count yet.").into_any_element()
    };
    let checks_card = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(eyebrow("Checks per month"))
        .child(checks_body);

    let claims_body: gpui::AnyElement = match &h.counts {
        Some(c) => bar_rows(&[
            ("subjects".to_string(), c.subjects as f32, c.subjects.to_string()),
            ("claims".to_string(), c.claims as f32, c.claims.to_string()),
            ("sources behind them".to_string(), c.evidence as f32, c.evidence.to_string()),
        ])
        .into_any_element(),
        None => empty_note("Counting what the store holds.").into_any_element(),
    };
    let claims_card = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(eyebrow("Evidence in the store"))
        .child(claims_body);

    let packs_body: gpui::AnyElement = match &h.packs {
        Some(packs) => {
            let mut live: Vec<_> = packs.iter().filter(|p| p.enabled).collect();
            live.sort_by(|a, b| b.claims.cmp(&a.claims));
            if live.is_empty() {
                empty_note("No catalog is switched on.").into_any_element()
            } else {
                let rows: Vec<(String, f32, String)> = live
                    .iter()
                    .take(4)
                    .map(|p| {
                        (
                            clip(&p.name, 20),
                            p.claims as f32,
                            format!("{} claims", p.claims),
                        )
                    })
                    .collect();
                bar_rows(&rows).into_any_element()
            }
        }
        None => empty_note("Reading the installed catalogs.").into_any_element(),
    };
    let packs_card = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(eyebrow("Claims per catalog"))
        .child(packs_body);

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .items_start()
                .child(div().flex_1().min_w(px(380.0)).child(recent))
                .child(div().flex_1().min_w(px(380.0)).child(drafts)),
        )
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .items_start()
                .child(div().flex_1().min_w(px(300.0)).child(checks_card))
                .child(div().flex_1().min_w(px(300.0)).child(claims_card))
                .child(div().flex_1().min_w(px(300.0)).child(packs_card)),
        )
}
