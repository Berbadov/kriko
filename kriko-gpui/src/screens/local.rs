//! Local LLM: a local model, for checks that run on this machine. What the
//! runtimes are, what this GPU and memory can hold, which model answers,
//! and getting a new one, all as the engine reports it
//! (`live::local`).

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::live::local::{Held, LibraryModel, Machine, Plane, PullPhase};
use crate::live::run;
use crate::marks::{self, mark_tile, Mark, Phase};
use crate::screens::run::option_chip;
use crate::screens::{empty_note, mono, row_desc, row_title, stepper, trust_icon};
use crate::theme::*;

pub fn runtime_settings(app: &mut Kriko, cx: &mut Context<Kriko>) -> Div {
    let runtime = app.live.local.plane.as_ref().map(|p| p.runtime.clone()).unwrap_or(crate::api::Value::Null);
    let supported = crate::api::b(&runtime, "supported");
    let stored = runtime.get("settings").cloned().unwrap_or(crate::api::Value::Null);
    let refresh = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_local(cx));
    let mut result = card().flex().flex_col().gap(px(12.0))
        .child(div().flex().items_center().justify_between().child(eyebrow("Local inference device"))
            .child(ghost("runtime-refresh", "Refresh device").on_click(refresh)))
        .child(row_desc(&format!("Active: {} · {}", crate::api::s(&runtime, "device"), crate::api::s(&runtime, "reason"))))
        .child(row_desc(&crate::api::s(&runtime, "settings_help")));
    if let Some(bytes) = crate::api::n(&runtime, "vram_bytes") {
        result = result.child(mono(&format!("Runtime VRAM {:.2} GB · context {}",
            bytes / 1e9, crate::api::n(&runtime, "context_tokens").map(|n| format!("{n:.0} tokens")).unwrap_or_else(|| "not reported".into())), MUTED));
    }
    if !supported { return result; }
    for (group, key, choices) in [
        ("Device", "local_device", vec![("Auto", ""), ("CPU", "cpu"), ("GPU", "gpu")]),
        ("GPU layers", "local_gpu_layers", vec![("Runtime default", ""), ("All", "-1"), ("16", "16"), ("32", "32")]),
        ("Context tokens", "local_context_tokens", vec![("Runtime default", ""), ("2048", "2048"), ("4096", "4096"), ("8192", "8192"), ("16384", "16384")]),
    ] {
        let mut controls = div().flex().flex_wrap().gap(px(8.0)).child(row_desc(group));
        for (i, (label, value)) in choices.into_iter().enumerate() {
            let key = key.to_string(); let value = value.to_string();
            let selected = crate::api::s(&stored, &key) == value;
            let button_id = gpui::ElementId::named_usize(format!("runtime-{key}"), i);
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                let body = serde_json::json!({key.clone(): value.clone()});
                this.fetch(cx, move || crate::api::put("/api/prefs", body), |this, reply, cx| {
                    this.note(&reply); if reply.is_ok() { this.refresh_local(cx); }
                });
            });
            controls = controls.child(pill(button_id, label, selected).on_click(pick));
        }
        result = result.child(controls);
    }
    result
}

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
            "Model app",
            if runtime_ready {
                format!("{up_name}, running")
            } else {
                "Install or start Ollama".to_string()
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
                .child(eyebrow("Use AI on this computer"))
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
        .child(row_desc("A local model is an AI that answers on your computer. Ollama is the app that runs it; a model is the downloaded file it needs. Research can still search the web."))
        .child(row_desc(if plane.ready { &plane.line } else { &plane.reason }))
        .when(!model_ready, |d| {
            let job = app.live.knowledge.agent_install.as_ref().filter(|(id, _)| id == "local");
            let busy = job.map(|(_, job)| !job.done).unwrap_or(false);
            d.child(row_desc("Start here: Kriko can install Ollama, download a small starter model, and choose it for you. Allow about 6 GB of free space and keep an internet connection during setup. Larger models need more space and memory."))
                .child(div().flex().flex_wrap().gap(px(8.0))
                    .child(key("local-guided-setup", if busy { "Setting up Ollama…" } else { "Set up Ollama and a starter model" }).opacity(if busy { 0.5 } else { 1.0 }).on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                        if this.live.knowledge.agent_install.as_ref().map(|(_, j)| !j.done).unwrap_or(false) { return; }
                        this.install_agent("local".into(), cx);
                    })))
                    .child(ghost("local-ollama-download", "Download Ollama manually").on_click(|_, _, cx| cx.open_url("https://ollama.com/download/windows"))))
                .children(job.map(|(_, j)| row_desc(&format!("{}: {}", j.state, j.message))))
                .child(row_desc("Manual setup: download Ollama from its official site, run the installer, then return here and press Check again. Next, choose a model below. A small model can miss details; try a larger one when your computer has room."))
        })
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
                .child(eyebrow("1 · App that runs the model"))
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
        } else if server.name == "Ollama" && installed {
            ghost(("rt-start", i), if app.live.local.runtime_starting { "Starting…" } else { "Start Ollama" })
                .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_start_ollama(cx))).into_any_element()
        } else if server.name == "Ollama" {
            ghost(("rt-download", i), "Download Ollama").on_click(|_, _, cx| cx.open_url("https://ollama.com/download/windows")).into_any_element()
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
    let drawer = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.local.catalogue_open = !this.live.local.catalogue_open;
        if this.live.local.catalogue_open && this.live.local.offered.is_empty() { this.refresh_local_catalogue(cx); }
        cx.notify();
    });
    let refresh_catalogue = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_local_catalogue(cx));
    let library = cx.listener(|_this, _: &gpui::ClickEvent, _w, cx| cx.open_url("https://ollama.com/library"));
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
                .child(ghost("local-download-drawer", if app.live.local.catalogue_open { "Close model drawer" } else { "Browse downloadable models" }).on_click(drawer)),
        )
        .child(hairline());
    if !ollama_installed && !ollama_up {
        catalogue = catalogue.child(row_desc(
            "Install Ollama with the setup button above, then choose a model here. If you use another model app, download a model in that app and press Check again.",
        ));
    } else {
        catalogue = catalogue.child(row_desc(if ollama_up {
            "Choose from Ollama's library. Ollama keeps downloaded files; download progress and errors appear here."
        } else { "Ollama is installed but not running. Start it to download a model." }));
    }
    // The library drawer: search, then each model with the parameter sizes it
    // comes in. It is built only while open and slides in through `reveal`.
    let open = app.live.local.catalogue_open;
    let mut drawer_body = div().flex().flex_col().gap(px(12.0));
    if open {
        let raw_query = app.library_search.value.trim().to_string();
        let query = raw_query.to_lowercase();
        let search = app.input_field(Field::LibrarySearch, "local-library-search", "Search models by name or what they do", Some("search"), window, cx);
        let loading = app.live.local.catalogue_loading;
        let total = app.live.local.library.len();
        let matches: Vec<LibraryModel> = app.live.local.library.iter()
            .filter(|m| query.is_empty() || m.name.to_lowercase().contains(&query) || m.about.to_lowercase().contains(&query))
            .cloned()
            .collect();
        let count_line = if loading && total == 0 {
            "Reading Ollama's library".to_string()
        } else if query.is_empty() {
            format!("{total} models")
        } else {
            format!("{} of {total} models", matches.len())
        };
        let busy = matches!(&app.live.local.pull, Some(p) if p.phase == PullPhase::Running);
        drawer_body = drawer_body
            .child(search)
            .child(div().flex().flex_wrap().items_center().gap(px(8.0))
                .child(ghost("local-catalogue-refresh", if loading { "Loading library" } else { "Refresh library" }).h(px(36.0)).px(px(16.0)).text_size(px(12.0)).on_click(refresh_catalogue))
                .child(ghost("local-catalogue-provider", "Open Ollama's library").h(px(36.0)).px(px(16.0)).text_size(px(12.0)).on_click(library))
                .child(mono(&count_line, DIM)));
        if !app.live.local.catalogue_error.is_empty() { drawer_body = drawer_body.child(row_desc(&app.live.local.catalogue_error)); }
        if matches.is_empty() && !loading {
            drawer_body = drawer_body.child(empty_note(if query.is_empty() {
                "No downloadable models loaded. Refresh the library."
            } else {
                "No model in the library matches that search."
            }));
            // a name Ollama knows that the list does not show: `name:size` typed
            if !raw_query.is_empty() && !raw_query.contains(' ') {
                let typed = raw_query.clone();
                let get_typed = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    if matches!(&this.live.local.pull, Some(p) if p.phase == PullPhase::Running) { return; }
                    this.local_get.set_value(typed.clone());
                    this.local_pull(cx);
                });
                drawer_body = drawer_body.child(div().flex().items_center().gap(px(12.0))
                    .child(ghost("local-get-typed", &format!("Get {raw_query}")).on_click(get_typed)));
            }
        }
        let mut choices = div().id("local-download-choices").max_h(px(380.0)).overflow_y_scroll().occlude().flex().flex_col();
        let shown: Vec<&LibraryModel> = matches.iter().take(60).collect();
        for (i, m) in shown.iter().enumerate() {
            let picked = app.live.local.library_size.get(&m.name).cloned().unwrap_or_default();
            let target = if picked.is_empty() { m.name.clone() } else { format!("{}:{}", m.name, picked) };
            let get_target = target.clone();
            let get = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                if matches!(&this.live.local.pull, Some(p) if p.phase == PullPhase::Running) { return; }
                this.local_get.set_value(get_target.clone());
                this.local_pull(cx);
            });
            let mut left = div().flex_1().min_w(px(0.0)).flex().flex_col().gap(px(2.0)).child(row_title(&m.name));
            if !m.about.is_empty() {
                left = left.child(row_desc(&crate::screens::history::clip(&m.about, 140)));
            }
            let mut row = div().flex().flex_col().gap(px(10.0)).py(px(12.0)).child(
                div().flex().items_start().justify_between().gap(px(16.0)).child(left).child(
                    if busy { ghost(("local-offered", i), "Busy").h(px(36.0)).px(px(16.0)).text_size(px(12.0)).into_any_element() } else { ghost(("local-offered", i), "Get").h(px(36.0)).px(px(16.0)).text_size(px(12.0)).on_click(get).into_any_element() },
                ),
            );
            if !m.sizes.is_empty() {
                let default_name = m.name.clone();
                let default_pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    this.live.local.library_size.remove(&default_name);
                    cx.notify();
                });
                let mut sizes = div().flex().flex_wrap().items_center().gap(px(6.0))
                    .child(mono("SIZE", DIM))
                    .child(option_chip(gpui::ElementId::named_usize(format!("lib-default-{i}"), 0), "default", picked.is_empty()).on_click(default_pick));
                for (si, size) in m.sizes.iter().enumerate() {
                    let (name, want) = (m.name.clone(), size.clone());
                    let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                        this.live.local.library_size.insert(name.clone(), want.clone());
                        cx.notify();
                    });
                    sizes = sizes.child(option_chip(gpui::ElementId::named_usize(format!("lib-size-{i}"), si + 1), &size.to_uppercase(), picked == *size).on_click(pick));
                }
                row = row.child(sizes);
            }
            row = row.child(mono(&format!("downloads {target}"), DIM));
            choices = choices.child(row);
            if i + 1 < shown.len() {
                choices = choices.child(hairline());
            }
        }
        if matches.len() > shown.len() {
            choices = choices.child(div().pt(px(8.0)).child(mono(&format!("Showing the first {}. Search to narrow the list.", shown.len()), DIM)));
        }
        drawer_body = drawer_body.child(choices);
    }
    catalogue = catalogue.child(reveal(drawer_body, "local-library-reveal", open, 760.0, motion));
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
    let cycle_model = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| { this.live.local.models_open = true; cx.notify(); });
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
    let drawer = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| { this.live.local.models_open = !this.live.local.models_open; cx.notify(); });
    let mut models = card().flex().flex_col();
    models = models
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(12.0))
                .pb(px(4.0))
                .child(ghost("local-installed-drawer", if app.live.local.models_open { "Close downloaded models" } else { "Choose downloaded model" }).on_click(drawer))
                .child(mono(&format!("{} on {}", plane.models.len(), if plane.name.is_empty() { "the server" } else { &plane.name }), DIM)),
        )
        .child(hairline())
        .child(row_desc(
            "Start with 4B or smaller for modest hardware. Every model on the server stays available below, including larger ones for machines with more VRAM.",
        ));
    if !app.live.local.models_open { return models.child(row_desc(&format!("Current model: {} · {} downloaded", plane.model, plane.models.len()))); }
    if plane.models.is_empty() {
        return models.child(div().pt(px(12.0)).child(empty_note(
            "No model is downloaded on the server Kriko is using. Get one above.",
        )));
    }
    for group in 0..3 {
      let members: Vec<_> = plane.models.iter().enumerate().filter(|(_, name)| {
          let info = held.iter().find(|h| &h.name == *name);
          model_group(info.and_then(|h| h.params.as_deref()), name) == group
      }).collect();
      if members.is_empty() {
          continue;
      }
      models = models.child(div().pt(px(14.0)).child(mono(match group {
          0 => "4B AND SMALLER",
          1 => "LARGER MODELS",
          _ => "SIZE NOT REPORTED",
      }, DIM)));
      for (i, name) in members {
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
        models = models.child(hairline());
      }
    }
    models
}

/// Group by the server's parameter count when it supplies one. The model name
/// is only a fallback for runtimes that list names without Ollama's details.
fn model_group(params: Option<&str>, name: &str) -> usize {
    let size = params.and_then(parse_billions).or_else(|| {
        name.split([':', '-', '_']).rev().find_map(parse_billions)
    });
    match size {
        Some(n) if n <= 4.0 => 0,
        Some(_) => 1,
        None => 2,
    }
}

fn parse_billions(raw: &str) -> Option<f64> {
    raw.trim().to_ascii_lowercase().strip_suffix('b')?.parse().ok()
}

#[cfg(test)]
mod model_group_tests {
    use super::model_group;

    #[test]
    fn installed_small_and_large_models_remain_visible_in_their_groups() {
        assert_eq!(model_group(Some("4.0B"), "any-model"), 0);
        assert_eq!(model_group(Some("27B"), "any-model"), 1);
        assert_eq!(model_group(None, "another:70b"), 1);
        assert_eq!(model_group(None, "custom-model"), 2);
    }
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
    let runtime = runtime_settings(app, cx);
    let server = server_card(app, &plane, window, cx);
    let models = model_card(app, &plane, &held, machine.as_ref(), cx);
    let open_compare = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::Compare;
        this.refresh_compare(cx);
        cx.notify();
    });
    let open_run = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.tab = Tab::Run;
        this.refresh_jobs(cx);
        cx.notify();
    });
    let use_card = card().flex().flex_col().gap(px(10.0))
        .child(eyebrow("Use and inspect"))
        .child(row_desc(if plane.ready {
            "Ask the local model about saved checks in Compare. The answer stays with the draft, including its model, source summary, and reported token use. Open a local run below for its log, cited pages, and self-check verdict."
        } else {
            "Start a runtime and pick a model above. Compare will then offer it beside connected agents."
        }))
        .child(div().flex().gap(px(10.0)).flex_wrap()
            .child(key("local-open-compare", "Open Compare").on_click(open_compare))
            .child(ghost("local-open-run", "View runs").on_click(open_run)));
    let refresh_work = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_jobs(cx));
    let recent_jobs: Vec<_> = app.live.run.jobs.iter()
        .filter(|j| j.backend == "local" || j.harness == "local")
        .take(5).cloned().collect();
    let mut work = card().flex().flex_col().gap(px(10.0))
        .child(div().flex().items_center().justify_between()
            .child(eyebrow("Recent local work"))
            .child(ghost("local-refresh-work", "Refresh").on_click(refresh_work)))
        .child(hairline());
    if !app.live.run.jobs_loaded {
        work = work.child(empty_note("Reading recent jobs from the engine."));
    } else if recent_jobs.is_empty() {
        work = work.child(empty_note("No local work in the recent jobs yet. Ask from Compare to see an answer and its steps here."));
    }
    for (i, job) in recent_jobs.iter().enumerate() {
        let id = job.id.clone();
        let open = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.run.pinned = Some(id.clone());
            this.tab = Tab::Run;
            this.refresh_jobs(cx);
            cx.notify();
        });
        let title = if !job.question.is_empty() { job.question.clone() }
            else if !job.product.is_empty() { job.product.clone() }
            else { run::kind_word(&job.kind) };
        let state = match job.state.as_str() {
            "succeeded" => TagState::Done,
            "failed" | "interrupted" => TagState::Block,
            "running" => TagState::Live,
            _ => TagState::Queue,
        };
        work = work.child(div().id(("local-work", i))
            .py(px(10.0)).flex().items_center().gap(px(12.0))
            .cursor_pointer().hover(|s| s.bg(rgba(GLASS_1)))
            .on_click(open)
            .child(tag(format!("local-work-state-{i}"), state, &job.state, motion))
            .child(div().flex_1().min_w(px(0.0)).flex().flex_col().gap(px(2.0))
                .child(row_title(&title))
                .child(mono(&format!("{} · {}", run::kind_word(&job.kind), job.message), MUTED)))
            .child(mono(&run::ago(&job.created_at), DIM)));
        work = work.child(crate::screens::logs::job_logs(app, job, cx));
        if let Some(telemetry) = job.result.get("telemetry") {
            work = work.child(row_desc(&format!("Queries: {} · pages: {} · calls: {} · tokens: {} · verification: {} · model self-check: {}",
                telemetry.get("queries").map(|v| v.to_string()).unwrap_or_else(|| "not reported".into()),
                telemetry.get("pages").map(|v| v.to_string()).unwrap_or_else(|| "not reported".into()),
                telemetry.get("model_calls").map(|v| v.to_string()).unwrap_or_else(|| "not reported".into()),
                job.result.get("tokens_used").map(|v| v.to_string()).unwrap_or_else(|| "not reported".into()),
                telemetry.get("verification").map(|v| v.to_string()).unwrap_or_else(|| "not reported".into()),
                telemetry.get("self_verify").map(|v| v.to_string()).unwrap_or_else(|| "not performed".into()))));
        }
    }
    div()
        .flex()
        .flex_col()
        .gap(px(24.0))
        .child(guide)
        .child(use_card)
        .child(work)
        .child(server)
        .child(runtime)
        .child(models)
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
        .flex_none()
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
        .active(|s| s.opacity(0.75).mt(px(2.0)))
        .child(label.to_string())
}
