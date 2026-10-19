//! Which engine to start: the one this app carries, or a newer one staged beside it.
//!
//! An engine update is a folder of its own, `<engines>/<version>/`, written
//! whole by the engine (`src/app/engineupdate.py`) and never written to again.
//! This side only reads them. At the next engine start the newest folder that is
//! ready, not marked bad, newer than the engine the app carries and meant for
//! this app wins; when it cannot start, [`mark_bad`] sets it aside and the next
//! start picks the one before it, ending at the engine beside this program,
//! which an update never touches. So a broken engine costs a restart, not a
//! reinstall.
//!
//! Plain `std` on purpose: the rule is small, and it has to be testable without
//! the window toolkit.

use std::path::{Path, PathBuf};

/// Written by the updater after everything else. A folder without it is half a download.
pub const READY: &str = "ready";
/// Written here when an engine would not start. Never removed: the engine's own
/// housekeeping deletes the folder.
pub const BAD: &str = "bad";
const MANIFEST: &str = "engine.json";

/// Where engine folders live. Must equal `engineupdate.engines_root` in the engine.
pub fn engines_root() -> Option<PathBuf> {
  if let Some(forced) = std::env::var_os("KRIKO_ENGINES_DIR") {
    return Some(PathBuf::from(forced));
  }
  if let Some(local) = std::env::var_os("LOCALAPPDATA") {
    return Some(PathBuf::from(local).join("Kriko").join("engines"));
  }
  std::env::var_os("USERPROFILE")
    .or_else(|| std::env::var_os("HOME"))
    .map(|home| PathBuf::from(home).join(".kriko").join("engines"))
}

/// A version as numbers, read as `appupdate.version_key` reads it: leading
/// dotted digits, anything after a `-` ignored, so `0.10.0` is after `0.2.3`.
pub fn version_key(text: &str) -> Vec<u64> {
  let core = text.trim().trim_start_matches(['v', 'V']).split('-').next().unwrap_or("");
  core
    .split('.')
    .map(|piece| {
      let digits: String = piece.chars().take_while(|c| c.is_ascii_digit()).collect();
      digits.parse().unwrap_or(0)
    })
    .collect()
}

/// An engine folder that may be started.
#[derive(Debug, PartialEq)]
pub struct Engine {
  pub version: String,
  pub dir: PathBuf,
  pub program: PathBuf,
}

/// The `min_shell` of an `engine.json`, `"0"` when it names none. The file is
/// written by this project's own packager, so a scan for the key is enough.
fn min_shell(manifest: &str) -> String {
  let Some(at) = manifest.find("\"min_shell\"") else { return "0".into() };
  let rest = &manifest[at + "\"min_shell\"".len()..];
  let Some(open) = rest.find('"') else { return "0".into() };
  let value = &rest[open + 1..];
  value.find('"').map(|close| value[..close].to_string()).unwrap_or_else(|| "0".into())
}

/// The newest staged engine that is newer than `carried` and runs under `shell`.
pub fn pick(root: &Path, carried: &str, shell: &str, program_name: &str) -> Option<Engine> {
  let mut best: Option<Engine> = None;
  for entry in std::fs::read_dir(root).ok()?.flatten() {
    let dir = entry.path();
    let Some(version) = dir.file_name().and_then(|n| n.to_str()).map(str::to_string) else { continue };
    let program = dir.join(program_name);
    let usable = dir.is_dir()
      && dir.join(READY).is_file()
      && !dir.join(BAD).exists()
      && program.is_file()
      && version_key(&version) > version_key(carried)
      && version_key(shell)
        >= version_key(&min_shell(&std::fs::read_to_string(dir.join(MANIFEST)).unwrap_or_default()));
    if !usable {
      continue;
    }
    if best.as_ref().is_none_or(|b| version_key(&version) > version_key(&b.version)) {
      best = Some(Engine { version, dir, program });
    }
  }
  best
}

/// Set an engine aside so the next start does not choose it again.
pub fn mark_bad(dir: &Path, why: &str) {
  let _ = std::fs::write(dir.join(BAD), why);
}

#[cfg(test)]
mod tests {
  use super::*;

  fn scratch(name: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("kriko-versions-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
  }

  fn engine(root: &Path, version: &str, ready: bool, min_shell: &str) -> PathBuf {
    let dir = root.join(version);
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("kriko-sidecar.exe"), b"x").unwrap();
    std::fs::write(dir.join(MANIFEST), format!("{{\"version\": \"{version}\", \"min_shell\": \"{min_shell}\"}}")).unwrap();
    if ready {
      std::fs::write(dir.join(READY), version).unwrap();
    }
    dir
  }

  #[test]
  fn versions_compare_as_numbers() {
    assert!(version_key("0.10.0") > version_key("0.2.3"));
    assert!(version_key("v1.0.0") > version_key("0.9.9"));
    assert_eq!(version_key("1.2.0-rc.1"), vec![1, 2, 0]);
    assert!(version_key("0.3.0") > version_key("0.2.5"));
  }

  #[test]
  fn the_newest_ready_engine_newer_than_the_one_carried_wins() {
    let root = scratch("newest");
    engine(&root, "0.2.5", true, "0");
    engine(&root, "0.3.0", true, "0");
    engine(&root, "0.3.1", true, "0");
    let got = pick(&root, "0.2.5", "0.2.5", "kriko-sidecar.exe").unwrap();
    assert_eq!(got.version, "0.3.1");
    assert_eq!(got.program, root.join("0.3.1").join("kriko-sidecar.exe"));
    std::fs::remove_dir_all(&root).ok();
  }

  #[test]
  fn an_engine_that_is_not_newer_than_the_carried_one_is_never_chosen() {
    let root = scratch("older");
    engine(&root, "0.2.4", true, "0");
    engine(&root, "0.2.5", true, "0");
    assert_eq!(pick(&root, "0.2.5", "0.2.5", "kriko-sidecar.exe"), None);
    std::fs::remove_dir_all(&root).ok();
  }

  #[test]
  fn half_a_download_a_bad_engine_and_one_for_a_newer_app_are_skipped() {
    let root = scratch("skipped");
    engine(&root, "0.3.0", false, "0");
    let bad = engine(&root, "0.3.1", true, "0");
    mark_bad(&bad, "did not start");
    engine(&root, "0.3.2", true, "9.0.0");
    let fine = engine(&root, "0.3.3", true, "0.2.5");
    assert_eq!(pick(&root, "0.2.5", "0.2.5", "kriko-sidecar.exe").unwrap().dir, fine);
    mark_bad(&fine, "did not start");
    assert_eq!(pick(&root, "0.2.5", "0.2.5", "kriko-sidecar.exe"), None);
    std::fs::remove_dir_all(&root).ok();
  }

  #[test]
  fn a_folder_with_no_program_is_skipped() {
    let root = scratch("noprogram");
    let dir = engine(&root, "0.3.0", true, "0");
    std::fs::remove_file(dir.join("kriko-sidecar.exe")).unwrap();
    assert_eq!(pick(&root, "0.2.5", "0.2.5", "kriko-sidecar.exe"), None);
    std::fs::remove_dir_all(&root).ok();
  }

  #[test]
  fn no_engines_folder_is_no_override() {
    assert_eq!(pick(Path::new("/definitely/not/here"), "0.2.5", "0.2.5", "kriko-sidecar.exe"), None);
  }

  #[test]
  fn the_manifest_floor_is_read() {
    assert_eq!(min_shell("{\"version\": \"1\", \"min_shell\": \"0.2.6\"}"), "0.2.6");
    assert_eq!(min_shell("{\"version\": \"1\"}"), "0");
    assert_eq!(min_shell(""), "0");
  }
}
