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
    let payload = body.map(|b| b.to_string()).unwrap_or_default();
    let typed = !payload.is_empty() || method == "POST" || method == "PUT";
    send(method, path, payload.as_bytes(), typed.then_some("application/json"), None)
}

/// A file's bytes as the body, for the one door that takes a file
/// (`POST /api/packs/install`). The name travels as metadata only.
pub fn post_bytes(path: &str, bytes: &[u8], filename: &str) -> Reply {
    send("POST", path, bytes, Some("application/octet-stream"), Some(filename))
}

/// The one-click extension install: the engine stages the folder and opens a
/// browser that already carries the extension (`POST /api/extension/launch`).
/// A browser it cannot start comes back as `launched: false` with a reason,
/// never as an error status, so the answer is read, not caught.
pub fn extension_launch() -> Reply {
    post("/api/extension/launch", serde_json::json!({}))
}

/// Refresh one product's saved check: the engine reads the product's own
/// identity from the catalog and answers with what is recorded about it.
pub fn product_check(subject_id: &str) -> Reply {
    post(&format!("/api/products/{}/check", seg(subject_id)), serde_json::json!({}))
}

/// Put one product in the research queue, which is what Compare reads.
///
/// A catalog product has no listing address, so the row is keyed by an address
/// of this app's own that names the product. It is a real URL so the queue's
/// own host column has something to say, and it is deliberately under
/// `kriko.local`: nothing resolves it, and a reader who opens the row's
/// address by mistake lands nowhere rather than on someone else's site.
pub fn product_to_compare(subject_id: &str, name: &str) -> Reply {
    post(
        "/api/queue",
        serde_json::json!({
            "url": format!("https://kriko.local/product/{}", seg(subject_id)),
            "name": name,
        }),
    )
}

fn send(method: &str, path: &str, payload: &[u8], content_type: Option<&str>, filename: Option<&str>) -> Reply {
    let raw = roundtrip(method, path, payload, content_type, filename)?;
    parse(&raw)
}

/// A `DELETE` that names the thing in the body, for the one door that works
/// that way: a local model server deletes a model by name, not by path.
pub fn delete_json(path: &str, body: Value) -> Reply {
    let payload = body.to_string();
    send("DELETE", path, payload.as_bytes(), Some("application/json"), None)
}

/// The raw body of a `GET`, for the doors that answer bytes instead of JSON:
/// a site icon is an image, and the JSON path would flatten it to a string.
pub fn get_bytes(path: &str) -> Result<Vec<u8>, ApiError> {
    let raw = roundtrip("GET", path, &[], None, None)?;
    let (status, body) = split(&raw)?;
    if (200..300).contains(&status) {
        Ok(body.to_vec())
    } else {
        let value: Value = serde_json::from_slice(body)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(body).into()));
        Err(err(status, explain(status, &value)))
    }
}

/// One request and its answer, whole. The blocking socket lives here and only
/// here, so the JSON door and the byte door cannot drift apart.
fn roundtrip(
    method: &str,
    path: &str,
    payload: &[u8],
    content_type: Option<&str>,
    filename: Option<&str>,
) -> Result<Vec<u8>, ApiError> {
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
    let mut head =
        format!("{method} {path} HTTP/1.0\r\nHost: {host}:{port}\r\nAccept: application/json\r\n");
    if let Some(kind) = content_type {
        head.push_str(&format!("Content-Type: {kind}\r\nContent-Length: {}\r\n", payload.len()));
    }
    if let Some(name) = filename {
        // A header value carries no line break; the engine checks the rest.
        let name: String = name.chars().filter(|c| !c.is_control()).collect();
        head.push_str(&format!("X-Filename: {name}\r\n"));
    }
    head.push_str("\r\n");
    stream
        .write_all(head.as_bytes())
        .and_then(|_| stream.write_all(payload))
        .map_err(|e| err(0, format!("Could not reach Kriko's engine: {e}")))?;
    let mut raw = Vec::new();
    stream
        .read_to_end(&mut raw)
        .map_err(|e| err(0, format!("Kriko's engine stopped answering: {e}")))?;
    Ok(raw)
}

/// `(status, body)` from a whole answer.
fn split(raw: &[u8]) -> Result<(u16, &[u8]), ApiError> {
    let at = raw
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .ok_or_else(|| err(0, "Kriko's engine sent a broken answer."))?;
    let head = String::from_utf8_lossy(&raw[..at]);
    let status = head
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse::<u16>().ok())
        .unwrap_or(0);
    Ok((status, &raw[at + 4..]))
}

fn parse(raw: &[u8]) -> Reply {
    let (status, body) = split(raw)?;
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

/// An object field, or None when absent or not an object.
pub fn obj<'a>(v: &'a Value, key: &str) -> Option<&'a serde_json::Map<String, Value>> {
    v.get(key).and_then(|x| x.as_object())
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
