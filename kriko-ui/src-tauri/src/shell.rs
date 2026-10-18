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
