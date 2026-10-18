//! Running an installer the engine has already downloaded and checked.
//!
//! The engine asks the releases page and fetches the installer against the
//! checksums published beside it (`src/app/appupdate.py`). Replacing the app is
//! this side's job, because only the shell can leave: the installer replaces
//! `kriko.exe`, and a running program is a locked file.
//!
//! The page is not trusted with the path. Only a file the engine's updater
//! could have written is run: `kriko-<version>-x86_64-setup.exe`, in a
//! `kriko-update-…` folder of the temp directory.

use std::path::{Path, PathBuf};

/// Whether this copy was put here by the installer, and so can be updated by it.
/// The installer writes `uninstall.exe` beside the app; a portable folder, a
/// development build and another platform have none, and are not touched.
pub fn installed() -> bool {
  cfg!(windows)
    && std::env::current_exe()
      .ok()
      .and_then(|exe| exe.parent().map(|dir| dir.join("uninstall.exe")))
      .is_some_and(|path| path.is_file())
}

/// `kriko-0.2.3-x86_64-setup.exe`: a version of digits, dots and a tag, nothing else.
fn is_installer_name(name: &str) -> bool {
  let Some(version) = name.strip_prefix("kriko-").and_then(|rest| rest.strip_suffix("-x86_64-setup.exe")) else {
    return false;
  };
  version.chars().next().is_some_and(|c| c.is_ascii_digit())
    && version.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
}

/// The file to run, or why it will not be run.
pub fn vetted(path: &Path, temp: &Path) -> Result<PathBuf, String> {
  let file = path.canonicalize().map_err(|_| "The downloaded update is not there any more.".to_string())?;
  let temp = temp.canonicalize().map_err(|e| e.to_string())?;
  let name = file.file_name().and_then(|n| n.to_str()).unwrap_or("");
  let folder = file.parent().and_then(|p| p.file_name()).and_then(|n| n.to_str()).unwrap_or("");
  let inside = file.parent().and_then(|p| p.parent()).is_some_and(|parent| parent == temp);
  if !(inside && folder.starts_with("kriko-update-") && is_installer_name(name) && file.is_file()) {
    return Err("That is not an update Kriko downloaded.".into());
  }
  Ok(file)
}

/// Start the installer so that it outlives this process. It runs with a
/// progress window (`/P`), as an update (`/UPDATE`), and opens Kriko again when it
/// is done (`/R`). It is started through `cmd /c start` so that it is not a
/// child of this program: its first act is to end every running Kriko by name
/// and with its children, and a child would be ended with them.
#[cfg(windows)]
pub fn launch(installer: &Path) -> Result<(), String> {
  use std::os::windows::process::CommandExt;
  const CREATE_NO_WINDOW: u32 = 0x0800_0000;
  std::process::Command::new("cmd")
    .raw_arg(format!("/c start \"\" \"{}\" /P /UPDATE /R", installer.display()))
    .creation_flags(CREATE_NO_WINDOW)
    .spawn()
    .map(|_| ())
    .map_err(|e| format!("The installer could not be started: {e}"))
}

#[cfg(not(windows))]
pub fn launch(_installer: &Path) -> Result<(), String> {
  Err("Updating from inside the app is for the Windows installer.".into())
}

#[cfg(test)]
mod tests {
  use super::*;

  #[test]
  fn only_the_updaters_own_file_names_pass() {
    assert!(is_installer_name("kriko-0.2.3-x86_64-setup.exe"));
    assert!(is_installer_name("kriko-1.0.0-rc.1-x86_64-setup.exe"));
    assert!(!is_installer_name("kriko-x86_64-setup.exe"));
    assert!(!is_installer_name("kriko--x86_64-setup.exe"));
    assert!(!is_installer_name("setup.exe"));
    assert!(!is_installer_name("kriko-0.2.3-x86_64-setup.exe.bat"));
    assert!(!is_installer_name("kriko-0.2.3 & calc-x86_64-setup.exe"));
    assert!(!is_installer_name("kriko-0.2.3\"-x86_64-setup.exe"));
  }

  #[test]
  fn a_file_outside_the_update_folder_is_refused() {
    let temp = std::env::temp_dir().join(format!("kriko-vet-{}", std::process::id()));
    let good = temp.join("kriko-update-abc");
    let other = temp.join("elsewhere");
    std::fs::create_dir_all(&good).unwrap();
    std::fs::create_dir_all(&other).unwrap();
    let ok = good.join("kriko-0.2.3-x86_64-setup.exe");
    let wrong_folder = other.join("kriko-0.2.3-x86_64-setup.exe");
    let wrong_name = good.join("evil.exe");
    for file in [&ok, &wrong_folder, &wrong_name] {
      std::fs::write(file, b"x").unwrap();
    }
    assert!(vetted(&ok, &temp).is_ok());
    assert!(vetted(&wrong_folder, &temp).is_err());
    assert!(vetted(&wrong_name, &temp).is_err());
    assert!(vetted(&good.join("missing-x86_64-setup.exe"), &temp).is_err());
    std::fs::remove_dir_all(&temp).ok();
  }
}
