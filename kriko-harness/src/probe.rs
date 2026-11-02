//! Run short commands (`--help`, `models`) all at once.
//!
//! Each gets its own deadline and no queue, so a slow CLI never makes a fast
//! one look dead. A command that outlives its deadline is killed with
//! everything it started.

use serde_json::{Value, json};
use std::collections::VecDeque;
use std::io::{BufRead, BufReader};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

const DEFAULT_SECONDS: f64 = 12.0;
const DEFAULT_KEEP: usize = 400;

pub fn answer(request: &Value) -> Value {
    let seconds = request["seconds"].as_f64().unwrap_or(DEFAULT_SECONDS);
    let deadline = Instant::now() + Duration::from_secs_f64(seconds);
    let env: Vec<(String, String)> = request["env"]
        .as_object()
        .into_iter()
        .flatten()
        .filter_map(|(k, v)| Some((k.clone(), v.as_str()?.to_owned())))
        .collect();
    let jobs = request["jobs"].as_array().map(Vec::as_slice).unwrap_or_default();
    let workers: Vec<_> = jobs
        .iter()
        .map(|job| {
            let key = job["key"].as_str().unwrap_or_default().to_owned();
            let argv = crate::strings(&job["argv"]);
            let keep = job["keep"].as_u64().map_or(DEFAULT_KEEP, |n| n as usize);
            let env = env.clone();
            thread::spawn(move || (key, ask(&argv, &env, keep, deadline)))
        })
        .collect();
    let mut results = serde_json::Map::new();
    for worker in workers {
        if let Ok((key, result)) = worker.join() {
            results.insert(key, match result {
                Ok(text) => json!({ "ok": true, "text": text }),
                Err(reason) => json!({ "ok": false, "reason": reason }),
            });
        }
    }
    json!({ "results": results })
}

fn ask(argv: &[String], env: &[(String, String)], keep: usize, deadline: Instant) -> Result<String, String> {
    let (program, args) = argv.split_first().ok_or("empty command")?;
    let (output, input) = std::io::pipe().map_err(|e| e.to_string())?;
    let mut command = Command::new(program);
    command
        .args(args)
        .envs(env.iter().cloned())
        .stdin(Stdio::null())
        .stdout(input.try_clone().map_err(|e| e.to_string())?)
        .stderr(input);
    if let Some(path) = path_with_home_of(program, env) {
        command.env("PATH", path);
    }
    new_group(&mut command);
    let mut child = command.spawn().map_err(|e| format!("could not start: {e}"))?;
    drop(command);

    let (lines, heard) = mpsc::channel();
    thread::spawn(move || {
        for line in BufReader::new(output).lines().map_while(Result::ok) {
            if lines.send(line).is_err() {
                break;
            }
        }
    });

    let mut tail = VecDeque::new();
    loop {
        match heard.recv_timeout(deadline.saturating_duration_since(Instant::now())) {
            Ok(line) => {
                tail.push_back(line);
                if tail.len() > keep {
                    tail.pop_front();
                }
            }
            Err(mpsc::RecvTimeoutError::Timeout) => return timed_out(&mut child),
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
        }
    }
    while child.try_wait().map_err(|e| e.to_string())?.is_none() {
        if Instant::now() >= deadline {
            return timed_out(&mut child);
        }
        thread::sleep(Duration::from_millis(10));
    }
    Ok(tail.into_iter().map(|line| line + "\n").collect())
}

fn timed_out(child: &mut Child) -> Result<String, String> {
    kill_tree(child);
    Err("timed out".into())
}

fn path_with_home_of(program: &str, env: &[(String, String)]) -> Option<std::ffi::OsString> {
    let home = Path::new(program).parent().filter(|p| !p.as_os_str().is_empty())?;
    let current = env.iter().find(|(k, _)| k == "PATH").map(|(_, v)| v.into()).or_else(|| std::env::var_os("PATH"))?;
    std::env::join_paths(std::iter::once(home.to_path_buf()).chain(std::env::split_paths(&current))).ok()
}

#[cfg(unix)]
fn new_group(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.process_group(0);
}

#[cfg(unix)]
fn kill_tree(child: &mut Child) {
    unsafe { libc::kill(-(child.id() as i32), libc::SIGKILL) };
    let _ = child.wait();
}

#[cfg(windows)]
fn new_group(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x0800_0000);
}

#[cfg(windows)]
fn kill_tree(child: &mut Child) {
    use std::os::windows::process::CommandExt;
    let _ = Command::new("taskkill")
        .args(["/F", "/T", "/PID", &child.id().to_string()])
        .creation_flags(0x0800_0000)
        .output();
    let _ = child.kill();
    let _ = child.wait();
}
