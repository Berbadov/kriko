//! The tab screens. Each screen is a function over the shared [`Kriko`] state;
//! anything a screen changes, it changes through `cx.listener`, so the whole
//! app re-renders from one place.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, ClickEvent, Context, Div,
    FontWeight, Stateful, Styled, Window,
};

use crate::app::Kriko;
use crate::theme::*;

pub(crate) mod about;
pub(crate) mod activity;
pub(crate) mod agents;
pub(crate) mod benchmark;
pub(crate) mod browse;
pub(crate) mod compare;
pub(crate) mod extension;
pub(crate) mod history;
pub(crate) mod logs;
pub(crate) mod home;
pub(crate) mod knowledge;
pub(crate) mod local;
pub(crate) mod run;
pub(crate) mod settings;
pub(crate) mod sites;

/// Dispatch to the active tab's screen.
pub fn screen(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> gpui::AnyElement {
    match app.tab {
        crate::app::Tab::Home => home::home(app, window, cx).into_any_element(),
        crate::app::Tab::Run => run::run(app, window, cx).into_any_element(),
        crate::app::Tab::History => history::history(app, window, cx).into_any_element(),
        crate::app::Tab::Compare => compare::compare(app, window, cx).into_any_element(),
        crate::app::Tab::Extension => extension::extension(app, window, cx).into_any_element(),
        crate::app::Tab::Overview => knowledge::overview(app, window, cx).into_any_element(),
        crate::app::Tab::Browse => browse::browse(app, window, cx).into_any_element(),
        crate::app::Tab::Sites => sites::sites(app, window, cx).into_any_element(),
        crate::app::Tab::Activity => activity::activity(app, window, cx).into_any_element(),
        crate::app::Tab::Agents => agents::agents(app, window, cx).into_any_element(),
        crate::app::Tab::Benchmark => benchmark::benchmark(app, window, cx).into_any_element(),
        crate::app::Tab::Local => local::local(app, window, cx).into_any_element(),
        crate::app::Tab::Settings => settings::settings(app, window, cx).into_any_element(),
        crate::app::Tab::About => about::about(app, window, cx).into_any_element(),
    }
    .into_any_element()
}

// ---- shared building blocks ----

/// A big-number card: eyebrow, display value, mono note. Home's totals and
/// knowledge's totals share it.
pub fn total_card(label: &str, value: &str, note: &str) -> Div {
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

/// Sans title of a settings-style row.
pub fn row_title(text: &str) -> Div {
    div()
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(15.0))
        .text_color(rgb(INK))
        .child(text.to_string())
}

/// Muted description under a row title.
pub fn row_desc(text: &str) -> Div {
    div()
        .font_family(SANS)
        .text_size(px(13.0))
        .text_color(rgb(MUTED))
        .child(text.to_string())
}

/// What a card shows while its slice of the engine has not arrived, or when
/// the engine holds nothing for it: one quiet well, never sample numbers.
pub fn empty_note(text: &str) -> Div {
    well()
        .px(px(16.0))
        .py(px(14.0))
        .font_family(SANS)
        .text_size(px(13.0))
        .text_color(rgb(DIM))
        .child(text.to_string())
}

/// Mono table cell text.
pub fn mono(text: &str, color: u32) -> Div {
    div()
        .font_family(MONO)
        .text_size(px(12.0))
        .text_color(rgb(color))
        .child(text.to_string())
}

/// A table header cell: mono capitals in DIM.
pub fn th(label: &str) -> Div {
    div()
        .font_family(MONO)
        .text_size(px(11.0))
        .text_color(rgb(DIM))
        .child(label.to_uppercase())
}

/// The Segmented control (k-seg): LED-glyph cells in a well, the bezel thumb
/// sliding to the picked one. `current`/`prev` drive the slide; `motion ==
/// false` snaps the thumb instead.
pub fn segmented(
    id: &'static str,
    options: &[(&'static str, [&'static str; 5])],
    current: usize,
    prev: usize,
    motion: bool,
    cx: &mut Context<Kriko>,
    on_pick: impl Fn(&mut Kriko, usize, &mut Context<Kriko>) + Copy + 'static,
) -> Div {
    // The thumb's animation id mixes this control's id into the state, so
    // two segmented controls never share one animation.
    let mut id_hash = 0u64;
    for byte in id.bytes() {
        id_hash = id_hash.wrapping_mul(31).wrapping_add(byte as u64);
    }
    let id_key = id_hash.rotate_left(24)
        | ((current as u64) << 8)
        | prev as u64
        | (options.len() as u64) << 16;
    let mut track = segmented_track().child(segmented_thumb(id_key, prev, current, motion));
    for (i, (_, glyph)) in options.iter().enumerate() {
        let listener = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            on_pick(this, i, cx);
        });
        track = track.child(
            segmented_cell((id, i), *glyph, i == current).on_click(listener),
        );
    }
    track
}

/// A small bezel button (pagination, small actions).
pub fn plate_s(id: impl Into<gpui::ElementId>, label: &str) -> Stateful<Div> {
    div()
        .id(id)
        .h(px(36.0))
        .px(px(16.0))
        .flex()
        .items_center()
        .justify_center()
        .gap(px(8.0))
        .rounded(px(10.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .text_color(rgb(INK_2))
        .cursor_pointer()
        .border_1()
        .border_color(rgb(BEZEL_EDGE))
        .bg(rgb(BEZEL_LO))
        .hover(|s| s.bg(rgb(BEZEL_HI)).text_color(rgb(INK)))
        .active(|s| s.bg(rgb(WELL)))
        .child(label.to_uppercase())
}

/// A control in a filter bar: flat glass with a control ring that lights when
/// the panel it opens is showing. `chevron` marks the ones that open a panel.
pub fn filter_btn(id: impl Into<gpui::ElementId>, label: &str, open: bool, chevron: bool) -> Stateful<Div> {
    div()
        .id(id)
        .h(px(40.0))
        .px(px(14.0))
        .flex()
        .flex_none()
        .items_center()
        .justify_center()
        .gap(px(8.0))
        .rounded(px(10.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .cursor_pointer()
        .text_color(rgb(if open { ICE } else { INK_2 }))
        .bg(rgba(GLASS_1))
        .border_1()
        .border_color(rgba(BORDER_CONTROL))
        .when(open, |s| s.border_color(rgb(ICE)))
        .hover(|s| s.bg(rgba(GLASS_2)).text_color(rgb(INK)))
        .child(label.to_uppercase())
        .when(chevron, |s| {
            s.child(icon(if open { "collapse" } else { "chevron-down" }, 12.0).text_color(rgb(MUTED)))
        })
}

// ---- compare + local helpers ----

/// One spec cell's trust status icon: BACKED (check), DISPUTED (bang),
/// NO EVIDENCE (queue), or nothing when nothing is recorded.
pub fn trust_icon(backed: Option<bool>) -> gpui::AnyElement {
    match backed {
        Some(true) => led_matrix(&CHECK5, ICE, 3.0, 1.0),
        Some(false) => led_matrix(&BANG5, 0xffb86b, 3.0, 1.0),
        None => led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0),
    }
}

/// The - / + stepper around a mono value: how a number parameter is set.
/// `value` is already formatted.
pub fn stepper(
    id: &'static str,
    value: String,
    cx: &mut Context<Kriko>,
    on_minus: impl Fn(&mut Kriko, &mut Context<Kriko>) + Copy + 'static,
    on_plus: impl Fn(&mut Kriko, &mut Context<Kriko>) + Copy + 'static,
) -> Div {
    let minus = cx.listener(move |this, _: &ClickEvent, _w, cx| on_minus(this, cx));
    let plus = cx.listener(move |this, _: &ClickEvent, _w, cx| on_plus(this, cx));
    div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .child(
            div()
                .id((id, 0usize))
                .w(px(28.0))
                .h(px(28.0))
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(8.0))
                .font_family(MONO)
                .text_size(px(13.0))
                .text_color(rgb(INK_2))
                .cursor_pointer()
                .border_1()
                .border_color(rgb(BEZEL_EDGE))
                .bg(linear_gradient(
                    180.0,
                    linear_color_stop(hsla(BEZEL_HI), 0.0),
                    linear_color_stop(hsla(BEZEL_LO), 1.0),
                ))
                .hover(|s| s.text_color(rgb(INK)))
                .child("−")
                .on_click(minus),
        )
        .child(
            div()
                .min_w(px(84.0))
                .h(px(28.0))
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(8.0))
                .bg(rgb(WELL))
                .border_1()
                .border_color(rgba(HAIRLINE))
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(INK_2))
                .child(value),
        )
        .child(
            div()
                .id((id, 1usize))
                .w(px(28.0))
                .h(px(28.0))
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(8.0))
                .font_family(MONO)
                .text_size(px(13.0))
                .text_color(rgb(INK_2))
                .cursor_pointer()
                .border_1()
                .border_color(rgb(BEZEL_EDGE))
                .bg(linear_gradient(
                    180.0,
                    linear_color_stop(hsla(BEZEL_HI), 0.0),
                    linear_color_stop(hsla(BEZEL_LO), 1.0),
                ))
                .hover(|s| s.text_color(rgb(INK)))
                .child("+")
                .on_click(plus),
        )
}

