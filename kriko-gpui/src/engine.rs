//! The engine's supervisor: start it, learn its port, wait until it answers,
//! and end it with the app. A supervisor, not a second engine: nothing here
//! knows what the engine stores, only how to keep it alive and reachable.
//!
//! Where the engine comes from, first match wins:
//!
//! 1. `KRIKO_URL` set: attach to that address, start nothing.
//! 2. `kriko-sidecar[.exe]` beside this app executable (the installed layout): start it.
//! 3. An engine already answering on the extension port: attach to it.
//! 4. A source checkout: `python -m app.sidecar` (`KRIKO_PYTHON` picks the
//!    interpreter).
//!
//! The handshake is the sidecar's: the first stdout line holding
//! [`PORT_LINE`] names a port it already holds. `--exit-with-parent` makes it
//! watch its stdin, so the write end is kept here for the whole run: if this
//! process dies in any way at all, the pipe closes and the engine follows.
//! On Windows a one-file bundle re-executes, so the pid spawned is only a
//! bootloader; [`stop`] ends the whole tree.

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

/// The sidecar prints this, then its port. Must equal `app.sidecar.PORT_LINE`.
pub const PORT_LINE: &str = "KRIKO_PORT";
/// The sidecar prints this with a route when something asks to raise Kriko.
pub const FOCUS_LINE: &str = "KRIKO_FOCUS";
/// Default second socket for the browser extension. Must equal
/// `app.web.settings.EXTENSION_PORT`.
pub const EXTENSION_PORT: u16 = 8787;

fn extension_port_path() -> Option<std::path::PathBuf> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(|home| std::path::PathBuf::from(home).join(".kriko").join("extension-port"))
}

/// What OpenSERP is started with unless the reader has their own file.
///
/// Two stock settings made a quick look's searches the slowest part of it
/// (measured, four searches: 52 s). Its limiter lets each engine answer one
/// query in ten seconds: 3 s for the first, then 10.0 s for every one after.
/// And an engine that times out is tried four times before the search
/// answers, because a search waits for its slowest engine: 35-40 s for one
/// query. One query per three seconds with a burst of three, and no retries
/// (the other engine answers meanwhile), brings a search to 3-8 s. The file is
/// written once and never again, so an edit survives every update, as
/// `models.toml` does.
const OPENSERP_CONFIG: &str = "# Written once by Kriko and never rewritten: edit freely.
# Each engine answers one query per `rate_seconds`, with `rate_burst` allowed
# at once; the stock limiter is about one query in ten seconds. `max_retries`
# is how often a timed-out engine is asked again before the search answers
# (stock: 3, which made a failing engine cost 35 s).
resilience:
  max_retries: 0
bing:
  rate_requests: 1
  rate_seconds: 3
  rate_burst: 3
duckduckgo:
  rate_requests: 1
  rate_seconds: 3
  rate_burst: 3
";

fn openserp_config_path() -> Option<std::path::PathBuf> {
    extension_port_path().map(|path| path.with_file_name("openserp.yaml"))
}

/// The config file to start OpenSERP with: the reader's own, else the default
/// written beside it. `None` (stock limits) when it cannot be written.
fn ensure_openserp_config() -> Option<std::path::PathBuf> {
    let path = openserp_config_path()?;
    write_openserp_config_once(&path)?;
    Some(path)
}

/// Writes the default only when no file is there, so an edit is never lost.
fn write_openserp_config_once(path: &std::path::Path) -> Option<()> {
    if !path.is_file() {
        std::fs::create_dir_all(path.parent()?).ok()?;
        std::fs::write(path, OPENSERP_CONFIG).ok()?;
    }
    Some(())
}

/// The reader's saved listener port, or the default on a new install.
pub fn configured_extension_port() -> u16 {
    extension_port_path()
        .and_then(|path| std::fs::read_to_string(path).ok())
        .and_then(|text| text.trim().parse::<u16>().ok())
        .filter(|port| *port != 0)
        .unwrap_or(EXTENSION_PORT)
}

/// Save a port before restarting the supervised sidecar.
pub fn set_extension_port(port: u16) -> Result<(), String> {
    if port == 0 {
        return Err("Choose a port from 1 to 65535.".into());
    }
    let path = extension_port_path().ok_or("Cannot find the user home directory.")?;
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::write(path, port.to_string()).map_err(|e| e.to_string())
}
/// How long the engine gets to answer `/api/health` after it names a port.
const HEALTH_TIMEOUT: Duration = Duration::from_secs(45);
/// The most stderr kept for the failure screen (the tail is what matters).
const STDERR_KEEP: usize = 24 * 1024;

#[derive(Clone, Debug, PartialEq)]
pub enum Status {
    /// Looking for, starting, or waiting on the engine. The string says which.
    Starting(String),
    /// Answering at `base` (`http://127.0.0.1:<port>`).
    Ready { base: String, version: String },
    /// It could not start, or it stopped. `detail` is what it said on stderr.
    Failed { title: String, detail: String },
}

/// Something the engine asked the window to do.
#[derive(Clone, Debug, PartialEq)]
pub enum ShellEvent {
    /// Raise the window (and open this route, when there is one).
    Focus(String),
}

struct Supervisor {
    status: Status,
    events: Vec<ShellEvent>,
    child: Option<Child>,
    /// OpenSERP, only when this app started it. A healthy service already on
    /// the local search port is reused and never put in this slot.
    openserp_child: Option<Child>,
    openserp_health_failures: u8,
    openserp_unhealthy_since: Option<Instant>,
    stdin: Option<ChildStdin>,
    stderr: String,
    started: bool,
    generation: u64,
}

fn sup() -> &'static Mutex<Supervisor> {
    static SUP: OnceLock<Mutex<Supervisor>> = OnceLock::new();
    SUP.get_or_init(|| {
        Mutex::new(Supervisor {
            status: Status::Starting("Starting Kriko's engine…".into()),
            events: Vec::new(),
            child: None,
            openserp_child: None,
            openserp_health_failures: 0,
            openserp_unhealthy_since: None,
            stdin: None,
            stderr: String::new(),
            started: false,
            generation: 0,
        })
    })
}

fn set_status(generation: u64, status: Status) {
    let mut s = sup().lock().unwrap();
    if s.started && s.generation == generation {
        s.status = status;
    }
}

/// The engine's state right now.
pub fn status() -> Status {
    sup().lock().unwrap().status.clone()
}

/// The engine's address once it answers.
pub fn base() -> Option<String> {
    match status() {
        Status::Ready { base, .. } => Some(base),
        _ => None,
    }
}

/// What the engine asked for since the last call, oldest first.
pub fn take_events() -> Vec<ShellEvent> {
    std::mem::take(&mut sup().lock().unwrap().events)
}

/// Starts the engine (or attaches to one) on a background thread. Calling
/// it again while a start is in flight or done does nothing, so a retry
/// after a failure is [`restart`].
pub fn start() {
    let generation = {
        let mut s = sup().lock().unwrap();
        if s.started {
            return;
        }
        s.started = true;
        s.generation += 1;
        s.stderr.clear();
        s.status = Status::Starting("Starting Kriko's engine…".into());
        s.generation
    };
    std::thread::Builder::new()
        .name("engine-supervisor".into())
        .spawn(move || supervise(generation))
        .ok();
}

/// Starts again after a failure.
pub fn restart() {
    stop();
    start();
}

fn supervise(generation: u64) {
    if let Ok(url) = std::env::var("KRIKO_URL") {
        let url = url.trim_end_matches('/').to_string();
        attach(&url, generation);
        return;
    }
    ensure_openserp(generation);
    // Search is an optional sidecar from the engine's point of view, but it
    // must recover if our owned process exits after the initial health check.
    // The generation guard makes this watcher end with stop/restart.
    std::thread::Builder::new()
        .name("openserp-supervisor".into())
        .spawn(move || supervise_openserp(generation))
        .ok();
    let extension_port = configured_extension_port();
    let beside = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join(sidecar_name())))
        .filter(|path| path.is_file());
    let mut command = match beside {
        Some(path) => Command::new(path),
        None => {
            // no bundled engine: a running one is the next best thing
            let fixed = format!("http://127.0.0.1:{extension_port}");
            if health(&fixed).is_ok() {
                attach(&fixed, generation);
                return;
            }
            let python = std::env::var("KRIKO_PYTHON")
                .ok()
                .map(std::path::PathBuf::from)
                .or_else(checkout_python)
                .unwrap_or_else(|| "python".into());
            let mut c = Command::new(python);
            c.args(["-m", "app.sidecar"]);
            c
        }
    };
    command.arg("--extension-port").arg(extension_port.to_string());
    spawn(command, generation);
}

/// The source checkout's own virtualenv, found by walking up from this exe
/// (`kriko-gpui/target/<profile>/kriko[.exe]` sits three levels below it).
fn checkout_python() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let venv = if cfg!(windows) { ".venv/Scripts/python.exe" } else { ".venv/bin/python" };
    exe.ancestors().skip(1).take(6).map(|dir| dir.join(venv)).find(|p| p.is_file())
}

fn sidecar_name() -> &'static str {
    if cfg!(windows) {
        "kriko-sidecar.exe"
    } else {
        "kriko-sidecar"
    }
}

fn attach(base: &str, generation: u64) {
    set_status(generation, Status::Starting(format!("Connecting to {base}…")));
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    loop {
        match health(base) {
            Ok(version) => {
                set_status(generation, Status::Ready { base: base.to_string(), version });
                return;
            }
            Err(e) if Instant::now() >= deadline => {
                set_status(generation, Status::Failed {
                    title: "Kriko's engine never answered".into(),
                    detail: format!("{base}/api/health: {e}"),
                });
                return;
            }
            Err(_) => std::thread::sleep(Duration::from_millis(200)),
        }
    }
}

fn spawn(mut command: Command, generation: u64) {
    command
        .args(["--exit-with-parent", "--supervised"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(e) => {
            set_status(generation, Status::Failed {
                title: "Kriko's engine could not be started".into(),
                detail: format!("{:?}: {e}", command.get_program()),
            });
            return;
        }
    };
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    {
        let mut s = sup().lock().unwrap();
        s.stdin = child.stdin.take();
        s.child = Some(child);
    }
    if let Some(mut err) = stderr {
        std::thread::spawn(move || {
            let mut buf = [0u8; 4096];
            while let Ok(n) = err.read(&mut buf) {
                if n == 0 {
                    break;
                }
                let mut s = sup().lock().unwrap();
                s.stderr.push_str(&String::from_utf8_lossy(&buf[..n]));
                if s.stderr.len() > STDERR_KEEP {
                    let from = s.stderr.len() - STDERR_KEEP;
                    let cut = (from..s.stderr.len())
                        .find(|i| s.stderr.is_char_boundary(*i))
                        .unwrap_or(0);
                    s.stderr.drain(..cut);
                }
            }
        });
    }
    let Some(out) = stdout else { return };
    let mut port: Option<u16> = None;
    for line in BufReader::new(out).lines() {
        let Ok(line) = line else { break };
        if port.is_none() && line.contains(PORT_LINE) {
            port = line
                .split(PORT_LINE)
                .nth(1)
                .and_then(|rest| rest.trim().parse::<u16>().ok());
            if let Some(p) = port {
                std::thread::spawn(move || attach(&format!("http://127.0.0.1:{p}"), generation));
            }
        } else if line.contains(FOCUS_LINE) {
            let route = line.split(FOCUS_LINE).nth(1).unwrap_or("").trim().to_string();
            sup().lock().unwrap().events.push(ShellEvent::Focus(route));
        }
    }
    // stdout closed: the engine has ended, or is about to
    let mut code = None;
    for _ in 0..20 {
        let mut s = sup().lock().unwrap();
        match s.child.as_mut().map(|c| c.try_wait()) {
            Some(Ok(Some(st))) => {
                code = st.code();
                break;
            }
            Some(Ok(None)) => {}
            _ => break,
        }
        drop(s);
        std::thread::sleep(Duration::from_millis(50));
    }
    let mut s = sup().lock().unwrap();
    if !s.started || s.generation != generation {
        return; // stopped on purpose
    }
    let said = s.stderr.trim().to_string();
    let detail = if said.is_empty() {
        format!(
            "It exited without saying anything. Exit code: {}.",
            code.map(|c| c.to_string()).unwrap_or_else(|| "unknown".into())
        )
    } else {
        said
    };
    s.status = Status::Failed {
        title: if port.is_none() {
            "Kriko's engine stopped before it started".into()
        } else {
            "Kriko's engine stopped".into()
        },
        detail,
    };
}

/// Ends the engine this app started, the whole process tree. An attached
/// engine is left alone: it was not ours to end.
pub fn stop() {
    let (child, stdin, openserp) = {
        let mut s = sup().lock().unwrap();
        s.started = false;
        s.generation += 1;
        (s.child.take(), s.stdin.take(), s.openserp_child.take())
    };
    drop(stdin); // the polite way: the sidecar watches this pipe
    if let Some(mut child) = child {
        let pid = child.id();
        let _ = child.kill();
        kill_tree(pid);
        let _ = child.wait();
    }
    if let Some(mut child) = openserp {
        let pid = child.id();
        let _ = child.kill();
        kill_tree(pid);
        let _ = child.wait();
    }
}

/// Start the bundled search service only when its default loopback port is
/// free. Existing healthy services are reused; another process is never
/// terminated or replaced.
fn ensure_openserp(generation: u64) {
    const PORT: u16 = 7000;
    const BASE: &str = "http://127.0.0.1:7000";
    const START_TIMEOUT: Duration = Duration::from_secs(12);
    // Reap our child before deciding whether to attach or start. A healthy
    // listener with no owned child is external and must be left alone.
    let mut owned = {
        let mut state = sup().lock().unwrap();
        if !state.started || state.generation != generation {
            return;
        }
        match state.openserp_child.as_mut().map(Child::try_wait) {
            Some(Ok(Some(_))) => state.openserp_child.take(),
            Some(Ok(None)) | Some(Err(_)) => None,
            None => None,
        }
    };
    if let Some(mut child) = owned.take() {
        log::warn!("The supervised OpenSERP process exited; checking whether its port is available.");
        let _ = child.wait();
        let mut state = sup().lock().unwrap();
        if state.generation == generation {
            state.openserp_health_failures = 0;
            state.openserp_unhealthy_since = None;
        }
    }
    if openserp_healthy(BASE) {
        let mut state = sup().lock().unwrap();
        if state.generation == generation {
            state.openserp_health_failures = 0;
            state.openserp_unhealthy_since = None;
        }
        return;
    }

    // One slow health response can overlap an in-flight search. Require
    // repeated failures before replacing a live process we own. A process
    // that has exited is still recovered immediately above.
    let mut owned_unhealthy = {
        let mut state = sup().lock().unwrap();
        if !state.started || state.generation != generation {
            return;
        }
        let running = matches!(state.openserp_child.as_mut().map(Child::try_wait), Some(Ok(None)));
        if !running {
            state.openserp_health_failures = 0;
            state.openserp_unhealthy_since = None;
            None
        } else {
            state.openserp_health_failures = state.openserp_health_failures.saturating_add(1);
            let since = *state.openserp_unhealthy_since.get_or_insert_with(Instant::now);
            if state.openserp_health_failures >= 3 || since.elapsed() >= Duration::from_secs(10) {
                state.openserp_health_failures = 0;
                state.openserp_unhealthy_since = None;
                state.openserp_child.take()
            } else {
                None
            }
        }
    };
    if let Some(mut child) = owned_unhealthy.take() {
        let pid = child.id();
        let _ = child.kill();
        kill_tree(pid);
        let _ = child.wait();
    }
    if TcpStream::connect_timeout(
        &std::net::SocketAddr::from(([127, 0, 0, 1], PORT)),
        Duration::from_millis(250),
    ).is_ok() {
        log::warn!("Port {PORT} is in use, but the service did not pass OpenSERP health; leaving it untouched.");
        return;
    }
    let Some(executable) = openserp_executable() else {
        log::warn!("OpenSERP is not bundled or present in this checkout; local research needs OpenSERP on port {PORT}.");
        return;
    };
    let mut command = Command::new(&executable);
    command.args(["serve", "--host", "127.0.0.1", "--port", "7000", "--quiet"]);
    // Only the OpenSERP shipped beside this app, whose config schema the file
    // was written against; another binary keeps its own stock limits.
    let bundled = std::env::current_exe()
        .ok()
        .and_then(|app| app.parent().map(|dir| dir == executable.parent().unwrap_or(dir)))
        .unwrap_or(false);
    if bundled {
        if let Some(config) = ensure_openserp_config() {
            command.arg("-c").arg(config);
        }
    }
    command
        .current_dir(executable.parent().unwrap_or_else(|| std::path::Path::new(".")))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let child = match command.spawn() {
        Ok(child) => child,
        Err(error) => {
            log::warn!("Could not start OpenSERP at {}: {error}", executable.display());
            return;
        }
    };
    let pid = child.id();
    {
        let mut state = sup().lock().unwrap();
        if !state.started || state.generation != generation {
            drop(state);
            let mut child = child;
            let _ = child.kill();
            kill_tree(pid);
            let _ = child.wait();
            return;
        }
        state.openserp_child = Some(child);
    }
    let deadline = Instant::now() + START_TIMEOUT;
    while Instant::now() < deadline {
        if openserp_healthy(BASE) {
            return;
        }
        {
            let mut state = sup().lock().unwrap();
            if !state.started || state.generation != generation {
                return;
            }
            if let Some(child) = state.openserp_child.as_mut() {
                if child.try_wait().ok().flatten().is_some() {
                    log::warn!("OpenSERP exited before its health check passed.");
                    state.openserp_child = None;
                    return;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    log::warn!("OpenSERP did not become healthy on port {PORT} in time.");
    let owned = {
        let mut state = sup().lock().unwrap();
        if state.started && state.generation == generation {
            state.openserp_child.take()
        } else {
            None
        }
    };
    if let Some(mut child) = owned {
        let pid = child.id();
        let _ = child.kill();
        kill_tree(pid);
        let _ = child.wait();
    }
}

fn supervise_openserp(generation: u64) {
    loop {
        {
            let state = sup().lock().unwrap();
            if !state.started || state.generation != generation {
                return;
            }
        }
        ensure_openserp(generation);
        std::thread::sleep(Duration::from_secs(3));
    }
}

fn openserp_executable() -> Option<std::path::PathBuf> {
    let current = std::env::current_exe().ok()?;
    let sibling = current.parent()?.join(if cfg!(windows) { "OpenSERP.exe" } else { "openserp" });
    if sibling.is_file() {
        return Some(sibling);
    }
    if let Some(path) = std::env::var_os("KRIKO_OPENSERP_EXE") {
        let path = std::path::PathBuf::from(path);
        if path.is_file() {
            return Some(path);
        }
    }
    current.ancestors().find_map(|dir| {
        let candidate = dir.join(".local-evaluation/openserp")
            .join(if cfg!(windows) { "openserp.exe" } else { "openserp" });
        candidate.is_file().then_some(candidate)
    })
}

fn openserp_healthy(base: &str) -> bool {
    let Ok((host, port)) = host_port(base) else { return false };
    let Ok(address) = format!("{host}:{port}").parse() else { return false };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(350)) else {
        return false;
    };
    stream.set_read_timeout(Some(Duration::from_millis(700))).ok();
    if write!(stream, "GET /health HTTP/1.0\r\nHost: {host}:{port}\r\n\r\n").is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() { return false; }
    let body = response.split("\r\n\r\n").nth(1).unwrap_or("");
    let Ok(value) = serde_json::from_str::<serde_json::Value>(body) else { return false };
    let status = value.get("status").and_then(|v| v.as_str()).unwrap_or("");
    if status == "healthy" || status == "ok" || value.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        return true;
    }
    // OpenSERP reports `degraded` when one upstream engine has opened its
    // circuit breaker. It remains useful when at least one engine is ready;
    // treating that partial failure as service death causes needless restarts.
    status == "degraded"
        && value.get("engines").and_then(|engines| engines.as_array()).is_some_and(|engines| {
            engines.iter().any(|engine| {
                engine.get("status").and_then(|v| v.as_str()) == Some("ready")
            })
        })
}

#[cfg(windows)]
fn kill_tree(pid: u32) {
    use std::os::windows::process::CommandExt;
    let _ = Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .creation_flags(0x0800_0000)
        .status();
}

#[cfg(not(windows))]
fn kill_tree(_pid: u32) {}

/// `GET /api/health`: the engine's version when it answers `ok`.
fn health(base: &str) -> Result<String, String> {
    let (host, port) = host_port(base)?;
    let addr = format!("{host}:{port}").parse().map_err(|e| format!("{e}"))?;
    let mut stream =
        TcpStream::connect_timeout(&addr, Duration::from_millis(800)).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(5))).ok();
    write!(stream, "GET /api/health HTTP/1.0\r\nHost: {host}:{port}\r\n\r\n")
        .map_err(|e| e.to_string())?;
    let mut body = String::new();
    stream.read_to_string(&mut body).map_err(|e| e.to_string())?;
    let json = body.split("\r\n\r\n").nth(1).unwrap_or("");
    let value: serde_json::Value = serde_json::from_str(json).map_err(|_| "not ready".to_string())?;
    if value.get("ok").and_then(|v| v.as_bool()) != Some(true) {
        return Err("not ready".into());
    }
    Ok(value
        .get("version")
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string())
}

/// `http://127.0.0.1:8787` -> ("127.0.0.1", 8787).
pub fn host_port(base: &str) -> Result<(String, u16), String> {
    let rest = base
        .strip_prefix("http://")
        .ok_or_else(|| format!("{base}: only http:// on this machine"))?;
    let rest = rest.split('/').next().unwrap_or(rest);
    let (host, port) = rest.rsplit_once(':').unwrap_or((rest, "80"));
    let port = port.parse::<u16>().map_err(|e| format!("{base}: {e}"))?;
    let host = if host == "localhost" { "127.0.0.1" } else { host };
    Ok((host.to_string(), port))
}

#[cfg(test)]
mod openserp_config_tests {
    use super::*;

    #[test]
    fn the_default_is_written_once_and_an_edit_survives() {
        let dir = std::env::temp_dir().join(format!("kriko-openserp-{}", std::process::id()));
        let path = dir.join("nested").join("openserp.yaml");
        let _ = std::fs::remove_dir_all(&dir);

        assert!(write_openserp_config_once(&path).is_some());
        let written = std::fs::read_to_string(&path).unwrap();
        assert!(written.contains("rate_seconds: 3"));
        assert!(written.contains("max_retries: 0"));

        std::fs::write(&path, "# mine
").unwrap();
        assert!(write_openserp_config_once(&path).is_some());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "# mine
");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
