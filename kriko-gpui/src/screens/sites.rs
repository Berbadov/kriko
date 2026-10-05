//! Sites: the sites Kriko can read, and the ones people have asked for.
//! An add field on top; underneath, the adapters the packs and this install
//! carry (with whether the extension has reported on each) and the sites that
//! were asked for and have no adapter yet.

use gpui::{div, prelude::*, px, rgb, rgba, ClickEvent, Context, Div, Styled, Window};

use crate::app::{Field, Kriko};
use crate::live::knowledge::ago;
use crate::screens::{empty_note, mono, plate_s, row_desc, th};
use crate::theme::*;

fn activation_tag(state: &str) -> (TagState, &'static str) {
    match state {
        "active" => (TagState::Done, "Active"),
        "unknown" | "" => (TagState::Queue, "Not reported"),
        "blocked" | "denied" | "refused" => (TagState::Block, "Blocked"),
        _ => (TagState::Need, "Needs you"),
    }
}

fn request_tag(state: &str) -> (TagState, &'static str) {
    match state {
        "working" => (TagState::Live, "Working"),
        "done" => (TagState::Done, "Done"),
        "refused" => (TagState::Block, "Refused"),
        _ => (TagState::Queue, "Asked for"),
    }
}

pub fn sites(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let add_field = app.input_field(
        Field::SitesAdd,
        "sites-add",
        "Teach Kriko a site, e.g. reviews.example",
        None,
        window,
        cx,
    );
    let add_click = cx.listener(|this, _: &ClickEvent, _w, cx| {
        let text = this.sites_add.value.trim().to_string();
        if !text.is_empty() {
            this.sites_add.value.clear();
            this.register_site(&text, cx);
        }
        cx.notify();
    });
    let k = &app.live.knowledge;

    let add_row = div()
        .flex()
        .gap(px(16.0))
        .child(div().flex_1().min_w(px(0.0)).child(add_field))
        .child(plate_s("sites-add-btn", "Add site").on_click(add_click));

    // the job in flight, or the last thing that went wrong
    let mut status = div().flex().flex_col().gap(px(4.0));
    if let Some((host, job)) = &k.site_job {
        let said = if job.message.is_empty() { job.state.clone() } else { job.message.clone() };
        status = status.child(mono(
            &format!("{host}: {said}"),
            if job.state == "failed" { DANGER } else { MUTED },
        ));
    }
    if let Some(n) = &k.sites_notice {
        status = status.child(mono(n, DANGER));
    }

    if !k.sites_loaded {
        return div()
            .flex()
            .flex_col()
            .gap(px(16.0))
            .child(add_row)
            .child(empty_note("Waiting for Kriko's engine. The sites it can read appear here."));
    }

    // ---- the adapters ----
    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().child(th("Site")))
                .child(div().w(px(220.0)).child(th("Pack")))
                .child(div().w(px(100.0)).child(th("Source")))
                .child(div().w(px(150.0)).child(th("Extension")))
                .child(div().w(px(90.0))),
        )
        .child(hairline());
    if k.registered.is_empty() {
        table = table.child(div().pt(px(12.0)).child(empty_note(
            "No site has an adapter yet. Add one above and an agent works out how to read it.",
        )));
    }
    for (i, r) in k.registered.iter().enumerate() {
        let (state, label) = activation_tag(&r.activation);
        let host = r.host.clone();
        let forget = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.forget_site(host.clone(), cx);
        });
        let source = if r.local { "this install" } else { "pack" };
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
                            .child(r.host.clone()),
                    ),
            )
            .child(div().w(px(220.0)).child(mono(&r.pack_id, INK_2)))
            .child(div().w(px(100.0)).child(mono(source, INK_2)))
            .child(div().w(px(150.0)).child(tag(format!("sites-reg-{i}"), state, label, motion)))
            .child(div().w(px(90.0)).flex().justify_end().when(r.local, |d| {
                d.child(ghost(("site-forget", i), "Forget").on_click(forget))
            }));
        table = table.child(row);
        if !r.detail.is_empty() {
            table = table.child(div().pb(px(8.0)).pl(px(28.0)).child(mono(&r.detail, DIM)));
        }
        if i + 1 < k.registered.len() {
            table = table.child(hairline());
        }
    }

    // ---- the asks with no adapter ----
    let mut asked = card().flex().flex_col();
    asked = asked
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().child(th("Asked for")))
                .child(div().w(px(80.0)).child(th("Asks")))
                .child(div().w(px(130.0)).child(th("Last")))
                .child(div().w(px(150.0)).child(th("State")))
                .child(div().w(px(90.0))),
        )
        .child(hairline());
    if k.requested.is_empty() {
        asked = asked.child(div().pt(px(12.0)).child(empty_note(
            "Nobody has asked for a site Kriko cannot read yet.",
        )));
    }
    for (i, r) in k.requested.iter().enumerate() {
        let (state, label) = request_tag(&r.state);
        let host = r.host.clone();
        let teach = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.register_site(&host, cx);
        });
        let idle = r.state != "working" && r.state != "done";
        asked = asked.child(
            div()
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
                                .font_family(MONO)
                                .text_size(px(13.0))
                                .text_color(rgb(INK))
                                .child(r.host.clone()),
                        )
                        .when(!r.detail.is_empty(), |d| d.child(row_desc(&r.detail))),
                )
                .child(div().w(px(80.0)).child(mono(&r.asks.to_string(), INK_2)))
                .child(div().w(px(130.0)).child(mono(&ago(&r.last_at), INK_2)))
                .child(div().w(px(150.0)).child(tag(format!("sites-ask-{i}"), state, label, motion)))
                .child(div().w(px(90.0)).flex().justify_end().when(idle, |d| {
                    d.child(ghost(("site-teach", i), "Teach").on_click(teach))
                })),
        );
        if i + 1 < k.requested.len() {
            asked = asked.child(hairline());
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(add_row)
        .child(status)
        .child(table)
        .child(asked)
        .child(mono(
            "Adapters from a pack update with the pack. One taught here lives on this install only, and Forget removes just that.",
            DIM,
        ))
}
