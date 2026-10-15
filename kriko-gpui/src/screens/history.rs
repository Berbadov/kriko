//! History: every check you have run, with the evidence it was based on.
//! Search on top with the catalog and date-span filters beside it, stats over
//! what the filters admit, the runs in a glass card, pagination underneath.
//! Each row unfolds into a drawer: the claims the check grounded with the
//! sources behind each, and the page it read. Information only — no
//! verdicts, no confidence. Everything here is the engine's own record
//! (`/api/history`, `/api/lookup/{id}`).

use gpui::{
    div, prelude::*, px, rgb, rgba, Animation, AnimationExt,
    ClickEvent, Context, Div, FontWeight, Styled, Window,
};

use crate::app::{Field, Kriko, SpanFilter};
use crate::data;
use crate::live::history::{ago, month_buckets, now_secs, ClaimView};
use crate::screens::run::{option_chip, quick_look_result_card};
use crate::screens::{empty_note, filter_btn, mono, plate_s, row_desc, th};
use crate::theme::*;

/// `text` on one line, cut to `n` characters with an ellipsis when longer.
pub(crate) fn clip(text: &str, n: usize) -> String {
    let flat = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= n {
        return flat;
    }
    let mut out: String = flat.chars().take(n).collect();
    out.push('…');
    out
}

/// The engine's own severity word in its own tint: the hot ones run warm,
/// the rest sit quiet. Whatever word the catalog used is the word shown.
pub(crate) fn severity_word_chip(word: &str) -> Div {
    let (glyph, fg, bg): (&[&str], u32, u32) = match word {
        "critical" => (&X5, DANGER, DANGER_WASH),
        "high" | "serious" => (&BANG5, 0xffb86b, 0xffb86b1f),
        _ => (&QUEUE5, MUTED, WELL),
    };
    div()
        .h(px(24.0))
        .px(px(8.0))
        .flex()
        .flex_none()
        .items_center()
        .gap(px(7.0))
        .rounded(px(7.0))
        .bg(rgb(bg))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .font_family(MONO)
        .text_size(px(10.0))
        .text_color(rgb(fg))
        .child(led_matrix(glyph, fg, 3.0, 1.0))
        .child(if word.is_empty() {
            "NOTED".to_string()
        } else {
            word.to_uppercase()
        })
}

/// One claim of an opened check: its severity and title, then the sources
/// behind it, each with its domain, its stance and the quote it was read from.
fn claim_block(claim: &ClaimView) -> Div {
    let mut block = div().flex().flex_col().gap(px(6.0)).child(
        div()
            .flex()
            .items_start()
            .gap(px(8.0))
            .child(div().pt(px(2.0)).child(led_matrix(&CHECK5, INK_2, 3.0, 1.0)))
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .font_family(SANS)
                    .text_size(px(13.0))
                    .text_color(rgb(INK_2))
                    .child(claim.title.clone()),
            )
            .child(severity_word_chip(&claim.severity)),
    );
    if claim.sources.is_empty() {
        block = block.child(
            div()
                .pl(px(24.0))
                .child(mono("No source stored behind this one yet.", DIM)),
        );
    }
    for src in claim.sources.iter().take(4) {
        let against = src.stance == "refutes";
        block = block.child(
            div()
                .pl(px(24.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(6.0))
                        .child(mono(
                            if src.domain.is_empty() { &src.url } else { &src.domain },
                            ICE,
                        ))
                        .child(mono(
                            if against { "AGAINST" } else { "FOR" },
                            if against { 0xffb86b } else { MUTED },
                        )),
                )
                .when(!src.quote.is_empty(), |d| {
                    d.child(
                        div()
                            .font_family(SANS)
                            .text_size(px(12.0))
                            .text_color(rgb(MUTED))
                            .child(format!("“{}”", clip(&src.quote, 260))),
                    )
                }),
        );
    }
    block
}

pub fn history(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    if !app.live.history.loaded {
        return div().child(empty_note("Reading your history from the engine."));
    }

    // ---- the controls row: search + the catalog and date-span filters ----
    let search = app.input_field(
        Field::HistorySearch,
        "history-search",
        "Search past checks",
        Some("search"),
        window,
        cx,
    );

    let mut controls = div().flex().flex_col().mb(px(24.0));
    let mut bar = div().flex().flex_wrap().items_center().gap(px(6.0)).pb(px(12.0))
        .child(div().flex_1().min_w(px(220.0)).child(search));
    let open_field = app.live.history.filter_open.clone();
    let filters = [
        ("pack", format!("Pack · {}", app.live.history.pack_word())),
        ("time", format!("Date · {}", app.history_span.word())),
        ("kind", format!("Kind · {}", if app.live.history.record_kind.is_empty() { "All" } else { &app.live.history.record_kind })),
        ("status", format!("Status · {}", if app.live.history.record_status.is_empty() { "All" } else { &app.live.history.record_status })),
    ];
    for (i, (field, label)) in filters.iter().enumerate() {
        let is_open = open_field.as_deref() == Some(*field);
        let field = field.to_string();
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.live.history.filter_open = if this.live.history.filter_open.as_deref() == Some(&field) { None } else { Some(field.clone()) };
            cx.notify();
        });
        bar = bar.child(filter_btn(("history-filter", i), label, is_open, true).on_click(toggle));
    }
    let clear = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.live.history.pack = None;
        this.live.history.record_kind.clear(); this.live.history.record_status.clear();
        this.history_span = SpanFilter::All; this.history_search.set_value(String::new()); this.page = 0;
        cx.notify();
    });
    controls = controls.child(bar.child(filter_btn("history-filter-reset", "Reset filters", false, false).on_click(clear)));
    // The panel is always mounted so it can slide open; closed, it is empty.
    let mut panel = div().flex().flex_col().pb(px(12.0));
    if let Some(field) = open_field.clone() {
        let current: String = match field.as_str() {
            "pack" => app.live.history.pack.clone().unwrap_or_default(),
            "time" => match app.history_span { SpanFilter::All => "0", SpanFilter::Month => "1", SpanFilter::Quarter => "2", SpanFilter::Half => "3" }.to_string(),
            "kind" => app.live.history.record_kind.clone(),
            "status" => app.live.history.record_status.clone(),
            _ => String::new(),
        };
        let mut choices: Vec<(String, String)> = vec![(String::new(), "All".into())];
        match field.as_str() {
            "pack" => choices.extend(app.live.history.pack_options()),
            "time" => choices = vec![("0".into(), "All time".into()), ("1".into(), "Past month".into()), ("2".into(), "Past quarter".into()), ("3".into(), "Past six months".into())],
            "kind" => choices.extend([("check", "Checks"), ("run", "Agent runs"), ("queue", "Queue-ups"), ("pack_build", "Pack builds")].map(|(v,l)| (v.into(),l.into()))),
            "status" => choices.extend(["queued", "running", "succeeded", "failed", "cancelled", "interrupted", "waiting", "researching", "done", "removed"].map(|v| (v.into(),v.into()))),
            _ => {}
        }
        let title = match field.as_str() { "pack" => "pack", "time" => "date", "kind" => "kind", _ => "status" };
        let close = cx.listener(|this, _: &ClickEvent, _w, cx| { this.live.history.filter_open = None; cx.notify(); });
        let drawer = card().flex().flex_col().gap(px(SPACE_CARD)).child(
            div().flex().items_center().justify_between()
                .child(eyebrow(&format!("Filter by {title}")))
                .child(filter_btn("history-filter-close", "Close", false, false).on_click(close)),
        );
        let mut options = div().flex().flex_wrap().gap(px(8.0));
        for (i, (value, label)) in choices.iter().enumerate() {
            let picked = *value == current;
            let value = value.clone(); let field = field.clone();
            let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                match field.as_str() {
                    "pack" => this.live.history.pack = if value.is_empty() { None } else { Some(value.clone()) },
                    "time" => this.history_span = match value.as_str() { "1" => SpanFilter::Month, "2" => SpanFilter::Quarter, "3" => SpanFilter::Half, _ => SpanFilter::All },
                    "kind" => this.live.history.record_kind = value.clone(),
                    "status" => this.live.history.record_status = value.clone(), _ => {}
                }
                this.page = 0; this.live.history.filter_open = None; this.live.history.open = None; cx.notify();
            });
            options = options.child(option_chip(("history-filter-option", i), label, picked).on_click(pick));
        }
        panel = panel.child(drawer.child(options));
    }
    controls = controls.child(reveal(panel, "history-filter-reveal", open_field.is_some(), 520.0, motion));

    // ---- filtering ----
    let now = now_secs();
    let query = app.history_search.value.to_lowercase();
    let span: SpanFilter = app.history_span;
    let filtered = app.live.history.filtered(&query, span.days(), now);
    let total = filtered.len();
    controls = controls.child(mono(&format!("{total} matching records"), MUTED));
    let pages = if total == 0 {
        1
    } else {
        (total + data::PAGE_SIZE - 1) / data::PAGE_SIZE
    };
    if let Some(id) = app.history_focus.clone() {
        if let Some(at) = filtered.iter().position(|&i| app.live.history.history_rows()[i].id == id) {
            app.page = at / data::PAGE_SIZE;
            app.history_focus = None;
        }
    }
    let page = app.page.min(pages - 1);
    let rows: Vec<usize> = filtered
        .iter()
        .skip(page * data::PAGE_SIZE)
        .take(data::PAGE_SIZE)
        .copied()
        .collect();

    // ---- the stats: what the current filters admit ----
    let items = app.live.history.history_rows();
    let months = month_buckets(filtered.iter().filter_map(|&i| items[i].ts), now, 6);
    let bar_max = months.iter().map(|(_, c)| *c).max().unwrap_or(1).max(1) as f32;
    // the bars regrow whenever the filters change: the id carries them, so
    // a new catalog or span remounts the graph and the animation replays
    let bar_anim_id = format!(
        "hist-bar-{}-{}",
        app.live.history.pack.as_deref().unwrap_or("all"),
        span.word()
    );
    let mut bars = div().flex().items_end().gap(px(6.0)).h(px(96.0));
    for (bi, (label, value)) in months.iter().enumerate() {
        let value = *value;
        let height = if value == 0 {
            3.0
        } else {
            8.0 + 64.0 * (value as f32) / bar_max
        };
        let opacity = if value == 0 {
            0.15
        } else {
            0.55 + 0.45 * (value as f32) / bar_max
        };
        let bar = div()
            .w_full()
            .h(px(height))
            .rounded(px(3.0))
            .bg(rgb(ICE))
            .opacity(opacity)
            .shadow(vec![shadow(0xbfe4ff40, 0.0, 0.0, 8.0, 0.0)]);
        // each bar rises a beat after the one before it, from the baseline
        let bar: gpui::AnyElement = if motion {
            let delay = bi as f32 * 90.0;
            bar.with_animation(
                gpui::ElementId::named_usize(bar_anim_id.clone(), bi),
                Animation::new(std::time::Duration::from_millis(1200)).with_easing(move |t| {
                    let local = ((t * 1200.0 - delay) / 700.0).clamp(0.0, 1.0);
                    1.0 - (1.0 - local).powi(3)
                }),
                move |el, v| el.h(px(3.0 + (height - 3.0) * v)),
            )
            .into_any_element()
        } else {
            bar.into_any_element()
        };
        bars = bars.child(
            div()
                .flex_1()
                .flex()
                .flex_col()
                .items_center()
                .gap(px(6.0))
                .child(
                    div()
                        .w_full()
                        .max_w(px(24.0))
                        .flex()
                        .flex_col()
                        .justify_end()
                        .h(px(84.0))
                        .child(bar),
                )
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(MUTED))
                        .child(label.clone()),
                ),
        );
    }

    let distinct_packs = |idx: &mut dyn Iterator<Item = usize>| -> usize {
        let mut seen: Vec<&str> = Vec::new();
        for i in idx {
            for p in &items[i].packs {
                if !seen.contains(&p.0.as_str()) {
                    seen.push(p.0.as_str());
                }
            }
        }
        seen.len()
    };
    let packs_touched = distinct_packs(&mut filtered.iter().copied());
    let packs_all = distinct_packs(&mut (0..items.len())).max(1);
    let claims_grounded: usize = filtered.iter().map(|&i| items[i].claims).sum();
    let claims_all: usize = items.iter().map(|c| c.claims).sum::<usize>().max(1);

    let stat = |label: &str,
                value: String,
                meter_id: &'static str,
                pct: f32,
                delay: f32|
     -> gpui::AnyElement {
        let body = div()
            .w(px(150.0))
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(eyebrow(label))
            .child(
                div()
                    .font_family(MONO)
                    .text_size(px(22.0))
                    .text_color(rgb(INK))
                    .child(value),
            )
            .child(meter_live(meter_id, pct, 12, false, motion));
        // the numbers settle in after the bars, one after the other
        if motion {
            body.with_animation(
                gpui::ElementId::named_usize("hist-stat-in", delay as usize),
                Animation::new(std::time::Duration::from_millis(900)).with_easing(move |t| {
                    let local = ((t * 900.0 - delay) / 500.0).clamp(0.0, 1.0);
                    1.0 - (1.0 - local).powi(3)
                }),
                |el, v| el.opacity(v),
            )
            .into_any_element()
        } else {
            body.into_any_element()
        }
    };

    let stats = card()
        .flex()
        .flex_wrap()
        .gap(px(28.0))
        .mb(px(24.0))
        .child(
            div()
                .flex_1()
                .min_w(px(240.0))
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(eyebrow("Records per month"))
                .child(bars),
        )
        .child(stat(
            "Packs touched",
            packs_touched.to_string(),
            "hist-stats-packs",
            packs_touched as f32 / packs_all as f32 * 100.0,
            550.0,
        ))
        .child(stat(
            "Claims grounded",
            claims_grounded.to_string(),
            "hist-stats-claims",
            claims_grounded as f32 / claims_all as f32 * 100.0,
            700.0,
        ));

    // ---- the table card ----
    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().w(px(28.0)))
                .child(div().flex_1().child(th("Record")))
                .child(div().w(px(120.0)).child(th("Findings")))
                .child(div().w(px(110.0)).child(th("When"))),
        )
        .child(hairline());

    if rows.is_empty() {
        table = table.child(
            div()
                .py(px(48.0))
                .flex()
                .flex_col()
                .items_center()
                .gap(px(8.0))
                .child(led_matrix_anim(
                    "hist-empty",
                    &QUEUE5,
                    LED_DIM,
                    4.0,
                    2.0,
                    LedAnim::Boot,
                    motion,
                ))
                .child(row_desc(if app.live.history.history_rows().is_empty() {
                    "No checks yet. A listing you check from the browser extension shows up here."
                } else {
                    "No check matches. Clear the search or the filters."
                })),
        );
    }

    let pack_key = app
        .live
        .history
        .pack
        .clone()
        .unwrap_or_else(|| "all".to_string());
    for (ri, &gi) in rows.iter().enumerate() {
        let check = &items[gi];
        let open = app.live.history.open.as_deref() == Some(check.id.as_str());
        let open_id = check.id.clone();
        let kind = check.kind.clone();
        let source = check.source.clone();
        let kind_label: &str = if source == "quick_look" { "Quick Look" } else { check.kind.as_str() };
        let count_label = if source == "quick_look" {
            format!("{} sourced risks", check.claims)
        } else {
            format!("{} claims", check.claims)
        };
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            if source == "quick_look" {
                this.toggle_history_open(open_id.clone(), cx);
            } else if let Some(job_id) = open_id.strip_prefix("job:") {
                this.live.run.pinned = Some(job_id.to_string()); this.tab = crate::app::Tab::Run; this.refresh_jobs(cx);
            } else if kind == "check" { this.toggle_history_open(open_id.clone(), cx); }
            cx.notify();
        });
        let columns = div()
            .id(gpui::ElementId::named_usize("hist-row", gi))
            .flex()
            .items_center()
            .py(px(4.0))
            .cursor_pointer()
            .hover(|s| s.bg(rgba(GLASS_1)))
            .on_click(toggle)
            .child(
                div().w(px(28.0)).flex_none().child(
                    icon(if open { "collapse" } else { "expand" }, 14.0).text_color(rgb(MUTED)),
                ),
            )
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
                    .child(mono(&format!("{} · {} · {} {}", kind_label, check.status, clip(&check.pack_line(), 60), check.agent), MUTED)),
            )
            .child(div().w(px(120.0)).child(mono(&count_label, INK_2)))
            .child(div().w(px(110.0)).child(mono(&ago(check.ts, now), MUTED)));

        let mut row = div().flex().flex_col().child(columns);
        if open {
            // A Quick Look has a separate, explicit catalog-assignment flow.
            let mut panel = well()
                .mt(px(2.0))
                .mb(px(6.0))
                .p(px(16.0))
                .flex()
                .flex_col()
                .gap(px(6.0));
            if check.source == "quick_look" {
                match &app.live.history.quick_look_detail {
                    Some(detail) if detail.id == check.id => {
                        if let Some(result) = quick_look_result_card(
                            &detail.result, &detail.product, &detail.state,
                        ) {
                            panel = panel.child(result);
                        } else {
                            panel = panel.child(mono("No saved result was returned for this Quick Look.", MUTED));
                        }
                    }
                    _ if app.live.history.quick_look_loading => {
                        panel = panel.child(mono("Reading the saved Quick Look result.", MUTED));
                    }
                    _ if app.live.history.quick_look_error.is_some() => {
                        panel = panel.child(row_desc(app.live.history.quick_look_error.as_deref().unwrap_or("Could not read the saved Quick Look.")));
                    }
                    _ => panel = panel.child(mono("Reading the saved Quick Look result.", MUTED)),
                }
                panel = panel.child(eyebrow("Catalog assignment"));
                let assignment = check.categorization.as_ref();
                let assigned = assignment.is_some_and(|one| one.status == "assigned");
                let busy = app.live.history.categorizing.as_deref() == Some(check.id.as_str());
                let message = assignment
                    .map(|one| one.message.as_str())
                    .filter(|text| !text.is_empty())
                    .or_else(|| {
                        app.live.history.categorization_message.as_deref()
                            .filter(|_| busy)
                    });
                let catalog_name = assignment
                    .map(|one| one.pack_name.as_str())
                    .filter(|name| !name.is_empty())
                    .unwrap_or_else(|| check.category.as_str());
                let mut status = callout()
                    .child(div().flex().flex_col().gap(px(5.0))
                        .child(eyebrow(if assigned { "Assigned" } else { "Needs a catalog" }))
                        .child(div().font_family(SANS).font_weight(FontWeight::SEMIBOLD)
                            .text_size(px(14.0)).text_color(rgb(INK))
                            .child(if assigned && !catalog_name.is_empty() {
                                catalog_name.to_string()
                            } else if !assigned {
                                "No catalog was selected automatically".to_string()
                            } else {
                                "Catalog assignment saved".to_string()
                            }))
                        .child(mono(message.unwrap_or(if assigned {
                            "The assignment is grounded in the saved product details and installed catalog definitions."
                        } else {
                            "This look remains saved. Choose an installed catalog or ask the configured agent to match it."
                        }), MUTED)));
                if assigned {
                    if let Some(one) = assignment {
                        let route = match one.method.as_str() {
                            "reader" => "Chosen by you".to_string(),
                            "agent" => "Matched by configured agent".to_string(),
                            _ => "Matched from saved category".to_string(),
                        };
                        status = status.child(mono(&route, INK_2));
                    }
                }
                panel = panel.child(status);

                if !assigned {
                    let quick_id = check.id.clone();
                    let run_agent = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                        this.categorize_saved_look(quick_id.clone(), cx);
                    });
                    panel = panel.child(
                        div().flex().flex_wrap().items_center().gap(px(6.0))
                            .child(key(
                                gpui::ElementId::named_usize("hist-categorize", gi),
                                if busy { "Categorising…" } else { "Categorise with agent" },
                            ).when(!busy, |button| button.on_click(run_agent)))
                            .child(mono(
                                "Uses this saved look and installed definitions; it does not research the product again.",
                                MUTED,
                            )),
                    );
                }

                let picker_open = app.live.history.category_picker.as_deref() == Some(check.id.as_str());
                let pick_id = check.id.clone();
                let toggle_picker = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    let history = &mut this.live.history;
                    history.category_picker = if history.category_picker.as_deref() == Some(pick_id.as_str()) {
                        None
                    } else {
                        Some(pick_id.clone())
                    };
                    cx.notify();
                });
                panel = panel.child(
                    ghost(
                        gpui::ElementId::named_usize("hist-pick-category", gi),
                        if picker_open { "Close catalog choices" } else { "Choose a catalog" },
                    ).on_click(toggle_picker),
                );
                if picker_open {
                    if app.live.history.categorization_catalogs.is_empty() {
                        panel = panel.child(mono("No installed catalogs are available yet.", MUTED));
                    } else {
                        panel = panel.child(eyebrow("Installed catalogs"));
                        for (ci, catalog) in app.live.history.categorization_catalogs.iter().enumerate() {
                            let id = catalog.pack_id.clone();
                            let label = catalog.name.clone();
                            let current = assignment.is_some_and(|one| one.status == "assigned" && one.pack_id == id);
                            let enabled = catalog.enabled;
                            let editable = catalog.editable;
                            let lookup_id = check.id.clone();
                            let choose = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                                this.choose_saved_look_category(lookup_id.clone(), id.clone(), cx);
                            });
                            panel = panel.child(
                                div().flex().flex_wrap().items_center().justify_between().gap(px(8.0))
                                    .py(px(4.0))
                                    .child(div().flex().flex_col().gap(px(2.0))
                                        .child(div().font_family(SANS).text_size(px(13.0))
                                            .text_color(rgb(INK_2)).child(label.clone()))
                                        .child(mono(&format!("{} · {}", if enabled { "enabled" } else { "disabled" },
                                            if editable { "harvest target" } else { "read-only catalog" }), MUTED)))
                                    .child(ghost(
                                        gpui::ElementId::named_usize(format!("hist-catalog-{gi}"), ci),
                                        if current { "Current catalog" } else { "Assign" },
                                    ).when(!busy && !current, |button| button.on_click(choose))),
                            );
                        }
                    }
                }
                if !check.packs.is_empty() {
                    panel = panel.child(hairline()).child(mono(&format!("Saved catalog · {}", clip(&check.pack_line(), 72)), INK_2));
                }
            } else {
                // the drawer: the claims with their sources, then the page read.
                panel = panel.child(eyebrow("Evidence"));
                match &app.live.history.detail {
                    Some(detail) if detail.id == check.id => {
                        if detail.claims.is_empty() {
                            panel = panel.child(mono("This check grounded no claim.", MUTED));
                        }
                        for (item, claim) in detail.claims.iter().enumerate() {
                            let line = claim_block(claim);
                            let line: gpui::AnyElement = if motion {
                                let delay = 120.0 + item.min(8) as f32 * 90.0;
                                line.with_animation(
                                    gpui::ElementId::named_usize(format!("hist-claim-{}", check.id), item),
                                    Animation::new(std::time::Duration::from_millis(800)).with_easing(
                                        move |t| {
                                            let local = ((t * 800.0 - delay) / 450.0).clamp(0.0, 1.0);
                                            1.0 - (1.0 - local).powi(3)
                                        },
                                    ),
                                    |el, v| el.opacity(v),
                                )
                                .into_any_element()
                            } else {
                                line.into_any_element()
                            };
                            panel = panel.child(line);
                        }
                        if !detail.url.is_empty() {
                            panel = panel
                                .child(hairline())
                                .child(eyebrow("Read from"))
                                .child(
                                    div()
                                        .flex()
                                        .items_center()
                                        .gap(px(6.0))
                                        .child(icon("arrow-right", 12.0).text_color(rgb(MUTED)))
                                        .child(
                                            div()
                                                .min_w(px(0.0))
                                                .font_family(MONO)
                                                .text_size(px(12.0))
                                                .text_color(rgb(ICE))
                                                .child(clip(&detail.url, 90)),
                                        ),
                                );
                        }
                    }
                    _ => {
                        panel = panel.child(mono("Reading this check from the store.", MUTED));
                    }
                }
                let armed = app.live.history.forget_armed.as_deref() == Some(check.id.as_str());
                let forget_id = check.id.clone();
                let forget = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.forget_check(forget_id.clone(), cx);
                });
                panel = panel.child(hairline()).child(
                    div()
                        .flex()
                        .items_center()
                        .justify_between()
                        .gap(px(8.0))
                        .child(
                            div()
                                .font_family(MONO)
                                .text_size(px(11.0))
                                .text_color(rgb(MUTED))
                                .child(format!(
                                    "{} claims · from {} · stored to {}",
                                    check.claims,
                                    if check.source.is_empty() { "the app" } else { &check.source },
                                    clip(&check.pack_line(), 50),
                                )),
                        )
                        .child(
                            danger(
                                gpui::ElementId::named_usize("hist-forget", gi),
                                if armed { "Press again to forget" } else { "Forget" },
                            )
                            .on_click(forget),
                        ),
                );
            }
            row = row.child(panel);
        }

        // the rows cascade in whenever the page or the filters change;
        // opening a drawer does not replay it (the ids hold steady)
        let row: gpui::AnyElement = if motion {
            let delay = ri as f32 * 60.0;
            row.with_animation(
                gpui::ElementId::named_usize(
                    format!("hist-row-in-{page}-{pack_key}-{}", span.word()),
                    ri,
                ),
                Animation::new(std::time::Duration::from_millis(900)).with_easing(move |t| {
                    let local = ((t * 900.0 - delay) / 600.0).clamp(0.0, 1.0);
                    1.0 - (1.0 - local).powi(3)
                }),
                |el, v| el.opacity(v),
            )
            .into_any_element()
        } else {
            row.into_any_element()
        };
        table = table.child(row);
        if ri + 1 < rows.len() {
            table = table.child(hairline());
        }
    }

    // ---- pagination ----
    let prev = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.page = this.page.saturating_sub(1);
        this.live.history.open = None;
        this.live.history.detail = None;
        cx.notify();
    });
    let next = cx.listener(|this, _: &ClickEvent, _w, cx| {
        // clamp here too, so the page counter never runs past the last page
        let total = this
            .live
            .history
            .filtered(&this.history_search.value, this.history_span.days(), now_secs())
            .len();
        let pages = if total == 0 {
            1
        } else {
            (total + data::PAGE_SIZE - 1) / data::PAGE_SIZE
        };
        if this.page + 1 < pages {
            this.page += 1;
        }
        this.live.history.open = None;
        this.live.history.detail = None;
        cx.notify();
    });
    let shown = rows.len();
    let count_text = if shown <= 1 {
        format!("{} of {} · newest first", shown, total)
    } else {
        format!(
            "{}-{} of {} · newest first",
            page * data::PAGE_SIZE + 1,
            page * data::PAGE_SIZE + shown,
            total
        )
    };
    // Wraps under the count when the card is narrow, so Next is never cut off.
    let pagination = div()
        .mt(px(16.0))
        .pt(px(16.0))
        .flex()
        .flex_wrap()
        .gap(px(8.0))
        .items_center()
        .justify_between()
        .child(
            div()
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(MUTED))
                .child(count_text),
        )
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(
                    plate_s("hist-prev", "Previous")
                        .when(page == 0, |b| b.opacity(0.4))
                        .on_click(prev),
                )
                .child(
                    plate_s("hist-next", "Next")
                        .when(page + 1 >= pages, |b| b.opacity(0.4))
                        .on_click(next),
                ),
        );

    table = table.child(hairline()).child(pagination);

    div()
        .flex()
        .flex_col()
        .child(controls)
        .child(stats)
        .child(
            div()
                .id("hist-table-scroll")
                .overflow_x_scroll().map(horizontal_wheel)
                .child(table.min_w(px(640.0))),
        )
}
