//! The tab screens. Each screen is a function over the shared [`Kriko`] state;
//! anything a screen changes, it changes through `cx.listener`, so the whole
//! app re-renders from one place.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba, ClickEvent, Context, Div,
    FontWeight, Stateful, Styled, Window,
};

use crate::app::Kriko;
use crate::data::Severity;
use crate::theme::*;

pub(crate) mod about;
pub(crate) mod activity;
pub(crate) mod agents;
pub(crate) mod benchmark;
pub(crate) mod browse;
pub(crate) mod compare;
pub(crate) mod extension;
pub(crate) mod history;
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
    let id_key = ((current as u64) << 8) | (prev as u64) | (options.len() as u64) << 16;
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
        .bg(linear_gradient(
            180.0,
            linear_color_stop(hsla(BEZEL_HI), 0.0),
            linear_color_stop(hsla(BEZEL_LO), 1.0),
        ))
        .shadow(vec![shadow(0x00000099, 0.0, 4.0, 10.0, 0.0)])
        .hover(|s| s.text_color(rgb(INK)))
        .active(|s| s.mt(px(1.0)).shadow(vec![]))
        .child(label.to_uppercase())
}

// ---- compare + local helpers ----

/// A risk severity word in its own tint, with its LED glyph: the status
/// icon of a risk cell. MINOR sits quiet; SERIOUS and CRITICAL run hot.
pub fn severity_chip(severity: Severity) -> Div {
    let (glyph, fg, bg): (&[&str], u32, u32) = match severity {
        Severity::Minor => (&QUEUE5, MUTED, WELL),
        Severity::Serious => (&BANG5, 0xffb86b, 0xffb86b1f),
        Severity::Critical => (&X5, DANGER, DANGER_WASH),
    };
    div()
        .h(px(24.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .gap(px(7.0))
        .rounded(px(7.0))
        .bg(rgb(bg))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .font_family(MONO)
        .text_size(px(10.0))
        .text_color(rgb(fg))
        .child(led_matrix(glyph, fg, 3.0, 1.0))
        .child(severity.word())
}

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

