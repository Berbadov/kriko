//! The engine's HTTP API, from the window's side. Loopback only, so a plain
//! HTTP/1.0 exchange over a socket is the whole client: one request, the
//! server closes, the body is everything after the headers. No connection
//! pool, no TLS, no async runtime of its own, nothing to warm up.
//!
//! Every call blocks, so screens never call these directly: they go through
//! [`crate::app::Kriko::fetch`], which runs the call on the background
//! executor and hands the answer back on the UI thread.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::time::Duration;

pub use serde_json::Value;

use crate::engine;

/// Why a call did not return JSON: the HTTP status (0 when it never got an
/// answer) and the engine's own words, flattened to one line.
#[derive(Clone, Debug)]
pub struct ApiError {
    pub status: u16,
    pub message: String,
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

pub type Reply = Result<Value, ApiError>;

fn err(status: u16, message: impl Into<String>) -> ApiError {
    ApiError { status, message: message.into() }
}

pub fn get(path: &str) -> Reply {
    request("GET", path, None)
}

pub fn post(path: &str, body: Value) -> Reply {
    request("POST", path, Some(body))
}

pub fn put(path: &str, body: Value) -> Reply {
    request("PUT", path, Some(body))
}

pub fn delete(path: &str) -> Reply {
    request("DELETE", path, None)
}

/// A path segment, percent-encoded (ids are opaque strings to this side).
pub fn seg(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

pub fn request(method: &str, path: &str, body: Option<Value>) -> Reply {
    let base = engine::base().ok_or_else(|| err(0, "Kriko's engine is not running yet."))?;
    let (host, port) = engine::host_port(&base).map_err(|e| err(0, e))?;
    let addr = format!("{host}:{port}")
        .parse()
        .map_err(|e| err(0, format!("{e}")))?;
    let mut stream = TcpStream::connect_timeout(&addr, Duration::from_secs(2))
        .map_err(|e| err(0, format!("Kriko's engine did not answer: {e}")))?;
    // long enough for a slow lookup, short enough that a hung engine shows
    stream.set_read_timeout(Some(Duration::from_secs(60))).ok();
    stream.set_write_timeout(Some(Duration::from_secs(10))).ok();
    let payload = body.map(|b| b.to_string()).unwrap_or_default();
    let mut head =
        format!("{method} {path} HTTP/1.0\r\nHost: {host}:{port}\r\nAccept: application/json\r\n");
    if !payload.is_empty() || method == "POST" || method == "PUT" {
        head.push_str(&format!(
            "Content-Type: application/json\r\nContent-Length: {}\r\n",
            payload.len()
        ));
    }
    head.push_str("\r\n");
    stream
        .write_all(head.as_bytes())
        .and_then(|_| stream.write_all(payload.as_bytes()))
        .map_err(|e| err(0, format!("Could not reach Kriko's engine: {e}")))?;
    let mut raw = Vec::new();
    stream
        .read_to_end(&mut raw)
        .map_err(|e| err(0, format!("Kriko's engine stopped answering: {e}")))?;
    parse(&raw)
}

fn parse(raw: &[u8]) -> Reply {
    let split = raw
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .ok_or_else(|| err(0, "Kriko's engine sent a broken answer."))?;
    let head = String::from_utf8_lossy(&raw[..split]);
    let body = &raw[split + 4..];
    let status = head
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse::<u16>().ok())
        .unwrap_or(0);
    let value: Value = if body.is_empty() {
        Value::Null
    } else {
        serde_json::from_slice(body)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(body).into()))
    };
    if (200..300).contains(&status) {
        Ok(value)
    } else {
        Err(err(status, explain(status, &value)))
    }
}

/// FastAPI's error shapes, said as one line: `{detail: "..."}`,
/// `{detail: [{loc, msg}]}` for a refused body, `{detail: {message}}`.
fn explain(status: u16, value: &Value) -> String {
    let detail = value.get("detail").unwrap_or(value);
    let said = match detail {
        Value::String(s) => s.clone(),
        Value::Array(items) => items
            .iter()
            .filter_map(|i| i.get("msg").and_then(|m| m.as_str()))
            .collect::<Vec<_>>()
            .join("; "),
        Value::Object(o) => o
            .get("message")
            .or_else(|| o.get("error"))
            .and_then(|m| m.as_str())
            .unwrap_or_default()
            .to_string(),
        _ => String::new(),
    };
    if said.is_empty() {
        format!("Kriko's engine answered {status}.")
    } else {
        said
    }
}

// ---- reading JSON without ceremony ----

/// A string field, or "" when absent.
pub fn s(v: &Value, key: &str) -> String {
    match v.get(key) {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) => n.to_string(),
        Some(Value::Bool(b)) => b.to_string(),
        _ => String::new(),
    }
}

/// A number field, or None when absent or null ("not measured" is not 0).
pub fn n(v: &Value, key: &str) -> Option<f64> {
    v.get(key).and_then(|x| x.as_f64())
}

/// A boolean field; the engine sends some flags as 0/1.
pub fn b(v: &Value, key: &str) -> bool {
    match v.get(key) {
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().unwrap_or(0.0) != 0.0,
        _ => false,
    }
}

/// An array field, or the value itself when `key` is "" and it is a bare
/// array (`/api/packs` and `/api/subjects` answer with one).
pub fn arr<'a>(v: &'a Value, key: &str) -> &'a [Value] {
    let target = if key.is_empty() { Some(v) } else { v.get(key) };
    target
        .and_then(|x| x.as_array())
        .map(|a| a.as_slice())
        .unwrap_or(&[])
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_success_parses_its_body() {
        let r = parse(b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"ok\":true}").unwrap();
        assert_eq!(r["ok"], true);
    }

    #[test]
    fn an_error_says_the_engines_detail() {
        let e = parse(b"HTTP/1.1 409 Conflict\r\n\r\n{\"detail\":\"The queue is full.\"}").unwrap_err();
        assert_eq!(e.status, 409);
        assert_eq!(e.message, "The queue is full.");
        let e = parse(b"HTTP/1.1 422 X\r\n\r\n{\"detail\":[{\"loc\":[\"body\"],\"msg\":\"field required\"}]}")
            .unwrap_err();
        assert_eq!(e.message, "field required");
    }

    #[test]
    fn segments_are_encoded() {
        assert_eq!(seg("a b/c"), "a%20b%2Fc");
    }
}
