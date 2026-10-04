//! History: every check you have run, with the evidence it was based on.
//! Search on top with the pack and date-span filters beside it, stats over
//! what the filters admit, the runs in a glass card, pagination underneath.
//! Each row unfolds into a drawer: the claims it grounded, the product
//! links it read from, and what it took. Information only — no verdicts,
//! no confidence.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, Animation, AnimationExt,
    ClickEvent, Context, Div, FontWeight, Styled, Window,
};

use crate::app::{Field, Kriko, PackFilter, SpanFilter};
use crate::data;
use crate::screens::{agent_by_monogram, mono, plate_s, row_desc, th};
use crate::theme::*;

/// The indices into CHECKS the current search, pack and span filters
/// admit, newest first.
fn filtered_checks(query: &str, pack: PackFilter, span: SpanFilter) -> Vec<usize> {
    data::CHECKS
        .iter()
        .enumerate()
        .filter(|(_, c)| {
            let ok_query = query.is_empty()
                || c.name.to_lowercase().contains(query)
                || c.pack.to_lowercase().contains(query);
            let ok_pack = match pack {
                PackFilter::All => true,
                PackFilter::Samsung => c.pack.starts_with("samsung"),
                PackFilter::Apple => c.pack.starts_with("apple"),
                PackFilter::Volkswagen => c.pack.starts_with("volkswagen"),
            };
            let ok_span = c.days_ago <= span.days();
            ok_query && ok_pack && ok_span
        })
        .map(|(i, _)| i)
        .collect()
}

/// The links a check read its product from: the review site and the
/// maker's page, built from the product's own name.
fn product_links(check: &data::Check) -> Vec<String> {
    let mut parts = check.name.split_whitespace();
    let brand = parts.next().unwrap_or("maker").to_lowercase();
    let slug = parts.collect::<Vec<_>>().join("-").to_lowercase();
    let review = if data::is_car(check) {
        "edmunds.com"
    } else {
        "rtings.com"
    };
    vec![
        format!("{review}/{brand}/{slug}"),
        format!("{brand}.com/{slug}"),
    ]
}

/// A cycling mono control: one click advances to the next value.
fn cycle_ctrl(id: &'static str, label: &str, value: &str) -> gpui::Stateful<Div> {
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

pub fn history(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;

    // ---- the controls row: search + the pack and date-span filters ----
    let search = app.input_field(
        Field::HistorySearch,
        "history-search",
        "Search past checks",
        Some("search"),
        window,
        cx,
    );

    let pack_next = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.pack_filter = this.pack_filter.next();
        this.page = 0;
        this.history_open = None;
        cx.notify();
    });
    let span_next = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.history_span = this.history_span.next();
        this.page = 0;
        this.history_open = None;
        cx.notify();
    });

    let controls = div()
        .flex()
        .flex_wrap()
        .items_center()
        .gap(px(12.0))
        .mb(px(24.0))
        .child(div().flex_1().min_w(px(220.0)).child(search))
        .child(
            cycle_ctrl("filter-pack", "PACK", app.pack_filter.word()).on_click(pack_next),
        )
        .child(
            cycle_ctrl("filter-span", "TIME", app.history_span.word()).on_click(span_next),
        );

    // ---- filtering ----
    let query = app.history_search.value.to_lowercase();
    let pack = app.pack_filter;
    let span = app.history_span;
    let filtered = filtered_checks(&query, pack, span);
    let total = filtered.len();
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
    let mut buckets = [0u32; 6];
    for &i in &filtered {
        let b = (data::CHECKS[i].days_ago / 30).min(5) as usize;
        buckets[5 - b] += 1; // index 0 is the oldest month, 5 is now
    }
    let bar_max = buckets.iter().copied().max().unwrap_or(1).max(1) as f32;
    let bar_labels = ["5 m", "4 m", "3 m", "2 m", "1 m", "now"];
    // the bars regrow whenever the filters change: the id carries them, so
    // a new pack or span remounts the graph and the animation replays
    let bar_anim_id = format!("hist-bar-{}-{}", pack.word(), span.word());
    let mut bars = div().flex().items_end().gap(px(10.0)).h(px(96.0));
    for bi in 0..6 {
        let value = buckets[bi];
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
                        .child(bar_labels[bi]),
                ),
        );
    }

    let packs_touched = {
        let mut packs: Vec<&str> = Vec::new();
        for &i in &filtered {
            let p = data::CHECKS[i].pack;
            if !packs.contains(&p) {
                packs.push(p);
            }
        }
        packs.len()
    };
    let packs_all = {
        let mut packs: Vec<&str> = Vec::new();
        for c in data::CHECKS {
            if !packs.contains(&c.pack) {
                packs.push(c.pack);
            }
        }
        packs.len().max(1)
    };
    let claims_grounded: usize = filtered
        .iter()
        .map(|&i| data::evidence_for(&data::CHECKS[i]).claims.len())
        .sum();
    let claims_all: usize = data::CHECKS
        .iter()
        .map(|c| data::evidence_for(c).claims.len())
        .sum::<usize>()
        .max(1);

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
    // header
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().w(px(28.0)))
                .child(div().flex_1().child(th("Check")))
                .child(div().w(px(108.0)).child(th("Agents")))
                .child(div().w(px(120.0)).child(th("Took")))
                .child(div().w(px(100.0)).child(th("When"))),
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

    for (ri, &gi) in rows.iter().enumerate() {
        let check = &data::CHECKS[gi];
        let open = app.history_open == Some(gi);
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.history_open = if this.history_open == Some(gi) {
                None
            } else {
                Some(gi)
            };
            cx.notify();
        });
        let mut agent_tiles = div().w(px(108.0)).flex().items_center().gap(px(6.0));
        for m in check.agents {
            agent_tiles = agent_tiles.child(agent_by_monogram(*m));
        }
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
                            .child(check.name.to_string()),
                    )
                    .child(mono(check.pack, MUTED)),
            )
            .child(agent_tiles)
            .child(div().w(px(120.0)).child(mono(check.took, INK_2)))
            .child(div().w(px(100.0)).child(mono(check.when, MUTED)));

        let mut row = div().flex().flex_col().child(columns);
        if open {
            // the drawer: the claims, then the links, then what it took.
            // Everything inside settles in one item after another.
            let ev = data::evidence_for(check);
            let mut panel = well()
                .mt(px(2.0))
                .mb(px(6.0))
                .p(px(16.0))
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(eyebrow("Evidence"));
            let mut item = 0usize;
            for (claim, source) in ev.claims {
                let line = div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(led_matrix(&CHECK5, INK_2, 3.0, 1.0))
                    .child(
                        div()
                            .flex_1()
                            .min_w(px(0.0))
                            .font_family(SANS)
                            .text_size(px(13.0))
                            .text_color(rgb(INK_2))
                            .child(claim.to_string()),
                    )
                    .child(mono(source, DIM));
                let line: gpui::AnyElement = if motion {
                    let delay = 120.0 + item as f32 * 90.0;
                    item += 1;
                    line.with_animation(
                        gpui::ElementId::named_usize(format!("hist-claim-{gi}"), item),
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
            panel = panel.child(hairline()).child(eyebrow("Product links"));
            for link in product_links(check) {
                let line = div()
                    .flex()
                    .items_center()
                    .gap(px(10.0))
                    .child(icon("arrow-right", 12.0).text_color(rgb(MUTED)))
                    .child(
                        div()
                            .font_family(MONO)
                            .text_size(px(12.0))
                            .text_color(rgb(ICE))
                            .child(link),
                    );
                let line: gpui::AnyElement = if motion {
                    let delay = 120.0 + item as f32 * 90.0;
                    item += 1;
                    line.with_animation(
                        gpui::ElementId::named_usize(format!("hist-link-{gi}"), item),
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
            panel = panel.child(
                div()
                    .pt(px(2.0))
                    .font_family(MONO)
                    .text_size(px(11.0))
                    .text_color(rgb(MUTED))
                    .child(format!(
                        "{} agents took part · took {} · stored to {}",
                        check.agents.len(),
                        check.took,
                        check.pack
                    )),
            );
            row = row.child(panel);
        }

        // the rows cascade in whenever the page or the filters change;
        // opening a drawer does not replay it (the ids hold steady)
        let row: gpui::AnyElement = if motion {
            let delay = ri as f32 * 60.0;
            row.with_animation(
                gpui::ElementId::named_usize(
                    format!("hist-row-in-{page}-{}-{}", pack.word(), span.word()),
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
        this.history_open = None;
        cx.notify();
    });
    let next = cx.listener(|this, _: &ClickEvent, _w, cx| {
        // clamp here too, so the page counter never runs past the last page
        let query = this.history_search.value.to_lowercase();
        let total = filtered_checks(&query, this.pack_filter, this.history_span).len();
        let pages = if total == 0 {
            1
        } else {
            (total + data::PAGE_SIZE - 1) / data::PAGE_SIZE
        };
        if this.page + 1 < pages {
            this.page += 1;
        }
        this.history_open = None;
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
