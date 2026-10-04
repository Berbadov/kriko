//! Home: what you were doing, what you saved, and the shape of the knowledge.
//! Recent work and drafts side by side, then the graphs. Information only —
//! no verdicts, no bare totals — and nothing asks you for anything here.

use gpui::{
    div, prelude::*, px, rgb, rgba, relative, ClickEvent, Context, Div, FontWeight, Stateful,
    Styled, Window,
};

use crate::app::{Kriko, Tab};
use crate::data;
use crate::screens::{agent_by_monogram, mono, plate_s};
use crate::theme::*;

/// One recent check: who ran it, what it was about, when. Info, no verdict.
fn recent_row(cx: &mut Context<Kriko>, ri: usize, check: &data::Check) -> Stateful<Div> {
    let open_history = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::History;
        this.page = 0;
        cx.notify();
    });
    let mut agents = div().flex().items_center().gap(px(6.0));
    for m in check.agents {
        agents = agents.child(agent_by_monogram(*m));
    }
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
        .child(agents)
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
                        .child(check.name.to_string()),
                )
                .child(mono(check.pack, MUTED)),
        )
        .child(
            div()
                .w(px(110.0))
                .flex()
                .items_center()
                .justify_end()
                .child(mono(check.when, DIM)),
        )
}

/// A saved comparison draft, openable straight into Compare.
fn draft_row(cx: &mut Context<Kriko>, i: usize) -> Stateful<Div> {
    let open_draft = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        if let Some(draft) = this.compare_drafts.get(i) {
            this.compare_slots = draft.slots.clone();
            this.compare_draft = i;
        }
        this.tab = Tab::Compare;
        cx.notify();
    });
    let draft = &data::COMPARE_DRAFTS[i];
    let subjects: Vec<&str> = draft
        .slots
        .iter()
        .filter_map(|slot| data::CHECKS.get(*slot).map(|check| check.name))
        .collect();
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
                        .child(draft.name.to_string()),
                )
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(MUTED))
                        .child(subjects.join(" · ")),
                ),
        )
        .child(icon("compare", 16.0).text_color(rgb(DIM)))
}

/// The activity graph: one column per month, the bar as tall as the count.
fn checks_graph() -> Div {
    let max = data::HOME_CHECKS_BARS
        .iter()
        .map(|(_, v)| *v)
        .max()
        .unwrap_or(1) as f32;
    let mut cols = div().flex().items_end().gap(px(10.0));
    for (label, value) in data::HOME_CHECKS_BARS {
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
                                .h(px(height))
                                .rounded(px(3.0))
                                .bg(rgb(ICE))
                                .opacity(0.55 + 0.45 * (*value as f32) / max)
                                .shadow(vec![shadow(0xbfe4ff40, 0.0, 0.0, 8.0, 0.0)]),
                        ),
                )
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(DIM))
                        .child(label.to_string()),
                ),
        );
    }
    cols
}

/// The evidence graph: how much of the store is backed, as one meter.
fn claims_graph() -> Div {
    let backed = 1214.0;
    let stored = 1402.0;
    div()
        .flex()
        .flex_col()
        .gap(px(14.0))
        .child(meter(backed / stored * 100.0, 24))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(16.0))
                .font_family(MONO)
                .text_size(px(10.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(6.0))
                        .text_color(rgb(INK_2))
                        .child(div().size(px(6.0)).rounded(px(1.5)).bg(rgb(ICE)))
                        .child("BACKED"),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(6.0))
                        .text_color(rgb(DIM))
                        .child(div().size(px(6.0)).rounded(px(1.5)).bg(rgb(LED_OFF)))
                        .child("STORED, NOT YET"),
                ),
        )
}

/// The reading graph: pages held per site, longest bar on top.
fn sites_graph() -> Div {
    let mut rows: Vec<&data::SiteRow> = data::SITES.iter().collect();
    rows.sort_by(|a, b| b.pages.cmp(&a.pages));
    let max = rows
        .first()
        .map(|site| site.pages)
        .unwrap_or(1) as f32;
    let mut graph = div().flex().flex_col().gap(px(12.0));
    for site in rows.iter().take(4) {
        graph = graph.child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(
                    div()
                        .w(px(120.0))
                        .font_family(MONO)
                        .text_size(px(11.0))
                        .text_color(rgb(MUTED))
                        .child(site.host.to_string()),
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
                                .w(relative(site.pages as f32 / max))
                                .rounded(px(2.0))
                                .bg(rgb(ICE))
                                .opacity(0.8),
                        ),
                )
                .child(
                    div()
                        .w(px(46.0))
                        .flex()
                        .justify_end()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(DIM))
                        .child(format!("{} p", site.pages)),
                ),
        );
    }
    graph
}

pub fn home(_app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let open_history = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::History;
        this.page = 0;
        cx.notify();
    });

    // ---- recent work ----
    let recent_count = 4.min(data::CHECKS.len());
    let mut recent = card().flex().flex_col();
    recent = recent.child(div().mb(px(14.0)).child(eyebrow("Recent work")));
    for (ri, check) in data::CHECKS.iter().take(recent_count).enumerate() {
        let last = ri + 1 == recent_count;
        recent = recent
            .child(recent_row(cx, ri, check))
            .when(!last, |d| d.child(hairline()));
    }
    recent = recent.child(
        div()
            .mt(px(16.0))
            .flex()
            .items_center()
            .justify_end()
            .child(plate_s("home-all", "All history").on_click(open_history)),
    );

    // ---- drafts ----
    let mut drafts = card().flex().flex_col();
    drafts = drafts.child(div().mb(px(14.0)).child(eyebrow("Drafts")));
    for (i, _) in data::COMPARE_DRAFTS.iter().enumerate() {
        let last = i + 1 == data::COMPARE_DRAFTS.len();
        drafts = drafts
            .child(draft_row(cx, i))
            .when(!last, |d| d.child(hairline()));
    }

    // ---- the graphs ----
    let checks_card = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(eyebrow("Checks per month"))
        .child(checks_graph());
    let claims_card = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(eyebrow("Evidence in the store"))
        .child(claims_graph());
    let sites_card = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(eyebrow("Pages held per site"))
        .child(sites_graph());

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
                .child(div().flex_1().min_w(px(300.0)).child(sites_card)),
        )
}
