//! Knowledge overview: what the packs know, and where they run thin, read
//! from the engine: the installed packs and their switches, the totals of the
//! ones that are on, the subjects nobody has researched, and the claims that
//! rest on the least. Information only; nothing here ranks anything.

use gpui::{div, prelude::*, px, rgb, rgba, Animation, AnimationExt, ClickEvent, Context, Div, Window};

use crate::app::Kriko;
use crate::screens::{empty_note, mono, row_desc, row_title, total_card};
use crate::theme::*;

/// The smooth settle the whole page shares: a fade with a stagger.
fn settle(
    id: gpui::ElementId,
    delay: f32,
    motion: bool,
) -> impl FnMut(Div) -> gpui::AnyElement {
    move |el: Div| -> gpui::AnyElement {
        if motion {
            el.with_animation(
                id.clone(),
                Animation::new(std::time::Duration::from_millis(900)).with_easing(move |t| {
                    let local = ((t * 900.0 - delay) / 500.0).clamp(0.0, 1.0);
                    1.0 - (1.0 - local).powi(3)
                }),
                |el, v| el.opacity(v),
            )
            .into_any_element()
        } else {
            el.into_any_element()
        }
    }
}

pub fn overview(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let k = &app.live.knowledge;

    if !k.packs_loaded {
        return div().child(empty_note(
            "Waiting for Kriko's engine. The packs appear here as soon as it answers.",
        ));
    }

    // ---- pack updates: only when a newer version is on offer ----
    let mut banner: Option<Div> = None;
    if !k.offers.is_empty() {
        let mut b = card()
            .flex()
            .flex_col()
            .child(div().mb(px(4.0)).child(eyebrow("Pack updates")))
            .child(hairline());
        let working = k.update_job.as_ref().map(|j| !j.done).unwrap_or(false);
        for (i, o) in k.offers.iter().enumerate() {
            let id = o.pack_id.clone();
            let go = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.update_pack(id.clone(), cx);
            });
            let button = key(("pack-update", i), "Update");
            let button = if working { button.opacity(0.5) } else { button.on_click(go) };
            b = b.child(
                div()
                    .py(px(12.0))
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap(px(16.0))
                    .child(
                        div()
                            .flex_1()
                            .min_w(px(0.0))
                            .flex()
                            .flex_col()
                            .gap(px(2.0))
                            .child(row_title(&o.name))
                            .child(mono(&format!("{} to {}", o.installed, o.offered), MUTED)),
                    )
                    .child(button),
            );
        }
        if let Some(job) = &k.update_job {
            let line = if job.message.is_empty() { job.state.clone() } else { job.message.clone() };
            b = b.child(mono(&line, if job.state == "failed" { DANGER } else { MUTED }));
        }
        banner = Some(b);
    }

    // ---- packs with switches; the meter is each pack's share of subjects ----
    let max_subjects = k.packs.iter().map(|p| p.subjects).max().unwrap_or(1).max(1) as f32;
    let switching = k.switching.is_some();
    let choose_pack = cx.listener(|this, _: &ClickEvent, _w, cx| this.choose_pack_file(cx));
    let mut packs = card().flex().flex_col();
    packs = packs.child(
        div()
            .flex()
            .items_center()
            .justify_between()
            .gap(px(12.0))
            .mb(px(4.0))
            .child(eyebrow("Packs"))
            .child(crate::screens::plate_s(
                "knowledge-import-pack",
                if k.pack_installing { "Installing" } else { "Import .kpack" },
            ).on_click(choose_pack)),
    );
    packs = packs.child(hairline());
    if let Some(note) = &k.pack_install_note {
        packs = packs.child(row_desc(note));
    }
    if k.packs.is_empty() {
        packs = packs.child(div().pt(px(12.0)).child(empty_note(
            "No packs are installed. Import a trusted .kpack file to add local product knowledge.",
        )));
    }
    for (i, pack) in k.packs.iter().enumerate() {
        let id = pack.id.clone();
        let want = !pack.enabled;
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.set_pack_enabled(id.clone(), want, cx);
        });
        let note = if pack.enabled {
            format!("{} subjects · {} claims", pack.subjects, pack.claims)
        } else {
            "off, not read".to_string()
        };
        packs = packs.child(
            div()
                .py(px(14.0))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(24.0))
                .when(!pack.enabled, |s| s.opacity(0.5))
                .when(switching && k.switching.as_deref() != Some(pack.id.as_str()), |s| s.opacity(0.35))
                .child(
                    div()
                        .flex()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex_col()
                        .gap(px(6.0))
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .justify_between()
                                .gap(px(16.0))
                                .child(div().flex_1().min_w(px(0.0)).truncate().child(row_title(&pack.name)))
                                .child(div().flex_none().child(mono(&note, MUTED))),
                        )
                        .child(meter_slim(pack.subjects as f32 / max_subjects * 100.0, 10))
                        .child(mono(&format!("{} · {}", pack.id, pack.version), DIM)),
                )
                .child(switch_anim(("pack-sw", i), pack.enabled, motion).on_click(toggle)),
        );
        if i + 1 < k.packs.len() {
            packs = packs.child(hairline());
        }
    }

    // ---- coverage gaps: subjects of the enabled packs nothing reaches ----
    let mut gaps_card = card().flex().flex_col();
    gaps_card = gaps_card.child(div().mb(px(4.0)).child(eyebrow("Coverage gaps")));
    gaps_card = gaps_card.child(hairline());
    if k.gaps.is_empty() {
        gaps_card = gaps_card.child(div().pt(px(12.0)).child(empty_note(
            "Every subject in the enabled packs has at least one claim.",
        )));
    }
    let shown = 8usize;
    for (gi, gap) in k.gaps.iter().take(shown).enumerate() {
        gaps_card = gaps_card.child(
            div()
                .py(px(12.0))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(16.0))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title(&gap.label))
                        .child(mono(&format!("{} · {}", gap.kind, gap.pack_id), MUTED)),
                )
                .child(tag(format!("knowledge-gap-{gi}"), TagState::Queue, "No claims", motion)),
        );
        if gi + 1 < shown.min(k.gaps.len()) {
            gaps_card = gaps_card.child(hairline());
        }
    }
    if k.gaps.len() > shown {
        gaps_card = gaps_card.child(
            div()
                .pt(px(8.0))
                .child(mono(&format!("and {} more", k.gaps.len() - shown), DIM)),
        );
    }

    // ---- the thinnest claims, found rather than asserted ----
    let max_sources = k.thin.iter().map(|r| r.sources).max().unwrap_or(1).max(1) as f32;
    let mut thin_card = card().flex().flex_col();
    thin_card = thin_card.child(div().mb(px(4.0)).child(eyebrow("Runs thin")));
    thin_card = thin_card.child(hairline());
    if !k.thin_loaded {
        thin_card = thin_card.child(div().pt(px(12.0)).child(empty_note("Looking for the thinnest claims.")));
    } else if k.thin.is_empty() {
        thin_card = thin_card.child(
            div()
                .py(px(32.0))
                .flex()
                .flex_col()
                .items_center()
                .gap(px(8.0))
                .child(led_matrix_anim("ov-thin-empty", &CHECK5, INK_2, 4.0, 2.0, LedAnim::Boot, motion))
                .child(row_desc("No claim with evidence rests on thin ground.")),
        );
    }
    for (ti, row) in k.thin.iter().enumerate() {
        let open = k.thin_open.as_deref() == Some(row.claim_id.as_str());
        let (cid, sid) = (row.claim_id.clone(), row.subject_id.clone());
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.toggle_thin(cid.clone(), sid.clone(), cx);
            cx.notify();
        });
        let state_tag = if row.refuted_by > 0 {
            tag(format!("thin-{ti}"), TagState::Need, "Disputed", motion)
        } else {
            tag(format!("thin-{ti}"), TagState::Queue, "Thin", motion)
        };
        let mut line = div().id(("thin-row", ti)).py(px(12.0)).flex().flex_col().child(
            div()
                .id(("thin-open", ti))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(16.0))
                .cursor_pointer()
                .hover(|s| s.bg(rgba(GLASS_1)))
                .on_click(toggle)
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .justify_between()
                                .gap(px(16.0))
                                .child(row_title(&row.title))
                                .child(mono(
                                    &format!(
                                        "{} source{}",
                                        row.sources,
                                        if row.sources == 1 { "" } else { "s" }
                                    ),
                                    MUTED,
                                )),
                        )
                        .child(meter_slim(row.sources as f32 / max_sources * 100.0, 10))
                        .child(mono(&row.subject, DIM)),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(10.0))
                        .child(icon(if open { "collapse" } else { "expand" }, 14.0).text_color(rgb(MUTED)))
                        .child(state_tag),
                ),
        );
        if open {
            let mut panel = well().mt(px(4.0)).mb(px(6.0)).p(px(14.0)).flex().flex_col().gap(px(10.0));
            if !k.thin_quotes_loaded {
                panel = panel.child(row_desc("Reading the evidence."));
            } else if k.thin_quotes.is_empty() {
                panel = panel.child(row_desc("No evidence on record for this claim."));
            }
            for q in &k.thin_quotes {
                let (glyph, color): (&[&str], u32) =
                    if q.stance == "refutes" { (&QUEUE5, LED_DIM) } else { (&CHECK5, INK_2) };
                panel = panel.child(
                    div()
                        .flex()
                        .items_start()
                        .gap(px(12.0))
                        .child(led_matrix(glyph, color, 3.0, 1.0))
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
                                        .child(format!("\u{201c}{}\u{201d}", q.quote)),
                                )
                                .child(mono(&format!("{} · {} · {}", q.domain, q.stance, q.tier), MUTED)),
                        ),
                );
            }
            line = line.child(panel);
        }
        thin_card = thin_card.child(line);
        if ti + 1 < k.thin.len() {
            thin_card = thin_card.child(hairline());
        }
    }

    // ---- the totals, from the packs that are on ----
    let t = &k.totals;
    let packs_note = format!(
        "across {} enabled pack{}",
        t.enabled_packs,
        if t.enabled_packs == 1 { "" } else { "s" }
    );
    let claims_note = format!("{} packs installed", t.packs);

    let mut left = div().flex_1().min_w(px(0.0)).flex().flex_col().gap(px(24.0));
    if let Some(b) = banner {
        left = left.child(b);
    }
    left = left.child(packs);

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .child(settle(gpui::ElementId::named_usize("ov-total", 0), 0.0, motion)(
                    total_card("Subjects", &t.subjects.to_string(), &packs_note).flex_1(),
                ))
                .child(settle(gpui::ElementId::named_usize("ov-total", 1), 90.0, motion)(
                    total_card("Claims", &t.claims.to_string(), &claims_note).flex_1(),
                ))
                .child(settle(gpui::ElementId::named_usize("ov-total", 2), 180.0, motion)(
                    total_card("Evidence", &t.evidence.to_string(), "quotes with their sources").flex_1(),
                )),
        )
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .items_start()
                .child(settle(gpui::ElementId::named_usize("ov-card", 0), 260.0, motion)(left))
                .child(settle(gpui::ElementId::named_usize("ov-card", 1), 340.0, motion)(
                    div().flex_1().min_w(px(0.0)).child(gaps_card),
                )),
        )
        .child(settle(gpui::ElementId::named_usize("ov-card", 2), 420.0, motion)(thin_card))
}
