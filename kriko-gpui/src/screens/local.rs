//! Local LLM: a local model, for checks that never leave this machine.
//! The server card, the model table with its parameters and status icons,
//! the tuning card, the GPU memory card, and the one-tap model test.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data;
use crate::screens::{mono, row_desc, row_title, stepper, trust_icon};
use crate::marks::{mark_tile, Phase};
use crate::theme::*;

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

// ---- the guided setup: a runtime, a model, a test ----

/// One cell of the three-step strip: its number (or a check once done),
/// what the step is, and what it settled on.
fn step_cell(n: usize, title: &str, value: String, done: bool, current: bool) -> Div {
    let glyph: gpui::AnyElement = if done {
        led_matrix(&CHECK5, ICE, 3.0, 1.0)
    } else {
        div()
            .font_family(MONO)
            .text_size(px(13.0))
            .text_color(rgb(if current { INK } else { DIM }))
            .child(n.to_string())
            .into_any_element()
    };
    let cell = if current { well() } else { div() };
    cell.flex_1()
        .min_w(px(180.0))
        .p(px(12.0))
        .rounded(px(12.0))
        .flex()
        .items_center()
        .gap(px(12.0))
        .when(current, |d| d.border_color(rgb(BRAND_LOW)))
        .child(
            div()
                .size(px(28.0))
                .flex_none()
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(8.0))
                .border_1()
                .border_color(rgb(if done || current { BRAND_LOW } else { BEZEL_HI }))
                .child(glyph),
        )
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .min_w(px(0.0))
                .child(mono(&title.to_uppercase(), if current { ICE } else { DIM }))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(14.0))
                        .text_color(rgb(if done || current { INK } else { MUTED }))
                        .child(value),
                ),
        )
}

/// A small picked/unpicked pill, for the model source.
fn pill(id: impl Into<gpui::ElementId>, label: &str, picked: bool) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(34.0))
        .px(px(14.0))
        .flex()
        .items_center()
        .rounded(px(10.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .cursor_pointer()
        .text_color(rgb(if picked { ICE } else { MUTED }))
        .when(picked, |d| {
            d.bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL))
        })
        .hover(|s| s.text_color(rgb(INK)))
        .child(label.to_uppercase())
}

/// The catalogue model that fits this GPU with the most parameters.
fn best_fit() -> Option<usize> {
    data::CATALOGUE
        .iter()
        .enumerate()
        .filter(|(_, m)| m.need_gb <= data::GPU_VRAM_GB)
        .max_by(|a, b| a.1.need_gb.total_cmp(&b.1.need_gb))
        .map(|(i, _)| i)
}

fn setup(app: &mut Kriko, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let rt = app.local_runtime;
    let runtime_ready = app.runtime_state[rt] == data::RuntimeState::Running;
    let model_name = app
        .catalogue_loaded
        .map(|i| data::CATALOGUE[i].name)
        .or_else(|| {
            app.model_loaded
                .iter()
                .position(|l| *l)
                .map(|i| data::MODELS[i].name)
        });
    let tested = app.local_test == 2;
    let current = if !runtime_ready {
        0
    } else if model_name.is_none() {
        1
    } else if !tested {
        2
    } else {
        3
    };
    let steps = div()
        .flex()
        .gap(px(8.0))
        .flex_wrap()
        .child(step_cell(
            1,
            "Runtime",
            if runtime_ready {
                format!("{}, running", data::RUNTIMES[rt].name)
            } else {
                "Pick what serves the model".to_string()
            },
            runtime_ready,
            current == 0,
        ))
        .child(step_cell(
            2,
            "Model",
            model_name
                .map(|n| format!("{n}, loaded"))
                .unwrap_or_else(|| "Get one sized to this machine".to_string()),
            model_name.is_some(),
            current == 1,
        ))
        .child(step_cell(
            3,
            "Test",
            match app.local_test {
                2 => "Passed, offline".to_string(),
                1 => "Grounding pass in flight".to_string(),
                _ => "One pass proves it works".to_string(),
            },
            tested,
            current == 2,
        ));
    let guide = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .child(eyebrow("Set up a local model"))
                .child(if current == 3 {
                    tag("local-setup-done", TagState::Done, "Ready", motion)
                } else if current == 2 && app.local_test == 0 {
                    // the last step is one key: the grounding pass itself
                    let test = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                        this.run_local_test(cx);
                    });
                    div().child(key("local-setup-test", "Test the model").on_click(test))
                } else {
                    tag(
                        format!("local-setup-step-{current}"),
                        TagState::Live,
                        &format!("Step {} of 3", current + 1),
                        motion,
                    )
                }),
        )
        .child(row_desc(
            "Three steps, all on this computer. Kriko finds what is already \
             installed; anything missing installs from here.",
        ))
        .child(steps);

    // ---- runtimes ----
    let mut runtimes = card().flex().flex_col();
    runtimes = runtimes
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .pb(px(4.0))
                .child(eyebrow("1 · Runtime"))
                .child(mono("found on this machine", DIM)),
        )
        .child(hairline());
    for (i, r) in data::RUNTIMES.iter().enumerate() {
        let state = app.runtime_state[i];
        let installing = app.runtime_install.filter(|(j, _)| *j == i).map(|(_, p)| p);
        let in_use = i == rt && state == data::RuntimeState::Running;
        let phase = if installing.is_some() {
            Phase::Writing
        } else if state == data::RuntimeState::Missing {
            Phase::Off
        } else {
            Phase::Idle
        };
        let (tag_state, tag_label) = match state {
            data::RuntimeState::Running => (TagState::Live, "Running"),
            data::RuntimeState::Installed => (TagState::Done, "Installed"),
            data::RuntimeState::Missing => (TagState::Queue, "Not found"),
        };
        let install = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.install_runtime(i, cx);
        });
        let use_it = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.use_runtime(i, cx);
        });
        let action: gpui::AnyElement = if in_use {
            tag(format!("rt-inuse-{i}"), TagState::Live, "In use", motion).into_any_element()
        } else if installing.is_some() {
            mono("installing", ICE).into_any_element()
        } else if state == data::RuntimeState::Missing {
            key(("rt-install", i), "Install").on_click(install).into_any_element()
        } else {
            ghost(("rt-use", i), "Use").on_click(use_it).into_any_element()
        };
        let mut body = div()
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
                    .child(row_title(r.name))
                    .child(tag(format!("rt-state-{i}-{tag_label}"), tag_state, tag_label, motion))
                    .when(i == 0, |d| d.child(chip("No install"))),
            )
            .child(row_desc(r.detail))
            .child(mono(
                &if state == data::RuntimeState::Missing {
                    r.install.to_string()
                } else {
                    format!("127.0.0.1:{}", r.port)
                },
                DIM,
            ));
        if let Some(p) = installing {
            body = body.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(10.0))
                    .child(meter_live(format!("rt-meter-{i}"), p, 20, true, motion).max_w(px(320.0)))
                    .child(mono(&format!("{:.0}%", p.min(100.0)), INK_2)),
            );
        }
        runtimes = runtimes.child(
            div()
                .py(px(12.0))
                .px(px(8.0))
                .rounded(px(12.0))
                .when(in_use, |d| d.bg(rgba(GLASS_1)))
                .flex()
                .items_center()
                .gap(px(16.0))
                .child(mark_tile(&format!("rt-tile-{i}"), r.mark, phase, 40.0, motion))
                .child(body)
                .child(div().flex_none().child(action)),
        );
        if i + 1 < data::RUNTIMES.len() {
            runtimes = runtimes.child(hairline());
        }
    }

    // ---- the model catalogue, sized to this machine ----
    let source = app.local_source.min(data::MODEL_SOURCES.len() - 1);
    let mut sources = div().flex().items_center().gap(px(6.0)).flex_wrap();
    for (si, (label, _)) in data::MODEL_SOURCES.iter().enumerate() {
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.local_source_prev = this.local_source;
            this.local_source = si;
            cx.notify();
        });
        sources = sources.child(pill(("local-source", si), label, si == source).on_click(pick));
    }
    let best = best_fit();
    let mut catalogue = card().flex().flex_col();
    catalogue = catalogue
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .pb(px(4.0))
                .flex_wrap()
                .child(eyebrow("2 · Get a model"))
                .child(chip(&format!(
                    "{} · {:.0} GB VRAM · {} RAM",
                    data::GPU_NAME,
                    data::GPU_VRAM_GB,
                    data::SYSTEM_RAM
                ))),
        )
        .child(
            div()
                .py(px(8.0))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(16.0))
                .flex_wrap()
                .child(sources)
                .child(row_desc(data::MODEL_SOURCES[source].1)),
        )
        .child(hairline());
    if source == 2 {
        catalogue = catalogue.child(
            div()
                .py(px(16.0))
                .flex()
                .items_center()
                .justify_between()
                .gap(px(24.0))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title("Use a .gguf you already have"))
                        .child(row_desc(
                            "Kriko reads it in place and sizes it against this GPU before loading.",
                        )),
                )
                .child(key("local-pick-file", "Choose file")),
        );
    } else {
        for (i, m) in data::CATALOGUE.iter().enumerate() {
            let fits = m.need_gb <= data::GPU_VRAM_GB;
            let progress = app.pull_progress[i];
            let on_disk = app.pulled[i];
            let loaded = app.catalogue_loaded == Some(i);
            let get = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.pull_model(i, cx);
            });
            let load = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                if this.catalogue_loaded == Some(i) {
                    this.catalogue_loaded = None;
                } else {
                    this.catalogue_loaded = Some(i);
                    // one model holds the memory: the on-disk ones step aside
                    for l in this.model_loaded.iter_mut() {
                        *l = false;
                    }
                }
                this.local_test = 0;
                cx.notify();
            });
            let right: gpui::AnyElement = if let Some(p) = progress {
                let got = m.size_gb * p.min(100.0) / 100.0;
                div()
                    .w(px(300.0))
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(meter_live(format!("pull-meter-{i}"), p, 20, true, motion))
                    .child(mono(
                        &format!(
                            "{got:.1} / {:.1} GB · {:.0} MB/s",
                            m.size_gb,
                            crate::app::PULL_GBPS * 1000.0
                        ),
                        INK_2,
                    ))
                    .into_any_element()
            } else if on_disk {
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(mono(if loaded { "loaded" } else { "on disk" }, if loaded { ICE } else { MUTED }))
                    .child(switch_anim(("pull-load", i), loaded, motion).on_click(load))
                    .into_any_element()
            } else {
                key(("pull-get", i), &format!("Get · {:.1} GB", m.size_gb))
                    .on_click(get)
                    .into_any_element()
            };
            catalogue = catalogue.child(
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
                                    .child(row_title(m.name))
                                    .child(mono(m.maker, DIM))
                                    .when(best == Some(i), |d| {
                                        d.child(tag(format!("pull-best-{i}"), TagState::Live, "Best fit", motion))
                                    })
                                    .child(
                                        div()
                                            .flex()
                                            .items_center()
                                            .gap(px(6.0))
                                            .child(trust_icon(Some(fits)))
                                            .child(mono(
                                                &format!(
                                                    "needs {:.1} of {:.0} GB",
                                                    m.need_gb,
                                                    data::GPU_VRAM_GB
                                                ),
                                                if fits { MUTED } else { DANGER },
                                            )),
                                    ),
                            )
                            .child(mono(
                                &format!("{} params · {}", m.params, m.quant),
                                MUTED,
                            ))
                            .child(row_desc(m.note)),
                    )
                    .child(div().flex_none().child(right)),
            );
            if i + 1 < data::CATALOGUE.len() {
                catalogue = catalogue.child(hairline());
            }
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(guide)
        .child(runtimes)
        .child(catalogue)
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
                .child(eyebrow("Already running a server?"))
                .child(tag("local-live", TagState::Live, "Live", motion)),
        )
        .child(row_desc(
            "Point Kriko at it by hand. The setup above fills this in for you.",
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
                                    d.child(tag(format!("local-model-{i}"), TagState::Live, "Loaded", motion))
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
                .child(tag("local-guaranteed", TagState::Done, "Guaranteed", motion)),
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
                    .child(tag("local-grounding", TagState::Live, "Grounding pass in flight", motion))
                    .child(
                        meter_live("local-ground-meter", 62.0, 20, true, motion)
                            .max_w(px(320.0)),
                    ),
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
                    .child(tag("local-passed", TagState::Done, "Passed", motion))
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

    let setup = setup(app, cx);
    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(setup)
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
