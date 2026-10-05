//! Kriko desktop app. Everything it draws (fonts, icons, sky images) is
//! embedded in the binary, so the app runs from any working directory.

// A release build is a window program: without this Windows gives kriko.exe a
// console, and a double-clicked shortcut opened a terminal titled "Kriko"
// beside the app. Debug builds keep the console for their logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod api;
mod app;
mod data;
mod dock;
mod engine;
mod live;
mod marks;
mod screens;
mod shell;
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
    App, AppContext, Application, Bounds, KeyBinding, Result, SharedString, WindowBounds,
    WindowOptions, point, px, size, TitlebarOptions,
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
const ASSETS: &[(&str, &[u8])] = &[
    ("icons/about.svg", include_bytes!("../assets/icons/about.svg")),
    ("icons/activity.svg", include_bytes!("../assets/icons/activity.svg")),
    ("icons/agents.svg", include_bytes!("../assets/icons/agents.svg")),
    ("icons/arrow-left.svg", include_bytes!("../assets/icons/arrow-left.svg")),
    ("icons/arrow-right.svg", include_bytes!("../assets/icons/arrow-right.svg")),
    ("icons/benchmark.svg", include_bytes!("../assets/icons/benchmark.svg")),
    ("icons/browse.svg", include_bytes!("../assets/icons/browse.svg")),
    ("icons/check.svg", include_bytes!("../assets/icons/check.svg")),
    ("icons/chevron-down.svg", include_bytes!("../assets/icons/chevron-down.svg")),
    ("icons/collapse.svg", include_bytes!("../assets/icons/collapse.svg")),
    ("icons/compare.svg", include_bytes!("../assets/icons/compare.svg")),
    ("icons/expand.svg", include_bytes!("../assets/icons/expand.svg")),
    ("icons/database.svg", include_bytes!("../assets/icons/database.svg")),
    ("icons/extension.svg", include_bytes!("../assets/icons/extension.svg")),
    ("icons/history.svg", include_bytes!("../assets/icons/history.svg")),
    ("icons/home.svg", include_bytes!("../assets/icons/home.svg")),
    ("icons/key.svg", include_bytes!("../assets/icons/key.svg")),
    ("icons/layers.svg", include_bytes!("../assets/icons/layers.svg")),
    ("icons/local.svg", include_bytes!("../assets/icons/local.svg")),
    ("icons/maximize.svg", include_bytes!("../assets/icons/maximize.svg")),
    ("icons/minus.svg", include_bytes!("../assets/icons/minus.svg")),
    ("icons/monitor.svg", include_bytes!("../assets/icons/monitor.svg")),
    ("icons/overview.svg", include_bytes!("../assets/icons/overview.svg")),
    ("icons/plus.svg", include_bytes!("../assets/icons/plus.svg")),
    ("icons/run.svg", include_bytes!("../assets/icons/run.svg")),
    ("icons/search.svg", include_bytes!("../assets/icons/search.svg")),
    ("icons/settings.svg", include_bytes!("../assets/icons/settings.svg")),
    ("icons/restore.svg", include_bytes!("../assets/icons/restore.svg")),
    ("icons/sites.svg", include_bytes!("../assets/icons/sites.svg")),
    ("icons/x.svg", include_bytes!("../assets/icons/x.svg")),
    ("kriko-mark-white.svg", include_bytes!("../assets/kriko-mark-white.svg")),
    ("kriko-wordmark-white.svg", include_bytes!("../assets/kriko-wordmark-white.svg")),
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
        Ok(ASSETS
            .iter()
            .map(|(p, _)| SharedString::from(*p))
            .collect())
    }
}

fn main() {
    init_logger();
    // a second launch raises the first and leaves: one engine per machine
    if shell::raise_running_instance() {
        return;
    }
    engine::start();
    Application::new().with_assets(Assets).run(|cx: &mut App| {
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

        let (screen_w, screen_h) = screen_size();
        let width = 1280.0f32.min(screen_w - 80.0).max(940.0);
        let height = 906.0f32.min(screen_h - 80.0).max(640.0);
        let bounds = Bounds {
            origin: point(
                px(((screen_w - width) / 2.0).max(20.0)),
                px(((screen_h - height) / 2.0 - 20.0).max(20.0)),
            ),
            size: size(px(width), px(height)),
        };
        let opts = WindowOptions {
            window_bounds: Some(WindowBounds::Windowed(bounds)),
            window_min_size: Some(size(px(940.0), px(640.0))),
            titlebar: Some(TitlebarOptions {
                title: Some(SharedString::from("Kriko")),
                // no system titlebar: the app draws its own, merged into the
                // window, with minimize / restore / close on the right
                appears_transparent: true,
                ..Default::default()
            }),
            app_id: Some(SharedString::from("kriko").to_string()),
            ..Default::default()
        };
        shell::build_tray();
        // Quit from anywhere (tray, engine, keyboard) ends the engine first
        cx.on_app_quit(|_cx| {
            engine::stop();
            shell::remove_tray();
            async {}
        })
        .detach();
        cx.open_window(opts, |window, cx| {
            shell::remember_window(window);
            // Window is not Quit: closing hides, the engine keeps serving
            // the extension, and the tray brings it back or ends it
            window.on_window_should_close(cx, |_window, cx| {
                if shell::can_hide() {
                    shell::hide_window();
                    false
                } else {
                    engine::stop();
                    cx.quit();
                    true
                }
            });
            cx.new(|cx| Kriko::new(cx))
        })
        .expect("kriko window");
    });
}
