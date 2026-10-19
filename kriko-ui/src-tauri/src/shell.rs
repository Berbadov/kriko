//! The window's life: it hides instead of closing, and a tray icon holds the
//! process. The engine outlives the window, so the browser extension still has
//! something to talk to while the reader is on a listing page. Only Quit ends
//! it.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager};

use crate::engine;

/// Set only when the tray was actually built. A hidden window with no tray is
/// a process nobody can find, so without one, closing the window quits.
static TRAY: AtomicBool = AtomicBool::new(false);

pub fn can_hide() -> bool {
  TRAY.load(Ordering::SeqCst)
}

/// Bring the window back, also when it was hidden or minimised.
pub fn show_window(app: &AppHandle) {
  if let Some(window) = app.get_webview_window("main") {
    let _ = window.show();
    let _ = window.unminimize();
    let _ = window.set_focus();
  }
}

pub fn hide_window(app: &AppHandle) {
  if let Some(window) = app.get_webview_window("main") {
    let _ = window.hide();
  }
}

/// End the engine this app started, then the app. In this order: ending the
/// app first leaves the engine to notice that its pipe closed, and the next
/// installer then fails on a `kriko-sidecar.exe` that is still mapped.
pub fn quit(app: &AppHandle) {
  engine::stop();
  app.exit(0);
}

/// Where the window's size and place are remembered.
///
/// `tauri.conf.json` declares 1360×860 and nothing else ever recorded anything,
/// so a reader who resizes Kriko, moves it to their second screen and maximises
/// it got 1360×860 in the same place on the primary screen at every launch.
/// This is a small JSON file in the reader's own folder rather than a plugin:
/// one boolean and four numbers do not need a dependency, and a dependency here
/// would be fetched (and re-resolved) by every build.
fn window_state_path() -> Option<std::path::PathBuf> {
  engine::data_dir().map(|dir| dir.join("window.json"))
}

fn read_window_state() -> Option<(f64, f64, f64, f64, bool)> {
  let text = std::fs::read_to_string(window_state_path()?).ok()?;
  let number = |key: &str| -> Option<f64> {
    let at = text.find(&format!("\"{key}\""))?;
    let rest = &text[at + key.len() + 2..];
    let colon = rest.find(':')? + 1;
    let tail = rest[colon..].trim_start();
    let end = tail.find(|c: char| c == ',' || c == '}').unwrap_or(tail.len());
    tail[..end].trim().parse::<f64>().ok()
  };
  let maximized = text.contains("\"maximized\":true") || text.contains("\"maximized\": true");
  Some((number("x")?, number("y")?, number("width")?, number("height")?, maximized))
}

fn write_window_state(window: &tauri::WebviewWindow) {
  let Some(path) = window_state_path() else { return };
  if let Some(parent) = path.parent() {
    let _ = std::fs::create_dir_all(parent);
  }
  let maximized = window.is_maximized().unwrap_or(false);
  // Position and size are recorded even while maximised: unmaximising should
  // return the window to the shape the reader chose, not to the default.
  let (x, y) = match window.outer_position() {
    Ok(at) => (at.x, at.y),
    Err(_) => (0, 0),
  };
  let size = window.inner_size().unwrap_or(tauri::PhysicalSize::new(1360, 860));
  let body = format!(
    "{{\"x\":{x},\"y\":{y},\"width\":{},\"height\":{},\"maximized\":{maximized}}}\n",
    size.width, size.height,
  );
  let _ = std::fs::write(path, body);
}

/// Apply what was remembered, once, before the window is shown.
pub fn restore_window(window: &tauri::WebviewWindow) {
  let Some((x, y, width, height, maximized)) = read_window_state() else { return };
  if width >= 320.0 && height >= 240.0 {
    let _ = window.set_size(tauri::LogicalSize::new(width, height));
  }
  // A screen that is gone is a real case (a laptop undocked from a second
  // monitor). Asking the window's own monitor list keeps the window reachable.
  let on_screen = match (window.current_monitor(), window.primary_monitor()) {
    (Ok(Some(current)), _) => (x, y).0 >= current.position().x as f64 - 4000.0
      && (x, y).1 >= current.position().y as f64 - 4000.0,
    _ => true,
  };
  if on_screen {
    let _ = window.set_position(tauri::LogicalPosition::new(x, y));
  }
  if maximized {
    let _ = window.maximize();
  }
}

/// Remember the window's shape as it changes, and once more on the way out.
pub fn watch_window(window: &tauri::WebviewWindow) {
  let handle = window.clone();
  window.on_window_event(move |event| match event {
    tauri::WindowEvent::Resized(_) | tauri::WindowEvent::Moved(_) => write_window_state(&handle),
    tauri::WindowEvent::CloseRequested { .. } => write_window_state(&handle),
    _ => {}
  });
}

pub fn build_tray(app: &AppHandle) -> tauri::Result<()> {
  let open = MenuItem::with_id(app, "open", "Open Kriko", true, None::<&str>)?;
  let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
  let menu = Menu::with_items(app, &[&open, &quit_item])?;
  let mut builder = TrayIconBuilder::with_id("kriko")
    .tooltip("Kriko")
    .menu(&menu)
    .show_menu_on_left_click(false)
    .on_menu_event(|app, event| match event.id.as_ref() {
      "open" => show_window(app),
      "quit" => quit(app),
      _ => {}
    })
    .on_tray_icon_event(|tray, event| {
      if let TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. } = event {
        show_window(tray.app_handle());
      }
    });
  if let Some(icon) = app.default_window_icon() {
    builder = builder.icon(icon.clone());
  }
  builder.build(app)?;
  TRAY.store(true, Ordering::SeqCst);
  Ok(())
}
