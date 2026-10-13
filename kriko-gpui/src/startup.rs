//! Per-user launch-at-login mode. The Windows Run entry and macOS LaunchAgent
//! are the platform sources of truth.
#[cfg(any(windows, target_os = "macos", test))]
use std::path::Path;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    Off,
    Window,
    Tray,
}

#[cfg(any(windows, test))]
pub fn command(exe: &Path, mode: Mode) -> String {
    format!("\"{}\"{}", exe.display(), if mode == Mode::Tray { " --background" } else { "" })
}

#[cfg(any(windows, test))]
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
    #[cfg(target_os = "macos")]
    {
        let path = launch_agent_path(name)?;
        if !path.exists() {
            return Ok(Mode::Off);
        }
        let output = std::process::Command::new("/usr/bin/plutil")
            .args(["-convert", "json", "-o", "-"])
            .arg(&path)
            .output()
            .map_err(|e| format!("Could not read the macOS login item: {e}"))?;
        if !output.status.success() {
            return Err("The macOS login item is not a valid property list.".into());
        }
        let plist: serde_json::Value = serde_json::from_slice(&output.stdout)
            .map_err(|e| format!("Could not read the macOS login item: {e}"))?;
        let arguments = plist
            .get("ProgramArguments")
            .and_then(serde_json::Value::as_array)
            .ok_or("The macOS login item has no program arguments.")?;
        if arguments.is_empty() || arguments.iter().any(|arg| !arg.is_string()) {
            return Err("The macOS login item has invalid program arguments.".into());
        }
        Ok(if arguments.iter().skip(1).any(|arg| arg == "--background") {
            Mode::Tray
        } else {
            Mode::Window
        })
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    { let _ = name; Ok(Mode::Off) }
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
    #[cfg(target_os = "macos")]
    {
        let path = launch_agent_path(name)?;
        if mode == Mode::Off {
            match std::fs::remove_file(path) {
                Ok(()) => Ok(()),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
                Err(error) => Err(format!("Could not remove the macOS login item: {error}")),
            }
        } else {
            let executable = std::env::current_exe().map_err(|e| e.to_string())?;
            let parent = path.parent().ok_or("Could not find the LaunchAgents folder.")?;
            std::fs::create_dir_all(parent)
                .map_err(|e| format!("Could not create the LaunchAgents folder: {e}"))?;
            let temporary = path.with_extension("plist.tmp");
            std::fs::write(&temporary, launch_agent_plist(name, &executable, mode))
                .map_err(|e| format!("Could not save the macOS login item: {e}"))?;
            std::fs::rename(&temporary, &path)
                .map_err(|e| format!("Could not install the macOS login item: {e}"))?;
            Ok(())
        }
    }
    #[cfg(not(any(windows, target_os = "macos")))]
    { let _ = (name, mode); Err("Launch at login is only available on Windows and macOS.".into()) }
}

#[cfg(target_os = "macos")]
fn launch_agent_path(name: &str) -> Result<std::path::PathBuf, String> {
    let home = std::env::var_os("HOME").ok_or("Cannot find the user home directory.")?;
    let label = launch_agent_label(name);
    Ok(std::path::PathBuf::from(home)
        .join("Library")
        .join("LaunchAgents")
        .join(format!("{label}.plist")))
}

#[cfg(any(target_os = "macos", test))]
fn launch_agent_label(name: &str) -> String {
    let suffix: String = name
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect();
    format!("com.kriko.{}", suffix.trim_matches('-'))
}

#[cfg(any(target_os = "macos", test))]
fn launch_agent_plist(name: &str, executable: &Path, mode: Mode) -> String {
    let xml = |value: &str| {
        value
            .replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('"', "&quot;")
            .replace('\'', "&apos;")
    };
    let mut arguments = vec![executable.display().to_string()];
    if mode == Mode::Tray {
        arguments.push("--background".into());
    }
    let arguments = arguments
        .iter()
        .map(|argument| format!("\t\t<string>{}</string>\n", xml(argument)))
        .collect::<String>();
    format!(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n\
         <!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \
         \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n\
         <plist version=\"1.0\">\n<dict>\n\
         \t<key>Label</key>\n\t<string>{}</string>\n\
         \t<key>ProgramArguments</key>\n\t<array>\n{}\t</array>\n\
         \t<key>RunAtLoad</key>\n\t<true/>\n\
         </dict>\n</plist>\n",
        xml(&launch_agent_label(name)),
        arguments,
    )
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
    #[test]
    fn mac_login_agent_escapes_its_path_and_selects_background_mode() {
        let plist = launch_agent_plist(
            "Kriko",
            Path::new("/Applications/Kriko & Tools/Kriko.app/Contents/MacOS/kriko"),
            Mode::Tray,
        );
        assert!(plist.contains("<string>/Applications/Kriko &amp; Tools/Kriko.app/Contents/MacOS/kriko</string>"));
        assert!(plist.contains("<string>--background</string>"));
        assert!(plist.contains("<string>com.kriko.kriko</string>"));
        assert!(!launch_agent_plist("Kriko", Path::new("/Applications/Kriko.app/Contents/MacOS/kriko"), Mode::Window)
            .contains("--background"));
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
