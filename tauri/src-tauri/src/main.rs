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
// 3. **Nothing outlives the app.** The child is killed when the window closes
//    and when the process exits, because an orphaned uvicorn holding the WAL
//    lock makes the *next* launch fail for a reason nobody can see.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

/// The sidecar's handshake. Must match `PORT_LINE` in `src/app/sidecar.py`.
const PORT_LINE: &str = "KRIKO_PORT";
/// How long the engine gets to answer `/api/health` before we call it dead.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Default)]
struct Engine {
    /// Kept so the child can be killed from the window-close handler. A
    /// `Mutex<Option<..>>` rather than a channel: killing is idempotent here
    /// and both exit paths reach for the same handle.
    child: Mutex<Option<CommandChild>>,
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
        let _ = window.show();
        let _ = window.set_focus();
    }
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

    let (mut rx, child) = app
        .shell()
        .sidecar("kriko-sidecar")
        .map_err(|error| format!("the engine binary is missing from this build: {error}"))?
        .spawn()
        .map_err(|error| format!("the engine would not start: {error}"))?;

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
            let _ = child.kill();
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Engine::default())
        .setup(|app| {
            // After setup, not before: the engine's startup is what the reader
            // is waiting on, and an update prompt in front of a window that has
            // not opened yet would look like the app failing to start.
            offer_update(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![start_engine])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                kill_engine(window.app_handle());
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to start Kriko")
        .run(|app, event| {
            // Also on Exit, not only on window close: a quit from the dock or
            // the tray never destroys a window, and the orphan it would leave
            // holds the store's WAL lock into the next launch.
            if let tauri::RunEvent::Exit = event {
                kill_engine(app);
            }
        });
}
