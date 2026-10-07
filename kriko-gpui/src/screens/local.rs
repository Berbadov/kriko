//! Local LLM: a local model, for checks that run on this machine. What the
//! runtimes are, what this GPU and memory can hold, which model answers,
//! and getting a new one, all as the engine reports it
//! (`live::local`).

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, Styled, Window};

use crate::api::{self, Value};
use crate::app::{Field, Kriko};
use crate::live::local::{Held, Machine, Plane, PullPhase};
use crate::live::run::Job;
use crate::marks::{self, mark_tile, Mark, Phase};
use crate::screens::{empty_note, mono, row_desc, row_title, stepper, trust_icon};
use crate::theme::*;

// ---- the guided setup: a runtime, then a model ----

/// One cell of the step strip: its number (or a check once done), what the
/// step is, and what it settled on.
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

fn gb_bytes(bytes: f64) -> String {
    format!("{:.1} GB", bytes / 1e9)
}

fn gb_mb(mb: f64) -> String {
    format!("{:.1} GB", mb / 1024.0)
}

/// The mark a server's program wears.
fn mark_of(name: &str) -> &'static Mark {
    match name {
        "Ollama" => &marks::OLLAMA,
        "LM Studio" => &marks::LMSTUDIO,
        "llama-server" => &marks::LLAMACPP,
        _ => &marks::BUILTIN,
    }
}

/// The runtime id the machine endpoint uses for a server's program.
fn runtime_id(name: &str) -> &'static str {
    match name {
        "Ollama" => "ollama",
        "LM Studio" => "lmstudio",
        "llama-server" => "llamacpp",
        _ => "",
    }
}

fn machine_line(m: Option<&Machine>) -> String {
    let Some(m) = m else { return "reading this machine".to_string() };
    format!(
        "{} · {} VRAM · {} RAM",
        m.gpu.clone().unwrap_or_else(|| "no GPU reported".to_string()),
        m.vram_total_mb.map(gb_mb).unwrap_or_else(|| "n/a".to_string()),
        m.ram_mb.map(gb_mb).unwrap_or_else(|| "n/a".to_string()),
    )
}

fn setup(
    app: &mut Kriko,
    plane: &Plane,
    machine: Option<&Machine>,
    window: &mut Window,
    cx: &mut Context<Kriko>,
) -> Div {
    let motion = !app.reduce_motion;
    let runtime_ready = plane.servers.iter().any(|s| s.up);
    let model_ready = plane.ready;
    let current = if !runtime_ready {
        0
    } else if !model_ready {
        1
    } else {
        2
    };
    let up_name = plane
        .servers
        .iter()
        .find(|s| s.up && s.url == plane.url)
        .or_else(|| plane.servers.iter().find(|s| s.up))
        .map(|s| s.name.clone())
        .unwrap_or_default();
    let steps = div()
        .flex()
        .gap(px(8.0))
        .flex_wrap()
        .child(step_cell(
            1,
            "Runtime",
            if runtime_ready {
                format!("{up_name}, running")
            } else {
                "Start what serves the model".to_string()
            },
            runtime_ready,
            current == 0,
        ))
        .child(step_cell(
            2,
            "Model",
            if model_ready {
                format!("{}, ready", plane.model)
            } else {
                "Get one sized to this machine".to_string()
            },
            model_ready,
            current == 1,
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
                .child(if current == 2 {
                    tag("local-setup-done", TagState::Done, "Ready", motion)
                } else {
                    tag(
                        format!("local-setup-step-{current}"),
                        TagState::Live,
                        &format!("Step {} of 2", current + 1),
                        motion,
                    )
                }),
        )
        .child(row_desc(if plane.ready { &plane.line } else { &plane.reason }))
        .child(steps);

    // ---- runtimes ----
    let checking = app.live.local.checking;
    let recheck = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_check_again(cx));
    let mut runtimes = card().flex().flex_col();
    runtimes = runtimes
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .pb(px(8.0))
                .child(eyebrow("1 · Runtime"))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(12.0))
                        .child(mono("found on this machine", DIM))
                        .child(ghost("local-recheck", if checking { "Checking" } else { "Check again" }).on_click(recheck)),
                ),
        )
        .child(hairline());
    if plane.servers.is_empty() {
        runtimes = runtimes.child(div().pt(px(12.0)).child(empty_note("The engine listed no model servers.")));
    }
    for (i, server) in plane.servers.iter().enumerate() {
        let found = machine.and_then(|m| m.runtimes.iter().find(|r| r.id == runtime_id(&server.name)));
        let installed = found.map(|r| r.installed).unwrap_or(false);
        let in_use = server.up && server.url == plane.url;
        let (tag_state, tag_label) = if server.up {
            (TagState::Live, "Running")
        } else if installed {
            (TagState::Done, "Installed")
        } else {
            (TagState::Queue, "Not found")
        };
        let phase = if server.up { Phase::Idle } else { Phase::Off };
        let detail = if server.up {
            match server.models.len() {
                0 => "Running, with no model downloaded.".to_string(),
                1 => "Running, with 1 model downloaded.".to_string(),
                n => format!("Running, with {n} models downloaded."),
            }
        } else if installed {
            "Installed; its server is not running. Start it, then check again.".to_string()
        } else {
            format!("Not found on this machine. Get {} from its own site, then check again.", server.name)
        };
        let foot = if server.up {
            server.url.clone()
        } else {
            found.and_then(|r| r.path.clone()).unwrap_or_else(|| server.url.clone())
        };
        let url = server.url.clone();
        let use_it = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.local_use_server(url.clone(), cx);
        });
        let action: gpui::AnyElement = if in_use {
            tag(format!("rt-inuse-{i}"), TagState::Live, "In use", motion).into_any_element()
        } else if server.up {
            ghost(("rt-use", i), "Use").on_click(use_it).into_any_element()
        } else {
            div().into_any_element()
        };
        let body = div()
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
                    .child(row_title(&server.name))
                    .child(tag(format!("rt-state-{i}-{tag_label}"), tag_state, tag_label, motion)),
            )
            .child(row_desc(&detail))
            .child(mono(&foot, DIM));
        runtimes = runtimes.child(
            div()
                .py(px(12.0))
                .px(px(8.0))
                .rounded(px(12.0))
                .when(in_use, |d| d.bg(rgba(GLASS_1)))
                .flex()
                .items_center()
                .gap(px(16.0))
                .child(mark_tile(&format!("rt-tile-{i}"), mark_of(&server.name), phase, 40.0, motion))
                .child(body)
                .child(div().flex_none().child(action)),
        );
        if i + 1 < plane.servers.len() {
            runtimes = runtimes.child(hairline());
        }
    }

    // ---- getting a model, sized to this machine ----
    let ollama_installed = machine
        .map(|m| m.runtimes.iter().any(|r| r.id == "ollama" && r.installed))
        .unwrap_or(false);
    let ollama_up = plane.servers.iter().any(|s| s.name == "Ollama" && s.up);
    let pulling = matches!(&app.live.local.pull, Some(p) if p.phase == PullPhase::Running);
    let get = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_pull(cx));
    let get_field = app.input_field(Field::LocalGet, "local-get", "Model name, as Ollama lists it", None, window, cx);
    let mut catalogue = card().flex().flex_col().gap(px(12.0));
    catalogue = catalogue
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .flex_wrap()
                .child(eyebrow("2 · Get a model"))
                .child(chip(&machine_line(machine))),
        )
        .child(hairline());
    if !ollama_installed && !ollama_up {
        catalogue = catalogue.child(row_desc(
            "Kriko downloads models through Ollama, and Ollama is not on this machine. \
             Get a model in the program you run instead, then check again.",
        ));
    } else {
        catalogue = catalogue
            .child(row_desc(if ollama_up {
                "Type the name of a model and Kriko downloads it through Ollama, which keeps the files."
            } else {
                "Ollama is installed but not running. Start it to download a model."
            }))
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(get_field)
                    .child(if pulling {
                        ghost("local-get-key", "Downloading").into_any_element()
                    } else {
                        key("local-get-key", "Get").on_click(get).into_any_element()
                    }),
            );
        for (i, name) in app.live.local.offered.clone().iter().enumerate() {
            let model = name.clone();
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.local_get.value = model.clone();
                this.local_pull(cx);
            });
            catalogue = catalogue.child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap(px(16.0))
                    .child(row_title(name))
                    .child(ghost(("local-offered", i), "Get").on_click(pick)),
            );
        }
    }
    if let Some(p) = app.live.local.pull.clone() {
        let cancel = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_pull_cancel(cx));
        catalogue = catalogue.child(match p.phase {
            PullPhase::Running => div()
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(12.0))
                        .child(row_title(&p.model))
                        .child(ghost("local-get-cancel", "Stop").on_click(cancel)),
                )
                .child(meter_live("pull-meter", p.progress, 20, true, motion).max_w(px(420.0)))
                .child(mono(&format!("{:.0}% · {}", p.progress.min(100.0), p.message), INK_2)),
            PullPhase::Done => div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(tag("local-get-done", TagState::Done, "Downloaded", motion))
                .child(row_desc(&format!("{} is on this machine.", p.model))),
            PullPhase::Failed(why) => div()
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(tag("local-get-failed", TagState::Block, "Not downloaded", motion))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(DANGER))
                        .child(why),
                ),
        });
    }

    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(guide)
        .child(runtimes)
        .child(catalogue)
}

// ---- the server card, the models, the memory ----

fn server_card(app: &mut Kriko, plane: &Plane, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let url_field = app.input_field(Field::LocalUrl, "local-url", "Found automatically", Some("local"), window, cx);
    let search_field = app.input_field(Field::LocalSearch, "local-search", "http://127.0.0.1:7000", Some("search"), window, cx);
    let cycle_model = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_cycle_model(cx));
    let save = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_save(cx));
    let timeout = app.live.local.timeout;
    let timeout_step = stepper(
        "local-timeout",
        format!("{timeout} s"),
        cx,
        |this, cx| this.local_timeout_step(false, cx),
        |this, cx| this.local_timeout_step(true, cx),
    );
    let picked = app
        .live
        .local
        .model_pick
        .clone()
        .unwrap_or_else(|| "No model".to_string());
    let saving = app.live.local.saving;
    let note = app.live.local.note.clone();
    card()
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
                .child(if plane.ready {
                    tag("local-live", TagState::Live, "Live", motion)
                } else {
                    tag("local-not-ready", TagState::Need, "Not ready", motion)
                }),
        )
        .child(row_desc(if plane.ready {
            &plane.line
        } else {
            &plane.reason
        }))
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
                                        .child(picked),
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
                .child(key("local-save", if saving { "Saving" } else { "Save" }).on_click(save)),
        )
        .children(note.map(|n| mono(&n, MUTED)))
}

fn model_card(app: &mut Kriko, plane: &Plane, held: &[Held], machine: Option<&Machine>, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let vram_bytes = machine.and_then(|m| m.vram_total_mb).map(|mb| mb * 1024.0 * 1024.0);
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
                .child(mono(&format!("{} on {}", plane.models.len(), if plane.name.is_empty() { "the server" } else { &plane.name }), DIM)),
        )
        .child(hairline());
    if plane.models.is_empty() {
        return models.child(div().pt(px(12.0)).child(empty_note(
            "No model is downloaded on the server Kriko is using. Get one above.",
        )));
    }
    for (i, name) in plane.models.iter().enumerate() {
        let info = held.iter().find(|h| &h.name == name);
        let in_use = *name == plane.model;
        let fit: Option<bool> = match (info.and_then(|h| h.size_bytes), vram_bytes) {
            (Some(size), Some(vram)) => Some(size <= vram),
            _ => None,
        };
        let facts: Vec<String> = [
            info.and_then(|h| h.params.clone()),
            info.and_then(|h| h.quant.clone()),
            info.and_then(|h| h.size_bytes).map(|b| format!("{} on disk", gb_bytes(b))),
        ]
        .into_iter()
        .flatten()
        .collect();
        let pick_name = name.clone();
        let use_it = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.local_use_model(pick_name.clone(), cx);
        });
        let right: gpui::AnyElement = if in_use {
            tag(format!("local-model-{i}"), TagState::Live, "In use", motion).into_any_element()
        } else {
            ghost(("model-use", i), "Use").on_click(use_it).into_any_element()
        };
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
                                .child(row_title(name))
                                .children(fit.map(|f| {
                                    div()
                                        .flex()
                                        .items_center()
                                        .gap(px(6.0))
                                        .child(trust_icon(Some(f)))
                                        .child(mono(
                                            if f { "weights fit in VRAM" } else { "weights exceed VRAM" },
                                            if f { MUTED } else { DANGER },
                                        ))
                                })),
                        )
                        .child(mono(
                            &if facts.is_empty() {
                                "size not reported by this server".to_string()
                            } else {
                                facts.join(" · ")
                            },
                            MUTED,
                        )),
                )
                .child(div().flex_none().child(right)),
        );
        if i + 1 < plane.models.len() {
            models = models.child(hairline());
        }
    }
    models
}

fn local_run_card(job: Option<&Job>) -> Div {
    let Some(job) = job else {
        return card()
            .flex()
            .flex_col()
            .gap(px(10.0))
            .child(eyebrow("Latest local run"))
            .child(empty_note(
                "No local quick-look run yet. A local run will leave its stages and quote checks here.",
            ));
    };

    let empty = Value::Null;
    let telemetry = job.result.get("telemetry").unwrap_or(&empty);
    let verification = telemetry.get("verification").unwrap_or(&empty);
    let self_verification = telemetry.get("self_verification").unwrap_or(&empty);
    let quote_repair = telemetry.get("quote_repair").unwrap_or(&empty);
    let stage = api::s(telemetry, "stage");
    let stage = if stage.is_empty() { "Waiting for the local model" } else { &stage };
    let label = if job.done {
        if job.state == "succeeded" { "Completed" } else { &job.state }
    } else if job.state == "queued" {
        "Queued"
    } else {
        "Running"
    };
    let model = api::s(&job.result, "model");
    let pages_read = api::n(telemetry, "pages_read")
        .map(|n| format!("{} page{} read", n, if n == 1.0 { "" } else { "s" }))
        .unwrap_or_else(|| "Pages not reported".into());
    let model_calls = api::n(telemetry, "model_calls")
        .map(|n| n.to_string())
        .unwrap_or_else(|| "—".into());
    let tokens = api::n(telemetry, "tokens_used")
        .or_else(|| api::n(&job.result, "tokens_used"))
        .map(|n| n.to_string())
        .unwrap_or_else(|| "not reported".into());
    let risks = job.result.get("risks")
        .and_then(Value::as_array)
        .map(|items| items.len())
        .unwrap_or(0);
    let risk_text = if job.done {
        format!("{risks} grounded risk(s)")
    } else {
        "risk check pending".into()
    };
    let verdict = api::s(verification, "verdict");
    let mut out = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .child(eyebrow("Latest local run"))
                .child(chip(label)),
        )
        .child(row_title(if job.product.is_empty() { "Quick look" } else { &job.product }))
        .child(row_desc(&format!(
            "{}{}{}",
            stage,
            if model.is_empty() { String::new() } else { format!(" · {model}") },
            if job.done { String::new() } else { format!(" · {}", job.message) },
        )))
        .child(
            div()
                .flex()
                .items_center()
                .flex_wrap()
                .gap(px(14.0))
                .child(mono(&pages_read, INK_2))
                .child(mono(&format!("{} model calls", model_calls), INK_2))
                .child(mono(&format!("{tokens} tokens"), INK_2))
                .child(mono(&risk_text, INK_2))
                .child(mono("self-hosted · no provider charge", MUTED)),
        );

    let queries: Vec<String> = api::arr(telemetry, "queries")
        .iter()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect();
    out = out.child(eyebrow("Searches"));
    if queries.is_empty() {
        out = out.child(row_desc("The local model has not returned any search queries yet."));
    } else {
        for query in queries {
            out = out.child(mono(&query, INK_2));
        }
    }

    let pages: Vec<String> = api::arr(telemetry, "pages")
        .iter()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect();
    out = out.child(eyebrow("Pages read"));
    if pages.is_empty() {
        out = out.child(row_desc("No fetched page is recorded yet."));
    } else {
        for page in pages {
            out = out.child(mono(&page, MUTED));
        }
    }

    out = out.child(eyebrow("Engine quote check"))
        .child(row_desc(if verdict.is_empty() {
            "Quote verification is waiting for the answer."
        } else {
            &verdict
        }));

    let self_verdict = api::s(self_verification, "verdict");
    out = out.child(eyebrow("Quote repair"));
    let repair_status = api::s(quote_repair, "status");
    let repair_checked = api::n(quote_repair, "checked").unwrap_or(0.0) as usize;
    let repaired = api::n(quote_repair, "repaired").unwrap_or(0.0) as usize;
    let repair_text = if repair_status.is_empty() {
        "Quote repair is waiting for the answer.".to_owned()
    } else if repair_status == "not needed" {
        "No quote correction was needed.".to_owned()
    } else {
        format!("{repaired} of {repair_checked} quote(s) corrected · {repair_status}")
    };
    out = out.child(row_desc(&repair_text));

    out.child(eyebrow("Local model self-check"))
        .child(row_desc(if self_verdict.is_empty() {
            "The model self-check is waiting for the answer."
        } else {
            &self_verdict
        }))
}

pub fn local(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let Some(plane) = app.live.local.plane.clone() else {
        return div().child(empty_note(
            "Asking Kriko's engine what runs on this machine. A local model needs the engine answering first.",
        ));
    };
    let machine = app.live.local.machine.clone();
    let held = app.live.local.held.clone().unwrap_or_default();
    let local_run = app.live.run.jobs.iter()
        .filter(|job| {
            job.kind == "quick_look"
                && (job.backend == "local"
                    || api::s(&job.result, "cost_basis") == "self_hosted")
        })
        .max_by(|a, b| a.created_at.cmp(&b.created_at))
        .cloned();

    // ---- the GPU memory card ----
    let vram = machine
        .as_ref()
        .and_then(|m| Some((m.vram_used_mb?, m.vram_total_mb?)));
    let memory = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(eyebrow("Memory"))
        .child(row_title(
            &machine
                .as_ref()
                .and_then(|m| m.gpu.clone())
                .unwrap_or_else(|| "No GPU reported".to_string()),
        ))
        .child(match vram {
            Some((used, total)) if total > 0.0 => div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(mono("VRAM", DIM))
                .child(meter((used / total * 100.0) as f32, 20))
                .child(mono(&format!("{} / {}", gb_mb(used), gb_mb(total)), INK_2)),
            _ => div().child(mono("VRAM not reported", DIM)),
        })
        .child(row_desc(
            "Used by every program on this GPU, not only the model server. \
             A model whose weights exceed it spills onto the CPU and slows down.",
        ));

    // ---- where the model and the search run ----
    let local_host = plane.url.contains("127.0.0.1") || plane.url.contains("localhost");
    let where_card = card()
        .flex()
        .flex_col()
        .gap(px(14.0))
        .child(eyebrow("Where things run"))
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
                        .child(row_title("The model"))
                        .child(row_desc(&if plane.url.is_empty() {
                            "No server answers yet.".to_string()
                        } else {
                            format!("{} at {}", plane.name, plane.url)
                        })),
                )
                .child(if plane.url.is_empty() {
                    tag("local-where-model", TagState::Queue, "None", motion)
                } else if local_host {
                    tag("local-where-model", TagState::Done, "This machine", motion)
                } else {
                    tag("local-where-model", TagState::Need, "Another machine", motion)
                }),
        )
        .child(hairline())
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title("The search"))
                .child(row_desc(&if plane.search_label.is_empty() {
                    "Not reported.".to_string()
                } else {
                    format!("Through {}.", plane.search_label)
                })),
        );

    let guide = setup(app, &plane, machine.as_ref(), window, cx);
    let server = server_card(app, &plane, window, cx);
    let models = model_card(app, &plane, &held, machine.as_ref(), cx);
    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(guide)
        .child(server)
        .child(models)
        .child(local_run_card(local_run.as_ref()))
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .items_start()
                .flex_wrap()
                .child(div().flex_1().min_w(px(320.0)).child(memory))
                .child(div().flex_1().min_w(px(320.0)).child(where_card)),
        )
}

/// A small picked/unpicked pill, for choices of one among a few.
pub fn pill(id: impl Into<gpui::ElementId>, label: &str, picked: bool) -> gpui::Stateful<Div> {
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
        .when(picked, |d| d.bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL)))
        .hover(|s| s.text_color(rgb(INK)))
        .child(label.to_uppercase())
}
