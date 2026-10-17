//! Site icons, fetched through the engine and kept for the window's lifetime.
//!
//! A screen cannot fetch, so `sources::site_mark` draws a generated monogram.
//! The engine can fetch, and it answers bytes GPUI can decode at
//! `/api/favicon?host=...`. This is the one place those bytes are remembered:
//! a queue of hosts a screen asked for and a map of the images that came back.
//! It is global like `theme::motion_on`, because a source row has nowhere to
//! carry a cache and should not have to.
//!
//! One host leaves the queue per pulse, and the fetch runs on the background
//! executor (`Kriko::fetch`), because the engine call can wait on the network
//! and the pulse runs on the UI thread. A page of twenty sources then costs
//! twenty small requests over two seconds rather than twenty stalls in one
//! paint, and a host the engine has no icon for is asked once, not on every
//! redraw.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::{Arc, Mutex, OnceLock};

use gpui::{Image, ImageFormat};

struct Icons {
    /// Hosts waiting for their one request.
    pending: VecDeque<String>,
    /// Hosts already queued or fetched. It is what makes `request` idempotent
    /// across the many redraws a visible row has, and what keeps a site with
    /// no icon from being asked for again this session.
    asked: HashSet<String>,
    icons: HashMap<String, Arc<Image>>,
}

fn icons() -> &'static Mutex<Icons> {
    static ICONS: OnceLock<Mutex<Icons>> = OnceLock::new();
    ICONS.get_or_init(|| {
        Mutex::new(Icons {
            pending: VecDeque::new(),
            asked: HashSet::new(),
            icons: HashMap::new(),
        })
    })
}

/// The key both the queue and the cache use, so `www.` and case cannot make
/// two entries for one site.
fn key(host: &str) -> String {
    host.trim().trim_start_matches("www.").to_ascii_lowercase()
}

/// Ask for a host's icon once. A redraw calls this for every visible source,
/// so the set is what keeps the 10 Hz pulse from queueing the same host twice.
pub fn request(host: &str) {
    let host = key(host);
    if host.is_empty() {
        return;
    }
    let Ok(mut icons) = icons().lock() else {
        return;
    };
    if icons.asked.contains(&host) {
        return;
    }
    icons.asked.insert(host.clone());
    icons.pending.push_back(host);
}

/// The icon already fetched for a host, or nothing while it is still coming.
pub fn cached(host: &str) -> Option<Arc<Image>> {
    let host = key(host);
    let icons = icons().lock().ok()?;
    icons.icons.get(&host).cloned()
}

/// The next host a screen asked for, or nothing while the queue is empty.
/// This only pops the queue: the caller fetches the bytes off the UI thread.
pub fn next_host() -> Option<String> {
    let Ok(mut icons) = icons().lock() else {
        return None;
    };
    icons.pending.pop_front()
}

/// Remember the bytes the engine answered for a host. False when they are not
/// an image GPUI can draw, so the monogram stays on screen.
pub fn store(host: &str, bytes: Vec<u8>) -> bool {
    let host = key(host);
    let Some(format) = format_of(&bytes) else {
        return false;
    };
    let image = Arc::new(Image::from_bytes(format, bytes));
    let Ok(mut icons) = icons().lock() else {
        return false;
    };
    icons.icons.insert(host, image);
    true
}

/// The format of the bytes the engine answered, so an SVG or a JPEG is not
/// labelled PNG and drawn as nothing. The engine already accepts only these
/// five; this reads the magic again because that is cheaper than a header the
/// socket client does not carry.
fn format_of(bytes: &[u8]) -> Option<ImageFormat> {
    if bytes.starts_with(&[0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a]) {
        Some(ImageFormat::Png)
    } else if bytes.starts_with(&[0xff, 0xd8, 0xff]) {
        Some(ImageFormat::Jpeg)
    } else if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        Some(ImageFormat::Gif)
    } else if bytes.len() >= 12 && &bytes[..4] == b"RIFF" && &bytes[8..12] == b"WEBP" {
        Some(ImageFormat::Webp)
    } else {
        let head = String::from_utf8_lossy(&bytes[..bytes.len().min(512)]).to_ascii_lowercase();
        if head.contains("<svg") {
            Some(ImageFormat::Svg)
        } else {
            None
        }
    }
}
