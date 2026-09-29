// The desktop shell. It owns one thing: the sidecar's lifetime.
//
// No engine logic is in Rust and none ever should be — `kriko/` stays Python,
// the window renders the same UI a browser does, and this file is the process
// supervisor between them. Three rules it exists to keep:
//
// 1. **The window opens on a healthy engine, never before.** It is created
//    hidden and shown once `/api/health` answers, so nobody sees a page that
//    cannot talk to anything.
// 2. **A failure is shown, not swallowed.** If the sidecar dies or never gets
//    healthy, its captured stderr goes to the boot screen. A blank window is
//    the one outcome that is not allowed.
// 3. **Nothing outlives *Quit*.** It used to be "nothing outlives the app",
//    with the window's close button as the thing that ended the engine. That
//    made the browser extension unusable the moment the reader put the window
//    away: the extension talks to the fixed EXTENSION_PORT, and there was
//    nothing listening on it. So closing the window now *hides* it, the tray
//    icon holds the engine's life, and Quit is the only thing that ends it.
//    The hazard this moved rather than removed: a reader who thinks they
//    closed Kriko still has a live sidecar, and a live sidecar breaks the next
//    installer — which is why `installer.nsh` stopped being a fallback for
//    leaked orphans and became the normal path. Three belts, because one was
//    not enough: `--exit-with-parent` makes the sidecar
//    end itself when this process's stdin pipe closes (covering a *crash*,
//    which no handler here would run for), `kill_engine` ends it on both exit
//    paths, and on Windows the kill takes the whole tree — PyInstaller onefile
//    re-execs, so the pid we spawned is a bootloader and the process actually
//    holding the `.exe` is its child. A survivor there does not just leak: it
//    keeps its own image mapped, and the next *installer* fails with "Error
//    opening file for writing: kriko-sidecar.exe".

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

/// The sidecar's handshake. Must match `PORT_LINE` in `src/app/sidecar.py`.
const PORT_LINE: &str = "KRIKO_PORT";
/// Raise the window. Must match `FOCUS_LINE` in
/// `src/app/web/routers/focus.py`.
///
/// A page cannot raise a native window, so the browser extension's "Open in
/// Kriko" posts a route to the engine and the engine prints this line. The
/// shell is already reading stdout for the port, so this is the cheapest
/// possible channel — and it stays a supervisor's job: the route itself is
/// never parsed here. Which screen to show is the SPA's business, and it
/// collects that from `GET /api/focus` on its own.
const FOCUS_LINE: &str = "KRIKO_FOCUS";
/// The page's answer to the close button. Must match `WINDOW_LINE` in
/// `src/app/web/routers/focus.py`; followed by `ack`, `hide` or `quit`.
///
/// The close button asks the page, not the OS: a native message box is the
/// OS's chrome and the OS's warning sound, and "don't show this again" is an
/// interface decision this file must not hold. The page draws the notice and
/// posts its answer to the engine, which prints this line.
const WINDOW_LINE: &str = "KRIKO_WINDOW";
/// How long the page gets to answer a close before the shell hides the
/// window itself — a boot or failure page has no one to answer.
const CLOSE_ANSWER_WAIT: Duration = Duration::from_millis(1500);
/// How long the engine gets to answer `/api/health` before we call it dead.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Default)]
struct Engine {
    /// Kept so the child can be killed from the tray's Quit item and from
    /// process exit. A `Mutex<Option<..>>` rather than a channel: killing is
    /// idempotent here and every exit path reaches for the same handle.
    child: Mutex<Option<CommandChild>>,
    /// Which close press this is, and the last one the page answered. A
    /// close the page has not answered within `CLOSE_ANSWER_WAIT` is hidden
    /// by the shell, so the X button can never do nothing.
    close_asked: AtomicU64,
    close_answered: AtomicU64,
}

fn emit_failure(app: &AppHandle, title: &str, detail: &str) {
    let _ = app.emit(
        "kriko://failed",
        serde_json::json!({ "title": title, "detail": detail }),
    );
    show_window(app);
}

fn show_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        // Unminimize before show: since the close button hides the window
        // rather than destroying it, the window the tray and the extension's
        // KRIKO_FOCUS have to raise can be hidden *and* minimized, and `show`
        // on a minimized window leaves it in the taskbar.
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// The close button: ask the page, and hide the window if it never answers.
fn ask_page_to_close(window: &tauri::Window) {
    let app = window.app_handle().clone();
    let Some(engine) = app.try_state::<Engine>() else { return };
    let asked = engine.close_asked.fetch_add(1, Ordering::SeqCst) + 1;
    if let Some(page) = app.get_webview_window("main") {
        let _ = page.eval("window.__krikoClose && window.__krikoClose()");
    }
    std::thread::spawn(move || {
        std::thread::sleep(CLOSE_ANSWER_WAIT);
        let Some(engine) = app.try_state::<Engine>() else { return };
        if engine.close_answered.load(Ordering::SeqCst) < asked {
            if let Some(page) = app.get_webview_window("main") {
                let _ = page.hide();
            }
        }
    });
}

/// What the page said to do with the window.
fn window_answer(app: &AppHandle, line: &str) {
    if let Some(engine) = app.try_state::<Engine>() {
        let asked = engine.close_asked.load(Ordering::SeqCst);
        engine.close_answered.store(asked, Ordering::SeqCst);
    }
    let action = line.split(WINDOW_LINE).nth(1).unwrap_or("").trim();
    match action {
        "hide" => {
            if let Some(page) = app.get_webview_window("main") {
                let _ = page.hide();
            }
        }
        // The tray's Quit, in the same order and for the same reason.
        "quit" => {
            kill_engine(app);
            app.exit(0);
        }
        _ => {}
    }
}

/// The tray icon, which owns the engine's life now that closing the window
/// does not.
///
/// Built in `setup` rather than declared in `tauri.conf.json` because the menu
/// is behaviour, not configuration: Quit must kill the engine *before* it
/// exits, and that ordering is the whole point of this file.
fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Open Kriko", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Kriko", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &quit])?;

    let mut tray = TrayIconBuilder::new()
        .tooltip("Kriko — engine running")
        .menu(&menu)
        // Left click opens; the menu is the right-click gesture. A left click
        // that opens a menu instead of the app is the wrong default for a tray
        // whose main job is "give me my window back".
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "open" => show_window(app),
            // kill_engine *then* exit, and never the other way round: on exit
            // the sidecar's stdin closes and `--exit-with-parent` would get
            // there eventually, but "eventually" is long enough for the next
            // installer to fail on a mapped kriko-sidecar.exe.
            "quit" => {
                kill_engine(app);
                app.exit(0);
            }
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                show_window(tray.app_handle());
            }
        });

    // The bundled app icon, so the tray never renders as a blank square. A
    // tray with no visible icon is a process the reader cannot stop.
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

/// Poll `/api/health` until it answers. Blocking on purpose — this runs on a
/// worker thread, and an async HTTP client would be a dependency earning
/// nothing.
fn wait_until_healthy(port: u16) -> Result<(), String> {
    use std::io::{Read, Write};
    use std::net::TcpStream;

    let deadline = Instant::now() + HEALTH_TIMEOUT;
    let mut last = String::from("no connection attempt succeeded");
    while Instant::now() < deadline {
        match TcpStream::connect(("127.0.0.1", port)) {
            Ok(mut stream) => {
                let request = format!(
                    "GET /api/health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n"
                );
                if stream.write_all(request.as_bytes()).is_ok() {
                    let mut body = String::new();
                    let _ = stream.read_to_string(&mut body);
                    if body.contains("\"ok\":true") {
                        return Ok(());
                    }
                    last = format!("the engine answered but not healthily: {body}");
                }
            }
            Err(error) => last = error.to_string(),
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    Err(last)
}

#[tauri::command]
fn start_engine(app: AppHandle, engine: State<'_, Engine>) -> Result<(), String> {
    if engine.child.lock().unwrap().is_some() {
        return Ok(()); // a reload must not start a second engine
    }

    // Errors here are *shown*, not only returned. The window is created
    // hidden and the boot page can only render into a visible one, so a bare
    // `Err` — which is what "Ignore" on a locked kriko-sidecar.exe produces —
    // would be a process with no window at all. Rule 2 has no exceptions.
    let spawned = app
        .shell()
        .sidecar("kriko-sidecar")
        .map_err(|error| format!("the engine binary is missing from this build: {error}"))
        .and_then(|command| {
            command
                // `--supervised` is a *claim by this process about itself*:
                // we are about to read the child's stdout, so a KRIKO_FOCUS
                // line will actually raise a window. Without it the engine
                // answers `delivery: "no_shell"` and the extension opens a
                // browser tab — which is right for a hand-run sidecar and
                // wrong here. Guarded by test_focus.py.
                .args(["--exit-with-parent", "--supervised"])
                .spawn()
                .map_err(|error| format!("the engine would not start: {error}"))
        });
    let (mut rx, child) = match spawned {
        Ok(pair) => pair,
        Err(reason) => {
            emit_failure(&app, "Kriko's engine could not be started", &reason);
            return Err(reason);
        }
    };

    *engine.child.lock().unwrap() = Some(child);

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        // Everything the engine says, kept. When it fails at second three,
        // this buffer is the only account of why.
        let mut stderr = String::new();
        let mut port: Option<u16> = None;

        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).to_string();
                    if line.contains(FOCUS_LINE) {
                        show_window(&handle);
                    }
                    if line.contains(WINDOW_LINE) {
                        window_answer(&handle, &line);
                    }
                    if port.is_none() {
                        if let Some(rest) = line.split(PORT_LINE).nth(1) {
                            if let Ok(parsed) = rest.trim().parse::<u16>() {
                                port = Some(parsed);
                                let inner = handle.clone();
                                // The health poll blocks, so it must not run on
                                // the runtime that is reading this pipe — a full
                                // stderr pipe with nobody draining it is a hung
                                // child.
                                tauri::async_runtime::spawn_blocking(move || {
                                    match wait_until_healthy(parsed) {
                                        Ok(()) => {
                                            let url =
                                                format!("http://127.0.0.1:{parsed}/");
                                            let _ = inner.emit(
                                                "kriko://ready",
                                                serde_json::json!({ "url": url }),
                                            );
                                            show_window(&inner);
                                        }
                                        Err(reason) => emit_failure(
                                            &inner,
                                            "Kriko's engine never became ready",
                                            &reason,
                                        ),
                                    }
                                });
                            }
                        }
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    stderr.push_str(&String::from_utf8_lossy(&bytes));
                }
                CommandEvent::Terminated(status) => {
                    if port.is_none() {
                        emit_failure(
                            &handle,
                            "Kriko's engine stopped before it started",
                            if stderr.is_empty() {
                                "It exited without saying anything. Exit code: \
                                 unknown."
                            } else {
                                &stderr
                            },
                        );
                    } else if status.code.unwrap_or(0) != 0 {
                        emit_failure(&handle, "Kriko's engine stopped", &stderr);
                    }
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(())
}

/// Offer the app's own update, once, in the background.
///
/// Packs update themselves through the engine (`/api/packs/update`) because
/// knowledge changes weekly; this is the other clock — the shell and the frozen
/// engine inside it, which change rarely and cannot replace themselves while
/// running. Hence a restart, and hence asking first: a download the reader did
/// not ask for that then closes their window is not an improvement.
///
/// Never fatal. No updater configured, no network, a malformed manifest — all
/// of it ends here quietly. An app that refuses to run because it could not
/// check for a newer one is worse than an old app.
fn offer_update(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let updater = match app.updater() {
            Ok(updater) => updater,
            // The common case on an unsigned local build: no endpoint, no key.
            Err(_) => return,
        };
        let update = match updater.check().await {
            Ok(Some(update)) => update,
            _ => return,
        };
        let version = update.version.clone();
        let answer = app
            .dialog()
            .message(format!(
                "Kriko {version} is available. It will download in the \
                 background and restart the app.\n\nYour knowledge packs and \
                 history in ~/.kriko are not touched."
            ))
            .title("Update Kriko")
            .buttons(MessageDialogButtons::OkCancelCustom(
                "Update".into(),
                "Not now".into(),
            ))
            .blocking_show();
        if !answer {
            return;
        }
        // Before the installer runs, not after: on Windows the update *is* an
        // NSIS run over these very files, and a live sidecar keeps its own
        // onefile image mapped. Installing around it is the same failure a
        // reader hit by hand — "Error opening file for writing:
        // kriko-sidecar.exe" — except here nobody is there to press Retry.
        kill_engine(&app);
        if let Err(error) = update.download_and_install(|_, _| {}, || {}).await {
            app.dialog()
                .message(format!("Kriko could not update itself: {error}"))
                .title("Update failed")
                .blocking_show();
            return;
        }
        // The installer replaced the binary; the engine still running beside it
        // is the old one, and it holds the store's WAL lock.
        kill_engine(&app);
        app.restart();
    });
}

fn kill_engine(app: &AppHandle) {
    if let Some(engine) = app.try_state::<Engine>() {
        if let Some(child) = engine.child.lock().unwrap().take() {
            let pid = child.pid();
            let _ = child.kill();
            kill_tree(pid);
        }
    }
}

/// End the descendants the spawned pid may have left behind.
///
/// Only Windows needs this, and only because the sidecar is a PyInstaller
/// onefile binary: the bootloader we spawned re-execs itself, and it is that
/// second process which holds the extracted image — and the file lock that
/// breaks the next install. `taskkill /T` is the one tool guaranteed present.
#[cfg(windows)]
fn kill_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let _ = std::process::Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .creation_flags(CREATE_NO_WINDOW)
        .status();
}

#[cfg(not(windows))]
fn kill_tree(_pid: u32) {}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Engine::default())
        .setup(|app| {
            // The updater is registered *here*, not on the builder, because it
            // is the one plugin whose configuration is written at package time:
            // `packaging/configure_updater.py` removes `plugins.updater`
            // entirely from a build with no signing key, which is every fork
            // and every release this repo has cut so far. A plugin on the
            // builder is initialized before `build()` returns, and the updater
            // refuses a missing config — so v0.2.4 died in `build().expect(..)`
            // with a panic on stderr nobody sees and no window at all. Rule 2
            // again: a shell that cannot check for updates still has to open.
            let updatable = app
                .handle()
                .plugin(tauri_plugin_updater::Builder::new().build())
                .is_ok();
            // Before the update offer: if the tray cannot be built the reader
            // has no way to reopen or quit the app, and they should find that
            // out from a failure to start rather than the first time they
            // press X. Rule 3 depends on this existing.
            build_tray(app.handle())?;

            if updatable {
                // After setup, not before: the engine's startup is what the
                // reader is waiting on, and an update prompt in front of a
                // window that has not opened yet would look like the app
                // failing to start.
                offer_update(app.handle().clone());
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![start_engine])
        .on_window_event(|window, event| match event {
            // Hide, do not close. The engine has to stay reachable on
            // EXTENSION_PORT while the reader is on a listing page, and the
            // window is not what they were using at that moment.
            tauri::WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                ask_page_to_close(window);
            }
            // Kept even though nothing destroys the window any more: if
            // something ever does, the engine must not outlive it.
            tauri::WindowEvent::Destroyed => kill_engine(window.app_handle()),
            _ => {}
        })
        .build(tauri::generate_context!())
        .expect("failed to start Kriko")
        .run(|app, event| {
            // The backstop for every exit that is not the tray's Quit item —
            // a dock quit, a session logout, `app.restart()` after an update.
            // None of them destroys a window, and the orphan they would leave
            // holds the store's WAL lock into the next launch and keeps its
            // own .exe mapped against the next install.
            if let tauri::RunEvent::Exit = event {
                kill_engine(app);
            }
        });
}
