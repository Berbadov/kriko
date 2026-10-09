//! History: every check you have run, with the evidence it was based on.
//! Search on top with the catalog and date-span filters beside it, stats over
//! what the filters admit, the runs in a glass card, pagination underneath.
//! Each row unfolds into a drawer: the claims the check grounded with the
//! sources behind each, and the page it read. Information only — no
//! verdicts, no confidence. Everything here is the engine's own record
//! (`/api/history`, `/api/lookup/{id}`).

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, Animation, AnimationExt,
    ClickEvent, Context, Div, FontWeight, Styled, Window,
};

use crate::app::{Field, Kriko, SpanFilter};
use crate::data;
use crate::live::history::{ago, month_buckets, now_secs, ClaimView};
use crate::screens::{empty_note, mono, plate_s, row_desc, th};
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

/// A cycling mono control: one click advances to the next value.
pub(crate) fn cycle_ctrl(
    id: impl Into<gpui::ElementId>,
    label: &str,
    value: &str,
) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(44.0))
        .px(px(16.0))
        .flex()
        .items_center()
        .justify_center()
        .gap(px(10.0))
        .rounded(px(12.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .text_color(rgb(INK_2))
        .cursor_pointer()
        .border_1()
        .border_color(rgb(BEZEL_EDGE))
        .bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BEZEL_HI), 0.0),
            linear_color_stop(hsla(BEZEL_LO), 1.0),
        ))
        .shadow(vec![shadow(0x00000099, 0.0, 6.0, 16.0, 0.0)])
        .hover(|s| s.text_color(rgb(INK)))
        .child(led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0))
        .child(format!("{label}: "))
        .child(div().text_color(rgb(INK)).child(value.to_string()))
        .child(icon("chevron-down", 14.0).text_color(rgb(MUTED)))
}

/// One claim of an opened check: its severity and title, then the sources
/// behind it, each with its domain, its stance and the quote it was read from.
fn claim_block(claim: &ClaimView) -> Div {
    let mut block = div().flex().flex_col().gap(px(6.0)).child(
        div()
            .flex()
            .items_start()
            .gap(px(12.0))
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
                        .gap(px(10.0))
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
    let motion = !app.reduce_motion;
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

    let mut controls = div().flex().flex_col().gap(px(12.0)).mb(px(24.0));
    let mut bar = div().flex().flex_wrap().items_center().gap(px(10.0))
        .child(div().flex_1().min_w(px(220.0)).child(search));
    let filters = [
        ("pack", format!("Pack · {}", app.live.history.pack_word())),
        ("time", format!("Date · {}", app.history_span.word())),
        ("kind", format!("Kind · {}", if app.live.history.record_kind.is_empty() { "All" } else { &app.live.history.record_kind })),
        ("status", format!("Status · {}", if app.live.history.record_status.is_empty() { "All" } else { &app.live.history.record_status })),
    ];
    for (i, (field, label)) in filters.iter().enumerate() {
        let field = field.to_string();
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.live.history.filter_open = if this.live.history.filter_open.as_deref() == Some(&field) { None } else { Some(field.clone()) };
            cx.notify();
        });
        bar = bar.child(plate_s(("history-filter", i), label).on_click(toggle));
    }
    let clear = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.live.history.pack = None;
        this.live.history.record_kind.clear(); this.live.history.record_status.clear();
        this.history_span = SpanFilter::All; this.history_search.set_value(String::new()); this.page = 0;
        cx.notify();
    });
    controls = controls.child(bar.child(plate_s("history-filter-reset", "Reset filters").on_click(clear)));
    if let Some(field) = app.live.history.filter_open.clone() {
        let mut choices: Vec<(String, String)> = vec![(String::new(), "All".into())];
        match field.as_str() {
            "pack" => choices.extend(app.live.history.pack_options()),
            "time" => choices = vec![("0".into(), "All time".into()), ("1".into(), "Past month".into()), ("2".into(), "Past quarter".into()), ("3".into(), "Past six months".into())],
            "kind" => choices.extend([("check", "Checks"), ("run", "Agent runs"), ("queue", "Queue-ups"), ("pack_build", "Pack builds")].map(|(v,l)| (v.into(),l.into()))),
            "status" => choices.extend(["queued", "running", "succeeded", "failed", "cancelled", "interrupted", "waiting", "researching", "done", "removed"].map(|v| (v.into(),v.into()))),
            _ => {}
        }
        let mut drawer = card().flex().flex_col().gap(px(10.0)).child(eyebrow(&format!("Choose {field}")));
        let mut options = div().flex().flex_wrap().gap(px(8.0));
        for (i, (value, label)) in choices.iter().enumerate() {
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
            options = options.child(plate_s(("history-filter-option",i),label).on_click(pick));
        }
        drawer = drawer.child(options).child(plate_s("history-filter-close", "Close").on_click(cx.listener(|this, _: &ClickEvent, _w, cx| { this.live.history.filter_open = None; cx.notify(); })));
        controls = controls.child(drawer);
    }

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
    let mut bars = div().flex().items_end().gap(px(10.0)).h(px(96.0));
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
                .gap(px(10.0))
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
                .child(div().w(px(120.0)).child(th("Claims")))
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
                .child(row_desc("No check matches. Clear the search or the filters.")),
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
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            if let Some(job_id) = open_id.strip_prefix("job:") {
                this.live.run.pinned = Some(job_id.to_string()); this.tab = crate::app::Tab::Run; this.refresh_jobs(cx);
            } else if kind == "check" { this.toggle_history_open(open_id.clone(), cx); }
            cx.notify();
        });
        let columns = div()
            .id(gpui::ElementId::named_usize("hist-row", gi))
            .flex()
            .items_center()
            .py(px(14.0))
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
                    .child(mono(&format!("{} · {} · {} {}", check.kind, check.status, clip(&check.pack_line(), 60), check.agent), MUTED)),
            )
            .child(div().w(px(120.0)).child(mono(&format!("{} claims", check.claims), INK_2)))
            .child(div().w(px(110.0)).child(mono(&ago(check.ts, now), MUTED)));

        let mut row = div().flex().flex_col().child(columns);
        if open {
            // the drawer: the claims with their sources, then the page read.
            let mut panel = well()
                .mt(px(2.0))
                .mb(px(6.0))
                .p(px(16.0))
                .flex()
                .flex_col()
                .gap(px(10.0))
                .child(eyebrow("Evidence"));
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
                                    .gap(px(10.0))
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
                    .gap(px(12.0))
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
    let pagination = div()
        .mt(px(16.0))
        .pt(px(16.0))
        .flex()
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
                .gap(px(12.0))
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
                .overflow_x_scroll().occlude()
                .child(table.min_w(px(640.0))),
        )
}
