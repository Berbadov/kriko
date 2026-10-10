//! Browse: every subject in the local store, one row each, and the evidence
//! drawer for the picked one on the right: its attributes, its claims, and
//! the sources for and against. Search and the filters go to the engine
//! (`/api/subjects`, `/api/subjects/filters`); the drawer reads
//! `/api/subjects/{id}` and `/api/health/subject/{id}`.

use gpui::{div, prelude::*, px, rgb, rgba, ClickEvent, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::live::history::{Evidence, State, Subject};
use crate::screens::history::{clip, drawer_ctrl, drawer_option, severity_word_chip};
use crate::screens::{empty_note, mono, plate_s, segmented, th};
use crate::theme::*;

/// A catalog's name, from the filter options the engine sent; its id when
/// the options do not list it.
fn pack_name(h: &State, id: &str) -> String {
    h.filters
        .iter()
        .find(|f| f.param == "pack_id")
        .and_then(|f| f.options.iter().find(|(v, _)| v == id))
        .map(|(_, label)| label.clone())
        .unwrap_or_else(|| id.to_string())
}

/// The evidence on one side of the drawer: up to four quotes with their
/// domains, or the line saying the side is empty.
fn side(title: &str, rows: &[&Evidence]) -> Div {
    let mut col = div().flex().flex_col().gap(px(6.0)).child(eyebrow(title));
    if rows.is_empty() {
        return col.child(
            div()
                .font_family(SANS)
                .text_size(px(14.0))
                .text_color(rgb(INK_2))
                .child("Nothing stored on this side yet."),
        );
    }
    for e in rows.iter().take(4) {
        col = col.child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(mono(&e.domain, ICE))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(INK_2))
                        .child(format!("“{}”", clip(&e.quote, 180))),
                )
                .child(mono(&clip(&e.claim, 60), DIM)),
        );
    }
    if rows.len() > 4 {
        col = col.child(mono(&format!("and {} more", rows.len() - 4), DIM));
    }
    col
}

fn drawer(app: &Kriko, motion: bool) -> Div {
    let _ = motion;
    let h = &app.live.history;
    let pick = |note: &str| {
        card()
            .flex()
            .flex_col()
            .items_center()
            .gap(px(8.0))
            .py(px(32.0))
            .child(led_matrix(&QUEUE5, LED_DIM, 4.0, 2.0))
            .child(mono(note, MUTED))
    };
    let Some(sel) = h.subject_sel.as_deref() else {
        return pick("Pick a row to read its evidence.");
    };
    let Some(detail) = h.subject_detail.as_ref().filter(|d| d.id == sel) else {
        return pick("Reading this subject from the store.");
    };
    let mut d = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Evidence"))
        .child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::SEMIBOLD)
                .text_size(px(16.0))
                .text_color(rgb(INK))
                .child(detail.label.clone()),
        )
        .child(mono(&detail.kind, MUTED));
    if !detail.attrs.is_empty() {
        d = d.child(hairline()).child(eyebrow("Attributes"));
        for a in detail.attrs.iter().take(10) {
            d = d.child(
                div()
                    .flex()
                    .items_start()
                    .justify_between()
                    .gap(px(12.0))
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(13.0))
                            .text_color(rgb(MUTED))
                            .child(a.label.clone()),
                    )
                    .child(
                        div()
                            .min_w(px(0.0))
                            .font_family(MONO)
                            .text_size(px(12.0))
                            .text_color(rgb(ICE))
                            .child(clip(&a.value, 40)),
                    ),
            );
        }
    }
    d = d.child(hairline()).child(eyebrow("Claims"));
    if detail.claims.is_empty() {
        d = d.child(mono("No claim is stored for this subject.", MUTED));
    }
    for c in detail.claims.iter().take(6) {
        d = d.child(
            div()
                .flex()
                .items_start()
                .gap(px(10.0))
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
                                .text_size(px(13.0))
                                .text_color(rgb(INK_2))
                                .child(clip(&c.title, 110)),
                        )
                        .child(mono(&c.domain, DIM)),
                )
                .child(severity_word_chip(&c.severity)),
        );
    }
    if detail.claims.len() > 6 {
        d = d.child(mono(&format!("and {} more", detail.claims.len() - 6), DIM));
    }
    d = d.child(hairline());
    match &h.subject_evidence {
        Some(all) => {
            let for_: Vec<&Evidence> = all.iter().filter(|e| !e.refutes).collect();
            let against: Vec<&Evidence> = all.iter().filter(|e| e.refutes).collect();
            d = d.child(side("For", &for_)).child(side("Against", &against));
        }
        None => d = d.child(mono("Reading the sources.", MUTED)),
    }
    d.child(hairline())
        .child(mono("Settled runs keep the evidence with the claim, not the source page.", DIM))
}

pub fn browse(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let search = app.input_field(
        Field::BrowseSearch,
        "browse-search",
        "Search knowledge",
        Some("search"),
        window,
        cx,
    );

    // ---- the filters, as the engine describes them, each a drawer ----
    let mut filter_row = div().flex().items_center().gap(px(12.0)).flex_wrap();
    {
        let h = &app.live.history;
        for (i, f) in h.filters.iter().enumerate() {
            let pick = h.filter_pick.get(i).copied().unwrap_or(0);
            let word = if pick == 0 {
                "ALL".to_string()
            } else {
                clip(&f.options[pick - 1].1, 22).to_uppercase()
            };
            let open = h.filter_drawer == Some(i);
            let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.open_browse_filter(i, cx);
            });
            filter_row = filter_row.child(
                drawer_ctrl(gpui::ElementId::named_usize("browse-filter", i), &f.label.to_uppercase(), &word, open)
                    .on_click(toggle),
            );
        }
    }
    let mut filters_col = div().flex().flex_col().gap(px(10.0)).child(filter_row);
    if let Some(i) = app.live.history.filter_drawer {
        if let Some(f) = app.live.history.filters.get(i) {
            let picked = app.live.history.filter_pick.get(i).copied().unwrap_or(0);
            let mut panel = well().p(px(8.0)).flex().flex_col().gap(px(2.0));
            let pick_all = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.pick_browse_filter(i, 0, cx);
            });
            panel = panel
                .child(drawer_option(gpui::ElementId::named_usize("browse-filter-all", i), "ALL", picked == 0).on_click(pick_all));
            for (oi, (_, label)) in f.options.iter().enumerate() {
                let want = oi + 1;
                let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.pick_browse_filter(i, want, cx);
                });
                panel = panel
                    .child(drawer_option(gpui::ElementId::named_usize("browse-filter-opt", i * 1000 + oi), label, picked == want).on_click(pick));
            }
            filters_col = filters_col.child(panel);
        }
    }

    let view_switch = segmented(
        "browse-view",
        &[("cols", COLS5), ("list", LIST5), ("grid", GRID5)],
        app.browse_view,
        app.browse_view_prev,
        motion,
        cx,
        |this, i, cx| {
            this.browse_view_prev = this.browse_view;
            this.browse_view = i;
            cx.notify();
        },
    );

    let head = div()
        .flex()
        .items_center()
        .gap(px(16.0))
        .flex_wrap()
        .child(div().flex_1().min_w(px(280.0)).child(search))
        .child(view_switch);

    if !app.live.history.subjects_loaded {
        return div()
            .flex()
            .flex_col()
            .gap(px(24.0))
            .child(head)
            .child(empty_note("Reading the subjects from the store."));
    }

    let h = &app.live.history;
    let rows: Vec<&Subject> = h.subjects.iter().collect();
    let selected = h.subject_sel.clone();
    let is_sel = |s: &Subject| selected.as_deref() == Some(s.id.as_str());
    macro_rules! click_for {
        ($cx:expr, $s:expr) => {{
            let id = $s.id.clone();
            $cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.select_subject(id.clone(), cx);
            })
        }};
    }

    // ---- the table: one row per subject ----
    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().child(th("Subject")))
                .child(div().w(px(130.0)).child(th("Kind")))
                .child(div().w(px(100.0)).child(th("Claims"))),
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
                .child(led_matrix(&QUEUE5, LED_DIM, 4.0, 2.0))
                .child(mono("Nothing matches this search.", MUTED)),
        );
    }

    for (ri, row) in rows.iter().enumerate() {
        let sel = is_sel(row);
        let r = div()
            .id(("browse-row", ri))
            .flex()
            .items_center()
            .py(px(12.0))
            .cursor_pointer()
            .hover(|s| s.bg(rgba(GLASS_1)))
            .when(sel, |s| s.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE)))
            .on_click(click_for!(cx, row))
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
                            .text_color(rgb(if sel { ICE } else { INK }))
                            .child(row.label.clone()),
                    )
                    .child(mono(&clip(&pack_name(h, &row.pack_id), 50), MUTED)),
            )
            .child(div().w(px(130.0)).child(mono(&row.kind, INK_2)))
            .child(div().w(px(100.0)).child(mono(&format!("{} claims", row.claims), INK)));
        table = table.child(r);
        if ri + 1 < rows.len() {
            table = table.child(hairline());
        }
    }

    // ---- the picked view ----
    let body: gpui::AnyElement = match app.browse_view {
        1 => {
            // list: one line per subject, dense
            let mut list = card().flex().flex_col();
            for (ri, row) in rows.iter().enumerate() {
                let sel = is_sel(row);
                list = list.child(
                    div()
                        .id(("browse-list-row", ri))
                        .flex()
                        .items_center()
                        .gap(px(14.0))
                        .py(px(10.0))
                        .px(px(16.0))
                        .mx(px(-16.0))
                        .rounded(px(10.0))
                        .cursor_pointer()
                        .hover(|s| s.bg(rgba(GLASS_1)))
                        .when(sel, |s| s.bg(rgb(WELL)))
                        .on_click(click_for!(cx, row))
                        .child(mono(&clip(&row.label, 40), if sel { ICE } else { INK }))
                        .child(div().w(px(8.0)))
                        .child(mono(&row.kind, MUTED))
                        .child(div().flex_1().min_w(px(0.0)))
                        .child(mono(&format!("{} claims", row.claims), INK_2)),
                );
            }
            list.into_any_element()
        }
        2 => {
            // grid: subject tiles
            let mut grid = div().flex().flex_wrap().gap(px(16.0));
            for (ri, row) in rows.iter().enumerate() {
                let sel = is_sel(row);
                grid = grid.child(
                    div()
                        .id(("browse-grid-tile", ri))
                        .w(px(210.0))
                        .cursor_pointer()
                        .when(sel, |s| s.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE)))
                        .when(!sel, |s| s.bg(rgba(GLASS_1)).border_1().border_color(rgba(HAIRLINE)))
                        .hover(|s| s.bg(rgb(WELL)))
                        .rounded(px(12.0))
                        .p(px(16.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .on_click(click_for!(cx, row))
                        .child(
                            div()
                                .font_family(SANS)
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_size(px(15.0))
                                .text_color(rgb(if sel { ICE } else { INK }))
                                .child(row.label.clone()),
                        )
                        .child(mono(&row.kind, MUTED))
                        .child(
                            div()
                                .font_family(MONO)
                                .text_size(px(13.0))
                                .text_color(rgb(ICE))
                                .child(format!("{} claims", row.claims)),
                        ),
                );
            }
            div().child(grid).into_any_element()
        }
        _ => div()
            .id("browse-table-scroll")
            .overflow_x_scroll()
            .child(table.min_w(px(520.0)))
            .into_any_element(),
    };

    let drawer = drawer(app, motion);

    let total = app.live.history.subjects_total.max(0) as usize;
    let page = app.browse_page;
    let pages = if total == 0 {
        1
    } else {
        (total + crate::data::BROWSE_PAGE_SIZE - 1) / crate::data::BROWSE_PAGE_SIZE
    };
    let shown = rows.len();
    let count_text = if shown <= 1 {
        format!("{} of {} · best evidence first", shown, total)
    } else {
        format!(
            "{}-{} of {} · best evidence first",
            page * crate::data::BROWSE_PAGE_SIZE + 1,
            page * crate::data::BROWSE_PAGE_SIZE + shown,
            total
        )
    };
    let prev = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.turn_browse_page(-1, cx);
    });
    let next = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.turn_browse_page(1, cx);
    });
    let pagination = div()
        .mt(px(16.0))
        .pt(px(16.0))
        .flex()
        .items_center()
        .justify_between()
        .when(total > 0, |d| {
            d.child(
                div()
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(rgb(MUTED))
                    .child(count_text),
            )
        })
        .when(total > 0, |d| {
            d.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(
                        plate_s("browse-prev", "Previous")
                            .when(page == 0, |b| b.opacity(0.4))
                            .on_click(prev),
                    )
                    .child(
                        plate_s("browse-next", "Next")
                            .when(page + 1 >= pages, |b| b.opacity(0.4))
                            .on_click(next),
                    ),
            )
        });

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(head)
        .when(!app.live.history.filters.is_empty(), |d| d.child(filters_col))
        .child(
            div()
                .id("browse-row-scroll")
                .overflow_x_scroll()
                .child(
                    div()
                        .flex()
                        .gap(px(24.0))
                        .items_start()
                        .min_w(px(904.0))
                        .child(
                            div()
                                .flex_1()
                                .min_w(px(0.0))
                                .flex()
                                .flex_col()
                                .child(body)
                                .child(pagination),
                        )
                        .child(div().w(px(320.0)).flex_none().child(drawer)),
                ),
        )
}
