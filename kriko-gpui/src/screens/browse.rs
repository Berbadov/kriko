//! Browse: every subject in the local store, one row each, and the evidence
//! drawer for the picked one on the right: its attributes, its claims, and
//! the sources for and against. Search and the filters go to the engine
//! (`/api/subjects`, `/api/subjects/filters`); the drawer reads
//! `/api/subjects/{id}` and `/api/health/subject/{id}`.

use gpui::{div, prelude::*, px, rgb, rgba, ClickEvent, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::live::history::{Evidence, State, Subject};
use crate::screens::history::{clip, severity_word_chip};
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

    // ---- explicit filters in a collapsible drawer ----
    let filters = app.live.history.filters.clone();
    let picks = app.live.history.filter_pick.clone();
    let active_filters = picks.iter().filter(|pick| **pick > 0).count();
    let toggle_filters = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.browse_filters_open = !this.browse_filters_open;
        cx.notify();
    });
    let filter_button = plate_s(
        "browse-filter-toggle",
        &format!("Filters · {active_filters} active"),
    )
    .on_click(toggle_filters);
    let close_filters = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.browse_filters_open = false;
        cx.notify();
    });
    let mut filter_drawer = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(eyebrow("Browse filters"))
                .child(plate_s("browse-filter-close", "Close").on_click(close_filters)),
        );
    for (i, filter) in filters.iter().enumerate() {
        let selected = picks.get(i).copied().unwrap_or(0);
        let mut choices = vec![(0, "All".to_string())];
        choices.extend(
            filter
                .options
                .iter()
                .enumerate()
                .map(|(option, (_, label))| (option + 1, label.clone())),
        );
        let mut row = div().flex().items_center().flex_wrap().gap(px(8.0));
        row = row.child(div().w(px(120.0)).child(eyebrow(&filter.label)));
        for (choice, label) in choices {
            let is_selected = selected == choice;
            let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.pick_browse_filter(i, choice, cx);
            });
            let control = plate_s(
                gpui::ElementId::named_usize(format!("browse-filter-{i}"), choice),
                &label,
            )
            .when(is_selected, |button| {
                button.bg(rgb(WELL)).text_color(rgb(ICE)).border_color(rgb(ICE))
            })
            .on_click(pick);
            row = row.child(control);
        }
        filter_drawer = filter_drawer.child(row);
    }
    if active_filters > 0 {
        let clear = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.clear_browse_filters(cx);
        });
        filter_drawer = filter_drawer.child(plate_s("browse-filter-clear", "Clear filters").on_click(clear));
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
        .child(filter_button)
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

    let page_size = app.browse_page_size.max(1);
    let page_count = h.subjects_total.div_ceil(page_size).max(1);
    let page = app.browse_page.min(page_count - 1);
    let page_start = if h.subjects_total == 0 { 0 } else { page * page_size + 1 };
    let page_end = (page * page_size + rows.len()).min(h.subjects_total);
    let page_summary = if h.subjects_total == 0 {
        "0 subjects".to_string()
    } else {
        format!(
            "Showing {page_start}–{page_end} of {} · page {} of {page_count}",
            h.subjects_total,
            page + 1
        )
    };
    let previous = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.browse_page_changed(this.browse_page.saturating_sub(1), this.browse_page_size, cx);
    });
    let next = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.browse_page_changed(this.browse_page + 1, this.browse_page_size, cx);
    });
    let mut page_sizes = div().flex().items_center().gap(px(6.0));
    page_sizes = page_sizes.child(mono("ROWS", MUTED));
    for size in [10usize, 25, 50, 100] {
        let pick_size = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.browse_page_changed(0, size, cx);
        });
        let button = plate_s(gpui::ElementId::named_usize("browse-page-size", size), &size.to_string())
            .when(size == page_size, |button| {
                button.bg(rgb(WELL)).text_color(rgb(ICE)).border_color(rgb(ICE))
            })
            .on_click(pick_size);
        page_sizes = page_sizes.child(button);
    }
    let pagination = div()
        .flex()
        .items_center()
        .justify_between()
        .flex_wrap()
        .gap(px(12.0))
        .child(mono(&page_summary, MUTED))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(page_sizes)
                .child(
                    plate_s("browse-page-previous", "Previous")
                        .when(page == 0, |button| button.opacity(0.4))
                        .on_click(previous),
                )
                .child(
                    plate_s("browse-page-next", "Next")
                        .when(page + 1 >= page_count, |button| button.opacity(0.4))
                        .on_click(next),
                ),
        );

    let drawer = drawer(app, motion);

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(head)
        .when(app.browse_filters_open && !filters.is_empty(), |d| d.child(filter_drawer))
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
                        .child(div().flex_1().min_w(px(0.0)).child(body))
                        .child(div().w(px(320.0)).flex_none().child(drawer)),
                ),
        )
        .child(pagination)
}
