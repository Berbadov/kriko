//! Kriko desktop app. Everything it draws (fonts, icons, sky images) is
//! embedded in the binary, so the app runs from any working directory.

// A release build is a window program: without this Windows gives kriko.exe a
// console, and a double-clicked shortcut opened a terminal titled "Kriko"
// beside the app. Debug builds keep the console for their logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api;
mod app;
// The arithmetic `build.rs` uses to choose the title ink; tested here.
#[cfg(test)]
mod contrast;
mod data;
mod dock;
mod engine;
mod live;
mod marks;
mod motion;
mod screens;
mod shell;
mod startup;
mod text_input;
mod theme;

use std::borrow::Cow;

struct StderrLogger;
impl log::Log for StderrLogger {
    fn enabled(&self, metadata: &log::Metadata) -> bool {
        metadata.level() <= log::Level::Warn
    }
    fn log(&self, record: &log::Record) {
        if self.enabled(record.metadata()) {
            eprintln!("[{}] {}", record.level(), record.args());
        }
    }
    fn flush(&self) {}
}

fn init_logger() {
    log::set_boxed_logger(Box::new(StderrLogger)).ok();
    log::set_max_level(log::LevelFilter::Warn);
}

use gpui::{
    point, px, size, App, AppContext, Application, Bounds, KeyBinding, Result, SharedString,
    TitlebarOptions, WindowBounds, WindowOptions,
};

// The primary screen's work-area size, via the Win32 metrics. The window
// opens inside whatever screen it finds, never bigger than it.
#[cfg(windows)]
extern "system" {
    fn GetSystemMetrics(nindex: i32) -> i32;
}

fn screen_size() -> (f32, f32) {
    #[cfg(windows)]
    unsafe {
        let width = GetSystemMetrics(0).max(640) as f32;
        let height = GetSystemMetrics(1).max(480) as f32;
        (width, height)
    }
    #[cfg(not(windows))]
    {
        (1920.0, 1080.0)
    }
}

use app::{JumpBrowse, Kriko, NewCheck, SearchKnowledge};
use theme::register_fonts;

/// Every asset the app can load, embedded at compile time.
macro_rules! icon_asset {
    ($name:literal) => {
        (
            concat!("icons/", $name, ".svg"),
            include_bytes!(concat!("../assets/icons/", $name, ".svg")),
        )
    };
}

const ASSETS: &[(&str, &[u8])] = &[
    icon_asset!("about"),
    icon_asset!("activity"),
    icon_asset!("agents"),
    icon_asset!("alert"),
    icon_asset!("arrow"),
    icon_asset!("benchmark"),
    icon_asset!("browse"),
    icon_asset!("cancel"),
    icon_asset!("chat"),
    icon_asset!("check"),
    icon_asset!("check2"),
    icon_asset!("chev"),
    icon_asset!("clock"),
    icon_asset!("cloud"),
    icon_asset!("compare"),
    icon_asset!("copy"),
    icon_asset!("cpu"),
    icon_asset!("download"),
    icon_asset!("extension"),
    icon_asset!("file"),
    icon_asset!("globe"),
    icon_asset!("grid"),
    icon_asset!("hand"),
    icon_asset!("history"),
    icon_asset!("home"),
    icon_asset!("llm"),
    icon_asset!("list"),
    icon_asset!("loader"),
    icon_asset!("mic"),
    icon_asset!("overview"),
    icon_asset!("pause"),
    icon_asset!("plus"),
    icon_asset!("puzzle"),
    icon_asset!("run"),
    icon_asset!("search"),
    icon_asset!("send"),
    icon_asset!("settings"),
    icon_asset!("shield"),
    icon_asset!("sites"),
    icon_asset!("sliders"),
    icon_asset!("term"),
    icon_asset!("trash"),
    icon_asset!("x"),
    (
        "icons/arrow-left.svg",
        include_bytes!("../assets/icons/arrow-left.svg"),
    ),
    (
        "icons/arrow-right.svg",
        include_bytes!("../assets/icons/arrow-right.svg"),
    ),
    (
        "icons/chevron-down.svg",
        include_bytes!("../assets/icons/chevron-down.svg"),
    ),
    (
        "icons/collapse.svg",
        include_bytes!("../assets/icons/collapse.svg"),
    ),
    (
        "icons/expand.svg",
        include_bytes!("../assets/icons/expand.svg"),
    ),
    (
        "icons/database.svg",
        include_bytes!("../assets/icons/database.svg"),
    ),
    ("icons/key.svg", include_bytes!("../assets/icons/key.svg")),
    ("icons/about.svg", include_bytes!("../assets/icons/about.svg")),
    ("icons/activity.svg", include_bytes!("../assets/icons/activity.svg")),
    ("icons/agents.svg", include_bytes!("../assets/icons/agents.svg")),
    ("icons/alert.svg", include_bytes!("../assets/icons/alert.svg")),
    ("icons/arrow-left.svg", include_bytes!("../assets/icons/arrow-left.svg")),
    ("icons/arrow-right.svg", include_bytes!("../assets/icons/arrow-right.svg")),
    ("icons/arrow.svg", include_bytes!("../assets/icons/arrow.svg")),
    ("icons/benchmark.svg", include_bytes!("../assets/icons/benchmark.svg")),
    ("icons/book-open.svg", include_bytes!("../assets/icons/book-open.svg")),
    ("icons/brain.svg", include_bytes!("../assets/icons/brain.svg")),
    ("icons/browse.svg", include_bytes!("../assets/icons/browse.svg")),
    ("icons/cancel.svg", include_bytes!("../assets/icons/cancel.svg")),
    ("icons/chat.svg", include_bytes!("../assets/icons/chat.svg")),
    ("icons/check.svg", include_bytes!("../assets/icons/check.svg")),
    ("icons/check2.svg", include_bytes!("../assets/icons/check2.svg")),
    ("icons/chev.svg", include_bytes!("../assets/icons/chev.svg")),
    ("icons/chevron-down.svg", include_bytes!("../assets/icons/chevron-down.svg")),
    ("icons/circle-alert.svg", include_bytes!("../assets/icons/circle-alert.svg")),
    ("icons/circle-check.svg", include_bytes!("../assets/icons/circle-check.svg")),
    ("icons/clock.svg", include_bytes!("../assets/icons/clock.svg")),
    ("icons/cloud.svg", include_bytes!("../assets/icons/cloud.svg")),
    ("icons/collapse.svg", include_bytes!("../assets/icons/collapse.svg")),
    ("icons/compare.svg", include_bytes!("../assets/icons/compare.svg")),
    ("icons/copy.svg", include_bytes!("../assets/icons/copy.svg")),
    ("icons/cpu.svg", include_bytes!("../assets/icons/cpu.svg")),
    ("icons/database.svg", include_bytes!("../assets/icons/database.svg")),
    ("icons/download.svg", include_bytes!("../assets/icons/download.svg")),
    ("icons/expand.svg", include_bytes!("../assets/icons/expand.svg")),
    ("icons/extension.svg", include_bytes!("../assets/icons/extension.svg")),
    ("icons/external-link.svg", include_bytes!("../assets/icons/external-link.svg")),
    ("icons/file.svg", include_bytes!("../assets/icons/file.svg")),
    ("icons/globe.svg", include_bytes!("../assets/icons/globe.svg")),
    ("icons/grid.svg", include_bytes!("../assets/icons/grid.svg")),
    ("icons/hand.svg", include_bytes!("../assets/icons/hand.svg")),
    ("icons/history.svg", include_bytes!("../assets/icons/history.svg")),
    ("icons/home.svg", include_bytes!("../assets/icons/home.svg")),
    ("icons/key.svg", include_bytes!("../assets/icons/key.svg")),
    ("icons/layers.svg", include_bytes!("../assets/icons/layers.svg")),
    ("icons/list.svg", include_bytes!("../assets/icons/list.svg")),
    ("icons/llm.svg", include_bytes!("../assets/icons/llm.svg")),
    ("icons/loader.svg", include_bytes!("../assets/icons/loader.svg")),
    ("icons/local.svg", include_bytes!("../assets/icons/local.svg")),
    ("icons/maximize.svg", include_bytes!("../assets/icons/maximize.svg")),
    ("icons/message.svg", include_bytes!("../assets/icons/message.svg")),
    ("icons/mic.svg", include_bytes!("../assets/icons/mic.svg")),
    ("icons/minus.svg", include_bytes!("../assets/icons/minus.svg")),
    ("icons/monitor.svg", include_bytes!("../assets/icons/monitor.svg")),
    ("icons/overview.svg", include_bytes!("../assets/icons/overview.svg")),
    ("icons/pause.svg", include_bytes!("../assets/icons/pause.svg")),
    ("icons/plus.svg", include_bytes!("../assets/icons/plus.svg")),
    ("icons/puzzle.svg", include_bytes!("../assets/icons/puzzle.svg")),
    ("icons/refresh-cw.svg", include_bytes!("../assets/icons/refresh-cw.svg")),
    ("icons/restore.svg", include_bytes!("../assets/icons/restore.svg")),
    ("icons/run.svg", include_bytes!("../assets/icons/run.svg")),
    ("icons/search.svg", include_bytes!("../assets/icons/search.svg")),
    ("icons/send.svg", include_bytes!("../assets/icons/send.svg")),
    ("icons/settings.svg", include_bytes!("../assets/icons/settings.svg")),
    ("icons/shield-check.svg", include_bytes!("../assets/icons/shield-check.svg")),
    ("icons/shield.svg", include_bytes!("../assets/icons/shield.svg")),
    ("icons/sidebar.svg", include_bytes!("../assets/icons/sidebar.svg")),
    ("icons/sites.svg", include_bytes!("../assets/icons/sites.svg")),
    ("icons/sliders.svg", include_bytes!("../assets/icons/sliders.svg")),
    ("icons/sparkles.svg", include_bytes!("../assets/icons/sparkles.svg")),
    ("icons/term.svg", include_bytes!("../assets/icons/term.svg")),
    ("icons/trash-2.svg", include_bytes!("../assets/icons/trash-2.svg")),
    ("icons/trash.svg", include_bytes!("../assets/icons/trash.svg")),
    ("icons/wifi.svg", include_bytes!("../assets/icons/wifi.svg")),
    ("icons/x.svg", include_bytes!("../assets/icons/x.svg")),
    ("icons/zap.svg", include_bytes!("../assets/icons/zap.svg")),
    ("logos/anthropic.svg", include_bytes!("../assets/logos/anthropic.svg")),
    ("logos/claude.svg", include_bytes!("../assets/logos/claude.svg")),
    ("logos/copilot.svg", include_bytes!("../assets/logos/copilot.svg")),
    ("logos/gemini.svg", include_bytes!("../assets/logos/gemini.svg")),
    ("logos/ollama.svg", include_bytes!("../assets/logos/ollama.svg")),
    ("logos/openai.svg", include_bytes!("../assets/logos/openai.svg")),
    ("kriko-mark-white.svg", include_bytes!("../assets/kriko-mark-white.svg")),
    ("kriko-wordmark-white.svg", include_bytes!("../assets/kriko-wordmark-white.svg")),
    ("sky-dim.png", include_bytes!("../assets/sky-dim.png")),
    ("sky-hero.png", include_bytes!("../assets/sky-hero.png")),
    ("sky-wide.png", include_bytes!("../assets/sky-wide.png")),
    ("sky-dim.png", include_bytes!("../assets/sky-dim.png")),
    ("sky-hero.png", include_bytes!("../assets/sky-hero.png")),
    ("sky-wide.png", include_bytes!("../assets/sky-wide.png")),
];

/// The fonts, embedded the same way.
const FONTS: &[(&str, &[u8])] = &[
    ("fonts/BarlowCondensed-600.ttf", include_bytes!("../assets/fonts/BarlowCondensed-600.ttf")),
    ("fonts/BarlowCondensed-700.ttf", include_bytes!("../assets/fonts/BarlowCondensed-700.ttf")),
    ("fonts/DMSans-400.ttf", include_bytes!("../assets/fonts/DMSans-400.ttf")),
    ("fonts/DMSans-600.ttf", include_bytes!("../assets/fonts/DMSans-600.ttf")),
    ("fonts/JetBrainsMono-400.ttf", include_bytes!("../assets/fonts/JetBrainsMono-400.ttf")),
    ("fonts/JetBrainsMono-600.ttf", include_bytes!("../assets/fonts/JetBrainsMono-600.ttf")),
    ("fonts/JetBrainsMono_400Regular.ttf", include_bytes!("../assets/fonts/JetBrainsMono_400Regular.ttf")),
];

struct Assets;

impl gpui::AssetSource for Assets {
    fn load(&self, path: &str) -> Result<Option<Cow<'static, [u8]>>> {
        Ok(ASSETS
            .iter()
            .find(|(p, _)| *p == path)
            .map(|(_, bytes)| Cow::Owned(bytes.to_vec())))
    }

    fn list(&self, _: &str) -> Result<Vec<SharedString>> {
        Ok(ASSETS.iter().map(|(p, _)| SharedString::from(*p)).collect())
    }
}

fn main() {
    init_logger();
    let background = std::env::args_os().skip(1).any(|arg| arg == "--background");
    // Verification uses an isolated engine/store and must not be redirected
    // to the reader's installed app. Normal launches remain single-instance.
    // Any page: KRIKO_VERIFY opens every route, and a fixed list here let
    // `KRIKO_VERIFY=settings` raise the reader's own app instead.
    let review = std::env::var("KRIKO_VERIFY").is_ok_and(|page| !page.trim().is_empty());
    // a second launch raises the first and leaves: one engine per machine
    if !review && shell::raise_running_instance(!background) {
        return;
    }
    engine::start();
    Application::new()
        .with_assets(Assets)
        .run(move |cx: &mut App| {
            register_fonts(
                cx,
                FONTS
                    .iter()
                    .map(|(_, bytes)| Cow::Owned(bytes.to_vec()))
                    .collect(),
            );

            cx.bind_keys([
                KeyBinding::new("ctrl-n", NewCheck, None),
                KeyBinding::new("ctrl-k", SearchKnowledge, None),
                KeyBinding::new("ctrl-b", JumpBrowse, None),
            ]);

            // The display the window opens on, where the platform reports it; the
            // fixed guess only when it does not (it was the only answer off
            // Windows, so a small screen got a window larger than itself).
            let (screen_w, screen_h) = cx
                .primary_display()
                .map(|d| {
                    let b = d.bounds();
                    (b.size.width / px(1.0), b.size.height / px(1.0))
                })
                .filter(|(w, h)| *w >= 640.0 && *h >= 480.0)
                .unwrap_or_else(screen_size);
            let mut width = 1280.0f32.min(screen_w - 80.0).max(940.0);
            let mut height = 906.0f32.min(screen_h - 80.0).max(640.0);
            // KRIKO_WINDOW_SIZE=WxH opens the window at that size, for capturing
            // a screen at, say, the 940x640 minimum.
            if let Some((w, h)) = std::env::var("KRIKO_WINDOW_SIZE").ok().and_then(|v| {
                let (w, h) = v.split_once('x')?;
                Some((w.trim().parse::<f32>().ok()?, h.trim().parse::<f32>().ok()?))
            }) {
                width = w.max(940.0);
                height = h.max(640.0);
            }
            let bounds = Bounds {
                origin: point(
                    px(((screen_w - width) / 2.0).max(20.0)),
                    px(((screen_h - height) / 2.0 - 20.0).max(20.0)),
                ),
                size: size(px(width), px(height)),
            };
            shell::build_tray();
            // Create hidden from the start: hiding after creation flashes a window.
            // A failed tray must leave a visible way to reach and quit the app.
            let visible = !background || !shell::has_tray();
            let opts = WindowOptions {
                show: visible,
                focus: visible,
                window_bounds: Some(WindowBounds::Windowed(bounds)),
                window_min_size: Some(size(px(940.0), px(640.0))),
                titlebar: Some(TitlebarOptions {
                    title: Some(SharedString::from(if review {
                        "Kriko — Review"
                    } else {
                        "Kriko"
                    })),
                    // no system titlebar: the app draws its own, merged into the
                    // window, with minimize / restore / close on the right
                    appears_transparent: true,
                    ..Default::default()
                }),
                app_id: Some(SharedString::from("kriko").to_string()),
                ..Default::default()
            };
            // Quit from anywhere (tray, engine, keyboard) ends the engine first
            cx.on_app_quit(|_cx| {
                engine::stop();
                shell::remove_tray();
                async {}
            })
            .detach();
            let opened = cx.open_window(opts, |window, cx| {
                shell::remember_window(window);
                // Window is not Quit: closing hides, the engine keeps serving
                // the extension, and the tray brings it back or ends it
                window.on_window_should_close(cx, |_window, cx| {
                    if shell::can_hide() {
                        shell::hide_window(cx);
                        false
                    } else {
                        engine::stop();
                        cx.quit();
                        true
                    }
                });
                cx.new(|cx| Kriko::new(cx))
            });
            // No window (no usable DirectX 11, say): tell the reader in a system
            // box, and take the engine down rather than leave it serving alone.
            if let Err(e) = opened {
                shell::tell_fatal(&shell::window_failure_text(&format!("{e:#}")));
                engine::stop();
                shell::remove_tray();
                cx.quit();
            }
        });
}
