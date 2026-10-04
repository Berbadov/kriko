//! Sites: the sites Kriko reads, and how far each one is trusted.
//! An add field on top, the site table with trust grades underneath.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data;
use crate::screens::{mono, plate_s, th};
use crate::theme::*;

pub fn sites(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let add_field = app.input_field(Field::SitesAdd, "sites-add", "Add a site, e.g. reviews.example", None, window, cx);
    let add_click = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        let host = this.sites_add.value.trim().to_string();
        if !host.is_empty() {
            this.added_sites.push(host);
            this.sites_add.value.clear();
        }
        cx.notify();
    });

    let add_row = div()
        .flex()
        .gap(px(16.0))
        .mb(px(24.0))
        .child(div().flex_1().min_w(px(0.0)).child(add_field))
        .child(plate_s("sites-add-btn", "Add site").on_click(add_click));

    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().child(th("Site")))
                .child(div().w(px(120.0)).child(th("Pages")))
                .child(div().w(px(120.0)).child(th("Claims")))
                .child(div().w(px(140.0)).child(th("Trust grade"))),
        )
        .child(hairline());

    let mut count = 0;
    let mut rows: Vec<(&str, u16, u16, TagState, &str)> = data::SITES
        .iter()
        .map(|s| (s.host, s.pages, s.claims, s.trust, s.trust_label))
        .collect();
    for added in &app.added_sites {
        rows.push((added, 0, 0, TagState::Queue, "Not read yet"));
    }
    let total_rows = rows.len();
    for (host, pages, claims, trust, label) in rows {
        count += 1;
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
                    .items_center()
                    .gap(px(12.0))
                    .child(icon("sites", 16.0).text_color(rgb(MUTED)))
                    .child(
                        div()
                            .font_family(MONO)
                            .text_size(px(13.0))
                            .text_color(rgb(INK))
                            .child(host.to_string()),
                    ),
            )
            .child(div().w(px(120.0)).child(mono(&pages.to_string(), INK_2)))
            .child(div().w(px(120.0)).child(mono(&claims.to_string(), INK_2)))
            .child(div().w(px(140.0)).child(tag(format!("sites-{host}"), trust, label, motion)));
        table = table.child(row);
        if count < total_rows {
            table = table.child(hairline());
        }
    }

    let note = mono(
        "A blocked site is refused in every run until you clear it in Settings.",
        DIM,
    );

    div()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(add_row)
        .child(table)
        .child(note)
}
