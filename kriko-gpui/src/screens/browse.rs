//! Browse: every subject in the local store, one row each, and the evidence
//! drawer for the picked one on the right: its attributes, its claims, and
//! the sources for and against. Search and the filters go to the engine
//! (`/api/subjects`, `/api/subjects/filters`); the drawer reads
//! `/api/subjects/{id}` and `/api/health/subject/{id}`.

use gpui::{div, prelude::*, px, rgb, rgba, ClickEvent, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::live::history::{Evidence, State, Subject};
use crate::screens::history::{clip, severity_word_chip};
use crate::screens::run::option_chip;
use crate::screens::{empty_note, filter_btn, mono, plate_s, segmented, th};
use crate::theme::*;

/// The evidence drawer's width, one column beside the table.
const DRAWER_W: f32 = 320.0;

fn section_title(label: &str) -> Div {
    div()
        .font_family(DISPLAY)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(18.0))
        .text_color(rgb(BRAND_BRIGHT))
        .child(label.to_uppercase())
}

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
    let mut col = div()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(section_title(title));
    if rows.is_empty() {
        return col.child(
            div()
                .font_family(SANS)
                .text_size(px(14.0))
                .text_color(rgb(INK_2))
                .child("None stored"),
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
        return pick("Select a subject to inspect it.");
    };
    let Some(detail) = h.subject_detail.as_ref().filter(|d| d.id == sel) else {
        return pick("Loading subject…");
    };
    let mut d = card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(section_title("Subject"))
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
        d = d.child(hairline()).child(section_title("Details"));
        for a in detail.attrs.iter().take(10) {
            d = d.child(
                div()
                    .flex()
                    .items_start()
                    .justify_between()
                    .gap(px(8.0))
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
    d = d.child(hairline()).child(section_title("Claims"));
    if detail.claims.is_empty() {
        d = d.child(mono("No claims yet", MUTED));
    }
    for c in detail.claims.iter().take(6) {
        d = d.child(
            div()
                .flex()
                .items_start()
                .gap(px(6.0))
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
                        .child(mono(
                            &if c.via.is_empty() {
                                c.domain.clone()
                            } else {
                                format!("{} · through {}", c.domain, clip(&c.via, 48))
                            },
                            DIM,
                        )),
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
    d
}

pub fn browse(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
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
    let filters_open = app.browse_filters_open && !filters.is_empty();
    let filter_label = if active_filters == 0 {
        "Filters".to_string()
    } else {
        format!("Filters · {active_filters}")
    };
    let filter_button = filter_btn("browse-filter-toggle", &filter_label, filters_open, true)
        .on_click(toggle_filters);
    let close_filters = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.browse_filters_open = false;
        cx.notify();
    });
    let mut filter_drawer = card().flex().flex_col().gap(px(8.0)).child(
        div()
            .flex()
            .items_center()
            .justify_between()
            .child(eyebrow("FILTER BY"))
            .child(
                filter_btn("browse-filter-close", "Close", false, false).on_click(close_filters),
            ),
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
        // the label keeps a fixed column; the chips wrap inside the rest, so a
        // second line of chips starts under the first chip, not under the label
        let mut row = div().flex().items_center().gap(px(8.0));
        row = row.child(div().flex_none().w(px(120.0)).child(eyebrow(&filter.label)));
        let mut chips = div()
            .flex()
            .flex_wrap()
            .gap(px(8.0))
            .flex_1()
            .min_w(px(0.0));
        for (choice, label) in choices {
            let is_selected = selected == choice;
            let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.pick_browse_filter(i, choice, cx);
            });
            let control = option_chip(
                gpui::ElementId::named_usize(format!("browse-filter-{i}"), choice),
                &label,
                is_selected,
            )
            .on_click(pick);
            chips = chips.child(control);
        }
        row = row.child(chips);
        filter_drawer = filter_drawer.child(row);
    }
    if active_filters > 0 {
        let clear = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.clear_browse_filters(cx);
        });
        filter_drawer = filter_drawer.child(div().flex().child(
            filter_btn("browse-filter-clear", "Clear filters", false, false).on_click(clear),
        ));
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
        .gap(px(8.0))
        .flex_wrap()
        .child(div().flex_1().min_w(px(280.0)).child(search))
        .child(filter_button)
        .child(view_switch);

    if !app.live.history.subjects_loaded {
        return div()
            .flex()
            .flex_col()
            .gap(px(SPACE_SECTION))
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
                .child(mono(
                    if !app.browse_search.value.trim().is_empty() || active_filters > 0 {
                        "No matching subjects"
                    } else if app.live.knowledge.totals.subjects == 0 {
                        "No subjects yet · install a catalog on Overview"
                    } else {
                        "No subjects to show"
                    },
                    MUTED,
                )),
        );
    }

    for (ri, row) in rows.iter().enumerate() {
        let sel = is_sel(row);
        // a 1px border on every row, lit only when picked: a picked row keeps
        // the same inner edge as the others, so its cells do not jump
        let r = div()
            .id(("browse-row", ri))
            .flex()
            .items_center()
            .py(px(12.0))
            .cursor_pointer()
            .hover(|s| s.bg(rgba(GLASS_1)))
            .border_1()
            .border_color(rgba(if sel { BORDER_CONTROL } else { 0x00000000 }))
            .when(sel, |s| s.bg(rgba(BRAND_WASH)))
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
                            .truncate()
                            .child(row.label.clone()),
                    )
                    .child(mono(&clip(&pack_name(h, &row.pack_id), 50), MUTED)),
            )
            .child(div().w(px(130.0)).child(mono(&row.kind, INK_2).truncate()))
            .child(div().w(px(100.0)).child(mono(&row.claims.to_string(), INK)));
        table = table.child(r);
        if ri + 1 < rows.len() {
            table = table.child(hairline());
        }
    }

    // Side by side when the page has room for the table (at least 520 px)
    // beside the drawer (DRAWER_W, SPACE_SECTION apart). Narrower, the drawer
    // stacks under the table at the page's full width: it is never cut off at
    // the edge, and nothing needs a sideways scroll to be reached.
    let side_by_side = app.content_w >= 864.0;

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
                        .gap(px(SPACE_CARD))
                        .py(px(4.0))
                        // card()'s inner edge: the highlight reaches it, and the
                        // text keeps the card's text edge
                        .px(px(PAD_CARD + 2.0))
                        .mx(px(-(PAD_CARD + 2.0)))
                        .rounded(px(10.0))
                        .cursor_pointer()
                        .hover(|s| s.bg(rgba(GLASS_1)))
                        .when(sel, |s| s.bg(rgba(BRAND_WASH)))
                        .on_click(click_for!(cx, row))
                        .child(
                            mono(&clip(&row.label, 40), if sel { ICE } else { INK })
                                .min_w(px(0.0))
                                .truncate(),
                        )
                        .child(div().w(px(8.0)))
                        .child(mono(&row.kind, MUTED).flex_none())
                        .child(div().flex_1().min_w(px(0.0)))
                        .child(mono(&format!("{} claims", row.claims), INK_2).flex_none()),
                );
            }
            list.into_any_element()
        }
        2 => {
            // grid: subject tiles in the shared grid, so the columns fill the
            // width the list has (the drawer keeps its own column beside it)
            let width = if side_by_side {
                app.content_w - DRAWER_W - SPACE_SECTION
            } else {
                app.content_w
            };
            let mut tiles: Vec<Div> = Vec::new();
            for (ri, row) in rows.iter().enumerate() {
                let sel = is_sel(row);
                tiles.push(
                    div().flex().child(
                        div()
                            .id(("browse-grid-tile", ri))
                            .flex_1()
                            .cursor_pointer()
                            .when(sel, |s| {
                                s.bg(rgba(BRAND_WASH))
                                    .border_1()
                                    .border_color(rgba(BORDER_CONTROL))
                            })
                            .when(!sel, |s| {
                                s.bg(rgba(GLASS_1)).border_1().border_color(rgba(HAIRLINE))
                            })
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
                    ),
                );
            }
            grid(width, 210.0, tiles).into_any_element()
        }
        _ => div()
            .id("browse-table-scroll")
            .overflow_x_scroll()
            .map(horizontal_wheel)
            .child(table.min_w(px(520.0)))
            .into_any_element(),
    };

    let page_size = app.browse_page_size.max(1);
    let page_count = h.subjects_total.div_ceil(page_size).max(1);
    let page = app.browse_page.min(page_count - 1);
    let page_start = if h.subjects_total == 0 {
        0
    } else {
        page * page_size + 1
    };
    let page_end = (page * page_size + rows.len()).min(h.subjects_total);
    let page_summary = if h.subjects_total == 0 {
        "0 subjects".to_string()
    } else {
        format!("{page_start}–{page_end} of {}", h.subjects_total)
    };
    let previous = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.browse_page_changed(
            this.browse_page.saturating_sub(1),
            this.browse_page_size,
            cx,
        );
    });
    let next = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.browse_page_changed(this.browse_page + 1, this.browse_page_size, cx);
    });
    let mut page_sizes = div().flex().items_center().gap(px(6.0));
    page_sizes = page_sizes.child(mono("PER PAGE", MUTED));
    for size in [10usize, 25, 50, 100] {
        let pick_size = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.browse_page_changed(0, size, cx);
        });
        let button = plate_s(
            gpui::ElementId::named_usize("browse-page-size", size),
            &size.to_string(),
        )
        .when(size == page_size, |button| {
            button
                .bg(rgba(BRAND_WASH))
                .text_color(rgb(BRAND_BRIGHT))
                .border_color(rgb(BRAND))
        })
        .on_click(pick_size);
        page_sizes = page_sizes.child(button);
    }
    // the controls take the rest of the row and sit at its end; on a line of
    // their own (a narrow list) they still end at the list's right edge
    let pagination = div()
        .flex()
        .items_center()
        .flex_wrap()
        .gap(px(8.0))
        .child(mono(&page_summary, MUTED))
        .child(
            div()
                .flex()
                .flex_grow()
                .justify_end()
                .items_center()
                .flex_wrap()
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

    // The paging belongs to the list, so it sits under the list's own column
    // and shares the list's edges, not the drawer's.
    let column = div()
        .flex()
        .flex_col()
        .gap(px(SPACE_SECTION))
        .child(body)
        .child(pagination);
    let picked = if side_by_side {
        div()
            .flex()
            .gap(px(SPACE_SECTION))
            .items_start()
            .child(div().flex_1().min_w(px(0.0)).child(column))
            .child(div().w(px(DRAWER_W)).flex_none().child(drawer))
    } else {
        div()
            .flex()
            .flex_col()
            .gap(px(SPACE_SECTION))
            .child(div().w_full().min_w(px(0.0)).child(column))
            .child(div().w_full().child(drawer))
    };

    div()
        .flex()
        .flex_col()
        .gap(px(SPACE_SECTION))
        .child(head)
        // always mounted so it can slide. A closed panel is zero-high but still
        // sits between two page gaps, so the negative top margin takes one back;
        // open, its top padding is that same gap.
        .child(div().mt(px(-SPACE_SECTION)).child(reveal(
            div().pt(px(SPACE_SECTION)).child(if filters_open {
                filter_drawer.into_any_element()
            } else {
                div().into_any_element()
            }),
            "browse-filters-reveal",
            filters_open,
            900.0,
            motion,
        )))
        .child(picked)
}
