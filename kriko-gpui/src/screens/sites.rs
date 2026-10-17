//! Sites: the sites Kriko can read, and the ones people have asked for.
//! An add field on top; underneath, the adapters the packs and this install
//! carry (with whether the extension has reported on each) and the sites that
//! were asked for and have no adapter yet.

use gpui::{div, prelude::*, px, ClickEvent, Context, Div, Styled, Window};

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
    let motion = app.motion;
    let add_field = app.input_field(
        Field::SitesAdd,
        "sites-add",
        "Add a site, e.g. reviews.example",
        None,
        window,
        cx,
    );
    let add_click = cx.listener(|this, _: &ClickEvent, _w, cx| {
        let text = this.sites_add.value.trim().to_string();
        if !text.is_empty() {
            this.sites_add.set_value(String::new());
            this.register_site(&text, cx);
        }
        cx.notify();
    });
    let k = &app.live.knowledge;

    let add_row = div()
        .flex()
        .gap(px(8.0))
        .child(div().flex_1().min_w(px(0.0)).child(add_field))
        .child(plate_s("sites-add-btn", "Add site").on_click(add_click));

    // the job in flight, or the last thing that went wrong
    let mut status = div().flex().flex_col().gap(px(4.0));
    if let Some((host, job)) = &k.site_job {
        let failed = job.done && matches!(job.state.as_str(), "failed" | "interrupted");
        let (state, label) = if failed {
            (TagState::Block, "Failed")
        } else if job.done {
            (TagState::Done, "Complete")
        } else {
            (TagState::Live, "Working")
        };
        let said = if job.message.is_empty() { job.state.as_str() } else { job.message.as_str() };
        status = status.child(
            div()
                .flex()
                .flex_wrap()
                .items_center()
                .gap(px(SPACE_S))
                .child(tag("site-registration", state, label, motion))
                .child(row_desc(&format!("{host}: {said}")))
                .when(!job.done, |d| d.child(spinner("site-registration-spinner", 16.0, motion))),
        );
    }
    if let Some(n) = &k.sites_notice {
        status = status.child(mono(n, DANGER));
    }

    if !k.sites_loaded {
        return div()
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(enter(add_row, "sites-0", 0, motion))
            .child(enter(status, "sites-1", 1, motion))
            .child(enter(
                empty_note("Waiting for the engine. Sites it can read appear here."),
                "sites-2",
                2,
                motion,
            ));
    }

    // ---- the adapters ----
    // Fixed columns sized to the room there is: at the window's minimum the
    // wide set left the site column nothing, and its header ran into "Pack".
    let stacked = app.content_w < 600.0;
    let narrow = app.content_w < 900.0;
    let (pack_w, source_w, ext_w, act_w) = if narrow { (130.0, 90.0, 120.0, 80.0) } else { (220.0, 100.0, 150.0, 90.0) };
    let mut table = card().flex().flex_col();
    table = table.child(card_head("globe", "Site adapters", motion));
    if stacked {
        table = table.child(hairline());
    } else {
        table = table.child(
            div()
                .flex()
                .items_center()
                .pb(px(SPACE_S))
                .child(div().flex_1().min_w(px(120.0)).child(th("Site")))
                .child(div().w(px(pack_w)).child(th("Pack")))
                .child(div().w(px(source_w)).child(th("Source")))
                .child(div().w(px(ext_w)).child(th("Status")))
                .child(div().w(px(act_w))),
        ).child(hairline());
    }
    if k.registered.is_empty() {
        table = table.child(div().pt(px(12.0)).child(empty_note(
            "No adapter yet. Add a site above and an agent learns to read it.",
        )));
    }
    for (i, r) in k.registered.iter().enumerate() {
        let (state, label) = activation_tag(&r.activation);
        let host = r.host.clone();
        let forget = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.forget_site(host.clone(), cx);
        });
        let source = if r.local { "this install" } else { "pack" };
        let row = if stacked {
            div()
                .flex()
                .flex_col()
                .gap(px(8.0))
                .py(px(12.0))
                .hover(|s| s.bg(paint_a(GLASS_1)))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .justify_between()
                        .gap(px(8.0))
                        .child(
                            div()
                                .flex_1()
                                .min_w(px(0.0))
                                .flex()
                                .items_center()
                                .gap(px(8.0))
                                .child(icon("sites", 16.0).text_color(paint(MUTED)))
                                .child(mono(&r.host, INK)),
                        )
                        .when(r.local, |d| {
                            d.child(ghost(("site-forget", i), "Forget").on_click(forget))
                        }),
                )
                .child(
                    div()
                        .flex()
                        .flex_wrap()
                        .items_center()
                        .gap(px(8.0))
                        .child(tag(format!("sites-reg-{i}"), state, label, motion))
                        .child(mono(&format!("Pack · {}", crate::screens::history::clip(&r.pack_id, 22)), INK_2))
                        .child(mono(source, INK_2)),
                )
        } else {
            div()
            .flex()
            .items_center()
            .py(px(4.0))
            .hover(|s| s.bg(paint_a(GLASS_1)))
            .child(
                div()
                    .flex_1()
                    .min_w(px(120.0))
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(icon("sites", 16.0).text_color(paint(MUTED)))
                    .child(
                        div()
                            .font_family(MONO)
                            .text_size(px(13.0))
                            .text_color(paint(INK))
                            .child(r.host.clone()),
                    ),
            )
            .child(div().w(px(pack_w)).child(mono(&crate::screens::history::clip(&r.pack_id, if narrow { 16 } else { 28 }), INK_2)))
            .child(div().w(px(source_w)).child(mono(source, INK_2)))
            .child(div().w(px(ext_w)).child(tag(format!("sites-reg-{i}"), state, label, motion)))
            .child(div().w(px(act_w)).flex().justify_end().when(r.local, |d| {
                d.child(ghost(("site-forget", i), "Forget").on_click(forget))
            }))
        };
        table = table.child(row);
        if !r.detail.is_empty() {
            table = table.child(div().pb(px(SPACE_S)).pl(px(SPACE_XL)).child(mono(&r.detail, DIM)));
        }
        if i + 1 < k.registered.len() {
            table = table.child(hairline());
        }
    }

    // ---- the asks with no adapter ----
    let mut asked = card().flex().flex_col();
    asked = asked.child(card_head("question", "Requested sites", motion));
    if stacked {
        asked = asked.child(hairline());
    } else {
        asked = asked.child(
            div()
                .flex()
                .items_center()
                .pb(px(SPACE_S))
                .child(div().flex_1().min_w(px(120.0)).child(th("Asked for")))
                .child(div().w(px(80.0)).child(th("Asks")))
                .child(div().w(px(130.0)).child(th("Last")))
                .child(div().w(px(150.0)).child(th("State")))
                .child(div().w(px(90.0))),
        ).child(hairline());
    }
    if k.requested.is_empty() {
        asked = asked.child(div().pt(px(12.0)).child(empty_note(
            "No requested sites yet.",
        )));
    }
    for (i, r) in k.requested.iter().enumerate() {
        let (state, label) = request_tag(&r.state);
        let host = r.host.clone();
        let teach = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.register_site(&host, cx);
        });
        let idle = r.state != "working" && r.state != "done";
        let row = if stacked {
            div()
                .flex()
                .flex_col()
                .gap(px(8.0))
                .py(px(12.0))
                .hover(|s| s.bg(paint_a(GLASS_1)))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .justify_between()
                        .gap(px(8.0))
                        .child(mono(&r.host, INK))
                        .when(idle, |d| d.child(ghost(("site-teach", i), "Teach").on_click(teach))),
                )
                .child(
                    div()
                        .flex()
                        .flex_wrap()
                        .items_center()
                        .gap(px(8.0))
                        .child(tag(format!("sites-ask-{i}"), state, label, motion))
                        .child(mono(&format!("{} asks", r.asks), INK_2))
                        .child(mono(&format!("Last · {}", ago(&r.last_at)), INK_2)),
                )
                .when(!r.detail.is_empty(), |d| d.child(row_desc(&r.detail)))
        } else {
            div()
                .flex()
                .items_center()
                .py(px(4.0))
                .hover(|s| s.bg(paint_a(GLASS_1)))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(SPACE_XS))
                        .child(
                            div()
                                .font_family(MONO)
                                .text_size(px(13.0))
                                .text_color(paint(INK))
                                .child(r.host.clone()),
                        )
                        .when(!r.detail.is_empty(), |d| d.child(row_desc(&r.detail))),
                )
                .child(div().w(px(80.0)).child(mono(&r.asks.to_string(), INK_2)))
                .child(div().w(px(130.0)).child(mono(&ago(&r.last_at), INK_2)))
                .child(div().w(px(150.0)).child(tag(format!("sites-ask-{i}"), state, label, motion)))
                .child(div().w(px(90.0)).flex().justify_end().when(idle, |d| {
                    d.child(ghost(("site-teach", i), "Teach").on_click(teach))
                }))
        };
        asked = asked.child(row);
        if i + 1 < k.requested.len() {
            asked = asked.child(hairline());
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(enter(add_row, "sites-0", 0, motion))
        .child(enter(status, "sites-1", 1, motion))
        .child(enter(table, "sites-2", 2, motion))
        .child(enter(asked, "sites-3", 3, motion))
        .child(enter(
            mono(
                "Pack adapters update with the pack. Taught ones stay on this install; Forget removes them.",
                DIM,
            ),
            "sites-4",
            4,
            motion,
        ))
}
