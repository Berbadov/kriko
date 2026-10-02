//! Knowledge overview: what the packs know, and where they run thin.
//! Totals, the packs with their switches, the support bar, and the gaps.

use gpui::{div, prelude::*, px, rgb, Context, Div, FontWeight, Styled, Window};

use crate::app::Kriko;
use crate::data;
use crate::screens::{mono, row_desc, row_title};
use crate::theme::*;

fn total_card(label: &str, value: &str, note: &str) -> Div {
    card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(eyebrow(label))
        .child(
            div()
                .font_family(DISPLAY)
                .font_weight(FontWeight::SEMIBOLD)
                .text_size(px(64.0))
                .line_height(px(60.0))
                .text_color(rgb(INK))
                .child(value.to_string()),
        )
        .child(mono(note, MUTED))
}

pub fn overview(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    // ---- packs with switches ----
    let mut packs = card().flex().flex_col();
    packs = packs.child(div().mb(px(4.0)).child(eyebrow("Packs")));
    packs = packs.child(hairline());
    for (i, pack) in data::PACKS.iter().enumerate() {
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            if i < this.pack_enabled.len() {
                this.pack_enabled[i] = !this.pack_enabled[i];
            }
            cx.notify();
        });
        let enabled = app.pack_enabled.get(i).copied().unwrap_or(false);
        packs = packs.child(
            div()
                .py(px(14.0))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(24.0))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title(pack.name))
                        .child(mono(&format!("{} subjects", pack.subjects), MUTED)),
                )
                .child(switch_anim(("pack-sw", i), enabled, motion).on_click(toggle)),
        );
        if i + 1 < data::PACKS.len() {
            packs = packs.child(hairline());
        }
    }

    // ---- support bar ----
    let support = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow("Support"))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(mono("BACKED", DIM))
                .child(meter(86.0, 24)),
        )
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(mono("DISPUTED", DIM))
                .child(meter(9.0, 24)),
        )
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(mono("NO EVIDENCE", DIM))
                .child(meter(5.0, 24)),
        )
        .child(row_desc("Share of stored claims, by trust grade."));

    // ---- coverage gaps ----
    let gaps: Vec<&data::KnowledgeRow> = data::KNOWLEDGE
        .iter()
        .filter(|r| r.trust != TagState::Done)
        .collect();
    let mut gaps_card = card().flex().flex_col();
    gaps_card = gaps_card.child(div().mb(px(4.0)).child(eyebrow("Coverage gaps")));
    gaps_card = gaps_card.child(hairline());
    for (i, row) in gaps.iter().enumerate() {
        gaps_card = gaps_card.child(
            div()
                .py(px(12.0))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(16.0))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title(row.attribute))
                        .child(mono(row.subject, MUTED)),
                )
                .child(tag(row.trust, row.trust_label, motion)),
        );
        if i + 1 < gaps.len() {
            gaps_card = gaps_card.child(hairline());
        }
    }

    // ---- weakest claims empty state ----
    let weakest = card()
        .flex()
        .flex_col()
        .items_center()
        .gap(px(8.0))
        .py(px(32.0))
        .child(led_matrix(&QUEUE5, LED_DIM, 4.0, 2.0))
        .child(row_desc("No claim is weaker than two sources right now."))
        .child(mono("Weakest: Product C earbuds · codec support", DIM));

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .child(total_card("Subjects", "760", "across 4 packs"))
                .child(total_card("Claims", "1 402", "1 214 backed"))
                .child(total_card("Sources", "388", "96 sites read")),
        )
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .items_start()
                .child(div().flex_1().min_w(px(0.0)).child(packs))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(24.0))
                        .child(support)
                        .child(gaps_card),
                ),
        )
        .child(weakest)
}
