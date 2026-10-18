mod engine;
mod shell;

use std::time::Duration;

use serde::Serialize;
use tauri::Manager;

/// Where the engine stands, for the page.
#[derive(Serialize)]
#[serde(tag = "state", rename_all = "lowercase")]
enum EngineState {
  Starting { message: String },
  Ready { version: String },
  Failed { title: String, detail: String },
}

#[tauri::command]
fn engine_status() -> EngineState {
  match engine::status() {
    engine::Status::Starting(message) => EngineState::Starting { message },
    engine::Status::Ready { version, .. } => EngineState::Ready { version },
    engine::Status::Failed { title, detail } => EngineState::Failed { title, detail },
  }
}

#[tauri::command]
fn engine_restart() {
  engine::restart();
}

#[derive(Serialize)]
struct Reply {
  status: u16,
  body: String,
}

/// One call to the engine, made here and not in the page. The engine refuses
/// a browser origin it does not know, and a packaged window has one of its
/// own. A call from this side carries no origin, which is how the engine
/// already treats a native client, so its policy stays as strict as it is.
#[tauri::command]
async fn engine_request(method: String, path: String, body: Option<String>, timeout_ms: Option<u64>) -> Result<Reply, String> {
  // Only the engine's own API, so the page cannot use this to reach anything else.
  if !path.starts_with("/api/") || path.contains("://") || path.contains("..") {
    return Err("Not an engine path.".into());
  }
  let base = engine::base().ok_or("The engine is not ready.")?;
  let timeout = Duration::from_millis(timeout_ms.unwrap_or(15_000));
  tauri::async_runtime::spawn_blocking(move || call_engine(&base, &method, &path, body, timeout))
    .await
    .map_err(|e| e.to_string())?
}

fn call_engine(base: &str, method: &str, path: &str, body: Option<String>, timeout: Duration) -> Result<Reply, String> {
  let agent: ureq::Agent = ureq::Agent::config_builder()
    .http_status_as_error(false)
    .timeout_global(Some(timeout))
    .build()
    .into();
  let request = ureq::http::Request::builder()
    .method(method)
    .uri(format!("{base}{path}"))
    .header("content-type", "application/json")
    .body(body.unwrap_or_default())
    .map_err(|e| e.to_string())?;
  let response = agent.run(request).map_err(|e| e.to_string())?;
  let status = response.status().as_u16();
  let body = response.into_body().read_to_string().map_err(|e| e.to_string())?;
  Ok(Reply { status, body })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let mut builder = tauri::Builder::default();
  // One Kriko per machine: a second launch raises the first and ends, before it starts a second engine.
  // A smoke test sets KRIKO_VERIFY so it tests this build, not an app the reader has open.
  if std::env::var_os("KRIKO_VERIFY").is_none() {
    builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| shell::show_window(app)));
  }
  builder
    // Opens a link from an answer in the reader's own browser; the window cannot.
    .plugin(tauri_plugin_opener::init())
    .on_window_event(|window, event| {
      if let tauri::WindowEvent::CloseRequested { api, .. } = event {
        if shell::can_hide() {
          // The engine outlives the window. Only Quit ends it.
          api.prevent_close();
          shell::hide_window(window.app_handle());
        } else {
          // No tray means no way back to a hidden window, so closing quits.
          engine::stop();
        }
      }
    })
    .invoke_handler(tauri::generate_handler![engine_status, engine_restart, engine_request])
    .setup(|app| {
      if cfg!(debug_assertions) {
        // A log folder that cannot be made must not stop the app.
        if let Err(error) = app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        ) {
          eprintln!("logging is off: {error}");
        }
      }
      if let Err(error) = shell::build_tray(app.handle()) {
        eprintln!("no tray, so closing the window quits: {error}");
      }
      engine::start(app.handle().clone());
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|_app, event| {
      // The engine this app started ends with it. One that was already running is left alone.
      if let tauri::RunEvent::Exit = event {
        engine::stop();
      }
    });
}

#[cfg(test)]
mod tests {
  use super::*;
  use std::io::{Read, Write};
  use std::net::TcpListener;

  /// A one-shot server: reads one request, answers, and hands the request text back.
  fn serve(status_line: &'static str, reply: &'static str) -> (String, std::thread::JoinHandle<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let base = format!("http://{}", listener.local_addr().unwrap());
    let handle = std::thread::spawn(move || {
      let (mut stream, _) = listener.accept().unwrap();
      let mut seen = Vec::new();
      let mut chunk = [0u8; 2048];
      loop {
        let n = stream.read(&mut chunk).unwrap();
        seen.extend_from_slice(&chunk[..n]);
        let text = String::from_utf8_lossy(&seen).to_string();
        if let Some(head_end) = text.find("\r\n\r\n") {
          let length = text
            .lines()
            .find_map(|l| l.to_lowercase().strip_prefix("content-length:").map(|v| v.trim().parse::<usize>().unwrap_or(0)))
            .unwrap_or(0);
          if seen.len() >= head_end + 4 + length {
            break;
          }
        }
        if n == 0 {
          break;
        }
      }
      write!(
        stream,
        "HTTP/1.1 {status_line}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{reply}",
        reply.len()
      )
      .unwrap();
      String::from_utf8_lossy(&seen).to_string()
    });
    (base, handle)
  }

  #[test]
  fn a_patch_with_a_body_arrives_whole_and_carries_no_origin() {
    let (base, server) = serve("200 OK", r#"{"item":{"state":"done"}}"#);
    let reply = call_engine(&base, "PATCH", "/api/queue/qa", Some(r#"{"state":"done"}"#.into()), Duration::from_secs(5)).unwrap();
    let request = server.join().unwrap().to_lowercase();
    assert_eq!(reply.status, 200);
    assert!(reply.body.contains("done"));
    assert!(request.starts_with("patch /api/queue/qa "), "{request}");
    assert!(request.contains(r#"{"state":"done"}"#));
    assert!(!request.contains("\r\norigin:"), "the engine treats a call with no origin as native: {request}");
  }

  #[test]
  fn an_error_status_is_an_answer_not_a_failure() {
    let (base, server) = serve("409 Conflict", r#"{"detail":"conflict"}"#);
    let reply = call_engine(&base, "GET", "/api/queue", None, Duration::from_secs(5)).unwrap();
    server.join().unwrap();
    assert_eq!(reply.status, 409);
    assert!(reply.body.contains("conflict"));
  }
}
