//! Local LLM: a local model, for checks that run on this machine. The model
//! store (search, filters, sort) over what this machine holds and what the
//! provider lists, the apps that run a model, what this GPU and memory can
//! hold, and where each thing runs, all as the engine reports it
//! (`live::local`).

use gpui::{div, prelude::*, px, Context, Div, Styled, Window};

use crate::app::{Field, Kriko, Tab};
use crate::live::local::{
    chosen_size, fits_limit_gb, library_url, params_b, params_label, remove_pressed, row_fits,
    size_gb, store_view, LibraryFilter, LibraryModel, LibrarySort, Machine, Plane, PullPhase,
};
use crate::live::run;
use crate::marks::{self, mark_tile, Mark, Phase};
use crate::screens::run::option_chip;
use crate::screens::{empty_note, guidance, mono, row_desc, row_title, stepper};
use crate::theme::*;

pub fn runtime_settings(app: &mut Kriko, cx: &mut Context<Kriko>) -> Div {
    let runtime = app.live.local.plane.as_ref().map(|p| p.runtime.clone()).unwrap_or(crate::api::Value::Null);
    let supported = crate::api::b(&runtime, "supported");
    let stored = runtime.get("settings").cloned().unwrap_or(crate::api::Value::Null);
    let motion = app.motion;
    let reading = app.live.local.device_reading;
    let refresh = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_device(cx));
    let mut result = card().flex().flex_col().gap(px(8.0))
        .child(card_head_row(
            "cpu",
            "Local inference device",
            Some(div().flex().items_center().gap(px(6.0))
                .children(reading.then(|| spinner("runtime-refresh-spinner", 14.0, motion)))
                .child(ghost("runtime-refresh", "Refresh device").on_click(refresh))
                .into_any_element()),
            motion,
        ))
        .child(row_desc(&format!("Active: {} · {}", crate::api::s(&runtime, "device"), crate::api::s(&runtime, "reason"))))
        .child(row_desc(&crate::api::s(&runtime, "settings_help")));
    if let Some(bytes) = crate::api::n(&runtime, "vram_bytes") {
        result = result.child(mono(&format!("Runtime VRAM {:.2} GB · context {}",
            bytes / 1e9, crate::api::n(&runtime, "context_tokens").map(|n| format!("{n:.0} tokens")).unwrap_or_else(|| "not reported".into())), MUTED));
    }
    let (output_language, search_language) = app.live.local.plane.as_ref()
        .map(|plane| (plane.stored_output_language.clone(), plane.stored_search_language.clone()))
        .unwrap_or_default();
    // what a row shows: the reader's pick while it is being stored, else what the engine holds
    let pending = app.live.local.pref_pending.clone();
    let shown = |key: &str, stored: String| pending.get(key).map(|p| p.value.clone()).unwrap_or(stored);
    for (group, key, stored, choices) in [
        ("Answer language", "local_output_language", output_language,
            vec![("Automatic", "auto"), ("English", "en"), ("Turkish", "tr"),
                 ("German", "de"), ("French", "fr"), ("Spanish", "es"),
                 ("Japanese", "ja"), ("Chinese", "zh")]),
        ("Search language", "local_search_language", search_language,
            vec![("English", "en"), ("Turkish", "tr"), ("German", "de"),
                 ("French", "fr"), ("Spanish", "es"), ("Japanese", "ja"),
                 ("Chinese", "zh")]),
    ] {
        let current = shown(key, stored);
        let saving = pending.contains_key(key);
        let mut controls = div().flex().flex_wrap().gap(px(8.0)).child(choice_label(group, key, saving, motion));
        for (i, (label, value)) in choices.into_iter().enumerate() {
            let key = key.to_string();
            let value = value.to_string();
            let selected = if current.is_empty() {
                if key == "local_output_language" { value == "auto" } else { value == "en" }
            } else { current == value };
            let element_id = gpui::ElementId::named_usize(format!("local-language-{key}"), i);
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.local_pick_pref(key.clone(), value.clone(), cx);
            });
            controls = controls.child(pill(element_id, label, selected).on_click(pick));
        }
        result = result.child(controls);
    }
    if !supported { return result; }
    for (group, key, choices) in [
        ("Device", "local_device", vec![("Auto", ""), ("CPU", "cpu"), ("GPU", "gpu")]),
        ("GPU layers", "local_gpu_layers", vec![("Runtime default", ""), ("All", "-1"), ("16", "16"), ("32", "32")]),
        ("Context tokens", "local_context_tokens", vec![("Runtime default", ""), ("2048", "2048"), ("4096", "4096"), ("8192", "8192"), ("16384", "16384")]),
    ] {
        let saving = pending.contains_key(key);
        let mut controls = div().flex().flex_wrap().gap(px(8.0)).child(choice_label(group, key, saving, motion));
        for (i, (label, value)) in choices.into_iter().enumerate() {
            let key = key.to_string(); let value = value.to_string();
            let selected = shown(key.as_str(), crate::api::s(&stored, &key)) == value;
            let button_id = gpui::ElementId::named_usize(format!("runtime-{key}"), i);
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.local_pick_pref(key.clone(), value.clone(), cx);
            });
            controls = controls.child(pill(button_id, label, selected).on_click(pick));
        }
        result = result.child(controls);
    }
    result
}

/// A row's label, with a turning mark beside it while the engine stores a
/// choice on that row, so a click is answered even before the engine is.
fn choice_label(label: &str, key: &str, saving: bool, motion: bool) -> Div {
    div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .child(row_desc(label))
        .when(saving, |d| d.child(spinner(format!("choice-saving-{key}"), 14.0, motion)))
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
            .text_color(paint(if current { INK } else { DIM }))
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
        .gap(px(8.0))
        .when(current, |d| d.border_color(paint(BRAND_LOW)))
        .child(
            div()
                .size(px(28.0))
                .flex_none()
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(8.0))
                .border_1()
                .border_color(paint(if done || current { BRAND_LOW } else { BEZEL_HI }))
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
                        .text_color(paint(if done || current { INK } else { MUTED }))
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

fn setup(
    app: &mut Kriko,
    plane: &Plane,
    machine: Option<&Machine>,
    cx: &mut Context<Kriko>,
) -> Div {
    let motion = app.motion;
    let selected_server = plane.servers.iter().find(|s| !plane.url.is_empty() && s.url == plane.url);
    let runtime_ready = selected_server.is_some_and(|s| s.up);
    let model_ready = plane.ready;
    let current = if model_ready { 2 } else if runtime_ready { 1 } else { 0 };
    let up_name = selected_server
        .filter(|s| s.up)
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
                format!("{up_name} is running")
            } else {
                "Start the model app".to_string()
            },
            runtime_ready,
            current == 0,
        ))
        .child(step_cell(
            2,
            "Model",
            if model_ready {
                format!("{} selected", plane.model)
            } else {
                "Choose or download one".to_string()
            },
            model_ready,
            current == 1,
        ));
    let guide = card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(card_head_row(
            "local",
            "Use AI on this computer",
            Some(if current == 2 {
                tag("local-setup-done", TagState::Done, "Ready", motion).into_any_element()
            } else {
                tag(
                    format!("local-setup-step-{current}"),
                    TagState::Live,
                    &format!("Step {} of 2", current + 1),
                    motion,
                )
                .into_any_element()
            }),
            motion,
        ))
        .child(row_desc("A local model answers on this machine. Ollama runs it; a model is the file it needs. Research can still search the web."))
        .child(row_desc(if plane.ready { &plane.line } else { &plane.reason }))
        .when(!model_ready, |d| {
            if runtime_ready {
                let open_models = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                    this.live.local.catalogue_open = true;
                    if this.live.local.offered.is_empty() { this.refresh_local_catalogue(cx); }
                    cx.notify();
                });
                d
                    .child(row_desc("The app is running. Choose a model it holds, or download one."))
                    .child(key("local-guided-models", "Browse models").on_click(open_models))
            } else {
                let job = app.live.knowledge.agent_install.as_ref().filter(|(id, _)| id == "local");
                let busy = job.map(|(_, job)| !job.done).unwrap_or(false);
                let failed = job.map(|(_, job)| job.done && matches!(job.state.as_str(), "failed" | "interrupted")).unwrap_or(false);
                let running_other = plane.servers.iter().find(|s| s.up);
                let ollama_installed = machine.map(|m| m.runtimes.iter().any(|r| r.id == "ollama" && r.installed)).unwrap_or(false);
                let detail = if failed {
                    "Setup stopped before a model was confirmed. Try again, or set it up by hand."
                } else {
                    "Kriko installs Ollama, downloads the recommended model and selects it. Allow about 8 GB of free space and a connection."
                };
                let setup_button = if let Some(server) = running_other {
                    let url = server.url.clone();
                    ghost("local-guided-use-running", &format!("Use {}", server.name)).on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                        this.local_use_server(url.clone(), cx);
                    }))
                } else if ollama_installed {
                    ghost("local-guided-start-ollama", if app.live.local.runtime_starting { "Starting Ollama…" } else { "Start Ollama" })
                        .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_start_ollama(cx)))
                } else {
                    key("local-guided-setup", if busy { "Setting up Ollama…" } else if failed { "Try setup again" } else { "Set up Ollama and a model" })
                        .opacity(if busy { 0.5 } else { 1.0 })
                        .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                            if this.live.knowledge.agent_install.as_ref().map(|(_, j)| !j.done).unwrap_or(false) { return; }
                            this.install_agent("local".into(), cx);
                        }))
                };
                d.child(row_desc(detail))
                    .child(div().flex().flex_wrap().gap(px(8.0))
                        .child(setup_button)
                        .when(!ollama_installed && running_other.is_none(), |d| d.child(ghost("local-ollama-download", "Download Ollama").on_click(|_, _, cx| cx.open_url("https://ollama.com/download/windows")))))
                    .children(job.map(|(_, j)| row_desc(&format!("Setup {}: {}", j.state, j.message))))
                    .child(row_desc("Manual setup: install Ollama from its site, then press Check again and pick a model below."))
            }
        })
        .child(steps);

    // ---- runtimes ----
    let checking = app.live.local.checking;
    let recheck = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_check_again(cx));
    let mut runtimes = card().flex().flex_col();
    runtimes = runtimes
        .child(card_head_row(
            "cpu",
            "1 · App that runs the model",
            Some(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(mono("on this machine", DIM))
                    .child(ghost("local-recheck", if checking { "Checking" } else { "Check again" }).on_click(recheck))
                    .into_any_element(),
            ),
            motion,
        ))
        .child(hairline());
    if plane.servers.is_empty() {
        runtimes = runtimes.child(div().pt(px(12.0)).child(empty_note("The engine listed no model apps.")));
    }
    for (i, server) in plane.servers.iter().enumerate() {
        let found = machine.and_then(|m| m.runtimes.iter().find(|r| r.id == runtime_id(&server.name)));
        let installed = found.map(|r| r.installed).unwrap_or(false);
        let in_use = server.up && server.url == plane.url;
        // one line each: the LED mark says running or not, the words say what
        let (phase, line) = if server.up {
            let line = match server.models.len() {
                0 => "Running · no model downloaded".to_string(),
                1 => "Running · 1 model downloaded".to_string(),
                n => format!("Running · {n} models downloaded"),
            };
            (Phase::Idle, line)
        } else if installed {
            (Phase::Off, "Installed · not running".to_string())
        } else {
            (Phase::Off, "Not found on this machine".to_string())
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
            ghost(("rt-start", i), if app.live.local.runtime_starting { "Starting…" } else { "Start" })
                .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_start_ollama(cx))).into_any_element()
        } else if server.name == "Ollama" {
            ghost(("rt-download", i), "Get Ollama").on_click(|_, _, cx| cx.open_url("https://ollama.com/download/windows")).into_any_element()
        } else {
            div().into_any_element()
        };
        runtimes = runtimes.child(
            div()
                .py(px(10.0))
                .px(px(8.0))
                .rounded(px(12.0))
                .when(in_use, |d| d.bg(paint_a(GLASS_1)))
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(mark_tile(&format!("rt-tile-{i}"), mark_of(&server.name), phase, 32.0, motion))
                .child(row_title(&server.name))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .child(mono(&line, if server.up { MUTED } else { DIM })),
                )
                .child(div().flex_none().child(action)),
        );
        if i + 1 < plane.servers.len() {
            runtimes = runtimes.child(hairline());
        }
    }

    div()
        .flex()
        .flex_col()
        .gap(px(SPACE_SECTION))
        .child(guide)
        .child(runtimes)
}

// ---- the model store ----

/// One small card for a store state the list cannot show: an icon, a line
/// saying what happened, and the one action that moves past it.
fn state_card(
    icon_name: &str,
    title: &str,
    body: &str,
    action: gpui::AnyElement,
    motion: bool,
) -> Div {
    card()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(card_head(icon_name, title, motion))
        .child(row_desc(body))
        .child(div().pt(px(2.0)).child(action))
}

/// The model store: one toolbar (search, filters, sort) over what this
/// machine holds and what the provider lists, then one card per model. The
/// library is read on demand, so a visit that never opens it costs nothing.
fn model_store(
    app: &mut Kriko,
    plane: &Plane,
    machine: Option<&Machine>,
    window: &mut Window,
    cx: &mut Context<Kriko>,
) -> Div {
    let motion = app.motion;
    let loading = app.live.local.catalogue_loading;
    let loaded = app.live.local.catalogue_loaded;
    let error = app.live.local.catalogue_error.clone();
    let filter = app.live.local.library_filter;
    let sort = app.live.local.library_sort;
    let open = app.live.local.catalogue_open;
    let running = matches!(&app.live.local.pull, Some(p) if p.phase == PullPhase::Running);
    let raw_query = app.library_search.value.trim().to_string();
    let limit = machine.and_then(fits_limit_gb);
    let held = app.live.local.held.clone().unwrap_or_default();
    let library: Vec<LibraryModel> = if open { app.live.local.library.clone() } else { Vec::new() };
    let rows = store_view(&library, &held, filter, &raw_query, limit, sort);
    let total = rows.len();
    let ollama_installed = machine
        .map(|m| m.runtimes.iter().any(|r| r.id == "ollama" && r.installed))
        .unwrap_or(false);
    let ollama_up = plane.servers.iter().any(|s| s.name == "Ollama" && s.up);
    let filtered = !raw_query.is_empty() || filter != LibraryFilter::All;

    let count_line = if loading && !loaded {
        "Reading the library".to_string()
    } else if filtered {
        format!("{total} shown")
    } else {
        format!("{total} models")
    };

    let retry = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_local_catalogue(cx));
    let head = div()
        .flex()
        .flex_wrap()
        .items_center()
        .justify_end()
        .gap(px(8.0))
        .child(mono(&count_line, DIM))
        .child(ghost("local-store-refresh", if loading { "Reading" } else { "Refresh library" }).on_click(retry))
        .child(ghost("local-store-library", "Open Ollama's library").on_click(|_, _, cx| cx.open_url("https://ollama.com/library")))
        .child(
            ghost("local-store-toggle", if open { "Hide downloadable" } else { "Downloadable models" })
                .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                    this.live.local.catalogue_open = !this.live.local.catalogue_open;
                    if this.live.local.catalogue_open && !this.live.local.catalogue_loaded {
                        this.refresh_local_catalogue(cx);
                    }
                    cx.notify();
                })),
        );

    // ---- the toolbar: search, filters, sort ----
    let search = app.input_field(
        Field::LibrarySearch,
        "local-store-search",
        "Search models by name or what they do",
        Some("search"),
        window,
        cx,
    );
    let mut filters = div().flex().flex_wrap().items_center().gap(px(6.0));
    for (i, (label, value)) in [
        ("Installed", LibraryFilter::Installed),
        ("Fits this machine", LibraryFilter::Fits),
        ("Small", LibraryFilter::Small),
        ("All", LibraryFilter::All),
    ]
    .into_iter()
    .enumerate()
    {
        if value == LibraryFilter::Fits && limit.is_none() {
            continue;
        }
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.local.library_filter = value;
            this.live.local.catalogue_open = true;
            if !this.live.local.catalogue_loaded { this.refresh_local_catalogue(cx); }
            cx.notify();
        });
        filters = filters.child(
            option_chip(("local-store-filter", i), label, filter == value).on_click(pick),
        );
    }
    let sort_next = match sort {
        LibrarySort::Name => LibrarySort::Size,
        LibrarySort::Size => LibrarySort::Name,
    };
    let sort_control = div()
        .id("local-store-sort")
        .h(px(30.0))
        .px(px(10.0))
        .flex()
        .items_center()
        .gap(px(6.0))
        .rounded(px(8.0))
        .cursor_pointer()
        .bg(paint_a(GLASS_1))
        .border_1()
        .border_color(paint_a(BORDER_CONTROL))
        .hover(|s| s.bg(paint_a(GLASS_2)))
        .child(icon("sort", 13.0).text_color(paint(MUTED)))
        .child(mono(
            match sort {
                LibrarySort::Name => "Name",
                LibrarySort::Size => "Size",
            },
            INK_2,
        ))
        .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.local.library_sort = sort_next;
            cx.notify();
        }));

    let mut body = card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(card_head_row("layers", "Model store", Some(head.into_any_element()), motion))
        .child(hairline())
        .child(div().flex().items_center().gap(px(8.0)).child(search).child(sort_control))
        .child(filters);

    // ---- a download in flight: the store's own work indicator ----
    if let Some(pull) = app.live.local.pull.clone() {
        let cancel = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_pull_cancel(cx));
        body = body.child(match pull.phase {
            PullPhase::Running => {
                let share = app.live.run.bar_value(&pull.job_id, pull.progress / 100.0, motion);
                div()
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .child(row_title(&pull.model))
                            .child(ghost("local-store-stop", "Stop").on_click(cancel)),
                    )
                    .child(progress_bar("local-store-pull", share, motion))
                    .child(mono(&format!("{:.0}% · {}", pull.progress.min(100.0), pull.message), INK_2))
            }
            PullPhase::Done => div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(tag("local-store-downloaded", TagState::Done, "Downloaded", motion))
                .child(row_desc(&format!("{} is on this machine.", pull.model))),
            PullPhase::Failed(why) => {
                let target = pull.model.clone();
                let again = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                    if matches!(&this.live.local.pull, Some(p) if p.phase == PullPhase::Running) { return; }
                    this.local_get.set_value(target.clone());
                    this.local_pull(cx);
                });
                div()
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(tag("local-store-failed", TagState::Block, "Not downloaded", motion))
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(13.0))
                            .text_color(paint(DANGER))
                            .child(why),
                    )
                    .child(ghost("local-store-retry", "Try again").on_click(again))
            }
        });
    }

    // ---- a removal the server refused: its words, beside the store ----
    if !app.live.local.remove_error.is_empty() {
        body = body.child(
            div()
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(tag("local-store-remove-failed", TagState::Block, "Not removed", motion))
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(paint(DANGER))
                        .child(app.live.local.remove_error.clone()),
                ),
        );
    }

    // ---- a model the library does not list, by name ----
    if open {
        let pull_now = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            if matches!(&this.live.local.pull, Some(p) if p.phase == PullPhase::Running) { return; }
            this.local_pull(cx);
        });
        body = body.child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(app.input_field(
                    Field::LocalGet,
                    "local-store-get",
                    "Or type a model name, e.g. llama3:8b",
                    Some("download"),
                    window,
                    cx,
                ))
                .child(
                    key("local-store-get-run", if running { "Downloading…" } else { "Download" })
                        .opacity(if running { 0.5 } else { 1.0 })
                        .on_click(pull_now),
                ),
        );
    }

    // ---- the app that downloads, when it is not there ----
    if open && !ollama_up {
        body = body.child(row_desc(if ollama_installed {
            "Ollama is installed but not running. Start it above to download or use a model."
        } else {
            "Ollama is not installed. Kriko downloads models through it."
        }));
        if !ollama_installed {
            body = body.child(
                ghost("local-store-get-ollama", "Download Ollama")
                    .on_click(|_, _, cx| cx.open_url("https://ollama.com/download/windows")),
            );
        }
    }

    // ---- reading, error, empty, or the tiles ----
    if !error.is_empty() {
        let again = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_local_catalogue(cx));
        body = body.child(state_card(
            "warning",
            "The library could not be read",
            &error,
            ghost("local-store-error-retry", "Try again").on_click(again).into_any_element(),
            motion,
        ));
    } else if open && loading && !loaded {
        let again = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_local_catalogue(cx));
        body = body.child(state_card(
            "download",
            "Reading the library",
            "The list of downloadable models has not arrived yet.",
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(spinner("local-store-reading", 16.0, motion))
                .child(ghost("local-store-loading-refresh", "Refresh library").on_click(again))
                .into_any_element(),
            motion,
        ));
    } else if rows.is_empty() {
        let action: gpui::AnyElement = if !open {
            key("local-store-empty-open", "Browse models")
                .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                    this.live.local.catalogue_open = true;
                    if !this.live.local.catalogue_loaded { this.refresh_local_catalogue(cx); }
                    cx.notify();
                }))
                .into_any_element()
        } else if filtered {
            ghost("local-store-clear", "Clear search and filters")
                .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                    this.library_search.set_value(String::new());
                    this.live.local.library_filter = LibraryFilter::All;
                    cx.notify();
                }))
                .into_any_element()
        } else {
            ghost("local-store-empty-refresh", "Refresh library")
                .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_local_catalogue(cx)))
                .into_any_element()
        };
        let (icon_name, title, note) = if !open {
            ("layers", "No model on this machine", "Open the downloadable models to get one.")
        } else if filtered {
            ("search-off", "No model matches", "Nothing matches this search and filter.")
        } else {
            ("download", "No models listed", "The provider listed no model. Refresh to ask again.")
        };
        body = body.child(state_card(icon_name, title, note, action, motion));
    } else {
        let mut cards: Vec<Div> = Vec::with_capacity(rows.len());
        for (i, row) in rows.iter().enumerate() {
            cards.push(store_tile(app, plane, row, i, limit, running, motion, cx));
        }
        let width = (app.content_w - 32.0).max(0.0);
        let mut list = div()
            .id("local-store-list")
            .max_h(px(640.0))
            .overflow_y_scroll()
            .occlude()
            .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
            .flex()
            .flex_col();
        list = list.child(grid(width, 340.0, cards));
        body = body.child(list);
    }

    body
}

/// One model's card: its name, parameter count and size, a chip row for the
/// sizes it comes in and its quantisation, a fit badge, and the actions that
/// apply to it.
fn store_tile(
    app: &mut Kriko,
    plane: &Plane,
    row: &LibraryModel,
    i: usize,
    limit: Option<f64>,
    busy: bool,
    motion: bool,
    cx: &mut Context<Kriko>,
) -> Div {
    let picked = app.live.local.library_size.get(&row.name).cloned().unwrap_or_default();
    let chosen = chosen_size(row, (!picked.is_empty()).then_some(picked.as_str()));
    let est = chosen.and_then(size_gb).or(row.est_gb);
    let params = chosen.and_then(params_b).or(row.params_b);
    let target = match chosen {
        Some(size) if !picked.is_empty() => format!("{}:{}", row.name, size),
        _ => row.name.clone(),
    };
    let pulling = busy
        && matches!(&app.live.local.pull, Some(p) if p.model == row.name || p.model == target);
    let installed_name = row.installed_name.clone().unwrap_or_else(|| row.name.clone());
    let in_use = plane.model == row.name || plane.model == installed_name;
    let removing = app.live.local.removing.as_deref() == Some(installed_name.as_str());
    let armed = app.live.local.remove_confirm.as_deref() == Some(installed_name.as_str());
    let recommended = !plane.recommended_model.is_empty()
        && (row.name.eq_ignore_ascii_case(&plane.recommended_model)
            || row.name
                .to_ascii_lowercase()
                .starts_with(&format!("{}-", plane.recommended_model.to_ascii_lowercase())));

    let size_line = if let Some(bytes) = row.bytes {
        format!("{} on disk", gb_bytes(bytes))
    } else if let Some(gb) = est {
        format!("≈ {gb:.1} GB download")
    } else {
        "size not reported".to_string()
    };
    let facts = match params {
        Some(b) => format!("{} · {}", params_label(b), size_line),
        None => size_line,
    };

    let mut chips = div().flex().flex_wrap().items_center().gap(px(4.0));
    if !row.sizes.is_empty() {
        let default_name = row.name.clone();
        chips = chips.child(
            option_chip(
                gpui::ElementId::named_usize(format!("store-default-{i}"), 0),
                "default",
                picked.is_empty(),
            )
            .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.local.library_size.remove(&default_name);
                cx.notify();
            })),
        );
        for (si, size) in row.sizes.iter().enumerate() {
            let (name, want) = (row.name.clone(), size.clone());
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.local.library_size.insert(name.clone(), want.clone());
                cx.notify();
            });
            let label = match size_gb(size) {
                Some(gb) => format!("{size} · ≈ {gb:.1} GB"),
                None => size.clone(),
            };
            chips = chips.child(
                option_chip(
                    gpui::ElementId::named_usize(format!("store-size-{i}"), si + 1),
                    &label,
                    picked == *size,
                )
                .on_click(pick),
            );
        }
    } else if let Some(b) = row.params_b {
        chips = chips.child(chip(&params_label(b)));
    }
    let quant = row.quant.clone().unwrap_or_else(|| {
        if row.installed { "quant not reported".to_string() } else { "q4 (estimated)".to_string() }
    });
    chips = chips.child(chip(&quant));

    let primary: gpui::AnyElement = if pulling {
        tag(format!("store-pulling-{i}"), TagState::Live, "Downloading", motion).into_any_element()
    } else if row.installed {
        if in_use {
            tag(format!("store-inuse-{i}"), TagState::Live, "In use", motion).into_any_element()
        } else {
            let name = installed_name.clone();
            key(("store-use", i), "Use")
                .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| this.local_use_model(name.clone(), cx)))
                .into_any_element()
        }
    } else if busy {
        ghost(("store-busy", i), "Busy").into_any_element()
    } else {
        let target = target.clone();
        key(("store-download", i), "Download")
            .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                if matches!(&this.live.local.pull, Some(p) if p.phase == PullPhase::Running) { return; }
                this.local_get.set_value(target.clone());
                this.local_pull(cx);
            }))
            .into_any_element()
    };
    let secondary: gpui::AnyElement = {
        let url = if row.listed {
            library_url(&row.name)
        } else {
            "https://ollama.com/library".to_string()
        };
        ghost(("store-open", i), "Open in library")
            .on_click(move |_, _, cx| cx.open_url(&url))
            .into_any_element()
    };
    let fit_badge: gpui::AnyElement = match row_fits(row, limit) {
        Some(true) => tag(format!("store-fits-{i}"), TagState::Live, "Fits", motion).into_any_element(),
        Some(false) => tag(format!("store-toolarge-{i}"), TagState::Block, "Too large", motion).into_any_element(),
        None => div().into_any_element(),
    };
    // an installed model can go: no dialog, the first press asks and the
    // second deletes, so a stray click only changes the button's words
    let remove: Option<gpui::AnyElement> = row.installed.then(|| {
        let name = installed_name.clone();
        let label = if removing {
            "Removing…"
        } else if armed {
            "Confirm remove"
        } else {
            "Remove"
        };
        ghost(("store-remove", i), label)
            .opacity(if removing { 0.5 } else { 1.0 })
            .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                if this.live.local.removing.is_some() {
                    return;
                }
                if remove_pressed(&mut this.live.local.remove_confirm, &name) {
                    this.remove_local_model(name.clone(), cx);
                } else {
                    cx.notify();
                }
            }))
            .into_any_element()
    });

    well()
        .p(px(10.0))
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(6.0))
                .flex_wrap()
                .child(div().flex_1().min_w(px(0.0)).child(row_title(&row.name)))
                .children(recommended.then(|| mono("RECOMMENDED", ICE)))
                .when(row.installed, |d| {
                    d.child(tag(format!("store-installed-{i}"), TagState::Done, "Installed", motion))
                }),
        )
        .child(mono(&facts, MUTED))
        .child(chips)
        .child(hairline())
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(8.0))
                .child(div().flex_none().child(fit_badge))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(6.0))
                        .child(secondary)
                        .child(primary)
                        .children(remove),
                ),
        )
}

// ---- the server card and the memory ----

fn server_card(app: &mut Kriko, plane: &Plane, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    let url_field = app.input_field(Field::LocalUrl, "local-url", "Found automatically", Some("local"), window, cx);
    let search_field = app.input_field(Field::LocalSearch, "local-search", "http://127.0.0.1:7000", Some("search"), window, cx);
    let cycle_model = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.local.catalogue_open = true;
        if !this.live.local.catalogue_loaded { this.refresh_local_catalogue(cx); }
        cx.notify();
    });
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
        .gap(px(8.0))
        .child(card_head_row(
            "globe",
            "Already running a server?",
            Some(if plane.ready {
                tag("local-live", TagState::Live, "Live", motion).into_any_element()
            } else {
                tag("local-not-ready", TagState::Need, "Not ready", motion).into_any_element()
            }),
            motion,
        ))
        .child(row_desc(if plane.ready {
            &plane.line
        } else {
            &plane.reason
        }))
        .child(
            div()
                .flex()
                .items_end()
                .gap(px(8.0))
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
                .gap(px(8.0))
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
                                .gap(px(8.0))
                                .rounded(px(12.0))
                                .bg(paint(WELL))
                                .border_1()
                                .border_color(paint_a(BORDER_CONTROL))
                                .cursor_pointer()
                                .hover(|s| s.border_color(paint(ICE)))
                                .on_click(cycle_model)
                                .child(
                                    div()
                                        .font_family(MONO)
                                        .text_size(px(13.0))
                                        .text_color(paint(INK_2))
                                        .child(picked),
                                )
                                .child(icon("chevron-down", 14.0).text_color(paint(MUTED))),
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



pub fn local(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    let plane_status = plane_read_state(
        app.live.local.plane.is_some(),
        app.live.local.checking,
        app.live.local.plane_error.is_some(),
    );
    let Some(plane) = app.live.local.plane.clone() else {
        let status = match plane_status {
            PlaneReadState::Checking => empty_note(
                "Reading what runs on this machine. Keep this screen open while it checks.",
            )
            .into_any_element(),
            PlaneReadState::Failed => {
                let error = app.live.local.plane_error.as_deref().unwrap_or("The local setup request failed.");
                let retry = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_check_again(cx));
                guidance::next_step(
                    "local-plane-error",
                    "Local setup could not be read",
                    &format!("{error} Your server address and model choice are still here."),
                    ghost("local-plane-retry", "Check again").on_click(retry).into_any_element(),
                    motion,
                )
            }
            PlaneReadState::Waiting => {
                let retry = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_check_again(cx));
                guidance::next_step(
                    "local-plane-waiting",
                    "Local setup has not loaded",
                    "The model server details have not arrived. Check again to retry.",
                    ghost("local-plane-retry", "Check again").on_click(retry).into_any_element(),
                    motion,
                )
            }
            PlaneReadState::Stale | PlaneReadState::Ready => unreachable!("no plane has no ready or stale state"),
        };
        return div()
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(enter(status, "local-0", 0, motion));
    };
    let machine = app.live.local.machine.clone();

    // ---- the GPU memory card ----
    let vram = machine
        .as_ref()
        .and_then(|m| Some((m.vram_used_mb?, m.vram_total_mb?)));
    let memory = card()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(card_head("memory", "Memory", motion))
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
                .gap(px(6.0))
                .child(mono("VRAM", DIM))
                .child(meter((used / total * 100.0) as f32, 20))
                .child(mono(&format!("{} / {}", gb_mb(used), gb_mb(total)), INK_2)),
            _ => div().child(mono("VRAM not reported", DIM)),
        })
        .child(row_desc(
            "Used by everything on this GPU, not only the model server. \
             A larger model spills onto the CPU and slows down.",
        ));

    // ---- where the model and the search run ----
    let local_host = plane.url.contains("127.0.0.1") || plane.url.contains("localhost");
    let model_line = if plane.url.is_empty() {
        "no server yet".to_string()
    } else {
        format!("{} at {}", plane.name, plane.url)
    };
    let search_line = if plane.search_label.is_empty() {
        "not reported".to_string()
    } else {
        format!("through {}", plane.search_label)
    };
    let where_card = card()
        .flex()
        .flex_col()
        .gap(px(SPACE_CARD))
        .child(card_head("monitor", "Where things run", motion))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(SPACE_SECTION))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .min_w(px(0.0))
                        .child(if plane.url.is_empty() {
                            tag("local-where-model", TagState::Queue, "None", motion)
                        } else if local_host {
                            tag("local-where-model", TagState::Done, "This machine", motion)
                        } else {
                            tag("local-where-model", TagState::Need, "Another machine", motion)
                        })
                        .child(row_title("The model")),
                )
                .child(mono(&model_line, DIM)),
        )
        .child(hairline())
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(SPACE_SECTION))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .min_w(px(0.0))
                        .child(if plane.search_label.is_empty() {
                            tag("local-where-search", TagState::Queue, "None", motion)
                        } else {
                            tag("local-where-search", TagState::Done, "Ready", motion)
                        })
                        .child(row_title("The search")),
                )
                .child(mono(&search_line, DIM)),
        );

    let guide = setup(app, &plane, machine.as_ref(), cx);
    let plane_notice = if plane_status == PlaneReadState::Stale {
        let error = app.live.local.plane_error.as_deref().unwrap_or("The last local setup refresh failed.");
        let retry = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.local_check_again(cx));
        Some(guidance::next_step(
            "local-plane-stale",
            "Could not refresh local setup",
            &format!("{error} The last known server and model details remain on screen. Check again to retry."),
            ghost("local-plane-retry", "Check again").on_click(retry).into_any_element(),
            motion,
        ))
    } else { None };
    let runtime = runtime_settings(app, cx);
    let server = server_card(app, &plane, window, cx);
    let models = model_store(app, &plane, machine.as_ref(), window, cx);
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
    let use_card = card().flex().flex_col().gap(px(6.0))
        .child(card_head("spark", "Use and inspect", motion))
        .child(row_desc(if plane.ready {
            "Ask the local model about saved checks in Compare. The answer stays with the draft, including its model, source summary, and reported token use. Open a local run below for its log, cited pages, and self-check verdict."
        } else {
            "Start a runtime and pick a model above. Compare will then offer it beside connected agents."
        }))
        .child(div().flex().gap(px(6.0)).flex_wrap()
            .child(key("local-open-compare", "Open Compare").on_click(open_compare))
            .child(ghost("local-open-run", "View runs").on_click(open_run)));
    let refresh_work = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| this.refresh_jobs(cx));
    let recent_jobs: Vec<_> = app.live.run.jobs.iter()
        .filter(|j| j.backend == "local" || j.harness == "local")
        .take(5).cloned().collect();
    let mut work = card().flex().flex_col().gap(px(6.0))
        .child(card_head_row(
            "history",
            "Recent local work",
            Some(ghost("local-refresh-work", "Refresh").on_click(refresh_work).into_any_element()),
            motion,
        ))
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
            .py(px(4.0)).flex().items_center().gap(px(8.0))
            .cursor_pointer().hover(|s| s.bg(paint_a(GLASS_1)))
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
        .gap(px(SPACE_SECTION))
        .children(plane_notice.map(|notice| enter(notice, "local-0", 0, motion)))
        .child(enter(guide, "local-1", 1, motion))
        .child(enter(use_card, "local-2", 2, motion))
        .child(enter(work, "local-3", 3, motion))
        .child(enter(server, "local-4", 4, motion))
        .child(enter(runtime, "local-5", 5, motion))
        .child(enter(models, "local-6", 6, motion))
        .child(enter(
            div()
                .flex()
                .gap(px(SPACE_SECTION))
                .items_start()
                .flex_wrap()
                .child(div().flex_1().min_w(px(320.0)).child(memory))
                .child(div().flex_1().min_w(px(320.0)).child(where_card)),
            "local-7",
            7,
            motion,
        ))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum PlaneReadState {
    Checking,
    Waiting,
    Failed,
    Stale,
    Ready,
}

/// A failed refresh keeps the previous plane visible, while a first read
/// failure gets its own retry surface instead of leaving a loading note up.
fn plane_read_state(has_plane: bool, checking: bool, failed: bool) -> PlaneReadState {
    if checking {
        return if has_plane { PlaneReadState::Ready } else { PlaneReadState::Checking };
    }
    match (has_plane, failed) {
        (true, true) => PlaneReadState::Stale,
        (true, false) => PlaneReadState::Ready,
        (false, true) => PlaneReadState::Failed,
        (false, false) => PlaneReadState::Waiting,
    }
}

#[cfg(test)]
mod plane_guidance_tests {
    use super::{plane_read_state, PlaneReadState};

    #[test]
    fn first_read_wait_failure_and_retry_have_distinct_surfaces() {
        assert_eq!(plane_read_state(false, true, false), PlaneReadState::Checking);
        assert_eq!(plane_read_state(false, false, false), PlaneReadState::Waiting);
        assert_eq!(plane_read_state(false, false, true), PlaneReadState::Failed);
    }

    #[test]
    fn refresh_failure_keeps_last_known_setup_visible() {
        assert_eq!(plane_read_state(true, true, false), PlaneReadState::Ready);
        assert_eq!(plane_read_state(true, false, true), PlaneReadState::Stale);
    }
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
        .text_color(paint(if picked { ICE } else { MUTED }))
        .when(picked, |d| d.bg(paint(WELL)).border_1().border_color(paint_a(BORDER_CONTROL)))
        .hover(|s| s.text_color(paint(INK)))
        .active(|s| s.opacity(0.75).mt(px(2.0)))
        .child(label.to_string())
}
