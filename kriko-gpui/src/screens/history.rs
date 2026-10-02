//! History: every check you have run, with the evidence it was based on.
//! Search on top, verdict and pack filters beside it, the runs in a glass
//! card, pagination underneath — the shape of the reference screen.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, Context, Div, FontWeight,
    Styled, Window,
};

use crate::app::{Field, Kriko, PackFilter, VerdictFilter};
use crate::data;
use crate::screens::{mono, plate_s, row_desc, th};
use crate::theme::*;

pub fn history(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    // ---- the controls row: search + two cycling filters ----
    let search = app.input_field(Field::HistorySearch, "history-search", "Search past checks", Some("search"), window, cx);

    let verdict_next = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.verdict_filter = this.verdict_filter.next();
        this.page = 0;
        cx.notify();
    });
    let pack_next = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.pack_filter = this.pack_filter.next();
        this.page = 0;
        cx.notify();
    });

    let verdict_ctrl = div()
        .id("filter-verdict")
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
        .on_click(verdict_next)
        .child(led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0))
        .child("VERDICT: ")
        .child(div().text_color(rgb(INK)).child(app.verdict_filter.word()))
        .child(icon("chevron-down", 14.0).text_color(rgb(MUTED)));

    let pack_ctrl = div()
        .id("filter-pack")
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
        .on_click(pack_next)
        .child(led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0))
        .child("PACK: ")
        .child(div().text_color(rgb(INK)).child(app.pack_filter.word()))
        .child(icon("chevron-down", 14.0).text_color(rgb(MUTED)));

    let controls = div()
        .flex()
        .flex_wrap()
        .items_center()
        .gap(px(16.0))
        .mb(px(24.0))
        .child(div().flex_1().min_w(px(0.0)).child(search))
        .child(verdict_ctrl)
        .child(pack_ctrl);

    // ---- filtering ----
    let query = app.history_search.value.to_lowercase();
    let verdict = app.verdict_filter;
    let pack = app.pack_filter;
    let matches = |c: &data::Check| -> bool {
        let ok_query = query.is_empty()
            || c.name.to_lowercase().contains(&query)
            || c.pack.to_lowercase().contains(&query);
        let ok_verdict = match verdict {
            VerdictFilter::Any => true,
            VerdictFilter::Recommended => c.verdict == Verdict::Recommended,
            VerdictFilter::WeighUp => c.verdict == Verdict::WeighUp,
            VerdictFilter::Avoid => c.verdict == Verdict::Avoid,
        };
        let ok_pack = match pack {
            PackFilter::All => true,
            PackFilter::Samsung => c.pack.starts_with("samsung"),
            PackFilter::Apple => c.pack.starts_with("apple"),
            PackFilter::Volkswagen => c.pack.starts_with("volkswagen"),
        };
        ok_query && ok_verdict && ok_pack
    };
    let filtered: Vec<&data::Check> = data::CHECKS.iter().filter(|c| matches(c)).collect();
    let total = filtered.len();
    let pages = if total == 0 { 1 } else { (total + data::PAGE_SIZE - 1) / data::PAGE_SIZE };
    let page = app.page.min(pages - 1);
    let rows: Vec<&&data::Check> = filtered
        .iter()
        .skip(page * data::PAGE_SIZE)
        .take(data::PAGE_SIZE)
        .collect();

    // ---- the table card ----
    let mut table = card().flex().flex_col();
    // header
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().child(th("Check")))
                .child(div().w(px(200.0)).child(th("Verdict")))
                .child(div().w(px(170.0)).child(th("Confidence")))
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
                .child(led_matrix(&QUEUE5, LED_DIM, 4.0, 2.0))
                .child(row_desc("No check matches. Clear the search or the filters.")),
        );
    }

    for (ri, check) in rows.iter().enumerate() {
        let cells = div().w(px(200.0)).flex().items_center().child(verdict_chip(check.verdict));
        let mut agent_tiles = div().w(px(108.0)).flex().items_center().gap(px(6.0));
        for m in check.agents {
            agent_tiles = agent_tiles.child(agent_tile(letter_rows(*m), None));
        }
        let row = div()
            .flex()
            .items_center()
            .py(px(14.0))
            .hover(|s| s.bg(rgba(GLASS_1)))
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
            .child(cells)
            .child(
                div()
                    .w(px(170.0))
                    .flex()
                    .items_center()
                    .gap(px(10.0))
                    .child(meter_slim(check.confidence as f32, 10))
                    .child(mono(&format!("{}%", check.confidence), INK_2)),
            )
            .child(agent_tiles)
            .child(div().w(px(120.0)).child(mono(check.took, INK_2)))
            .child(div().w(px(100.0)).child(mono(check.when, MUTED)));
        table = table.child(row);
        if ri + 1 < rows.len() {
            table = table.child(hairline());
        }
    }

    // ---- pagination ----
    let prev = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.page = this.page.saturating_sub(1);
        cx.notify();
    });
    let next = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.page += 1;
        cx.notify();
    });
    let shown = rows.len();
    let count_text = if shown <= 1 {
        format!("{} of {} · newest first", shown, total)
    } else {
        format!("{}-{} of {} · newest first", page * data::PAGE_SIZE + 1, page * data::PAGE_SIZE + shown, total)
    };
    let pagination = div()
        .mt(px(16.0))
        .pt(px(16.0))
        .flex()
        .items_center()
        .justify_between()
        .child(div().font_family(MONO).text_size(px(12.0)).text_color(rgb(MUTED)).child(count_text))
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
        .child(
            div()
                .id("hist-table-scroll")
                .overflow_x_scroll()
                .child(table.min_w(px(840.0))),
        )
}
