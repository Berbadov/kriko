//! Browse: every subject, attribute and claim in the local store.
//! A table on the left, the evidence drawer for the picked row on the right,
//! with evidence on both sides.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data;
use crate::screens::{mono, segmented, th};
use crate::theme::*;

pub fn browse(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let search = app.input_field(Field::BrowseSearch, "browse-search", "Search knowledge", Some("search"), window, cx);

    let query = app.browse_search.value.to_lowercase();
    let rows: Vec<&data::KnowledgeRow> = data::KNOWLEDGE
        .iter()
        .filter(|r| {
            query.is_empty()
                || r.subject.to_lowercase().contains(&query)
                || r.attribute.to_lowercase().contains(&query)
                || r.value.to_lowercase().contains(&query)
        })
        .collect();

    // keep the selection inside the filtered list
    let selected = app.browse_selected.min(rows.len().saturating_sub(1));
    let picked = rows.get(selected);

    // ---- the table ----
    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().child(th("Subject")))
                .child(div().w(px(180.0)).child(th("Attribute")))
                .child(div().w(px(150.0)).child(th("Value")))
                .child(div().w(px(120.0)).child(th("Trust"))),
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
        let is_selected = ri == selected;
        let click = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.browse_selected = ri;
            cx.notify();
        });
        let r = div()
            .id(("browse-row", ri))
            .flex()
            .items_center()
            .py(px(12.0))
            .cursor_pointer()
            .hover(|s| s.bg(rgba(GLASS_1)))
            .when(is_selected, |s| {
                s.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE))
            })
            .on_click(click)
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
                            .text_color(rgb(if is_selected { ICE } else { INK }))
                            .child(row.subject.to_string()),
                    )
                    .child(mono(&format!("{} claims · {} sources", row.claims, row.sources), MUTED)),
            )
            .child(
                div()
                    .w(px(180.0))
                    .font_family(SANS)
                    .text_size(px(14.0))
                    .text_color(rgb(INK_2))
                    .child(row.attribute.to_string()),
            )
            .child(
                div()
                    .w(px(150.0))
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(rgb(INK))
                    .child(row.value.to_string()),
            )
            .child(div().w(px(120.0)).child(tag(format!("browse-row-{ri}"), row.trust, row.trust_label, motion)));
        table = table.child(r);
        if ri + 1 < rows.len() {
            table = table.child(hairline());
        }
    }

    // ---- the drawer ----
    let drawer = match picked {
        Some(row) => card()
            .flex()
            .flex_col()
            .gap(px(12.0))
            .child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap(px(12.0))
                    .child(eyebrow("Evidence"))
                    .child(tag("browse-drawer", row.trust, row.trust_label, motion)),
            )
            .child(
                div()
                    .font_family(SANS)
                    .font_weight(FontWeight::SEMIBOLD)
                    .text_size(px(16.0))
                    .text_color(rgb(INK))
                    .child(format!("{} — {}", row.subject, row.attribute)),
            )
            .child(
                div()
                    .font_family(MONO)
                    .text_size(px(14.0))
                    .text_color(rgb(ICE))
                    .child(row.value.to_string()),
            )
            .child(hairline())
            .child(
                div()
                    .flex()
                    .flex_col()
                    .gap(px(4.0))
                    .child(eyebrow("For"))
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(14.0))
                            .text_color(rgb(INK_2))
                            .child(if row.evidence_for.is_empty() {
                                "Nothing stored on this side yet.".to_string()
                            } else {
                                row.evidence_for.to_string()
                            }),
                    ),
            )
            .child(
                div()
                    .flex()
                    .flex_col()
                    .gap(px(4.0))
                    .child(eyebrow("Against"))
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(14.0))
                            .text_color(rgb(INK_2))
                            .child(if row.evidence_against.is_empty() {
                                "Nothing stored on this side yet.".to_string()
                            } else {
                                row.evidence_against.to_string()
                            }),
                    ),
            )
            .child(hairline())
            .child(mono("Settled runs keep the evidence with the claim, not the source page.", DIM)),
        None => card()
            .flex()
            .flex_col()
            .items_center()
            .gap(px(8.0))
            .py(px(32.0))
            .child(led_matrix(&QUEUE5, LED_DIM, 4.0, 2.0))
            .child(mono("Pick a row to read its evidence.", MUTED)),
    };

    // ---- the view switch: cols (table), list (compact), grid (tiles) ----
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
            this.browse_selected = 0;
            cx.notify();
        },
    );

    // ---- the picked view ----
    let body: gpui::AnyElement = match app.browse_view {
        1 => {
            // list: one line per row, dense
            let mut list = card().flex().flex_col();
            for (ri, row) in rows.iter().enumerate() {
                let click = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    this.browse_selected = ri;
                    cx.notify();
                });
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
                        .when(ri == selected, |s| s.bg(rgb(WELL)))
                        .on_click(click)
                        .child(mono(row.subject, if ri == selected { ICE } else { INK }))
                        .child(div().w(px(8.0)))
                        .child(mono(row.attribute, MUTED))
                        .child(div().flex_1().min_w(px(0.0)))
                        .child(mono(row.value, INK_2))
                        .child(div().w(px(12.0)))
                        .child(tag(format!("browse-detail-{ri}"), row.trust, row.trust_label, motion)),
                );
            }
            list.into_any_element()
        }
        2 => {
            // grid: subject tiles
            let mut grid = div().flex().flex_wrap().gap(px(16.0));
            for (ri, row) in rows.iter().enumerate() {
                let click = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    this.browse_selected = ri;
                    cx.notify();
                });
                grid = grid.child(
                    div()
                        .id(("browse-grid-tile", ri))
                        .w(px(210.0))
                        .cursor_pointer()
                        .when(ri == selected, |s| {
                            s.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE))
                        })
                        .when(ri != selected, |s| {
                            s.bg(rgba(GLASS_1)).border_1().border_color(rgba(HAIRLINE))
                        })
                        .hover(|s| s.bg(rgb(WELL)))
                        .rounded(px(12.0))
                        .p(px(16.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .on_click(click)
                        .child(
                            div()
                                .font_family(SANS)
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_size(px(15.0))
                                .text_color(rgb(if ri == selected { ICE } else { INK }))
                                .child(row.subject.to_string()),
                        )
                        .child(mono(row.attribute, MUTED))
                        .child(
                            div()
                                .font_family(MONO)
                                .text_size(px(13.0))
                                .text_color(rgb(ICE))
                                .child(row.value.to_string()),
                        )
                        .child(div().mt(px(2.0)).child(tag(format!("browse-attr-{ri}"), row.trust, row.trust_label, motion))),
                );
            }
            div().child(grid).into_any_element()
        }
        _ => {
            // cols: the full table
            div()
                .id("browse-table-scroll")
                .overflow_x_scroll()
                .child(table.min_w(px(560.0)))
                .into_any_element()
        }
    }
    .into_any_element();

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(16.0))
                .flex_wrap()
                .child(div().flex_1().min_w(px(280.0)).child(search))
                .child(view_switch),
        )
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
}
