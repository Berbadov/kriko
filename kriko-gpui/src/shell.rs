//! The window's life outside the window: the tray, close-means-hide, and
//! one Kriko per machine.
//!
//! **Window is not Quit.** The browser extension needs the engine whether or
//! not the window is open, so closing the window hides it and the engine
//! keeps serving. The tray is how you get it back (Open Kriko, or a left
//! click) and the only way to end it (Quit Kriko: the engine first, then the
//! app). If the tray cannot be made, closing quits instead, because a hidden
//! window with no way back would be a process nobody can find.
//!
//! **One Kriko.** A second launch finds the first one's window, raises it,
//! and exits before it starts a second engine.

use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};

/// The main window's HWND, once it exists.
static HWND: AtomicIsize = AtomicIsize::new(0);
/// Whether the tray exists, i.e. whether hiding is safe.
static TRAY: AtomicBool = AtomicBool::new(false);

/// Something the reader did in the tray.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum TrayAction {
    Open,
    Quit,
}

#[cfg(windows)]
mod win {
    #[link(name = "user32")]
    extern "system" {
        pub fn ShowWindow(hwnd: isize, cmd: i32) -> i32;
        pub fn SetForegroundWindow(hwnd: isize) -> i32;
        pub fn IsIconic(hwnd: isize) -> i32;
        pub fn FindWindowW(class: *const u16, title: *const u16) -> isize;
        pub fn GetWindowThreadProcessId(hwnd: isize, pid: *mut u32) -> u32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        pub fn OpenProcess(access: u32, inherit: i32, pid: u32) -> isize;
        pub fn CloseHandle(h: isize) -> i32;
        pub fn QueryFullProcessImageNameW(h: isize, flags: u32, name: *mut u16, size: *mut u32) -> i32;
        pub fn GetCurrentProcessId() -> u32;
    }
    pub const SW_HIDE: i32 = 0;
    pub const SW_SHOW: i32 = 5;
    pub const SW_RESTORE: i32 = 9;
    pub const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
}

/// Remembers the main window, from GPUI's raw handle.
pub fn remember_window(window: &gpui::Window) {
    #[cfg(windows)]
    {
        use raw_window_handle::{HasWindowHandle, RawWindowHandle};
        if let Ok(handle) = HasWindowHandle::window_handle(window) {
            if let RawWindowHandle::Win32(h) = handle.as_raw() {
                HWND.store(h.hwnd.get(), Ordering::SeqCst);
            }
        }
    }
    #[cfg(not(windows))]
    let _ = window;
}

/// Whether closing the window should hide it (there is a tray to come back
/// through) rather than quit.
pub fn can_hide() -> bool {
    TRAY.load(Ordering::SeqCst) && HWND.load(Ordering::SeqCst) != 0
}

pub fn hide_window() {
    #[cfg(windows)]
    unsafe {
        let hwnd = HWND.load(Ordering::SeqCst);
        if hwnd != 0 {
            win::ShowWindow(hwnd, win::SW_HIDE);
        }
    }
}

/// Shows, un-minimises and raises the window.
pub fn show_window() {
    #[cfg(windows)]
    unsafe {
        let hwnd = HWND.load(Ordering::SeqCst);
        if hwnd != 0 {
            raise(hwnd);
        }
    }
}

#[cfg(windows)]
unsafe fn raise(hwnd: isize) {
    win::ShowWindow(hwnd, win::SW_SHOW);
    if win::IsIconic(hwnd) != 0 {
        win::ShowWindow(hwnd, win::SW_RESTORE);
    }
    win::SetForegroundWindow(hwnd);
}

/// When another Kriko is already running, raises its window and returns
/// true: this launch should exit. The window is matched by title *and* by
/// the owning process's exe name, so a browser tab called "Kriko" is not
/// mistaken for the app.
pub fn raise_running_instance() -> bool {
    #[cfg(windows)]
    unsafe {
        let title: Vec<u16> = "Kriko".encode_utf16().chain(std::iter::once(0)).collect();
        let hwnd = win::FindWindowW(std::ptr::null(), title.as_ptr());
        if hwnd == 0 {
            return false;
        }
        let mut pid = 0u32;
        win::GetWindowThreadProcessId(hwnd, &mut pid);
        if pid == 0 || pid == win::GetCurrentProcessId() {
            return false;
        }
        let ours = std::env::current_exe()
            .ok()
            .and_then(|p| p.file_name().map(|n| n.to_string_lossy().to_lowercase()));
        let proc = win::OpenProcess(win::PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if proc == 0 {
            return false;
        }
        let mut buf = [0u16; 1024];
        let mut len = buf.len() as u32;
        let ok = win::QueryFullProcessImageNameW(proc, 0, buf.as_mut_ptr(), &mut len);
        win::CloseHandle(proc);
        if ok == 0 {
            return false;
        }
        let theirs = String::from_utf16_lossy(&buf[..len as usize]).to_lowercase();
        if ours.is_some_and(|name| theirs.ends_with(&name)) {
            raise(hwnd);
            return true;
        }
        false
    }
    #[cfg(not(windows))]
    false
}

// ---- the tray ----

#[cfg(windows)]
mod tray {
    use super::TrayAction;
    use std::cell::RefCell;
    use tray_icon::menu::{Menu, MenuEvent, MenuItem};
    use tray_icon::{Icon, MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};

    thread_local! {
        // the icon lives as long as the UI thread; dropping it removes it
        static ICON: RefCell<Option<TrayIcon>> = const { RefCell::new(None) };
    }

    pub fn build() -> Result<(), String> {
        let open = MenuItem::with_id("open", "Open Kriko", true, None);
        let quit = MenuItem::with_id("quit", "Quit Kriko", true, None);
        let menu = Menu::with_items(&[&open, &quit]).map_err(|e| e.to_string())?;
        // the exe's own icon resource (build.rs embeds assets/kriko.ico as 1)
        let icon = Icon::from_resource(1, None).map_err(|e| e.to_string())?;
        let tray = TrayIconBuilder::new()
            .with_tooltip("Kriko — connecting to engine")
            .with_menu(Box::new(menu))
            .with_menu_on_left_click(false)
            .with_icon(icon)
            .build()
            .map_err(|e| e.to_string())?;
        ICON.with(|slot| *slot.borrow_mut() = Some(tray));
        Ok(())
    }

    pub fn poll() -> Vec<TrayAction> {
        let mut out = Vec::new();
        while let Ok(event) = MenuEvent::receiver().try_recv() {
            match event.id.0.as_str() {
                "open" => out.push(TrayAction::Open),
                "quit" => out.push(TrayAction::Quit),
                _ => {}
            }
        }
        while let Ok(event) = TrayIconEvent::receiver().try_recv() {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                out.push(TrayAction::Open);
            }
        }
        out
    }

    pub fn remove() {
        ICON.with(|slot| slot.borrow_mut().take());
    }

    pub fn set_tooltip(text: &str) {
        ICON.with(|slot| {
            if let Some(icon) = slot.borrow().as_ref() {
                let _ = icon.set_tooltip(Some(text));
            }
        });
    }
}

/// Puts Kriko in the tray. On failure closing will quit, never strand.
pub fn build_tray() {
    #[cfg(windows)]
    match tray::build() {
        Ok(()) => TRAY.store(true, Ordering::SeqCst),
        Err(e) => log::warn!("tray: {e}; closing the window will quit Kriko"),
    }
}

/// What was clicked in the tray since the last call.
pub fn poll_tray() -> Vec<TrayAction> {
    #[cfg(windows)]
    {
        tray::poll()
    }
    #[cfg(not(windows))]
    Vec::new()
}

pub fn remove_tray() {
    #[cfg(windows)]
    tray::remove();
}

/// The tray remains visible when the window is hidden, so its label must
/// describe the engine's actual state rather than merely the app process.
pub fn set_tray_status(ready: bool, failed: bool) {
    #[cfg(windows)]
    tray::set_tooltip(if ready {
        "Kriko — engine ready for browser extension"
    } else if failed {
        "Kriko — engine stopped; open the app"
    } else {
        "Kriko — connecting to engine"
    });
    #[cfg(not(windows))]
    let _ = (ready, failed);
}
