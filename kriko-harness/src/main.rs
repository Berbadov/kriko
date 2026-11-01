//! One request on stdin, one answer on stdout, both JSON.
//!
//! `locate` finds CLIs on disk. `probe` runs short commands, all at once, each
//! with its own deadline. See `docs/ARCHITECTURE.md` for who calls this.

mod locate;
mod probe;

use serde_json::{Value, json};
use std::io::Read;

fn main() {
    let mut input = String::new();
    if std::io::stdin().read_to_string(&mut input).is_err() {
        return fail("could not read the request");
    }
    let request: Value = match serde_json::from_str(&input) {
        Ok(value) => value,
        Err(error) => return fail(&format!("not JSON: {error}")),
    };
    let answer = match request["op"].as_str() {
        Some("locate") => locate::answer(&request),
        Some("probe") => probe::answer(&request),
        other => return fail(&format!("unknown op {other:?}")),
    };
    println!("{answer}");
}

fn fail(reason: &str) {
    println!("{}", json!({ "error": reason }));
    std::process::exit(2);
}

pub fn strings(value: &Value) -> Vec<String> {
    let list = value.as_array().map(Vec::as_slice).unwrap_or_default();
    list.iter().filter_map(|v| v.as_str().map(str::to_owned)).collect()
}
