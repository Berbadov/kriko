//! Knowledge overview: what the packs know, and where they run thin, read
//! from the engine: the installed packs and their switches, the totals of the
//! ones that are on, the subjects nobody has researched, and the claims that
//! rest on the least. Information only; nothing here ranks anything.

use gpui::{div, prelude::*, px, rgb, rgba, Animation, AnimationExt, ClickEvent, Context, Div, Window};

use crate::app::{Field, Kriko};
use crate::screens::{empty_note, mono, row_desc, row_title, total_card, plate_s};
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

pub fn overview(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let search = app.input_field(Field::OverviewSearch, "overview-search", "Search packs or products", Some("search"), window, cx);
    let query = app.overview_search.value.to_lowercase();
    let pack_pick = app.overview_pack.clone();
    let status_pick = app.overview_status.clone();
    let product_pick = app.overview_product.clone();
    let k = &app.live.knowledge;
    let matched = |text: &str| query.is_empty() || text.to_lowercase().contains(&query);
    let pack_rows: Vec<_> = k.packs.iter().filter(|p| (pack_pick.is_empty() || p.id == pack_pick)
        && product_pick.is_empty() && matched(&p.name)
        && match status_pick.as_str() { "enabled" => p.enabled, "disabled" => !p.enabled, "unresearched" | "thin" | "disputed" => false, _ => true }).collect();
    let gaps: Vec<_> = k.gaps.iter().filter(|g| (pack_pick.is_empty() || g.pack_id == pack_pick)
        && (product_pick.is_empty() || product_pick == format!("{}\n{}", g.pack_id, g.label))
        && matched(&g.label) && matches!(status_pick.as_str(), "" | "unresearched")).collect();
    let thin: Vec<_> = k.thin.iter().filter(|t| (pack_pick.is_empty() || t.pack_id == pack_pick)
        && (product_pick.is_empty() || product_pick == format!("{}\n{}", t.pack_id, t.subject))
        && matched(&format!("{} {}", t.subject, t.title))
        && match status_pick.as_str() { "" | "thin" => true, "disputed" => t.refuted_by > 0, _ => false }).collect();
    let matches = pack_rows.len() + gaps.len() + thin.len();
    let active = usize::from(!pack_pick.is_empty()) + usize::from(!status_pick.is_empty()) + usize::from(!product_pick.is_empty());
    let toggle = cx.listener(|this, _: &ClickEvent, _w, cx| { this.overview_filters_open = !this.overview_filters_open; cx.notify(); });
    let reset = cx.listener(|this, _: &ClickEvent, _w, cx| { this.overview_pack.clear(); this.overview_status.clear(); this.overview_product.clear(); this.overview_search.set_value(String::new()); cx.notify(); });
    let mut controls = div().flex().flex_col().gap(px(12.0)).child(
        div().flex().flex_wrap().gap(px(10.0)).child(search)
            .child(plate_s("overview-filters", &format!("Filters · {active} active")).on_click(toggle))
            .child(plate_s("overview-reset", "Reset filters").on_click(reset)))
        .child(row_desc(&format!("{matches} matching records · Pack: {} · Status: {} · Product: {}",
            if pack_pick.is_empty() { "All" } else { &pack_pick }, if status_pick.is_empty() { "All" } else { &status_pick },
            if product_pick.is_empty() { "All" } else { product_pick.split_once('\n').map(|(_,label)| label).unwrap_or(&product_pick) })));
    if app.overview_filters_open {
        let mut drawer = card().flex().flex_col().gap(px(12.0)).child(eyebrow("Overview filters"));
        let mut choices = div().flex().flex_wrap().gap(px(8.0));
        for (i, (id, label)) in std::iter::once((String::new(), "All packs".to_string())).chain(k.packs.iter().map(|p| (p.id.clone(), p.name.clone()))).enumerate() {
            let selected = id == pack_pick;
            let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| { this.overview_pack = id.clone(); cx.notify(); });
            choices = choices.child(plate_s(("overview-pack",i), &label).when(selected, |b| b.border_color(rgb(ICE))).on_click(pick));
        }
        drawer = drawer.child(eyebrow("Pack")).child(choices);
        let mut products = std::collections::BTreeMap::<String, String>::new();
        products.insert(String::new(), "All products".into());
        for gap in &k.gaps { if pack_pick.is_empty() || gap.pack_id == pack_pick {
            products.insert(format!("{}\n{}", gap.pack_id, gap.label), gap.label.clone());
        } }
        for thin in &k.thin { if pack_pick.is_empty() || thin.pack_id == pack_pick {
            products.insert(format!("{}\n{}", thin.pack_id, thin.subject), thin.subject.clone());
        } }
        let mut product_choices = div().flex().flex_wrap().gap(px(8.0));
        for (i, (id, label)) in products.into_iter().enumerate() {
            let selected = id == product_pick;
            let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| { this.overview_product = id.clone(); cx.notify(); });
            product_choices = product_choices.child(plate_s(("overview-product", i), &label).when(selected, |b| b.border_color(rgb(ICE))).on_click(pick));
        }
        drawer = drawer.child(eyebrow("Product")).child(product_choices);
        let mut choices = div().flex().flex_wrap().gap(px(8.0));
        for (i, (id, label)) in [("", "All records"), ("enabled", "Enabled packs"), ("disabled", "Disabled packs"), ("unresearched", "No claims"), ("thin", "Thin evidence"), ("disputed", "Disputed")].iter().enumerate() {
            let id = id.to_string(); let selected = id == status_pick;
            let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| { this.overview_status = id.clone(); cx.notify(); });
            choices = choices.child(plate_s(("overview-status",i), label).when(selected, |b| b.border_color(rgb(ICE))).on_click(pick));
        }
        drawer = drawer.child(eyebrow("Status")).child(choices).child(plate_s("overview-filter-close", "Close").on_click(cx.listener(|this, _: &ClickEvent, _w, cx| { this.overview_filters_open = false; cx.notify(); })));
        controls = controls.child(drawer);
    }
    if matches == 0 && k.packs_loaded { controls = controls.child(empty_note("No record matches. Reset the filters or change the search.")); }

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
    let mut packs = card().flex().flex_col();
    packs = packs.child(div().mb(px(4.0)).child(eyebrow("Packs")));
    packs = packs.child(hairline());
    if k.packs.is_empty() {
        packs = packs.child(div().pt(px(12.0)).child(empty_note(
            "No packs are installed. Install one from Browse and its knowledge lands here.",
        )));
    }
    for (i, pack) in pack_rows.iter().enumerate() {
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
        if i + 1 < pack_rows.len() {
            packs = packs.child(hairline());
        }
    }

    // ---- coverage gaps: subjects of the enabled packs nothing reaches ----
    let mut gaps_card = card().flex().flex_col();
    gaps_card = gaps_card.child(div().mb(px(4.0)).child(eyebrow("Coverage gaps")));
    gaps_card = gaps_card.child(hairline());
    if gaps.is_empty() {
        gaps_card = gaps_card.child(div().pt(px(12.0)).child(empty_note(
            "Every subject in the enabled packs has at least one claim.",
        )));
    }
    let shown = 8usize;
    for (gi, gap) in gaps.iter().take(shown).enumerate() {
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
        if gi + 1 < shown.min(gaps.len()) {
            gaps_card = gaps_card.child(hairline());
        }
    }
    if gaps.len() > shown {
        gaps_card = gaps_card.child(
            div()
                .pt(px(8.0))
                .child(mono(&format!("and {} more", gaps.len() - shown), DIM)),
        );
    }

    // ---- the thinnest claims, found rather than asserted ----
    let max_sources = k.thin.iter().map(|r| r.sources).max().unwrap_or(1).max(1) as f32;
    let mut thin_card = card().flex().flex_col();
    thin_card = thin_card.child(div().mb(px(4.0)).child(eyebrow("Runs thin")));
    thin_card = thin_card.child(hairline());
    if !k.thin_loaded {
        thin_card = thin_card.child(div().pt(px(12.0)).child(empty_note("Looking for the thinnest claims.")));
    } else if thin.is_empty() {
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
    for (ti, row) in thin.iter().enumerate() {
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
        if ti + 1 < thin.len() {
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
        .child(controls)
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
