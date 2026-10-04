//! Knowledge overview: what the packs know, and where they run thin.
//! The totals read from the packs that are actually on, each pack carries
//! its weight, the support bar is counted from the stored claims, the
//! coverage gaps unfold into their disputes, and the thinnest claims are
//! found, not hardcoded. Information only — nothing here ranks anything.

use gpui::{div, prelude::*, px, rgb, rgba, Animation, AnimationExt, ClickEvent, Context, Div,
    Styled, Window};

use crate::app::Kriko;
use crate::data;
use crate::screens::{mono, row_desc, row_title, total_card};
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

    // ---- packs with switches; the totals read from the enabled ones ----
    let enabled_packs: Vec<usize> = data::PACKS
        .iter()
        .enumerate()
        .filter(|(i, _)| app.pack_enabled.get(*i).copied().unwrap_or(false))
        .map(|(i, _)| i)
        .collect();
    let subjects_on: u32 = enabled_packs
        .iter()
        .map(|&i| data::PACKS[i].subjects as u32)
        .sum();
    let max_subjects = data::PACKS.iter().map(|p| p.subjects).max().unwrap_or(1) as f32;

    let mut packs = card().flex().flex_col();
    packs = packs.child(div().mb(px(4.0)).child(eyebrow("Packs")));
    packs = packs.child(hairline());
    for (i, pack) in data::PACKS.iter().enumerate() {
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            if i < this.pack_enabled.len() {
                this.pack_enabled[i] = !this.pack_enabled[i];
            }
            cx.notify();
        });
        let enabled = app.pack_enabled.get(i).copied().unwrap_or(false);
        let note = if enabled {
            format!("{} subjects", pack.subjects)
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
                .when(!enabled, |s| s.opacity(0.5))
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
                                .child(row_title(pack.name))
                                .child(mono(&note, MUTED)),
                        )
                        .child(
                            meter_slim(pack.subjects as f32 / max_subjects * 100.0, 10),
                        ),
                )
                .child(switch_anim(("pack-sw", i), enabled, motion).on_click(toggle)),
        );
        if i + 1 < data::PACKS.len() {
            packs = packs.child(hairline());
        }
    }

    // ---- the support bar, counted from the stored claims ----
    let total_rows = data::KNOWLEDGE.len().max(1) as f32;
    let share = |state: TagState| {
        data::KNOWLEDGE
            .iter()
            .filter(|r| r.trust == state)
            .count() as f32
            / total_rows
            * 100.0
    };
    let support_rows = [
        ("BACKED", share(TagState::Done), "check"),
        ("DISPUTED", share(TagState::Need), "queue"),
        ("NO EVIDENCE", share(TagState::Queue), "x"),
    ];
    let mut support = card().flex().flex_col().gap(px(10.0)).child(eyebrow("Support"));
    for (si, (label, pct, _glyph)) in support_rows.iter().enumerate() {
        let line = div()
            .flex()
            .items_center()
            .gap(px(10.0))
            .child(mono(label, DIM))
            .child(meter(*pct, 24));
        support = support.child(settle(
            gpui::ElementId::named_usize("ov-support", si),
            300.0 + si as f32 * 140.0,
            motion,
        )(line));
    }
    support = support.child(row_desc(
        "Share of stored claims, counted from the rows themselves.",
    ));

    // ---- coverage gaps, each one unfolding its dispute ----
    let mut gaps_card = card().flex().flex_col();
    gaps_card = gaps_card.child(div().mb(px(4.0)).child(eyebrow("Coverage gaps")));
    gaps_card = gaps_card.child(hairline());
    let mut gap_n = 0usize;
    for (ki, row) in data::KNOWLEDGE.iter().enumerate() {
        if row.trust == TagState::Done {
            continue;
        }
        let open = app.knowledge_open == Some(ki);
        let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.knowledge_open = if this.knowledge_open == Some(ki) {
                None
            } else {
                Some(ki)
            };
            cx.notify();
        });
        let mut gap_row = div()
            .id(("gap-row", ki))
            .py(px(12.0))
            .flex()
            .flex_col()
            .child(
                div()
                    .id(("gap-open", ki))
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
                            .gap(px(2.0))
                            .child(row_title(row.attribute))
                            .child(mono(row.subject, MUTED)),
                    )
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(10.0))
                            .child(icon(
                                if open { "collapse" } else { "expand" },
                                14.0,
                            )
                            .text_color(rgb(MUTED)))
                            .child(tag(
                                format!("knowledge-gap-{ki}"),
                                row.trust,
                                row.trust_label,
                                motion,
                            )),
                    ),
            );
        if open {
            // the dispute, both sides, the way the sources left it
            let mut panel = well()
                .mt(px(4.0))
                .mb(px(6.0))
                .p(px(14.0))
                .flex()
                .flex_col()
                .gap(px(8.0));
            if !row.evidence_for.is_empty() {
                panel = panel
                    .child(eyebrow("On one side"))
                    .child(
                        div()
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
                                    .child(row.evidence_for.to_string()),
                            ),
                    );
            }
            if !row.evidence_against.is_empty() {
                panel = panel
                    .child(eyebrow("On the other"))
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(12.0))
                            .child(led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0))
                            .child(
                                div()
                                    .flex_1()
                                    .min_w(px(0.0))
                                    .font_family(SANS)
                                    .text_size(px(13.0))
                                    .text_color(rgb(INK_2))
                                    .child(row.evidence_against.to_string()),
                            ),
                    );
            }
            if row.evidence_for.is_empty() && row.evidence_against.is_empty() {
                panel = panel.child(row_desc(
                    "Nothing on record. A run would go read for it.",
                ));
            }
            panel = panel.child(mono(
                &format!(
                    "{} claims · {} sources on record",
                    row.claims, row.sources
                ),
                MUTED,
            ));
            gap_row = gap_row.child(panel);
        }
        gaps_card = gaps_card.child(gap_row);
        gap_n += 1;
        // a hairline between gaps that skips the last one
        if gap_n < data::KNOWLEDGE.iter().filter(|r| r.trust != TagState::Done).count() {
            gaps_card = gaps_card.child(hairline());
        }
    }

    // ---- the thinnest claims, found rather than asserted ----
    let max_sources = data::KNOWLEDGE.iter().map(|r| r.sources).max().unwrap_or(1) as f32;
    let mut thinnest: Vec<&data::KnowledgeRow> =
        data::KNOWLEDGE.iter().filter(|r| r.sources > 0).collect();
    thinnest.sort_by_key(|r| r.sources);
    thinnest.truncate(3);
    let mut thin_card = card().flex().flex_col();
    thin_card = thin_card.child(div().mb(px(4.0)).child(eyebrow("Runs thin")));
    thin_card = thin_card.child(hairline());
    if thinnest.is_empty() {
        thin_card = thin_card.child(
            div()
                .py(px(32.0))
                .flex()
                .flex_col()
                .items_center()
                .gap(px(8.0))
                .child(led_matrix_anim(
                    "ov-thin-empty",
                    &CHECK5,
                    INK_2,
                    4.0,
                    2.0,
                    LedAnim::Boot,
                    motion,
                ))
                .child(row_desc("Every stored claim rests on more than one source.")),
        );
    } else {
        for (ti, row) in thinnest.iter().enumerate() {
            thin_card = thin_card.child(
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
                            .gap(px(6.0))
                            .child(
                                div()
                                    .flex()
                                    .items_center()
                                    .justify_between()
                                    .gap(px(16.0))
                                    .child(row_title(row.attribute))
                                    .child(mono(
                                        &format!("{} source{}", row.sources, if row.sources > 1 { "s" } else { "" }),
                                        MUTED,
                                    )),
                            )
                            .child(meter_slim(
                                row.sources as f32 / max_sources * 100.0,
                                10,
                            )),
                    )
                    .child(mono(row.subject, MUTED)),
            );
            if ti + 1 < thinnest.len() {
                thin_card = thin_card.child(hairline());
            }
        }
    }

    // ---- the totals: subjects counted from the packs that are on ----
    let packs_note = format!(
        "across {} enabled pack{}",
        enabled_packs.len(),
        if enabled_packs.len() == 1 { "" } else { "s" }
    );
    let backed_note = format!("{} backed", data::CLAIMS_BACKED);
    let sites_note = format!("{} sites read", data::SITES_READ);

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .child(settle(
                    gpui::ElementId::named_usize("ov-total", 0),
                    0.0,
                    motion,
                )(total_card("Subjects", &subjects_on.to_string(), &packs_note).flex_1()))
                .child(settle(
                    gpui::ElementId::named_usize("ov-total", 1),
                    90.0,
                    motion,
                )(total_card("Claims", data::CLAIMS_STORED, &backed_note).flex_1()))
                .child(settle(
                    gpui::ElementId::named_usize("ov-total", 2),
                    180.0,
                    motion,
                )(total_card("Sources", data::SOURCES_READ, &sites_note).flex_1())),
        )
        .child(
            div()
                .flex()
                .flex_wrap()
                .gap(px(24.0))
                .items_start()
                .child(settle(
                    gpui::ElementId::named_usize("ov-card", 0),
                    260.0,
                    motion,
                )(div().flex_1().min_w(px(0.0)).child(packs)))
                .child(
                    settle(
                        gpui::ElementId::named_usize("ov-card", 1),
                        340.0,
                        motion,
                    )(div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(24.0))
                        .child(support)
                        .child(gaps_card)),
                ),
        )
        .child(settle(
            gpui::ElementId::named_usize("ov-card", 2),
            420.0,
            motion,
        )(thin_card))
}
