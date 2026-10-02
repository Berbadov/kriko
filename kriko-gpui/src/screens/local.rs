//! Local LLM: a local model, for checks that never leave this machine.
//! The server card, the model table with its parameters and status icons,
//! the tuning card, the GPU memory card, and the one-tap model test.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data;
use crate::screens::{mono, row_desc, row_title, stepper, trust_icon};
use crate::theme::*;

/// The pale frost box on the hero: the one-tap model test.
pub fn frost_test(cx: &mut Context<Kriko>) -> Div {
    let test = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.run_local_test(cx);
    });
    frost()
        .absolute()
        .bottom(px(24.0))
        .left(px(40.0))
        .min_w(px(340.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(20.0))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(
                    div()
                        .font_family(DISPLAY)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(22.0))
                        .text_color(rgb(0x0a0e1a))
                        .child("TEST THE MODEL"),
                )
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(0x3a4156))
                        .child("One grounding pass, on this machine, offline."),
                ),
        )
        .child(key("local-test", "Test").on_click(test))
}

/// One settings-style row: title + description left, a control right.
fn row(title: &str, desc: &str, control: gpui::AnyElement) -> Div {
    div()
        .py(px(13.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(title))
                .child(row_desc(desc)),
        )
        .child(control)
}

fn switch_row(
    id: &'static str,
    title: &str,
    desc: &str,
    on: bool,
    motion: bool,
    cx: &mut Context<Kriko>,
    on_toggle: impl Fn(&mut Kriko, &mut Context<Kriko>) + Copy + 'static,
) -> Div {
    let listener = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| on_toggle(this, cx));
    row(
        title,
        desc,
        switch_anim(id, on, motion).on_click(listener).into_any_element(),
    )
}

pub fn local(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;

    // ---- the server card: where the LLM server is, and how to reach it ----
    let url_field = app.input_field(
        Field::LocalUrl,
        "local-url",
        "Found automatically",
        Some("local"),
        window,
        cx,
    );
    let search_field = app.input_field(
        Field::LocalSearch,
        "local-search",
        "http://127.0.0.1:7000",
        Some("search"),
        window,
        cx,
    );
    let cycle_model = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.local_model_pick = (this.local_model_pick + 1) % data::MODELS.len();
        cx.notify();
    });
    let save = cx.listener(|_this, _: &gpui::ClickEvent, _w, cx| {
        // The address is stored with this install; the plane re-reads it.
        cx.notify();
    });
    let timeout = app.local_timeout;
    let timeout_step = stepper(
        "local-timeout",
        format!("{timeout} s"),
        cx,
        move |this, cx| {
            this.local_timeout = this.local_timeout.saturating_sub(30).max(30);
            cx.notify();
        },
        move |this, cx| {
            this.local_timeout = (this.local_timeout + 30).min(900);
            cx.notify();
        },
    );
    let server = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .child(eyebrow("Local machine"))
                .child(tag(TagState::Live, "Live", motion)),
        )
        .child(row_desc(
            "An LLM running on this computer reads and researches for Kriko, \
             at no cost and with no key.",
        ))
        .child(
            div()
                .flex()
                .items_end()
                .gap(px(16.0))
                .flex_wrap()
                .child(
                    div()
                        .flex_1()
                        .min_w(px(220.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(mono("SERVER ADDRESS", DIM))
                        .child(url_field),
                )
                .child(
                    div()
                        .flex_1()
                        .min_w(px(220.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(mono("SEARCH SERVICE", DIM))
                        .child(search_field),
                ),
        )
        .child(
            div()
                .flex()
                .items_end()
                .gap(px(16.0))
                .flex_wrap()
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(mono("LLM", DIM))
                        .child(
                            div()
                                .id("local-model-pick")
                                .h(px(48.0))
                                .px(px(16.0))
                                .flex()
                                .items_center()
                                .justify_between()
                                .gap(px(12.0))
                                .rounded(px(12.0))
                                .bg(rgb(WELL))
                                .border_1()
                                .border_color(rgba(BORDER_CONTROL))
                                .cursor_pointer()
                                .hover(|s| s.border_color(rgb(ICE)))
                                .on_click(cycle_model)
                                .child(
                                    div()
                                        .font_family(MONO)
                                        .text_size(px(13.0))
                                        .text_color(rgb(INK_2))
                                        .child(
                                            data::MODELS[app.local_model_pick]
                                                .name
                                                .to_string(),
                                        ),
                                )
                                .child(icon("chevron-down", 14.0).text_color(rgb(MUTED))),
                        ),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(mono("WAIT FOR ONE ANSWER", DIM))
                        .child(timeout_step),
                )
                .child(div().flex_1().min_w(px(0.0)))
                .child(key("local-save", "Save").on_click(save)),
        );

    // ---- the models: parameters, status icons, load switches ----
    let mut models = card().flex().flex_col();
    models = models
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .pb(px(4.0))
                .child(eyebrow("Models"))
                .child(mono(&format!("{} on disk", data::MODELS.len()), DIM)),
        )
        .child(hairline());
    for (i, model) in data::MODELS.iter().enumerate() {
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            if i < this.model_loaded.len() {
                this.model_loaded[i] = !this.model_loaded[i];
                // Only one model holds the memory at a time.
                if this.model_loaded[i] {
                    for (j, loaded) in this.model_loaded.iter_mut().enumerate() {
                        if j != i {
                            *loaded = false;
                        }
                    }
                }
            }
            cx.notify();
        });
        let loaded = app.model_loaded.get(i).copied().unwrap_or(false);
        models = models.child(
            div()
                .py(px(14.0))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(20.0))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(4.0))
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .gap(px(10.0))
                                .flex_wrap()
                                .child(row_title(model.name))
                                .when(loaded, |d| {
                                    d.child(tag(TagState::Live, "Loaded", motion))
                                })
                                .child(
                                    div()
                                        .flex()
                                        .items_center()
                                        .gap(px(6.0))
                                        .child(trust_icon(Some(model.fits)))
                                        .child(mono(
                                            if model.fits {
                                                "fits in VRAM"
                                            } else {
                                                "overflows VRAM"
                                            },
                                            if model.fits { MUTED } else { DANGER },
                                        )),
                                ),
                        )
                        .child(mono(
                            &format!(
                                "{} params · {} · {} ctx · {} on disk · {} in memory",
                                model.params, model.quant, model.ctx, model.size, model.memory
                            ),
                            MUTED,
                        ))
                        .child(row_desc(model.note)),
                )
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(14.0))
                        .flex_none()
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .gap(px(8.0))
                                .child(mono(&format!("{} tok/s", model.speed), INK_2))
                                .child(meter_slim(model.speed as f32, 12)),
                        )
                        .child(switch_anim(("model-sw", i), loaded, motion).on_click(toggle)),
                ),
        );
        if i + 1 < data::MODELS.len() {
            models = models.child(hairline());
        }
    }

    // ---- the tuning card: the numbers the model runs with ----
    let temp = app.local_temp;
    let tokens = app.local_max_tokens;
    let layers = app.local_gpu_layers;
    let tuning = card()
        .flex()
        .flex_col()
        .gap(px(0.0))
        .child(div().pb(px(4.0)).child(eyebrow("Parameters")))
        .child(hairline())
        .child(row(
            "Temperature",
            "How far the model may stray from the likeliest word",
            stepper(
                "local-temp",
                format!("{:.1}", temp as f32 / 10.0),
                cx,
                move |this, cx| {
                    this.local_temp = this.local_temp.saturating_sub(1);
                    cx.notify();
                },
                move |this, cx| {
                    this.local_temp = (this.local_temp + 1).min(20);
                    cx.notify();
                },
            )
            .into_any_element(),
        ))
        .child(hairline())
        .child(row(
            "Max tokens per answer",
            "The longest answer the model may give",
            stepper(
                "local-tokens",
                format!("{tokens}"),
                cx,
                move |this, cx| {
                    this.local_max_tokens = this.local_max_tokens.saturating_sub(512).max(512);
                    cx.notify();
                },
                move |this, cx| {
                    this.local_max_tokens = (this.local_max_tokens + 512).min(16_384);
                    cx.notify();
                },
            )
            .into_any_element(),
        ))
        .child(hairline())
        .child(row(
            "GPU layers",
            "How many layers run on the GPU; the rest fall back to CPU",
            stepper(
                "local-layers",
                format!("{layers}"),
                cx,
                move |this, cx| {
                    this.local_gpu_layers = this.local_gpu_layers.saturating_sub(1);
                    cx.notify();
                },
                move |this, cx| {
                    this.local_gpu_layers = (this.local_gpu_layers + 1).min(99);
                    cx.notify();
                },
            )
            .into_any_element(),
        ))
        .child(hairline())
        .child(switch_row(
            "local-auto-unload",
            "Auto unload",
            "Loading a model unloads any other one first",
            app.local_auto_unload,
            motion,
            cx,
            |this, cx| {
                this.local_auto_unload = !this.local_auto_unload;
                cx.notify();
            },
        ))
        .child(hairline())
        .child(switch_row(
            "local-cpu-fallback",
            "CPU fallback",
            "When the GPU is busy, answer on the CPU instead of waiting",
            app.local_cpu_fallback,
            motion,
            cx,
            |this, cx| {
                this.local_cpu_fallback = !this.local_cpu_fallback;
                cx.notify();
            },
        ));

    // ---- the GPU memory card ----
    let memory = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow("Memory"))
        .child(row_title(data::GPU_NAME))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(mono("VRAM", DIM))
                .child(meter(58.0, 20))
                .child(mono(
                    &format!("{} / {}", data::GPU_VRAM_USED, data::GPU_VRAM_TOTAL),
                    INK_2,
                )),
        )
        .child(row_desc(if app.local_auto_unload {
            "One model in memory at a time; loading another unloads this one first."
        } else {
            "Auto unload is off: load a second model and the run waits for memory."
        }));

    // ---- privacy + the model test ----
    let privacy = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow("Privacy"))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(24.0))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title("Offline only"))
                        .child(row_desc("When a local model is loaded, no claim leaves this machine.")),
                )
                .child(tag(TagState::Done, "Guaranteed", motion)),
        );

    let run_test = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.run_local_test(cx);
    });
    let test_body = match app.local_test {
        0 => div()
            .flex()
            .items_center()
            .justify_between()
            .gap(px(24.0))
            .child(
                div()
                    .flex()
                    .flex_col()
                    .gap(px(2.0))
                    .child(row_title("The model has not been tested yet"))
                    .child(row_desc("One grounding pass proves the server, the model and the store agree.")),
            )
            .child(key("local-test-2", "Test").on_click(run_test)),
        1 => div()
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(tag(TagState::Live, "Grounding pass in flight", motion))
                    .child(meter_live(62.0, 20, true, motion).max_w(px(320.0))),
            )
            .child(row_desc("The model is reading a stored page and grounding its claims offline.")),
        _ => div()
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(tag(TagState::Done, "Passed", motion))
                    .child(ghost("local-test-again", "Run again").on_click(run_test)),
            )
            .children(
                data::LOCAL_TEST_LINES
                    .iter()
                    .map(|line| {
                        div()
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .child(led_matrix(&CHECK5, ICE, 3.0, 1.0))
                            .child(
                                div()
                                    .font_family(SANS)
                                    .text_size(px(14.0))
                                    .text_color(rgb(INK_2))
                                    .child(line.to_string()),
                            )
                    })
                    .collect::<Vec<_>>(),
            ),
    };
    let test_card = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow("Model test"))
        .child(test_body);

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(server)
        .child(models)
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .items_start()
                .flex_wrap()
                .child(div().flex_1().min_w(px(320.0)).child(tuning))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(320.0))
                        .flex()
                        .flex_col()
                        .gap(px(24.0))
                        .child(memory)
                        .child(privacy)
                        .child(test_card),
                ),
        )
}
