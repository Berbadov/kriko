use serde_json::{Value, json};
use std::io::Write;
use std::process::{Command, Stdio};
use std::time::Instant;

fn call(request: Value) -> Value {
    let mut child = Command::new(env!("CARGO_BIN_EXE_kriko-harness"))
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(request.to_string().as_bytes()).unwrap();
    serde_json::from_slice(&child.wait_with_output().unwrap().stdout).unwrap()
}

fn probe(seconds: f64, jobs: Value) -> Value {
    call(json!({ "op": "probe", "seconds": seconds, "jobs": jobs }))["results"].clone()
}

fn sh(key: &str, script: &str) -> Value {
    json!({ "key": key, "argv": ["sh", "-c", script] })
}

#[test]
fn locate_prefers_path_then_roots() {
    let dir = std::env::temp_dir().join(format!("kriko-locate-{}", std::process::id()));
    let (on_path, in_root) = (dir.join("a"), dir.join("b"));
    std::fs::create_dir_all(&on_path).unwrap();
    std::fs::create_dir_all(&in_root).unwrap();
    for file in [on_path.join("one"), in_root.join("one"), in_root.join("two")] {
        std::fs::write(&file, "#!/bin/sh\n").unwrap();
        #[cfg(unix)]
        #[cfg(unix)]
        std::fs::set_permissions(&file, std::os::unix::fs::PermissionsExt::from_mode(0o755)).unwrap();
    }
    let found = call(json!({
        "op": "locate", "path": on_path, "suffixes": [""],
        "items": [
            { "id": "x", "name": "one", "roots": [in_root] },
            { "id": "y", "name": "two", "roots": [in_root] },
            { "id": "z", "name": "missing", "roots": [in_root] },
        ],
    }))["found"]
        .clone();
    assert_eq!(found["x"], on_path.join("one").display().to_string());
    assert_eq!(found["y"], in_root.join("two").display().to_string());
    assert_eq!(found["z"], "");
}

#[cfg(unix)]
#[test]
fn probes_run_together_and_keep_stderr() {
    let started = Instant::now();
    let results = probe(5.0, json!([sh("a", "sleep 1; echo out; echo err >&2"), sh("b", "sleep 1; echo b")]));
    assert!(started.elapsed().as_secs_f64() < 1.8, "ran one after the other");
    assert_eq!(results["a"]["text"], "out\nerr\n");
    assert_eq!(results["b"]["text"], "b\n");
}

#[cfg(unix)]
#[test]
fn a_slow_probe_does_not_sink_a_fast_one() {
    let results = probe(1.0, json!([sh("slow", "sleep 30"), sh("fast", "echo hi")]));
    assert_eq!(results["slow"], json!({ "ok": false, "reason": "timed out" }));
    assert_eq!(results["fast"]["text"], "hi\n");
}

#[cfg(unix)]
#[test]
fn a_timeout_kills_what_the_command_started() {
    let marker = std::env::temp_dir().join(format!("kriko-grandchild-{}", std::process::id()));
    let script = format!("(sleep 2; touch {}) & sleep 30", marker.display());
    let started = Instant::now();
    let results = probe(0.5, json!([sh("a", &script)]));
    assert_eq!(results["a"]["reason"], "timed out");
    assert!(started.elapsed().as_secs_f64() < 2.0);
    std::thread::sleep(std::time::Duration::from_millis(2500));
    assert!(!marker.exists(), "the grandchild outlived the kill");
}

#[cfg(unix)]
#[test]
fn only_the_last_lines_are_kept() {
    let mut job = sh("a", "seq 1 1000");
    job["keep"] = json!(3);
    let results = probe(5.0, json!([job]));
    assert_eq!(results["a"]["text"], "998\n999\n1000\n");
}

#[test]
fn a_missing_program_is_a_reason_not_a_crash() {
    let results = probe(5.0, json!([{ "key": "a", "argv": ["/no/such/cli", "--help"] }]));
    assert_eq!(results["a"]["ok"], false);
}
