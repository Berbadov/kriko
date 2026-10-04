//! The engine's supervisor: start it, learn its port, wait until it answers,
//! and end it with the app. A supervisor, not a second engine: nothing here
//! knows what the engine stores, only how to keep it alive and reachable.
//!
//! Where the engine comes from, first match wins:
//!
//! 1. `KRIKO_URL` set: attach to that address, start nothing.
//! 2. `kriko-sidecar.exe` beside this exe (the installed layout): start it.
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
/// The sidecar prints this with `ack|hide|quit` when the window is answered.
pub const WINDOW_LINE: &str = "KRIKO_WINDOW";
/// The fixed second socket the browser extension knows. Must equal
/// `app.web.settings.EXTENSION_PORT`.
pub const EXTENSION_PORT: u16 = 8787;
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
    /// Hide the window: the reader chose "keep running".
    Hide,
    /// End the app and the engine.
    Quit,
}

struct Supervisor {
    status: Status,
    events: Vec<ShellEvent>,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    stderr: String,
    started: bool,
}

fn sup() -> &'static Mutex<Supervisor> {
    static SUP: OnceLock<Mutex<Supervisor>> = OnceLock::new();
    SUP.get_or_init(|| {
        Mutex::new(Supervisor {
            status: Status::Starting("Starting Kriko's engine…".into()),
            events: Vec::new(),
            child: None,
            stdin: None,
            stderr: String::new(),
            started: false,
        })
    })
}

fn set_status(status: Status) {
    sup().lock().unwrap().status = status;
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
    {
        let mut s = sup().lock().unwrap();
        if s.started {
            return;
        }
        s.started = true;
        s.stderr.clear();
        s.status = Status::Starting("Starting Kriko's engine…".into());
    }
    std::thread::Builder::new()
        .name("engine-supervisor".into())
        .spawn(supervise)
        .ok();
}

/// Starts again after a failure.
pub fn restart() {
    stop();
    start();
}

fn supervise() {
    if let Ok(url) = std::env::var("KRIKO_URL") {
        let url = url.trim_end_matches('/').to_string();
        attach(&url);
        return;
    }
    let beside = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join(sidecar_name())))
        .filter(|path| path.is_file());
    let command = match beside {
        Some(path) => Command::new(path),
        None => {
            // no bundled engine: a running one is the next best thing
            let fixed = format!("http://127.0.0.1:{EXTENSION_PORT}");
            if health(&fixed).is_ok() {
                attach(&fixed);
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
    spawn(command);
}

/// The source checkout's own virtualenv, found by walking up from this exe
/// (`kriko-gpui/target/<profile>/kriko.exe` sits three levels below it).
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

fn attach(base: &str) {
    set_status(Status::Starting(format!("Connecting to {base}…")));
    let deadline = Instant::now() + HEALTH_TIMEOUT;
    loop {
        match health(base) {
            Ok(version) => {
                set_status(Status::Ready { base: base.to_string(), version });
                return;
            }
            Err(e) if Instant::now() >= deadline => {
                set_status(Status::Failed {
                    title: "Kriko's engine never answered".into(),
                    detail: format!("{base}/api/health: {e}"),
                });
                return;
            }
            Err(_) => std::thread::sleep(Duration::from_millis(200)),
        }
    }
}

fn spawn(mut command: Command) {
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
            set_status(Status::Failed {
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
                std::thread::spawn(move || attach(&format!("http://127.0.0.1:{p}")));
            }
        } else if line.contains(FOCUS_LINE) {
            let route = line.split(FOCUS_LINE).nth(1).unwrap_or("").trim().to_string();
            sup().lock().unwrap().events.push(ShellEvent::Focus(route));
        } else if line.contains(WINDOW_LINE) {
            let answer = line.split(WINDOW_LINE).nth(1).unwrap_or("").trim().to_string();
            let event = match answer.as_str() {
                "hide" => Some(ShellEvent::Hide),
                "quit" => Some(ShellEvent::Quit),
                _ => None,
            };
            if let Some(event) = event {
                sup().lock().unwrap().events.push(event);
            }
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
    if !s.started {
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
    let (child, stdin) = {
        let mut s = sup().lock().unwrap();
        s.started = false;
        (s.child.take(), s.stdin.take())
    };
    drop(stdin); // the polite way: the sidecar watches this pipe
    if let Some(mut child) = child {
        let pid = child.id();
        let _ = child.kill();
        kill_tree(pid);
        let _ = child.wait();
    }
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
