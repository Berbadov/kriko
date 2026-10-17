//! Compare: the shortlist board and the table under it. Each slot is an
//! upright product card with a site mark and a pick/clear/reorder control; the
//! comparison puts the columns side by side under three groups (specs,
//! evidence, availability), with per-cell trust and every page behind a claim
//! one click away. "Differences only" hides the rows the columns agree on.
//! Nothing here ranks: it lines up what the saved checks say.
//!
//! Everything is the engine's own record (`/api/history`,
//! `/api/compare-drafts`, `/api/lookup/{id}`), read into `live.compare` and
//! drawn from there.

use gpui::{
    div, prelude::*, px, AnyElement, ClickEvent, Context, Div, FontWeight, Pixels, Window,
};

use crate::app::{Field, Kriko, Tab};
use crate::live::compare::{
    self as live, Check, Level, Loaded, QState, QueueOutcome, QuestionRun, MAX_SLOTS,
};
use crate::marks::{self, mark_tile, phase_beat, Phase};
use crate::screens::history::clip;
use crate::screens::{empty_note, mono, plate_s, row_desc, th, trust_icon};
use crate::sources::{host_of, source_row, source_strip, Source};
use crate::theme::*;

// ---- shared bits ----

/// The agent's own mark by the id the engine knows it by; the built-in mark
/// for one without a mark of its own.
fn mark_for(id: &str) -> &'static marks::Mark {
    match id {
        "claude-code" => &marks::CLAUDE,
        "codex" => &marks::CODEX,
        "opencode" => &marks::OPENCODE,
        "antigravity-cli" => &marks::ANTIGRAVITY,
        "mistral-vibe" => &marks::MISTRAL,
        "github-copilot" => &marks::COPILOT,
        _ => &marks::BUILTIN,
    }
}

/// The engine's own word for a risk's severity, in the chip's look.
fn level_chip(level: Level) -> Div {
    let (glyph, fg, bg): (&[&str], u32, u32) = match level {
        Level::Critical => (&X5, DANGER, DANGER_WASH),
        Level::High => (&BANG5, WARN, WARN_WASH),
        Level::Medium => (&BANG5, INK_2, WELL),
        Level::Low | Level::Unrated => (&QUEUE5, MUTED, WELL),
    };
    div()
        .h(px(24.0))
        .px(px(8.0))
        .flex()
        .flex_none()
        .items_center()
        .gap(px(7.0))
        .rounded(px(7.0))
        // The severity wash carries alpha in its low byte: paint() dropped it
        // and left a solid tint under the same-coloured word.
        .bg(paint_a(bg))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .font_family(MONO)
        .text_size(px(10.0))
        .text_color(paint(fg))
        .child(led_matrix(glyph, fg, 3.0, 1.0))
        .child(level.word())
}

/// A tiny bezel icon button (a slot's clear x).
fn x_button(
    id: impl Into<gpui::ElementId>,
    cx: &mut Context<Kriko>,
    on_click: impl Fn(&mut Kriko, &mut Context<Kriko>) + 'static,
) -> gpui::Stateful<Div> {
    let listener = cx.listener(move |this, _: &ClickEvent, _w, cx| on_click(this, cx));
    div()
        .id(id)
        .w(px(24.0))
        .h(px(24.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(7.0))
        .cursor_pointer()
        .bg(paint_a(GLASS_1))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .hover(|s| s.bg(paint_a(DANGER_WASH)))
        .child(icon("x", 12.0).text_color(paint(MUTED)))
        .on_click(listener)
}

/// A compact action used inside cards.
fn mini_action(id: impl Into<gpui::ElementId>, label: &str) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(26.0))
        .px(px(9.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(7.0))
        .cursor_pointer()
        .font_family(MONO)
        .text_size(px(12.0))
        .text_color(paint(ICE))
        .bg(paint_a(GLASS_1))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .hover(|s| s.bg(paint_a(BRAND_WASH)).border_color(paint_a(BORDER_CONTROL)))
        .child(label.to_string())
}

/// A row's pin: one click marks it as preferred, and the row tints.
fn pin_button(
    id: impl Into<gpui::ElementId>,
    marked: bool,
    cx: &mut Context<Kriko>,
    on_click: impl Fn(&mut Kriko, &mut Context<Kriko>) + 'static,
) -> gpui::Stateful<Div> {
    let listener = cx.listener(move |this, _: &ClickEvent, _w, cx| on_click(this, cx));
    div()
        .id(id)
        .h(px(20.0))
        .px(px(5.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(5.0))
        .cursor_pointer()
        .hover(|s| s.bg(paint_a(GLASS_1)))
        .child(led_matrix(
            if marked { &CHECK5 } else { &QUEUE5 },
            if marked { ICE } else { LED_DIM },
            3.0,
            1.0,
        ))
        .on_click(listener)
}

// ---- pages, as source rows ----

/// The page a specification was read from, named by what it states.
fn spec_source(spec: &live::Spec) -> Option<Source> {
    if spec.source.trim().is_empty() {
        return None;
    }
    Some(Source {
        host: host_of(&spec.source),
        title: format!("{}: {}", spec.label, spec.value),
        url: spec.source.clone(),
        backed: Some(true),
    })
}

/// The page behind a claim, titled by the claim it stands behind.
fn evidence_source(ev: &live::Evidence, claim: &str) -> Source {
    Source {
        host: if ev.host.is_empty() { host_of(&ev.url) } else { ev.host.clone() },
        title: claim.to_string(),
        url: ev.url.clone(),
        backed: Some(ev.backed()),
    }
}

/// Every page a product's knowledge was read from, one per site, in the order
/// the check names them: the slot card's and the column's site marks.
fn check_page_sources(check: &Check) -> Vec<Source> {
    let mut out: Vec<Source> = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    let push = |s: Source, seen: &mut Vec<String>, out: &mut Vec<Source>| {
        if !seen.contains(&s.host) {
            seen.push(s.host.clone());
            out.push(s);
        }
    };
    for spec in &check.specs {
        if let Some(s) = spec_source(spec) {
            push(s, &mut seen, &mut out);
        }
    }
    for risk in &check.risks {
        for ev in &risk.sources {
            push(evidence_source(ev, &risk.title), &mut seen, &mut out);
        }
    }
    out
}

/// (host, url) pairs, as the questions and the queue keep them, read as pages.
fn pair_sources(pairs: &[(String, String)]) -> Vec<Source> {
    pairs
        .iter()
        .filter(|(_, url)| !url.is_empty())
        .map(|(host, url)| Source {
            host: if host.is_empty() { host_of(url) } else { host.to_string() },
            title: url.to_string(),
            url: url.to_string(),
            backed: Some(true),
        })
        .collect()
}

/// A slot's saved-check name while the check itself has not been read.
fn slot_name(app: &Kriko, slot: &Option<String>) -> String {
    slot.as_ref()
        .and_then(|id| app.live.compare.history.iter().find(|h| h.lookup_id == *id))
        .map(|h| h.label.clone())
        .unwrap_or_else(|| "Reading the saved check".to_string())
}

// ---- the board: one upright card per slot ----

/// A slot card: the product's name, the site marks behind it, and the pick,
/// reorder and clear controls. No dragging.
fn slot_card(
    app: &mut Kriko,
    i: usize,
    slot: &Option<String>,
    filled_n: usize,
    motion: bool,
    cx: &mut Context<Kriko>,
) -> gpui::Stateful<Div> {
    let open_picker = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.live.compare.picker =
            if this.live.compare.picker == Some(i) { None } else { Some(i) };
        cx.notify();
    });
    let clear = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
        this.clear_slot(i);
        cx.notify();
    };
    let move_left = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        if i > 0 {
            this.move_slot(i, i - 1);
        }
        cx.notify();
    });
    let move_right = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        if i + 1 < filled_n {
            this.move_slot(i, i + 1);
        }
        cx.notify();
    });

    let nth = ["First", "Second", "Third", "Fourth"][i.min(3)];
    let mut head = div()
        .flex()
        .items_center()
        .gap(px(6.0))
        .child(mono(&nth.to_uppercase(), DIM))
        .child(div().flex_1().min_w(px(0.0)));
    if filled_n > 1 && slot.is_some() {
        head = head
            .child(
                mini_action(("slot-left", i), "‹")
                    .when(i == 0, |d| d.opacity(0.35))
                    .on_click(move_left),
            )
            .child(
                mini_action(("slot-right", i), "›")
                    .when(i + 1 >= filled_n, |d| d.opacity(0.35))
                    .on_click(move_right),
            );
    }
    if slot.is_some() {
        head = head.child(x_button(("slot-clear", i), cx, clear));
    }

    let mut card = well()
        .id(("slot", i))
        .w(px(214.0))
        .flex_none()
        .p(px(10.0))
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(head);

    let loaded = slot.as_ref().and_then(|id| app.live.compare.checks.get(id));
    card = if let Some(Loaded::Ready(check)) = loaded {
        let pages = check_page_sources(check);
        let mut c = card
            .child(
                div()
                    .font_family(SANS)
                    .font_weight(FontWeight::SEMIBOLD)
                    .text_size(px(15.0))
                    .text_color(paint(INK))
                    .whitespace_nowrap()
                    .overflow_hidden()
                    .text_ellipsis()
                    .child(check.name.clone()),
            )
            .child(mono(
                if check.category.is_empty() { "no catalog matched" } else { check.category.as_str() },
                MUTED,
            ));
        if pages.is_empty() {
            c = c.child(mono("no page on record", DIM));
        } else {
            c = c.child(source_strip(&pages[..pages.len().min(3)], motion));
        }
        c.child(mono(&format!("{} sources", check.sources()), DIM))
    } else if let Some(Loaded::Missing(why)) = loaded {
        let retry = cx.listener({
            let id = slot.clone().unwrap_or_default();
            move |this, _: &ClickEvent, _w, cx| this.retry_check(id.clone(), cx)
        });
        card.child(mono("COULD NOT READ THIS CHECK", DANGER))
            .child(row_desc(&clip(why, 110)))
            .child(mini_action(("slot-retry", i), "Retry").on_click(retry))
    } else if slot.is_some() {
        let name = slot_name(app, slot);
        card.child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::SEMIBOLD)
                .text_size(px(15.0))
                .text_color(paint(INK_2))
                .whitespace_nowrap()
                .overflow_hidden()
                .text_ellipsis()
                .child(name),
        )
        .child(div().py(px(2.0)).child(spinner(format!("slot-spin-{i}"), 15.0, motion)))
        .child(mono("Reading saved check…", DIM))
    } else {
        card.child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(icon("plus", 14.0).text_color(paint(DIM)))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(14.0))
                        .text_color(paint(DIM))
                        .child(if filled_n == 1 { "Add a second" } else { "Choose a product" }),
                ),
        )
    };

    card.child(
        div()
            .flex()
            .items_center()
            .gap(px(6.0))
            .child(
                plate_s(("slot-pick", i), if slot.is_some() { "Change" } else { "Choose" })
                    .on_click(open_picker),
            ),
    )
}

/// The board: the slots as a rail of upright cards, one click to pick or
/// clear, the arrows to reorder.
fn slot_board(app: &mut Kriko, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let filled: Vec<Option<String>> = app.live.compare.slots.clone();
    let filled_n = filled.iter().flatten().count();
    // one trailing empty card while there is room, and always a second place
    let mut cards: Vec<Option<String>> = filled.clone();
    if cards.len() < MAX_SLOTS {
        cards.push(None);
    }
    while cards.len() < 2 {
        cards.push(None);
    }
    cards.truncate(MAX_SLOTS);

    let mut rail = div()
        .id("cmp-board-rail")
        .flex()
        .items_start()
        .gap(px(SPACE_CARD))
        .overflow_x_scroll()
        .map(horizontal_wheel);
    for (i, slot) in cards.iter().enumerate() {
        rail = rail.child(slot_card(app, i, slot, filled_n, motion, cx));
    }

    card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(card_head_row(
            "compare",
            "Shortlist",
            Some(mono(&format!("{filled_n} of {MAX_SLOTS}"), DIM).into_any_element()),
            motion,
        ))
        .child(rail)
}

// ---- the comparison table ----
//
// No sideways scroll: the labels are one fixed-width column and the value
// columns divide the rest. When the slots would squeeze the values narrower
// than a page row needs, they wrap into a second band of the same rows, so the
// table never leaves the card's width. The header lines sit outside the body
// scroller, which is why they stay put while the rows scroll.

/// The narrowest a value column gets before the slots wrap into a second band.
const VALUE_MIN_W: f32 = 220.0;
/// The labels' column: fixed, so the attribute names never leave the screen.
const ATTR_W: f32 = 184.0;
/// How much of the table is on screen before its body scrolls. The header
/// above it is outside the scroller and does not move.
const TABLE_BODY_H: f32 = 420.0;

/// One group's sub-header, full width.
fn group_band(label: &str, count: usize) -> Div {
    div()
        .w_full()
        .pt(px(SPACE_M))
        .pb(px(SPACE_XS))
        .flex()
        .items_center()
        .gap(px(SPACE_S))
        .child(th(label))
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(paint(DIM))
                .child(count.to_string()),
        )
}

/// A leading attribute cell: the label and, when it differs, the word. Its
/// last child is the row's pin, so the pin sits at the cell's right edge.
fn attr_cell(width: Pixels, label: &str, note: Option<&str>) -> Div {
    let mut text = div()
        .flex_1()
        .min_w(px(0.0))
        .flex()
        .flex_col()
        .gap(px(SPACE_XS))
        .child(
            div()
                .font_family(SANS)
                .text_size(px(13.0))
                .text_color(paint(INK))
                .child(label.to_string()),
        );
    if let Some(n) = note {
        text = text.child(mono(n, BRAND_BRIGHT));
    }
    div()
        .w(width)
        .flex_none()
        .px(px(SPACE_S))
        .py(px(SPACE_S))
        .flex()
        .items_start()
        .gap(px(SPACE_XS))
        .child(text)
}

/// One column's value cell: the value and whatever backs it. It takes an even
/// share of the width the label column leaves, so rows align without a single
/// fixed column width.
fn value_cell() -> Div {
    div()
        .flex_1()
        .min_w(px(0.0))
        .px(px(SPACE_S))
        .py(px(SPACE_S))
        .flex()
        .flex_col()
        .gap(px(SPACE_XS))
        .border_l_1()
        .border_color(paint_a(HAIRLINE))
}

/// One value cell for a specification.
fn spec_value(cell: &Option<live::Spec>, motion: bool) -> Div {
    let mut c = value_cell();
    match cell {
        Some(spec) => {
            c = c.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(SPACE_XS))
                    .child(
                        div()
                            .flex_1()
                            .min_w(px(0.0))
                            .font_family(SANS)
                            .text_size(px(13.0))
                            .text_color(paint(INK_2))
                            .child(spec.value.clone()),
                    )
                    .child(trust_icon((!spec.source.is_empty()).then_some(true))),
            );
            if let Some(source) = spec_source(spec) {
                c = c.child(source_row(&source, motion));
            }
        }
        None => c = c.child(mono("Not stated", DIM)),
    }
    c
}

/// One value cell for a risk: its level chip, what stands behind it, and every
/// page the engine kept.
fn risk_value(cell: &Option<live::Risk>, motion: bool) -> Div {
    let mut c = value_cell();
    match cell {
        Some(risk) => {
            c = c.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(SPACE_XS))
                    .child(level_chip(risk.level))
                    .child(trust_icon(risk.backed())),
            );
            if !risk.body.is_empty() {
                c = c.child(row_desc(&clip(&risk.body, 180)));
            }
            if risk.sources.is_empty() {
                c = c.child(mono("No source on record", DIM));
            } else {
                for ev in &risk.sources {
                    let source = evidence_source(ev, &risk.title);
                    c = c.child(source_row(&source, motion));
                }
            }
        }
        None => c = c.child(mono("Not recorded", DIM)),
    }
    c
}

/// One value cell from the availability group's plain words.
fn availability_value(value: &str) -> Div {
    value_cell().child(mono(value, if value == "—" { DIM } else { INK_2 }))
}

/// One physical line of the table: the label cell, then a band's value cells.
/// The hairline closes a logical row under its last band, so a wrapped row
/// reads as one row and not as two.
fn table_line(attr: Div, marked: bool, last_band: bool) -> Div {
    div()
        .w_full()
        .flex()
        .when(marked, |d| d.bg(paint_a(BRAND_WASH)))
        .when(last_band, |d| d.border_b_1().border_color(paint_a(HAIRLINE)))
        .child(attr)
}

/// The header line for one band of slots: the attribute name and each slot's
/// product title over the pages behind it. It is built outside the body
/// scroller, so it stays above the rows as they move.
fn band_header_line(
    cis: &[usize],
    names: &[String],
    strips: &[Vec<Source>],
    attr_w: Pixels,
    band_i: usize,
    band_n: usize,
    motion: bool,
) -> Div {
    let mut label = div()
        .w(attr_w)
        .flex_none()
        .flex()
        .items_center()
        .gap(px(SPACE_S))
        .pb(px(SPACE_XS))
        .child(th("Attribute"));
    if band_n > 1 {
        let first = cis.first().map(|ci| ci + 1).unwrap_or(0);
        let last = cis.last().map(|ci| ci + 1).unwrap_or(0);
        label = label.child(mono(&format!("{first}–{last}"), DIM));
    }

    let mut head = div()
        .w_full()
        .flex()
        .items_end()
        .child(label);
    for ci in cis {
        let name = names.get(*ci).map(String::as_str).unwrap_or_default();
        let mut cell = div()
            .flex_1()
            .min_w(px(0.0))
            .px(px(SPACE_S))
            .flex()
            .flex_col()
            .gap(px(SPACE_XS))
            .child(
                div()
                    .font_family(MONO)
                    .text_size(px(11.0))
                    .text_color(paint(DIM))
                    .whitespace_nowrap()
                    .overflow_hidden()
                    .text_ellipsis()
                    .child(name.to_uppercase()),
            );
        cell = match strips.get(*ci) {
            Some(sources) if !sources.is_empty() => {
                let shown = &sources[..sources.len().min(4)];
                cell.child(source_strip(shown, motion))
            }
            _ => cell.child(mono("no page on record", DIM)),
        };
        head = head.child(cell);
    }
    if band_i == 0 {
        head
    } else {
        head.pt(px(SPACE_S))
    }
}

/// A message row spanning the whole table.
fn note_row(text: &str) -> Div {
    div()
        .w_full()
        .px(px(SPACE_S))
        .py(px(SPACE_S))
        .child(row_desc(text))
}

/// The evidence group when nothing is recorded: a card, never blank space,
/// with the pages the checks were read from to ask further questions.
fn no_issue_row(pages: &[Vec<Source>], motion: bool) -> Div {
    let mut row = well()
        .w_full()
        .px(px(SPACE_S))
        .py(px(SPACE_S))
        .flex()
        .flex_col()
        .gap(px(SPACE_XS))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(SPACE_S))
                .child(led_matrix(&CHECK5, INK_2, 3.0, 1.0))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(paint(INK_2))
                        .child("No issue found on record. Not proof there is none."),
                ),
        );
    let mut seen: Vec<String> = Vec::new();
    let mut links = div()
        .flex()
        .items_center()
        .flex_wrap()
        .gap(px(SPACE_S))
        .child(mono("Research further", DIM));
    for list in pages {
        if let Some(source) = list.first() {
            if seen.contains(&source.host) {
                continue;
            }
            seen.push(source.host.clone());
            links = links.child(source_row(source, motion));
        }
    }
    if !seen.is_empty() {
        row = row.child(links);
    }
    row
}

/// The comparison: a leading attribute column, one column per slot, grouped
/// into specs, evidence and availability, with every page one click away.
fn comparison_card(app: &mut Kriko, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let slots: Vec<Option<String>> = app.live.compare.slots.clone();
    let columns: Vec<usize> = (0..slots.len()).filter(|i| slots[*i].is_some()).collect();
    let diff_only = app.live.compare.differences_only && columns.len() >= 2;
    let marks: Vec<String> = app.marks_now().to_vec();

    let mut names: Vec<String> = Vec::new();
    let mut catalog: Vec<String> = Vec::new();
    let mut check_word: Vec<String> = Vec::new();
    let mut sources_n: Vec<String> = Vec::new();
    let mut refs: Vec<Option<&Check>> = Vec::new();
    let mut strips: Vec<Vec<Source>> = Vec::new();
    let mut pages: Vec<Vec<Source>> = Vec::new();
    let mut pending = 0usize;
    let mut unreadable = 0usize;
    for i in &columns {
        match slots[*i].as_ref().and_then(|id| app.live.compare.checks.get(id)) {
            Some(Loaded::Ready(c)) => {
                names.push(c.name.clone());
                catalog.push(if c.category.is_empty() { "not matched".to_string() } else { c.category.clone() });
                check_word.push("read".to_string());
                sources_n.push(c.sources().to_string());
                strips.push(check_page_sources(c));
                pages.push(check_page_sources(c));
                refs.push(Some(c));
            }
            Some(Loaded::Missing(_)) => {
                unreadable += 1;
                names.push(slot_name(app, &slots[*i]));
                catalog.push("—".to_string());
                check_word.push("could not read".to_string());
                sources_n.push("—".to_string());
                strips.push(Vec::new());
                pages.push(Vec::new());
                refs.push(None);
            }
            _ => {
                pending += 1;
                names.push(slot_name(app, &slots[*i]));
                catalog.push("—".to_string());
                check_word.push("reading".to_string());
                sources_n.push("—".to_string());
                strips.push(Vec::new());
                pages.push(Vec::new());
                refs.push(None);
            }
        }
    }
    let specs = live::spec_rows(&refs);
    let risks = live::risk_rows(&refs);

    let attr_w = px(ATTR_W);
    // The card is as wide as the page column less its own inset. The labels
    // keep ATTR_W; the value columns split the rest. When one band would make
    // them narrower than a page row needs, the slots wrap into two balanced
    // bands, so the table never asks for a sideways scroll.
    let table_w = (app.content_w - 2.0 * (PAD_CARD + 2.0)).max(0.0);
    let fitted = column_count((table_w - ATTR_W).max(0.0), VALUE_MIN_W, columns.len());
    let per_band = if columns.len() <= 1 || fitted >= columns.len() {
        columns.len().max(1)
    } else {
        // two bands at most: a wider wrap would leave one lone stretched column
        (columns.len() + 1) / 2
    };
    let bands: Vec<Vec<usize>> = (0..columns.len())
        .collect::<Vec<_>>()
        .chunks(per_band)
        .map(|band| band.to_vec())
        .collect();

    let control: AnyElement = if columns.len() < 2 {
        mono("ADD A SECOND TO COMPARE", DIM).into_any_element()
    } else {
        let toggle = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.live.compare.differences_only = !this.live.compare.differences_only;
            cx.notify();
        });
        div()
            .flex()
            .items_center()
            .gap(px(8.0))
            .child(mono("DIFFERENCES ONLY", DIM))
            .child(switch_anim("cmp-diff-only", diff_only, motion).on_click(toggle))
            .into_any_element()
    };

    // the header: one line per band, pinned above the body scroller
    let mut head = div()
        .w_full()
        .flex()
        .flex_col()
        .flex_none()
        .pb(px(SPACE_S))
        .border_b_1()
        .border_color(paint_a(HAIRLINE));
    for (bi, band) in bands.iter().enumerate() {
        head = head.child(band_header_line(
            band,
            &names,
            &strips,
            attr_w,
            bi,
            bands.len(),
            motion,
        ));
    }

    // the body: the only scroller, so the header above it stays visible
    let mut body = div()
        .id("cmp-table-body")
        .w_full()
        .max_h(px(TABLE_BODY_H))
        .overflow_y_scroll()
        .occlude()
        .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
        .flex()
        .flex_col();

    // ---- specs ----
    let spec_rows: Vec<&live::SpecRow> = specs.iter().filter(|r| !diff_only || r.differs).collect();
    body = body.child(group_band("Specs", spec_rows.len()));
    if spec_rows.is_empty() {
        body = body.child(note_row(
            if specs.is_empty() {
                if pending > 0 {
                    "Reading the saved checks…"
                } else if unreadable > 0 {
                    "A saved check could not be read, so its specifications are missing."
                } else {
                    "No specifications on record for these products."
                }
            } else {
                "Every specification agrees; nothing differs."
            },
        ));
    }
    for (ri, row) in spec_rows.iter().enumerate() {
        let key = format!("spec:{}", row.label);
        let marked = marks.iter().any(|m| m == &key);
        for (bi, band) in bands.iter().enumerate() {
            let mut attr = attr_cell(attr_w, &row.label, row.differs.then_some("DIFFERS"));
            if bi == 0 {
                let pin_key = key.clone();
                attr = attr.child(pin_button(
                    ("spec-pin", ri),
                    marked,
                    cx,
                    move |this: &mut Kriko, cx: &mut Context<Kriko>| {
                        this.toggle_mark(pin_key.clone(), cx);
                        cx.notify();
                    },
                ));
            }
            let mut line = table_line(attr, marked, bi + 1 == bands.len());
            for ci in band {
                line = line.child(spec_value(&row.cells[*ci], motion));
            }
            body = body.child(line);
        }
    }

    // ---- evidence ----
    let risk_rows: Vec<&live::RiskRow> = risks.iter().filter(|r| !diff_only || r.differs).collect();
    body = body.child(group_band("Evidence", risk_rows.len()));
    if risk_rows.is_empty() {
        if risks.is_empty() {
            if pending > 0 {
                body = body.child(note_row("Reading the saved checks…"));
            } else if unreadable > 0 {
                body = body.child(note_row(
                    "A saved check could not be read, so its claims are missing.",
                ));
            } else {
                body = body.child(no_issue_row(&pages, motion));
            }
        } else {
            body = body.child(note_row("Every recorded claim agrees; nothing differs."));
        }
    }
    for (ri, row) in risk_rows.iter().enumerate() {
        let key = format!("risk:{}", row.title);
        let marked = marks.iter().any(|m| m == &key);
        for (bi, band) in bands.iter().enumerate() {
            let mut attr = attr_cell(attr_w, &row.title, row.differs.then_some("DIFFERS"));
            if bi == 0 {
                let pin_key = key.clone();
                attr = attr.child(pin_button(
                    ("risk-pin", ri),
                    marked,
                    cx,
                    move |this: &mut Kriko, cx: &mut Context<Kriko>| {
                        this.toggle_mark(pin_key.clone(), cx);
                        cx.notify();
                    },
                ));
            }
            let mut line = table_line(attr, marked, bi + 1 == bands.len());
            for ci in band {
                line = line.child(risk_value(&row.cells[*ci], motion));
            }
            body = body.child(line);
        }
    }

    // ---- availability: what is on record for each product ----
    let availability = [
        ("Catalog", catalog),
        ("Check", check_word),
        ("Sources", sources_n),
    ];
    let avail_rows: Vec<(&str, Vec<String>)> = availability
        .into_iter()
        .filter(|(_, cells)| !diff_only || cells.windows(2).any(|w| w[0] != w[1]))
        .collect();
    body = body.child(group_band("Availability", avail_rows.len()));
    for (label, cells) in avail_rows {
        for (bi, band) in bands.iter().enumerate() {
            let attr = attr_cell(attr_w, label, None);
            let mut line = table_line(attr, false, bi + 1 == bands.len());
            for ci in band {
                line = line.child(availability_value(
                    cells.get(*ci).map(String::as_str).unwrap_or("—"),
                ));
            }
            body = body.child(line);
        }
    }

    card()
        .flex()
        .flex_col()
        .child(card_head_row("layers", "Comparison", Some(control), motion))
        .child(head)
        .child(body)
}

// ---- the answer, said from the lined-up data ----

fn answer_card(app: &Kriko, motion: bool) -> Option<Div> {
    let refs: Vec<Option<&Check>> = app
        .live
        .compare
        .slots
        .iter()
        .map(|slot| match slot.as_ref().and_then(|id| app.live.compare.checks.get(id)) {
            Some(Loaded::Ready(c)) => Some(c),
            _ => None,
        })
        .collect();
    let said = live::answer_lines(&refs);
    if said.is_empty() {
        return None;
    }
    let mut lines = div().flex().flex_col().gap(px(4.0));
    for line in said {
        lines = lines.child(row_desc(&line));
    }
    Some(
        card()
            .flex()
            .flex_col()
            .gap(px(SPACE_CARD))
            .child(card_head("chart", "What the columns say", motion))
            .child(lines)
            .child(mono("COUNTED FROM THE COLUMNS BELOW", DIM)),
    )
}

// ---- states ----

fn loading_card(motion: bool) -> Div {
    card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(card_head("compare", "Shortlist", motion))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(spinner("cmp-loading", 16.0, motion))
                .child(mono("Reading your saved checks…", DIM)),
        )
}

fn failed_card(error: String, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let retry = cx.listener(|this, _: &ClickEvent, _w, cx| this.load_drafts(true, cx));
    card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(card_head("warning", "Could not read the shortlist", motion))
        .child(row_desc(&format!("The engine said: {error}")))
        .child(plate_s("cmp-drafts-retry", "Retry").on_click(retry))
}

fn empty_card(motion: bool, cx: &mut Context<Kriko>) -> Div {
    let open_queue = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.live.compare.queue_open = true;
        cx.notify();
    });
    let open_picker = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.live.compare.picker = Some(0);
        cx.notify();
    });
    let open_history = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::History;
        cx.notify();
    });
    card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(card_head("compare", "No products yet", motion))
        .child(row_desc("Queue a product from its listing, or pick a saved check."))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .flex_wrap()
                .child(key("cmp-queue-open", "Queue a product").on_click(open_queue))
                .child(plate_s("cmp-pick-open", "Pick a saved check").on_click(open_picker))
                .child(plate_s("cmp-history", "Browse saved checks").on_click(open_history)),
        )
}

fn one_slot_card() -> Div {
    card()
        .flex()
        .items_center()
        .gap(px(8.0))
        .child(icon("plus", 15.0).text_color(paint(BRAND_BRIGHT)))
        .child(row_desc("Add a second product to see where they differ."))
        .child(div().flex_1().min_w(px(0.0)))
        .child(mono("ONE OF ONE", DIM))
}

// ---- the draft bar ----

fn draft_bar(app: &mut Kriko, cx: &mut Context<Kriko>) -> Div {
    let mut row = div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .flex_wrap()
        .child(mono("DRAFTS", DIM));
    let retry = cx.listener(|this, _: &ClickEvent, _w, cx| this.load_drafts(true, cx));
    let open = app.live.compare.draft.clone();
    for (i, draft) in app.live.compare.drafts.iter().enumerate() {
        let id = draft.draft_id.clone();
        let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.select_draft(&id, cx);
            cx.notify();
        });
        let current = open.as_deref() == Some(draft.draft_id.as_str());
        row = row.child(
            div()
                .id(("draft", i))
                .h(px(30.0))
                .px(px(12.0))
                .flex()
                .items_center()
                .rounded(px(8.0))
                .cursor_pointer()
                .font_family(MONO)
                .text_size(px(11.0))
                .when(current, |s| {
                    s.bg(paint(WELL)).border_1().border_color(paint_a(HAIRLINE)).text_color(paint(ICE))
                })
                .when(!current, |s| {
                    s.text_color(paint(MUTED))
                        .hover(|h| h.bg(paint_a(GLASS_1)).text_color(paint(INK)))
                })
                .child(draft.name.clone())
                .on_click(pick),
        );
    }
    if !app.live.compare.drafts_loaded {
        if let Some(error) = app.live.compare.drafts_error.clone() {
            row = row
                .child(mono(&format!("could not read · {error}"), DANGER))
                .child(mini_action("draft-retry-load", "Retry").on_click(retry));
        } else {
            row = row.child(mono("reading…", DIM));
        }
    } else if app.live.compare.drafts.is_empty() {
        row = row.child(mono("none saved yet", DIM));
    }
    let new_draft = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.new_draft(cx);
        cx.notify();
    });
    let save_draft = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.save_draft(cx);
        cx.notify();
    });
    let delete_draft = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.delete_draft(cx);
        cx.notify();
    });
    let revert_draft = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.revert_draft(cx);
        cx.notify();
    });
    let unsaved = app.draft_unsaved();
    let pending = app.live.compare.draft_pending;
    let has_draft = app.live.compare.draft.is_some();
    row = row
        .when(!pending, |d| {
            d.child(plate_s("draft-new", "+ New").on_click(new_draft))
                .child(plate_s("draft-save", if unsaved { "Save changes" } else { "Save" }).on_click(save_draft))
                .when(has_draft, |d| d.child(plate_s("draft-delete", "Delete").on_click(delete_draft)))
                .when(unsaved, |d| d.child(plate_s("draft-revert", "Revert").on_click(revert_draft)))
        })
        .when(pending, |d| d.child(mono("saving…", ICE)))
        .when(unsaved, |d| d.child(mono("UNSAVED SLOTS", DIM)));
    row
}

// ---- the picker ----

fn picker_card(app: &mut Kriko, motion: bool, cx: &mut Context<Kriko>) -> Option<Div> {
    let slot_i = app.live.compare.picker?;
    let slots = app.live.compare.slots.clone();
    let mut list = div().flex().flex_col().flex_none();
    for (ci, item) in app.live.compare.history.iter().enumerate() {
        let taken = !live::slot_available(&slots, slot_i, &item.lookup_id);
        let lookup_id = item.lookup_id.clone();
        let assign = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.assign_slot(slot_i, lookup_id.clone(), cx);
            cx.notify();
        });
        let when_line = if item.category.is_empty() {
            live::ago(&item.created_at)
        } else {
            format!("{} · {}", item.category, live::ago(&item.created_at))
        };
        let mut option = div()
            .id(("pick", ci))
            .py(px(5.0))
            .px(px(12.0))
            .flex()
            .items_center()
            .gap(px(8.0))
            .rounded(px(10.0))
            .when(!taken, |s| s.hover(|h| h.bg(paint_a(GLASS_1))))
            .when(taken, |s| s.opacity(0.35))
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .font_family(SANS)
                    .text_size(px(13.0))
                    .text_color(paint(if taken { MUTED } else { INK }))
                    .child(item.label.clone()),
            )
            .child(mono(&when_line, MUTED));
        if taken {
            option = option.child(mono("In another slot", DIM));
        } else {
            option = option.cursor_pointer().on_click(assign);
        }
        list = list.child(option);
    }
    let close = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.live.compare.picker = None;
        cx.notify();
    });
    let body: AnyElement = if !app.live.compare.history_loaded {
        if let Some(error) = app.live.compare.history_error.clone() {
            let retry = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_compare(cx));
            div()
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(row_desc(&format!("Could not read saved checks: {error}")))
                .child(mini_action("picker-retry-history", "Retry").on_click(retry))
                .into_any_element()
        } else {
            empty_note("Reading your saved checks…").into_any_element()
        }
    } else if app.live.compare.history.is_empty() {
        empty_note("No saved checks yet. Run a check first.").into_any_element()
    } else {
        div()
            .id("picker-scroll")
            .max_h(px(260.0))
            .overflow_y_scroll()
            .occlude()
            .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
            .flex()
            .flex_col()
            .child(list)
            .into_any_element()
    };
    Some(
        card()
            .flex()
            .flex_col()
            .gap(px(4.0))
            .child(card_head_row(
                "list",
                "Pick a saved check",
                Some(plate_s("picker-close", "Close").on_click(close).into_any_element()),
                motion,
            ))
            .child(hairline())
            .child(body),
    )
}

// ---- one agent in a row of agent keys ----

fn agent_key(
    id: impl Into<gpui::ElementId>,
    tile_id: &str,
    agent_id: &str,
    label: &str,
    picked: bool,
    working: bool,
    motion: bool,
) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(36.0))
        .pl(px(5.0))
        .pr(px(12.0))
        .flex()
        .items_center()
        .gap(px(8.0))
        .rounded(px(10.0))
        .cursor_pointer()
        .when(picked, |s| s.bg(paint(WELL)).border_1().border_color(paint_a(BORDER_CONTROL)))
        .when(!picked, |s| s.hover(|h| h.bg(paint_a(GLASS_1))))
        .child(mark_tile(
            tile_id,
            mark_for(agent_id),
            if picked && working { Phase::Thinking } else { Phase::Idle },
            26.0,
            motion,
        ))
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(paint(if picked { ICE } else { MUTED }))
                .child(label.to_string()),
        )
}

// ---- the research queue ----

/// Queue mode: the products queued from the browser extension, researched as
/// many at once as Settings → Runs allows, and the researched ones handed to
/// the slots above as a new draft.
fn queue_card(app: &mut Kriko, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    let c = &app.live.compare;
    let running = c.queue_running;
    let open = c.queue_open || running;
    let n = c.queue.len();
    let done_n = c.queue.iter().filter(|q| q.state == QState::Done).count();
    let ready_n = c
        .queue
        .iter()
        .filter(|q| q.state == QState::Done && !q.lookup_id.is_empty())
        .count();
    let left_n = n - done_n;
    let agent_name = c
        .harnesses
        .iter()
        .find(|(id, _)| *id == c.queue_harness)
        .map(|(_, label)| label.clone())
        .unwrap_or_else(|| "The agent".to_string());
    let working_id = c.queue_harness.clone();

    let mut agent_row = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (i, (id, label)) in c.harnesses.iter().enumerate() {
        let pick = {
            let id = id.clone();
            cx.listener(move |this, _: &ClickEvent, _w, cx| {
                if !this.live.compare.queue_running {
                    this.live.compare.queue_harness = id.clone();
                }
                cx.notify();
            })
        };
        agent_row = agent_row.child(
            agent_key(
                ("queue-agent", i),
                &format!("queue-agent-tile-{i}"),
                id,
                label,
                *id == working_id,
                running,
                motion,
            )
            .on_click(pick),
        );
    }

    let mut rows = div().flex().flex_col();
    for (qi, item) in c.queue.iter().enumerate() {
        let run = c.queue_run.get(&item.queue_id).cloned().unwrap_or_default();
        let phase = match item.state {
            QState::Researching => run.phase.unwrap_or(Phase::Thinking),
            QState::Done => Phase::Idle,
            QState::Waiting => Phase::Off,
        };
        let queue_id = item.queue_id.clone();
        let remove = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
            this.queue_remove(queue_id.clone(), cx);
            cx.notify();
        };
        let (state, word) = match (item.state, &run.note) {
            (QState::Researching, _) => (TagState::Live, "Researching".to_string()),
            (QState::Done, _) => (
                TagState::Done,
                match run.claims {
                    Some(k) => format!("{k} claims"),
                    None => "Researched".to_string(),
                },
            ),
            (QState::Waiting, Some(_)) if run.outcome == Some(QueueOutcome::NotInCatalogs) => {
                (TagState::Need, "Not in catalogs".to_string())
            }
            (QState::Waiting, Some(_)) => (
                TagState::Need,
                if run.outcome == Some(QueueOutcome::Stopped) { "Stopped" } else { "Failed" }.to_string(),
            ),
            (QState::Waiting, None) => (TagState::Queue, "Queued".to_string()),
        };
        let status: AnyElement = match item.state {
            QState::Researching if run.outcome == Some(QueueOutcome::InAnotherWindow) => {
                tag(format!("queue-tag-{qi}"), TagState::Live, "Another window", motion)
                    .into_any_element()
            }
            QState::Researching => {
                phase_beat(&format!("queue-beat-{qi}"), phase, motion).into_any_element()
            }
            _ => tag(format!("queue-tag-{qi}"), state, &word, motion).into_any_element(),
        };
        let since = live::ago(&item.added_at);
        let sub = match (item.state, &run.note) {
            (QState::Researching, _) => run.line.clone(),
            (QState::Done, _) => format!("from {} · ready to compare", item.origin),
            (QState::Waiting, Some(note)) => format!("from {} · {}", item.origin, note),
            (QState::Waiting, None) => format!("from {} · queued {}", item.origin, since),
        };
        let progress = match item.state {
            QState::Done => 100.0,
            QState::Researching => app.live.run.bar_value(&run.job, run.progress / 100.0, motion) * 100.0,
            QState::Waiting => 0.0,
        };
        rows = rows.child(
            div()
                .py(px(4.0))
                .flex()
                .items_center()
                .gap(px(SPACE_CARD))
                .child(
                    icon(
                        match item.state {
                            QState::Researching => "activity",
                            QState::Done => "check-circle",
                            QState::Waiting => "clock",
                        },
                        13.0,
                    )
                    .text_color(paint(match item.state {
                        QState::Researching => ICE,
                        QState::Done => INK_2,
                        QState::Waiting => DIM,
                    })),
                )
                .child(mono(&format!("{:02}", qi + 1), DIM))
                .child(mark_tile(
                    &format!("queue-row-tile-{qi}"),
                    mark_for(&working_id),
                    phase,
                    34.0,
                    motion,
                ))
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
                                .text_size(px(14.0))
                                .text_color(paint(if item.state == QState::Waiting { INK_2 } else { INK }))
                                .child(item.title()),
                        )
                        .child(mono(&sub, MUTED)),
                )
                .child(div().w(px(150.0)).flex_none().child(meter_slim(progress, 12)))
                .child(div().w(px(132.0)).flex_none().flex().child(status))
                .child(
                    div().w(px(24.0)).flex_none().children(
                        (item.state != QState::Researching)
                            .then(|| x_button(("queue-remove", qi), cx, remove).into_any_element()),
                    ),
                ),
        );
        if qi + 1 < n {
            rows = rows.child(hairline());
        }
    }
    if n == 0 {
        rows = rows.child(div().py(px(4.0)).child(row_desc(if c.queue_loaded {
            "Nothing queued. Queue a product from its listing."
        } else {
            "Reading the queue…"
        })));
    }

    let start = cx.listener(|this, _: &ClickEvent, _w, cx| {
        if this.live.compare.queue_running {
            this.queue_stop();
        } else {
            this.queue_start(cx);
        }
        cx.notify();
    });
    let to_compare = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.queue_to_compare(cx);
        cx.notify();
    });
    let clear_done = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.queue_clear_done(cx);
        cx.notify();
    });
    let auto_on = c.queue_auto;
    let auto_toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.set_queue_auto(!auto_on, cx);
        cx.notify();
    });
    let overall = if n == 0 {
        0.0
    } else {
        c.queue
            .iter()
            .map(|q| match q.state {
                QState::Done => 100.0,
                QState::Researching => c
                    .queue_run
                    .get(&q.queue_id)
                    .map(|r| app.live.run.bar_value(&r.job, r.progress / 100.0, motion) * 100.0)
                    .unwrap_or(0.0),
                QState::Waiting => 0.0,
            })
            .sum::<f32>()
            / n as f32
    };
    let summary = if let Some(error) = c.queue_error.as_deref() {
        format!("could not read queue · {error}")
    } else if !c.queue_loaded {
        "reading".to_string()
    } else if running {
        let at_once = c.queue.iter().filter(|q| q.state == QState::Researching).count();
        let together = if at_once > 1 { format!(" {at_once} at once") } else { String::new() };
        format!("{agent_name} researching{together} · {done_n} of {n} done")
    } else if n > 0 && left_n == 0 {
        format!("all {n} researched · ready to compare")
    } else if n == 0 {
        "nothing queued".to_string()
    } else if left_n > 1 && app.run_concurrency <= 1 {
        format!("{left_n} waiting · {done_n} researched · one at a time")
    } else {
        format!("{left_n} waiting · {done_n} researched")
    };
    let can_start = running
        || (c.queue.iter().any(|q| q.state == QState::Waiting) && !c.harnesses.is_empty());
    let retrying = c.queue.iter().any(|q| {
        q.state == QState::Waiting
            && c.queue_run.get(&q.queue_id).is_some_and(|run| run.outcome.is_some())
    });

    let keys = div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .flex_wrap()
        .when(can_start, |d| {
            d.child(
                key(
                    "queue-start",
                    if running {
                        "Stop queue"
                    } else if retrying {
                        "Retry waiting"
                    } else {
                        "Start queue"
                    },
                )
                .on_click(start),
            )
        })
        .when(ready_n >= 2, |d| {
            d.child(
                plate_s(
                    "queue-compare",
                    &if ready_n > MAX_SLOTS {
                        format!("Compare first {MAX_SLOTS}")
                    } else {
                        format!("Compare {ready_n}")
                    },
                )
                .on_click(to_compare),
            )
        })
        .when(done_n > 0 && !running, |d| {
            d.child(plate_s("queue-clear", "Clear done").on_click(clear_done))
        })
        .child(div().flex_1().min_w(px(0.0)))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(6.0))
                .child(mono("OPEN DRAFT WHEN DONE", DIM))
                .child(switch_anim("queue-auto", auto_on, motion).on_click(auto_toggle)),
        );

    let toggle_open = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.live.compare.queue_open = !this.live.compare.queue_open;
        cx.notify();
    });
    let retry_queue_load = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.load_queue(cx);
    });
    let details = if open {
        let queue_rows: AnyElement = if let Some(error) = c.queue_error.as_deref() {
            div()
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(row_desc(&format!("Could not read the research queue: {error}")))
                .child(mini_action("queue-load-retry", "Retry").on_click(retry_queue_load))
                .into_any_element()
        } else {
            well()
                .id("queue-list-scroll")
                .px(px(14.0))
                .py(px(4.0))
                .max_h(px(280.0))
                .overflow_y_scroll()
                .occlude()
                .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
                .child(rows)
                .into_any_element()
        };
        div()
            .flex()
            .flex_col()
            .gap(px(SPACE_CARD))
            .child(row_desc("Queued products are researched in order, up to your concurrency setting."))
            .child(meter_live("queue-overall", overall, 28, running, motion))
            .child(if c.harnesses.is_empty() {
                empty_note("No agent is ready on this machine. Settings shows which ones Kriko can start.")
                    .into_any_element()
            } else {
                agent_row.into_any_element()
            })
            .child(
                well()
                    .px(px(14.0))
                    .py(px(4.0))
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(icon("extension", 16.0).text_color(paint(ICE)))
                    .child(div().flex_1().min_w(px(0.0)).child(row_desc(
                        "On a listing, open the Kriko panel and press Add to queue.",
                    )))
                    .child(keycap("Alt"))
                    .child(keycap("K")),
            )
            .child(queue_rows)
    } else {
        div()
    };

    card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(
            div()
                .id("queue-toggle")
                .flex()
                .flex_col()
                .cursor_pointer()
                .on_click(toggle_open)
                .child(card_head_row(
                    "play",
                    "Research queue",
                    Some(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(6.0))
                            .child(mono(&summary, if running { ICE } else { MUTED }))
                            .child(
                                icon(if open { "chevron-down" } else { "arrow-right" }, 14.0)
                                    .text_color(paint(if open { ICE } else { MUTED })),
                            )
                            .into_any_element(),
                    ),
                    motion,
                )),
        )
        .child(details)
        .child(keys)
}

// ---- follow-up questions ----

fn question_sources(sources: &[(String, String)], motion: bool) -> Option<Div> {
    let list = pair_sources(sources);
    if list.is_empty() {
        return None;
    }
    let mut detail = div()
        .flex()
        .flex_col()
        .gap(px(4.0))
        .child(mono(&format!("Sources read · {}", list.len()), DIM));
    for source in &list {
        detail = detail.child(source_row(source, motion));
    }
    Some(detail)
}

fn question_run_detail(run: &QuestionRun, saved_sources: &[(String, String)], motion: bool) -> Div {
    let mut detail = div().pl(px(24.0)).flex().flex_col().gap(px(5.0));
    if !run.state.is_empty() {
        let stage = if run.state == "succeeded" { "Complete" }
            else if run.state == "failed" { "Failed" }
            else if run.state == "cancelled" { "Cancelled" }
            else { "In progress" };
        detail = detail.child(mono(
            &format!("{} · {:.0}% · {}", stage, (run.progress * 100.0).clamp(0.0, 100.0), run.message),
            MUTED,
        ));
    }
    if !run.saved_checks.is_empty() {
        let checks = run.saved_checks.iter()
            .map(|(name, risks)| format!("{name} ({risks} known risks)"))
            .collect::<Vec<_>>().join(" · ");
        detail = detail.child(mono(&format!("Saved checks: {checks}"), MUTED));
    }
    if !run.steps.is_empty() {
        detail = detail.child(mono("STEPS", DIM));
        for step in &run.steps {
            detail = detail.child(mono(&format!("• {step}"), MUTED));
        }
    }
    if !run.model.is_empty() {
        detail = detail.child(mono(&format!("Model: {}", run.model), MUTED));
    }
    if run.state == "succeeded" {
        let usage = match run.tokens_used {
            Some(total) => {
                let parts = match (run.tokens_in, run.tokens_out) {
                    (Some(input), Some(output)) => format!(" ({input} in, {output} out)"),
                    _ => String::new(),
                };
                format!("{total} tokens{parts}")
            }
            None => "Token use not reported".to_string(),
        };
        detail = detail.child(mono(&usage, MUTED));
    }
    let sources = if run.sources.is_empty() { saved_sources } else { &run.sources };
    if let Some(source_rows) = question_sources(sources, motion) {
        detail = detail.child(source_rows);
    } else if run.state == "succeeded" && run.web_searches.is_some_and(|count| count > 0) {
        detail = detail.child(mono("No source pages were reported for this answer", DIM));
    }
    detail
}

fn questions_card(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    let ask_input = app.input_field(
        Field::CompareAsk,
        "compare-ask",
        "Ask about this shortlist...",
        Some("agents"),
        window,
        cx,
    );
    let ask = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.ask_compare_question(cx);
        cx.notify();
    });
    let mut suggestions = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (i, text) in crate::data::COMPARE_SUGGESTIONS.iter().enumerate() {
        let fill = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.compare_question_input.set_value(text.to_string());
            cx.notify();
        });
        suggestions = suggestions.child(
            div()
                .id(("sugg", i))
                .h(px(30.0))
                .px(px(12.0))
                .flex()
                .items_center()
                .rounded(px(8.0))
                .cursor_pointer()
                .bg(paint(WELL))
                .border_1()
                .border_color(paint_a(HAIRLINE))
                .hover(|s| s.border_color(paint_a(BORDER_CONTROL)))
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(paint(INK_2))
                .child(text.to_string())
                .on_click(fill),
        );
    }

    let ready_n = app
        .live
        .compare
        .slots
        .iter()
        .flatten()
        .filter(|id| matches!(app.live.compare.checks.get(*id), Some(Loaded::Ready(_))))
        .count();
    let attached = format!("saved checks: {ready_n}");
    let waiting_answer = app.live.compare.asking
        || app.live.compare.questions.iter().any(|q| {
            q.answer.is_none() && !app.live.compare.failed.contains_key(&q.question_id)
        });
    let mut agent_row = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (ai, (id, label)) in app.live.compare.harnesses.iter().enumerate() {
        let pick = {
            let id = id.clone();
            cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.live.compare.harness = id.clone();
                cx.notify();
            })
        };
        agent_row = agent_row.child(
            agent_key(
                ("cmp-agent", ai),
                &format!("cmp-agent-tile-{ai}"),
                id,
                label,
                *id == app.live.compare.harness,
                waiting_answer,
                motion,
            )
            .on_click(pick),
        );
    }

    let draft_name = app
        .live
        .compare
        .draft
        .as_ref()
        .and_then(|id| app.live.compare.drafts.iter().find(|d| d.draft_id == *id))
        .map(|d| d.name.clone())
        .unwrap_or_default();
    let mut questions = div().flex().flex_col().gap(px(6.0));
    let saved_questions = app.live.compare.questions.clone();
    for (qi, q) in saved_questions.iter().enumerate() {
        let failure = app.live.compare.failed.get(&q.question_id);
        let run = app.live.compare.question_runs.get(&q.job_id);
        let retry = {
            let text = q.text.clone();
            cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.compare_question_input.set_value(text.clone());
                this.ask_compare_question(cx);
                cx.notify();
            })
        };
        questions = questions.child(
            well()
                .p(px(PAD_CARD_TIGHT))
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(6.0))
                        .child(icon("agents", 14.0).text_color(paint(BRAND_BRIGHT)))
                        .child(
                            div()
                                .min_w(px(0.0))
                                .font_family(SANS)
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_size(px(14.0))
                                .text_color(paint(INK))
                                .child(q.text.clone()),
                        ),
                )
                .child(match (&q.answer, failure) {
                    (Some(a), _) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(
                            div().flex().items_center().gap(px(8.0)).child(tag(
                                format!("compare-answered-{qi}"),
                                TagState::Done,
                                "answered",
                                motion,
                            )),
                        )
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .line_height(px(21.0))
                                .text_color(paint(INK_2))
                                .child(a.clone()),
                        ),
                    (None, Some(why)) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(
                            div().flex().items_center().gap(px(8.0)).child(tag(
                                format!("compare-failed-{qi}"),
                                TagState::Need,
                                "no answer",
                                motion,
                            )),
                        )
                        .child(row_desc(why))
                        .child(mini_action(("compare-retry-question", qi), "Ask again").on_click(retry)),
                    (None, None) if run.is_some_and(|r| {
                        matches!(r.state.as_str(), "failed" | "cancelled" | "interrupted")
                    }) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(tag(format!("compare-terminal-{qi}"), TagState::Need, "no answer", motion))
                        .child(row_desc(
                            run.map(|r| r.message.as_str()).unwrap_or("The agent stopped before answering."),
                        ))
                        .child(mini_action(("compare-retry-terminal", qi), "Ask again").on_click(retry)),
                    (None, None) if run.is_some_and(|r| !r.answer.trim().is_empty()) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(
                            div().flex().items_center().gap(px(8.0)).child(tag(
                                format!("compare-streaming-{qi}"),
                                TagState::Live,
                                "writing answer",
                                motion,
                            )),
                        )
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .line_height(px(21.0))
                                .text_color(paint(INK_2))
                                .child(run.map(|r| r.answer.clone()).unwrap_or_default()),
                        ),
                    (None, None) if run.is_some_and(|r| r.state == "succeeded") => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(tag(format!("compare-empty-{qi}"), TagState::Need, "no text returned", motion))
                        .child(mini_action(("compare-retry-empty", qi), "Ask again").on_click(retry)),
                    (None, None) if q.job_id.is_empty() => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(tag(format!("compare-untracked-{qi}"), TagState::Need, "no job saved", motion))
                        .child(row_desc("This question cannot be tracked. Ask it again."))
                        .child(
                            mini_action(gpui::ElementId::named_usize("compare-retry-untracked", qi), "Ask again")
                                .on_click(retry),
                        ),
                    (None, None) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(
                            div().flex().items_center().gap(px(8.0)).child(tag(
                                format!("compare-asking-{qi}"),
                                TagState::Live,
                                "answering",
                                motion,
                            )),
                        ),
                })
                .children(run.map(|run| {
                    let mut detail = question_run_detail(run, &q.sources, motion);
                    let live = !run.state.is_empty()
                        && !matches!(
                            run.state.as_str(),
                            "succeeded" | "failed" | "cancelled" | "interrupted"
                        );
                    if live {
                        detail = detail.child(progress_bar(
                            &format!("compare-question-bar-{qi}"),
                            app.live.run.bar_value(&q.job_id, run.progress, motion),
                            motion,
                        ));
                    }
                    detail
                })
                    .or_else(|| question_sources(&q.sources, motion)
                        .map(|sources| div().pl(px(24.0)).child(sources))))
                .child(mono(
                    &format!(
                        "kept with {} · asked {}",
                        if draft_name.is_empty() { "this draft" } else { draft_name.as_str() },
                        live::ago(&q.asked_at)
                    ),
                    DIM,
                )),
        );
    }
    for q in &saved_questions {
        if let Some(job) = app.live.run.jobs.iter().find(|job| job.id == q.job_id).cloned() {
            questions = questions.child(crate::screens::logs::job_logs(app, &job, cx));
        }
    }

    card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(card_head("question", "Ask about this comparison", motion))
        .child(row_desc("Ask about the shortlist; the saved checks stay the evidence."))
        .child(if app.live.compare.harnesses.is_empty() {
            let open_local = cx.listener(|this, _: &ClickEvent, _w, cx| {
                this.tab = Tab::Local;
                cx.notify();
            });
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(empty_note("No agent or local model is ready."))
                .child(ghost("compare-open-local", "Set up Local LLM").on_click(open_local))
                .into_any_element()
        } else {
            agent_row.into_any_element()
        })
        .children((!app.live.compare.local_note.is_empty()).then(|| {
            row_desc(&format!("Local agent: {}", app.live.compare.local_note))
        }))
        .child(div().font_family(MONO).text_size(px(11.0)).text_color(paint(MUTED)).child(attached))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .flex_wrap()
                .child(div().flex_1().min_w(px(260.0)).child(ask_input))
                .child(key("cmp-ask", if app.live.compare.asking { "Asking..." } else { "Ask" }).on_click(ask)),
        )
        .child(suggestions)
        .child(questions)
}

// ---- the screen ----

pub fn compare(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;

    let drafts = draft_bar(app, cx);
    let say = app.live.compare.say.clone();
    let picker = picker_card(app, motion, cx);
    let filled_n = app.live.compare.slots.iter().flatten().count();
    let loaded = app.live.compare.loaded;
    let error = app.live.compare.drafts_error.clone();

    let mut page = div().flex().flex_col().min_w(px(0.0)).gap(px(SPACE_SECTION));
    let mut index = 0usize;
    page = page.child(enter(drafts, "cmp-drafts", index, motion));
    index += 1;
    if let Some(say) = say {
        page = page.child(enter(
            div()
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(paint(DANGER))
                .child(say),
            "cmp-notice",
            index,
            motion,
        ));
        index += 1;
    }
    if let Some(picker) = picker {
        page = page.child(enter(picker, "cmp-picker", index, motion));
        index += 1;
    }

    if !loaded {
        page = if let Some(error) = error {
            page.child(enter(failed_card(error, motion, cx), "cmp-failed", index, motion))
        } else {
            page.child(enter(loading_card(motion), "cmp-loading", index, motion))
        };
        index += 1;
    } else if filled_n == 0 {
        page = page.child(enter(empty_card(motion, cx), "cmp-empty", index, motion));
        index += 1;
    } else {
        page = page.child(enter(slot_board(app, motion, cx), "cmp-board", index, motion));
        index += 1;
        if filled_n == 1 {
            page = page.child(enter(one_slot_card(), "cmp-one", index, motion));
            index += 1;
        }
        if let Some(answer) = answer_card(app, motion) {
            page = page.child(enter(answer, "cmp-answer", index, motion));
            index += 1;
        }
        page = page.child(enter(
            comparison_card(app, motion, cx),
            "cmp-table",
            index,
            motion,
        ));
        index += 1;
    }

    page = page.child(enter(questions_card(app, window, cx), "cmp-questions", index, motion));
    index += 1;
    page.child(enter(queue_card(app, cx), "cmp-queue", index, motion))
}
