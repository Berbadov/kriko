//! Where is each CLI? `PATH` first, then the folders these CLIs install into.

use serde_json::{Value, json};
use std::path::{Path, PathBuf};

pub fn answer(request: &Value) -> Value {
    let path = std::env::split_paths(request["path"].as_str().unwrap_or_default()).collect::<Vec<_>>();
    let suffixes = crate::strings(&request["suffixes"]);
    let mut found = serde_json::Map::new();
    for item in request["items"].as_array().map(Vec::as_slice).unwrap_or_default() {
        let name = item["name"].as_str().unwrap_or_default();
        let roots: Vec<PathBuf> = crate::strings(&item["roots"]).into_iter().map(PathBuf::from).collect();
        let hit = first_in(&path, name, &suffixes).or_else(|| first_in(&roots, name, &suffixes));
        found.insert(
            item["id"].as_str().unwrap_or_default().to_owned(),
            json!(hit.map(|p| p.display().to_string()).unwrap_or_default()),
        );
    }
    json!({ "found": found })
}

fn first_in(folders: &[PathBuf], name: &str, suffixes: &[String]) -> Option<PathBuf> {
    folders.iter().find_map(|folder| {
        suffixes.iter().map(|suffix| folder.join(format!("{name}{suffix}"))).find(|file| runnable(file))
    })
}

#[cfg(unix)]
fn runnable(file: &Path) -> bool {
    use std::os::unix::fs::PermissionsExt;
    file.metadata().is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
}

#[cfg(not(unix))]
fn runnable(file: &Path) -> bool {
    file.is_file()
}
