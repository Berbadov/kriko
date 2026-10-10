//! History: every check you have run, with the evidence it was based on —
//! and the runs, queue-ups and pack builds, each held as its own kind.
//! Search on top with the kind, catalog, date-span and status filters beside
//! it, each a drawer that opens rather than a button that cycles; stats over
//! what the filters admit, the rows in a glass card, pagination underneath.
//! Each check unfolds into a drawer: the claims the check grounded with the
//! sources behind each, and the page it read. Information only — no
//! verdicts, no confidence. Everything here is the engine's own record
//! (`/api/history`, `/api/jobs`, `/api/queue`, `/api/lookup/{id}`).

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, Animation, AnimationExt,
    ClickEvent, Context, Div, FontWeight, Styled, Window,
};

use crate::app::{Field, Kriko, SpanFilter};
use crate::data;
use crate::live::history::{ago, month_buckets, now_secs, ClaimView, Kind};
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

/// A drawer control: one click opens the choices below instead of stepping
/// through them.
pub(crate) fn drawer_ctrl(
    id: impl Into<gpui::ElementId>,
    label: &str,
    value: &str,
    open: bool,
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
        .when(open, |s| s.border_color(rgba(0xffffff40)))
        .child(led_matrix(&QUEUE5, if open { INK_2 } else { LED_DIM }, 3.0, 1.0))
        .child(format!("{label}: "))
        .child(div().text_color(rgb(INK)).child(value.to_string()))
        .child(icon(if open { "collapse" } else { "chevron-down" }, 14.0).text_color(rgb(MUTED)))
}

/// One choice inside an open drawer: a lit mark on the picked one.
pub(crate) fn drawer_option(
    id: impl Into<gpui::ElementId>,
    word: &str,
    chosen: bool,
) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(32.0))
        .px(px(12.0))
        .flex()
        .items_center()
        .gap(px(10.0))
        .rounded(px(8.0))
        .cursor_pointer()
        .hover(|s| s.bg(rgba(GLASS_1)))
        .child(if chosen {
            led_matrix(&CHECK5, INK_2, 3.0, 1.0)
        } else {
            led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0)
        })
        .child(
            div()
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(if chosen { INK } else { INK_2 }))
                .child(word.to_string()),
        )
}

/// One claim of an opened check: its severity and title, then the sources
/// behind it, each with its domain, its stance and the quote it was read from.
fn claim_block(claim: &ClaimView, cx: &mut Context<Kriko>) -> Div {
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
    for (si, src) in claim.sources.iter().take(4).enumerate() {
        let against = src.stance == "refutes";
        let url = src.url.clone();
        let open = cx.listener(move |_, _: &ClickEvent, _w, cx| cx.open_url(&url));
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
                        .child(
                            div()
                                .id(("history-source", si))
                                .cursor_pointer()
                                .hover(|s| s.opacity(0.8))
                                .on_click(open)
                                .child(mono(if src.domain.is_empty() { &src.url } else { &src.domain }, ICE)),
                        )
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

/// The runs, queue-ups and pack builds: one glass card of rows, one state
/// word each, pagination underneath. Same shape as the checks table.
#[allow(clippy::too_many_arguments)]
fn job_kind_page(
    app: &Kriko,
    kind: Kind,
    rows: &[usize],
    page: usize,
    pages: usize,
    total: usize,
    now: i64,
    motion: bool,
    cx: &mut Context<Kriko>,
) -> gpui::Stateful<Div> {
    let what = match kind {
        Kind::Run => "Run",
        Kind::Queue => "Queued product",
        Kind::Build => "Build",
        Kind::Check => "Check",
    };
    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().w(px(28.0)))
                .child(div().flex_1().child(th(what)))
                .child(div().w(px(130.0)).child(th("State")))
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
                    "hist-kind-empty",
                    &QUEUE5,
                    LED_DIM,
                    4.0,
                    2.0,
                    LedAnim::Boot,
                    motion,
                ))
                .child(row_desc("Nothing matches. Clear the search or the filters.")),
        );
    }

    for (ri, &gi) in rows.iter().enumerate() {
        let (title, sub, state_word, ts) = match kind {
            Kind::Queue => {
                let q = &app.live.history.queue[gi];
                let name = if q.name.is_empty() { clip(&q.url, 60) } else { q.name.clone() };
                (
                    name,
                    format!("{} · {}", if q.origin.is_empty() { "queued from the panel" } else { &q.origin }, clip(&q.url, 70)),
                    q.state.to_uppercase(),
                    q.ts,
                )
            }
            _ => {
                let j = &app.live.history.jobs[gi];
                (
                    if j.label.is_empty() { j.kind.clone() } else { j.label.clone() },
                    clip(&j.message, 110),
                    j.state_word().to_string(),
                    j.ts,
                )
            }
        };
        let state_fg = match state_word.as_str() {
            "FAILED" => 0xffb86b,
            "CANCELLED" => MUTED,
            "SUCCEEDED" | "DONE" => INK_2,
            _ => ICE,
        };
        let row = div()
            .flex()
            .items_center()
            .py(px(14.0))
            .child(div().w(px(28.0)))
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
                            .child(title),
                    )
                    .when(!sub.is_empty(), |d| d.child(mono(&sub, MUTED))),
            )
            .child(div().w(px(130.0)).child(mono(&state_word, state_fg)))
            .child(div().w(px(110.0)).child(mono(&ago(ts, now), MUTED)));
        let row: gpui::AnyElement = if motion {
            let delay = ri as f32 * 60.0;
            row.with_animation(
                gpui::ElementId::named_usize(format!("hist-kind-row-in-{page}"), ri),
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

    let prev = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.page = this.page.saturating_sub(1);
        cx.notify();
    });
    let next = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        let now = now_secs();
        let total = this
            .live
            .history
            .rows_now(this.live.history.kind, &this.history_search.value, this.history_span.days(), now)
            .len();
        let pages = if total == 0 {
            1
        } else {
            (total + data::PAGE_SIZE - 1) / data::PAGE_SIZE
        };
        if this.page + 1 < pages {
            this.page += 1;
        }
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
                    plate_s("hist-kind-prev", "Previous")
                        .when(page == 0, |b| b.opacity(0.4))
                        .on_click(prev),
                )
                .child(
                    plate_s("hist-kind-next", "Next")
                        .when(page + 1 >= pages, |b| b.opacity(0.4))
                        .on_click(next),
                ),
        );
    table = table.child(hairline()).child(pagination);

    div()
        .id("hist-kind-scroll")
        .overflow_x_scroll()
        .child(table.min_w(px(640.0)))
}

pub fn history(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let kind = app.live.history.kind;
    if !app.live.history.loaded {
        return div().child(empty_note("Reading your history from the engine."));
    }
    let nothing_here = match kind {
        Kind::Check => app.live.history.items.is_empty(),
        Kind::Queue => app.live.history.queue.is_empty(),
        Kind::Run | Kind::Build => app.live.history.jobs.is_empty(),
    };
    if nothing_here {
        return div().child(empty_note(match kind {
            Kind::Check =>
                "No checks yet. A check you run, or one the browser extension makes, lands here.",
            Kind::Run =>
                "No agent runs yet. A research run, one product at a time, lands here.",
            Kind::Queue =>
                "Nothing queued yet. A product you queue from the browser extension lands here.",
            Kind::Build =>
                "No pack builds yet. A bundle you make from research lands here.",
        }));
    }

    // ---- the controls row: search + the kind, pack, time and status drawers ----
    let drawer = app.live.history.drawer;
    let search = app.input_field(
        Field::HistorySearch,
        "history-search",
        match kind {
            Kind::Check => "Search past checks",
            Kind::Run => "Search runs",
            Kind::Queue => "Search queue-ups",
            Kind::Build => "Search pack builds",
        },
        Some("search"),
        window,
        cx,
    );

    let toggled =
        |open: Option<&'static str>, want: &'static str| -> Option<&'static str> {
            if open == Some(want) { None } else { Some(want) }
        };
    let kind_toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.live.history.drawer = toggled(this.live.history.drawer, "kind");
        cx.notify();
    });
    let pack_toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.live.history.drawer = toggled(this.live.history.drawer, "pack");
        cx.notify();
    });
    let time_toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.live.history.drawer = toggled(this.live.history.drawer, "time");
        cx.notify();
    });
    let status_toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.live.history.drawer = toggled(this.live.history.drawer, "status");
        cx.notify();
    });

    let pack_word = clip(&app.live.history.pack_word(), 26).to_uppercase();
    let status_word = app
        .live
        .history
        .status
        .clone()
        .unwrap_or_else(|| "ALL".to_string());
    let row = div()
        .flex()
        .flex_wrap()
        .items_center()
        .gap(px(12.0))
        .child(div().flex_1().min_w(px(220.0)).child(search))
        .child(
            drawer_ctrl("filter-kind", "KIND", kind.word(), drawer == Some("kind"))
                .on_click(kind_toggle),
        )
        .when(kind == Kind::Check, |r| {
            r.child(
                drawer_ctrl("filter-pack", "PACK", &pack_word, drawer == Some("pack"))
                    .on_click(pack_toggle),
            )
        })
        .child(
            drawer_ctrl("filter-span", "TIME", app.history_span.word(), drawer == Some("time"))
                .on_click(time_toggle),
        )
        .when(kind != Kind::Check, |r| {
            r.child(
                drawer_ctrl("filter-status", "STATUS", &status_word, drawer == Some("status"))
                    .on_click(status_toggle),
            )
        });

    let mut controls = div().mb(px(24.0)).flex().flex_col().gap(px(10.0)).child(row);
    let reset = move |this: &mut Kriko, cx: &mut gpui::Context<Kriko>| {
        this.page = 0;
        this.live.history.open = None;
        this.live.history.detail = None;
        this.live.history.drawer = None;
        cx.notify();
    };
    match drawer {
        Some("kind") => {
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(2.0));
            for (ki, k) in Kind::ALL.into_iter().enumerate() {
                let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.live.history.kind = k;
                    this.live.history.status = None;
                    reset(this, cx);
                });
                panel = panel
                    .child(drawer_option(gpui::ElementId::named_usize("hist-kind", ki), k.word(), kind == k).on_click(pick));
            }
            controls = controls.child(panel);
        }
        Some("pack") if kind == Kind::Check => {
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(2.0));
            let pick_all = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.live.history.pack = None;
                reset(this, cx);
            });
            panel = panel
                .child(drawer_option("hist-pack-all", "ALL", app.live.history.pack.is_none()).on_click(pick_all));
            for (pi, (id, name)) in app.live.history.pack_options().into_iter().enumerate() {
                let chosen = app.live.history.pack.as_deref() == Some(id.as_str());
                let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.live.history.pack = Some(id.clone());
                    reset(this, cx);
                });
                panel = panel
                    .child(drawer_option(gpui::ElementId::named_usize("hist-pack", pi), &name, chosen).on_click(pick));
            }
            controls = controls.child(panel);
        }
        Some("time") => {
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(2.0));
            for (i, s) in [SpanFilter::All, SpanFilter::Month, SpanFilter::Quarter, SpanFilter::Half]
                .into_iter()
                .enumerate()
            {
                let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.history_span = s;
                    reset(this, cx);
                });
                panel = panel
                    .child(drawer_option(gpui::ElementId::named_usize("hist-span", i), s.word(), app.history_span == s).on_click(pick));
            }
            controls = controls.child(panel);
        }
        Some("status") if kind != Kind::Check => {
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(2.0));
            let pick_all = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.live.history.status = None;
                reset(this, cx);
            });
            panel = panel
                .child(drawer_option("hist-status-all", "ALL", app.live.history.status.is_none()).on_click(pick_all));
            let words: Vec<&str> = if kind == Kind::Queue {
                vec!["WAITING", "RESEARCHING", "DONE"]
            } else {
                vec!["RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
            };
            for (si, w) in words.iter().enumerate() {
                let want = w.to_string();
                let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.live.history.status = Some(want.clone());
                    reset(this, cx);
                });
                panel = panel
                    .child(drawer_option(gpui::ElementId::named_usize("hist-status", si + 1), w, app.live.history.status.as_deref() == Some(*w)).on_click(pick));
            }
            controls = controls.child(panel);
        }
        _ => {}
    }

    // ---- filtering ----
    let now = now_secs();
    let query = app.history_search.value.to_lowercase();
    let span: SpanFilter = app.history_span;
    let src = app
        .live
        .history
        .rows_now(kind, &query, span.days(), now);
    let filtered = if kind == Kind::Check { src.clone() } else { Vec::new() };
    let total = src.len();
    let pages = if total == 0 {
        1
    } else {
        (total + data::PAGE_SIZE - 1) / data::PAGE_SIZE
    };
    let page = app.page.min(pages - 1);
    let rows: Vec<usize> = src
        .iter()
        .skip(page * data::PAGE_SIZE)
        .take(data::PAGE_SIZE)
        .copied()
        .collect();

    if kind != Kind::Check {
        return div()
            .flex()
            .flex_col()
            .child(controls)
            .child(job_kind_page(app, kind, &rows, page, pages, total, now, motion, cx));
    }

    // ---- the stats: what the current filters admit ----
    let items = &app.live.history.items;
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
                .child(eyebrow("Checks per month"))
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
                .child(div().flex_1().child(th("Check")))
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
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.toggle_history_open(open_id.clone(), cx);
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
                    .child(mono(&clip(&check.pack_line(), 60), MUTED)),
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
                        let line = claim_block(claim, cx);
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
                        let source_url = detail.url.clone();
                        let open_source = cx.listener(move |_, _: &ClickEvent, _w, cx| cx.open_url(&source_url));
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
                                            .id("history-page-source")
                                            .min_w(px(0.0))
                                            .cursor_pointer()
                                            .font_family(MONO)
                                            .text_size(px(12.0))
                                            .text_color(rgb(ICE))
                                            .child(clip(&detail.url, 90))
                                            .on_click(open_source),
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
    let prev = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.page = this.page.saturating_sub(1);
        this.live.history.open = None;
        this.live.history.detail = None;
        cx.notify();
    });
    let next = cx.listener(move |this, _: &ClickEvent, _w, cx| {
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
                .overflow_x_scroll()
                .child(table.min_w(px(640.0))),
        )
}
