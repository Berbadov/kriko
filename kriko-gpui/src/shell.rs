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
use gpui::AppContext;

/// The main window's HWND, once it exists.
static HWND: AtomicIsize = AtomicIsize::new(0);
/// Whether the tray exists, i.e. whether hiding is safe.
static TRAY: AtomicBool = AtomicBool::new(false);
thread_local! {
    static WINDOW: std::cell::Cell<Option<gpui::AnyWindowHandle>> = const { std::cell::Cell::new(None) };
}

/// Something the reader did in the tray.
#[cfg(any(windows, target_os = "macos"))]
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
        pub fn MessageBoxW(hwnd: isize, text: *const u16, caption: *const u16, kind: u32) -> i32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        pub fn OpenProcess(access: u32, inherit: i32, pid: u32) -> isize;
        pub fn CloseHandle(h: isize) -> i32;
        pub fn QueryFullProcessImageNameW(h: isize, flags: u32, name: *mut u16, size: *mut u32) -> i32;
        pub fn GetCurrentProcessId() -> u32;
        pub fn CreateEventW(security: *const std::ffi::c_void, manual_reset: i32, initial: i32, name: *const u16) -> isize;
        pub fn OpenEventW(access: u32, inherit: i32, name: *const u16) -> isize;
        pub fn SetEvent(event: isize) -> i32;
        pub fn WaitForSingleObject(event: isize, milliseconds: u32) -> u32;
    }
    pub const SW_HIDE: i32 = 0;
    pub const SW_SHOW: i32 = 5;
    pub const SW_RESTORE: i32 = 9;
    pub const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
    pub const MB_ICONERROR: u32 = 0x10;
}

/// What the reader is told when the window cannot be made at all.
pub fn window_failure_text(error: &str) -> String {
    format!(
        "Kriko could not open its window.\n\n{error}\n\n\
         Kriko draws with DirectX 11. Updating the graphics driver usually \
         fixes this. Over Remote Desktop or in a virtual machine it may not \
         be available."
    )
}

/// Say a failure that happened before there is a window to say it in. A
/// release build on Windows has no console, so without this a failed
/// window was a program that vanished without a word.
pub fn tell_fatal(text: &str) {
    eprintln!("{text}");
    #[cfg(windows)]
    {
        let wide = |s: &str| s.encode_utf16().chain(std::iter::once(0)).collect::<Vec<u16>>();
        let (body, title) = (wide(text), wide("Kriko"));
        unsafe {
            win::MessageBoxW(0, body.as_ptr(), title.as_ptr(), win::MB_ICONERROR);
        }
    }
}

#[cfg(test)]
mod fatal_tests {
    #[test]
    fn a_failed_window_says_why_and_what_to_try() {
        let t = super::window_failure_text("Creating DirectX renderer: Not implemented. (0x80004001)");
        assert!(t.starts_with("Kriko could not open its window."));
        assert!(t.contains("0x80004001"), "the cause is kept, so it can be reported");
        assert!(t.contains("graphics driver"));
    }
}

#[cfg(windows)]
mod activation {
    use super::{win, AtomicIsize, Ordering};
    static EVENT: AtomicIsize = AtomicIsize::new(0);
    fn name(pid: u32) -> Vec<u16> {
        format!("Local\\Kriko.OpenWindow.{pid}").encode_utf16().chain(Some(0)).collect()
    }
    pub fn init() {
        unsafe {
            let handle = win::CreateEventW(std::ptr::null(), 0, 0, name(win::GetCurrentProcessId()).as_ptr());
            EVENT.store(handle, Ordering::SeqCst);
        }
    }
    pub fn signal(pid: u32) -> bool {
        unsafe {
            let handle = win::OpenEventW(2, 0, name(pid).as_ptr()); // EVENT_MODIFY_STATE
            if handle == 0 { return false; }
            let result = win::SetEvent(handle) != 0;
            win::CloseHandle(handle);
            result
        }
    }
    pub fn take() -> bool {
        let handle = EVENT.load(Ordering::SeqCst);
        handle != 0 && unsafe { win::WaitForSingleObject(handle, 0) == 0 }
    }
    pub fn remove() {
        let handle = EVENT.swap(0, Ordering::SeqCst);
        if handle != 0 { unsafe { win::CloseHandle(handle); } }
    }
    #[cfg(test)]
    #[test]
    fn another_launch_can_request_one_window_activation() {
        init();
        assert!(!take());
        assert!(signal(unsafe { win::GetCurrentProcessId() }));
        assert!(take());
        assert!(!take());
        remove();
    }
}

/// Remembers the main window, from GPUI's raw handle.
pub fn remember_window(window: &gpui::Window) {
    WINDOW.set(Some(window.window_handle()));
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
    #[cfg(windows)]
    {
        TRAY.load(Ordering::SeqCst) && HWND.load(Ordering::SeqCst) != 0
    }
    #[cfg(target_os = "macos")]
    {
        TRAY.load(Ordering::SeqCst)
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    {
        false
    }
}

pub fn hide_window(cx: &mut gpui::App) {
    #[cfg(windows)]
    unsafe {
        let _ = cx;
        let hwnd = HWND.load(Ordering::SeqCst);
        if hwnd != 0 {
            win::ShowWindow(hwnd, win::SW_HIDE);
        }
    }
    // The status item remains in the menu bar while NSApp hides its windows.
    // Opening Kriko from that menu re-activates the app and its saved window.
    #[cfg(target_os = "macos")]
    cx.hide();
    #[cfg(not(any(windows, target_os = "macos")))]
    let _ = cx;
}

/// Shows, un-minimises and raises the window.
pub fn show_window(cx: &mut gpui::App) {
    // NSWindow activation alone does not unhide an application that was
    // hidden when its close button was used.
    #[cfg(target_os = "macos")]
    cx.activate(true);
    // A window created with show:false has deferred placement in GPUI.
    // Activation applies that placement before we restore/raise its HWND.
    if let Some(handle) = WINDOW.get() {
        let _ = cx.update_window(handle, |_root, window, _cx| window.activate_window());
    }
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
pub fn raise_running_instance(show: bool) -> bool {
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
            // Let the owning GPUI thread apply deferred window placement.
            // Older installed versions have no event and use the legacy raise.
            if show && !activation::signal(pid) { raise(hwnd); }
            return true;
        }
        false
    }
    #[cfg(not(windows))]
    {
        let _ = show;
        false
    }
}

pub fn has_tray() -> bool {
    TRAY.load(Ordering::SeqCst)
}

// ---- the tray ----

#[cfg(any(windows, target_os = "macos"))]
mod tray {
    use super::TrayAction;
    use std::cell::RefCell;
    use tray_icon::menu::{Menu, MenuEvent, MenuItem};
    use tray_icon::{MouseButton, MouseButtonState, TrayIcon, TrayIconBuilder, TrayIconEvent};
    #[cfg(windows)]
    use tray_icon::Icon;

    thread_local! {
        // the icon lives as long as the UI thread; dropping it removes it
        static ICON: RefCell<Option<TrayIcon>> = const { RefCell::new(None) };
    }

    pub fn build() -> Result<(), String> {
        let open = MenuItem::with_id("open", "Open Kriko", true, None);
        let quit = MenuItem::with_id("quit", "Quit Kriko", true, None);
        let menu = Menu::with_items(&[&open, &quit]).map_err(|e| e.to_string())?;
        // The exe's own icon resource (build.rs embeds assets/kriko.ico as 1).
        // macOS uses a text status item; its app icon is supplied by the bundle.
        #[cfg(windows)]
        let icon = Icon::from_resource(1, None).map_err(|e| e.to_string())?;
        #[cfg(windows)]
        let tray = TrayIconBuilder::new()
            .with_tooltip("Kriko — connecting to engine")
            .with_menu(Box::new(menu))
            .with_menu_on_left_click(false)
            .with_icon(icon)
            .build()
            .map_err(|e| e.to_string())?;
        #[cfg(target_os = "macos")]
        let tray = TrayIconBuilder::new()
            .with_title("Kriko")
            .with_tooltip("Kriko — connecting to engine")
            .with_menu(Box::new(menu))
            .with_menu_on_left_click(false)
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
    activation::init();
    #[cfg(any(windows, target_os = "macos"))]
    match tray::build() {
        Ok(()) => TRAY.store(true, Ordering::SeqCst),
        Err(e) => log::warn!("tray: {e}; closing the window will quit Kriko"),
    }
}

/// What was clicked in the tray since the last call.
#[cfg(any(windows, target_os = "macos"))]
pub fn poll_tray() -> Vec<TrayAction> {
    let mut actions = tray::poll();
    #[cfg(windows)]
    if activation::take() { actions.push(TrayAction::Open); }
    actions
}

pub fn remove_tray() {
    #[cfg(any(windows, target_os = "macos"))]
    {
        tray::remove();
        #[cfg(windows)]
        activation::remove();
    }
}

/// The tray remains visible when the window is hidden, so its label must
/// describe the engine's actual state rather than merely the app process.
pub fn set_tray_status(ready: bool, failed: bool) {
    #[cfg(any(windows, target_os = "macos"))]
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
