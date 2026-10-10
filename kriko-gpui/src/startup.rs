//! Windows login mode. The Run entry is the source of truth.
use std::path::Path;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    Off,
    Window,
    Tray,
}

pub fn command(exe: &Path, mode: Mode) -> String {
    format!("\"{}\"{}", exe.display(), if mode == Mode::Tray { " --background" } else { "" })
}

pub fn command_mode(value: &str) -> Mode {
    // Ignore the executable itself, including spaces and flag-like filenames.
    let value = value.trim();
    let args = if let Some(quoted) = value.strip_prefix('"') {
        quoted.split_once('"').map(|(_, args)| args).unwrap_or("")
    } else {
        value.split_once(char::is_whitespace).map(|(_, args)| args).unwrap_or("")
    };
    if args.split_whitespace().any(|arg| arg == "--background") { Mode::Tray } else { Mode::Window }
}

#[cfg(windows)]
const KEY: &str = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run";

#[cfg(windows)]
fn reg(args: &[&str]) -> Result<std::process::Output, String> {
    use std::os::windows::process::CommandExt;
    std::process::Command::new("reg.exe").args(args).creation_flags(0x0800_0000)
        .output().map_err(|e| e.to_string())
}

pub fn read(name: &str) -> Result<Mode, String> {
    #[cfg(windows)] {
        #[link(name = "advapi32")]
        extern "system" {
            fn RegGetValueW(key: isize, subkey: *const u16, value: *const u16, flags: u32,
                kind: *mut u32, data: *mut std::ffi::c_void, size: *mut u32) -> i32;
        }
        let wide = |value: &str| value.encode_utf16().chain(Some(0)).collect::<Vec<_>>();
        let key = wide(r"Software\Microsoft\Windows\CurrentVersion\Run");
        let value = wide(name);
        let mut bytes = 0;
        let get = |data, bytes: &mut u32| unsafe {
            RegGetValueW(0x8000_0001u32 as i32 as isize, key.as_ptr(), value.as_ptr(),
                2, std::ptr::null_mut(), data, bytes)
        };
        match get(std::ptr::null_mut(), &mut bytes) {
            2 => return Ok(Mode::Off), // ERROR_FILE_NOT_FOUND (also a missing Run key)
            0 => {},
            code => return Err(format!("Windows could not read the login setting (error {code}).")),
        }
        let mut data = vec![0u16; (bytes as usize + 1) / 2];
        let code = get(data.as_mut_ptr().cast(), &mut bytes);
        if code != 0 { return Err(format!("Windows could not read the login setting (error {code}).")); }
        let text = String::from_utf16_lossy(&data[..data.iter().position(|c| *c == 0).unwrap_or(data.len())]);
        Ok(command_mode(&text))
    }
    #[cfg(not(windows))] { let _ = name; Ok(Mode::Off) }
}

pub fn write(name: &str, mode: Mode) -> Result<(), String> {
    #[cfg(windows)] {
        let out = if mode == Mode::Off {
            if read(name)? == Mode::Off { return Ok(()); }
            reg(&["delete", KEY, "/v", name, "/f"])?
        } else {
            let exe = std::env::current_exe().map_err(|e| e.to_string())?;
            reg(&["add", KEY, "/v", name, "/t", "REG_SZ", "/d", &command(&exe, mode), "/f"])?
        };
        if out.status.success() { Ok(()) } else { Err("Windows would not save the login setting.".into()) }
    }
    #[cfg(not(windows))] { let _ = (name, mode); Err("Launch at login is only available on Windows.".into()) }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn quoted_paths_and_background_arguments_round_trip() {
        let exe = Path::new(r"C:\Program Files\Kriko\kriko.exe");
        assert_eq!(command_mode(&command(exe, Mode::Window)), Mode::Window);
        assert_eq!(command_mode(&command(exe, Mode::Tray)), Mode::Tray);
        assert_eq!(command_mode(r#""C:\--background\kriko.exe""#), Mode::Window);
        assert_eq!(command_mode(r#""C:\Kriko\kriko.exe" --background-other"#), Mode::Window);
    }
    #[cfg(windows)]
    #[test]
    fn windows_login_modes_round_trip() {
        let name = format!("KrikoTestLoginMode-{}", std::process::id());
        struct Cleanup(String);
        impl Drop for Cleanup { fn drop(&mut self) { let _ = write(&self.0, Mode::Off); } }
        let _cleanup = Cleanup(name.clone());
        for mode in [Mode::Window, Mode::Tray, Mode::Window, Mode::Off] {
            write(&name, mode).unwrap();
            assert_eq!(read(&name).unwrap(), mode);
        }
    }
}
