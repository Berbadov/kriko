//! Benchmark: how long the parts of a check take on this machine.
//! A wide run plate, the LED bars of the previous runs, and the raw numbers.

use gpui::{div, point, prelude::*, px, rgb, Context, Div, Styled, Window};

use crate::app::Kriko;
use crate::data;
use crate::screens::{mono, row_desc};
use crate::theme::*;

/// A horizontal LED bar: `value` 0..=100 of 28 segments lit.
fn led_bar(value: u8, color: u32) -> Div {
    let lit = ((value as f32 / 100.0) * 28.0).round() as usize;
    let mut bar = div().flex().gap(px(2.0));
    for i in 0..28 {
        let d = div().w(px(8.0)).h(px(14.0)).rounded(px(1.5));
        bar = bar.child(if i < lit {
            d.bg(rgb(color)).shadow(vec![gpui::BoxShadow {
                color: hsla(color),
                offset: point(px(0.0), px(0.0)),
                blur_radius: px(5.0),
                spread_radius: px(0.0),
            }])
        } else {
            d.bg(rgb(LED_OFF))
        });
    }
    bar
}

pub fn benchmark(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let run = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.running = !this.running;
        cx.notify();
    });

    let start_panel = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(24.0))
                .child(plate_wide("bench-run", "Run benchmark").on_click(run))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_desc("Times every stage of a check with the packs that are enabled now."))
                        .child(mono("Last benchmark: 2 min ago", DIM)),
                ),
        )
        .when(app.running, |d| d.child(tag(TagState::Live, "Running", motion)))
        .when(!app.running, |d| d.child(tag(TagState::Done, "Idle", motion)));

    let mut bars = card().flex().flex_col();
    bars = bars.child(div().mb(px(12.0)).child(eyebrow("Previous runs")));
    for (i, entry) in data::BENCH_RUNS.iter().enumerate() {
        let color = if i == 0 { ICE } else { LED_DIM };
        bars = bars.child(
            div()
                .py(px(12.0))
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .justify_between()
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .text_color(rgb(INK_2))
                                .child(entry.label.to_string()),
                        )
                        .child(mono(entry.took, MUTED)),
                )
                .child(led_bar(entry.value, color)),
        );
        if i + 1 < data::BENCH_RUNS.len() {
            bars = bars.child(hairline());
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(start_panel)
        .child(bars)
}
