//! Local LLM and Benchmark, as the engine says it.
//!
//! The local model server, its models and this machine's GPU and memory come
//! from `/api/local-plane`, `/api/local-models` and `/api/machine`; a model
//! download is a `model_pull` job and a benchmark is a `bench` job, both
//! followed by polling `/api/jobs/{id}`. Nothing here is a sample: a slice
//! that has not arrived is `None` and the screens say so.

use std::time::Duration;

use gpui::Context;

use crate::api::{self, Value};
use crate::app::{DockFeedEntry, Kriko};
use crate::theme::TagState;

// ---- the local plane ----

#[derive(Default, Clone)]
pub struct Server {
    pub name: String,
    pub url: String,
    pub up: bool,
    pub models: Vec<String>,
}

#[derive(Default, Clone)]
pub struct Plane {
    pub ready: bool,
    pub reason: String,
    pub line: String,
    pub url: String,
    pub name: String,
    pub model: String,
    /// The model the engine recommends and installs; the screens never name one.
    pub recommended_model: String,
    pub models: Vec<String>,
    pub servers: Vec<Server>,
    pub search_label: String,
    pub timeout: f64,
    pub stored_url: String,
    pub stored_search: String,
    pub stored_output_language: String,
    pub stored_search_language: String,
    pub runtime: Value,
}

#[derive(Default, Clone)]
pub struct RuntimeFound {
    pub id: String,
    pub installed: bool,
    pub path: Option<String>,
}

/// This computer, as `/api/machine` reports it. `None` is "not reported",
/// never zero.
#[derive(Default, Clone)]
pub struct Machine {
    pub gpu: Option<String>,
    pub vram_total_mb: Option<f64>,
    pub vram_used_mb: Option<f64>,
    pub ram_mb: Option<f64>,
    pub cpu: Option<String>,
    pub cores: Option<f64>,
    pub runtimes: Vec<RuntimeFound>,
}

/// A model Ollama holds, with the sizes it reports.
#[derive(Default, Clone)]
pub struct Held {
    pub name: String,
    pub size_bytes: Option<f64>,
    pub params: Option<String>,
    pub quant: Option<String>,
}

#[derive(Clone, PartialEq)]
pub enum PullPhase {
    Running,
    Failed(String),
    Done,
}

#[derive(Clone)]
pub struct Pull {
    pub model: String,
    pub job_id: String,
    /// 0..=100
    pub progress: f32,
    pub message: String,
    pub phase: PullPhase,
}

// ---- the benchmark ----

#[derive(Default, Clone)]
pub struct BenchRun {
    pub batch_id: String,
    pub at: String,
    pub subject: String,
    pub plane: String,
    pub llm: String,
    pub ms: Option<f64>,
    pub tokens: Option<f64>,
    pub usd: Option<f64>,
    pub accepted: f64,
    pub refused: f64,
    pub error: String,
    pub raw: Value,
}

#[derive(Default, Clone)]
pub struct BenchRow {
    pub plane: String,
    pub llm: String,
    pub protocol: String,
    pub runs: f64,
    pub ms: Option<f64>,
    pub tokens: Option<f64>,
    pub accepted: f64,
    pub failures: f64,
}

#[derive(Default, Clone)]
pub struct Scored {
    pub plane: String,
    pub llm: String,
    pub hallucination: Option<f64>,
}

#[derive(Clone)]
pub struct Estimate {
    pub runs: i64,
    pub usd: Option<f64>,
}

#[derive(Clone)]
pub enum BenchPhase {
    Idle,
    Estimating,
    /// The grid was priced; one more press spends.
    Confirm(Estimate),
    Running { job_id: String, progress: f32, message: String },
    Failed(String),
}

impl Default for BenchPhase {
    fn default() -> Self {
        BenchPhase::Idle
    }
}

#[derive(Default, Clone)]
pub struct Bench {
    pub suite: String,
    pub loaded: bool,
    pub runs: Vec<BenchRun>,
    pub summary: Vec<BenchRow>,
    pub scored: Vec<Scored>,
    /// (plane, what it is), from the engine's own vocabulary.
    pub planes: Vec<(String, String)>,
    pub picked: Vec<String>,
    pub set_label: String,
    pub phase: BenchPhase,
    /// How the last job ended, in the engine's words.
    pub last: Option<String>,
    pub cases: Vec<Value>,
    pub case_ids: Vec<String>,
    pub models: Vec<String>,
    pub harness: String,
    pub case_count: usize,
    pub documents: usize,
    pub repeats: usize,
    pub timeout: usize,
    pub max_tokens: usize,
    pub temperature: f64,
    pub detail: Option<usize>,
    pub snapshot: Value,
}

/// One model the store draws: a name the provider's library lists, an
/// installed model the local server holds, or both at once. `sizes` are the
/// parameter badges the provider offers for it (`4b`, `8x7b`), `est_gb` the q4
/// download the first badge implies, and `bytes` what the server reports on
/// disk for the model it holds. `installed_name` is the server's own name for
/// that model (`llama3:8b`), which is what "Use" selects. A side that reports
/// nothing leaves its fields `None`.
#[derive(Default, Clone)]
pub struct LibraryModel {
    pub name: String,
    /// The provider lists this name, so "Open in library" has a page for it.
    pub listed: bool,
    pub sizes: Vec<String>,
    pub about: String,
    pub est_gb: Option<f64>,
    pub installed: bool,
    /// The server's own name for the model it holds.
    pub installed_name: Option<String>,
    pub bytes: Option<f64>,
    /// Parameter count in billions: the size badge's, or the server's details.
    pub params_b: Option<f64>,
    /// Quantisation the server reports, e.g. `Q4_K_M`.
    pub quant: Option<String>,
}

/// The provider's own page for a model, so a listed row can open it. The tag
/// is dropped: the library names a model, not one of its sizes.
pub fn library_url(name: &str) -> String {
    let slug = name.trim().split(':').next().unwrap_or("").to_ascii_lowercase();
    format!("https://ollama.com/library/{slug}")
}

/// The installed model a library name stands for: the same name, or a sized
/// tag of it (`llama3` names `llama3:8b`). A different model that merely
/// begins with the name (`llama3.2`) is not one.
fn sized_tag_of(held_name: &str, library_name: &str) -> bool {
    let held = held_name.trim().to_ascii_lowercase();
    let library = library_name.trim().to_ascii_lowercase();
    if library.is_empty() {
        return false;
    }
    let prefix = format!("{library}:");
    held.strip_prefix(prefix.as_str())
        .is_some_and(|tag| !tag.is_empty() && !tag.contains(':'))
}

/// The parameter count in billions for an installed model: the server's own
/// details string (`8.0B`), else the size tag in the name (`llama3:8b`).
pub fn held_params_b(held: &Held) -> Option<f64> {
    held.params
        .as_deref()
        .and_then(params_b)
        .or_else(|| held.name.split([':', '-', '_']).rev().find_map(params_b))
}

/// A parameter count written the way a model card does: `7B`, `1.5B`, `270M`.
pub fn params_label(billions: f64) -> String {
    if billions >= 1.0 {
        if (billions - billions.round()).abs() < 0.05 {
            format!("{billions:.0}B")
        } else {
            format!("{billions:.1}B")
        }
    } else {
        format!("{:.0}M", billions * 1000.0)
    }
}

/// The disk weight the store shows for a row: what the server reports, else
/// the size badge's estimate.
pub fn row_gb(row: &LibraryModel) -> Option<f64> {
    row.bytes.map(|bytes| bytes / 1e9).or(row.est_gb)
}

/// Machine memory a model may claim on this machine: VRAM when the GPU reports
/// any, else RAM, with 20% left for everything else on it.
pub fn fits_limit_gb(machine: &Machine) -> Option<f64> {
    machine
        .vram_total_mb
        .filter(|mb| *mb > 0.0)
        .or(machine.ram_mb.filter(|mb| *mb > 0.0))
        .map(|mb| mb / 1024.0 * 0.8)
}

/// Whether a row's model fits that limit. `None` when either side is unknown,
/// so an unmeasured machine makes no claim.
pub fn row_fits(row: &LibraryModel, limit_gb: Option<f64>) -> Option<bool> {
    match (row_gb(row), limit_gb) {
        (Some(gb), Some(limit)) => Some(gb <= limit),
        _ => None,
    }
}

/// The size badge a row is set to: the reader's pick when it is one of the
/// row's sizes, else the first the provider lists.
pub fn chosen_size<'a>(row: &'a LibraryModel, picked: Option<&str>) -> Option<&'a str> {
    if let Some(pick) = picked {
        if let Some(size) = row.sizes.iter().find(|size| size.as_str() == pick) {
            return Some(size.as_str());
        }
    }
    row.sizes.first().map(String::as_str)
}

/// Every row the store draws: the provider's library, then any installed model
/// the library does not list, so a model downloaded outside Kriko is never
/// invisible.
pub fn store_rows(library: &[LibraryModel], held: &[Held]) -> Vec<LibraryModel> {
    let mut rows = library.to_vec();
    for model in held {
        if rows
            .iter()
            .any(|row| row.installed_name.as_deref() == Some(model.name.as_str()))
        {
            continue;
        }
        rows.push(LibraryModel {
            name: model.name.clone(),
            installed: true,
            installed_name: Some(model.name.clone()),
            bytes: model.size_bytes,
            params_b: held_params_b(model),
            quant: model.quant.clone(),
            ..Default::default()
        });
    }
    rows
}

/// Name first, or the lightest model first; unknown sizes sort last either
/// way.
pub fn sort_rows(rows: &mut [LibraryModel], sort: LibrarySort) {
    rows.sort_by(|a, b| {
        let by_name = a.name.to_lowercase().cmp(&b.name.to_lowercase());
        match sort {
            LibrarySort::Name => by_name,
            LibrarySort::Size => match (row_gb(a), row_gb(b)) {
                (Some(x), Some(y)) => x.total_cmp(&y).then(by_name),
                (Some(_), None) => std::cmp::Ordering::Less,
                (None, Some(_)) => std::cmp::Ordering::Greater,
                (None, None) => by_name,
            },
        }
    });
}

/// The store's rows under one search, filter and sort. `limit_gb` is this
/// machine's memory (`fits_limit_gb`); with none, the Fits filter keeps
/// nothing, so a machine that measures nothing never claims a model fits.
pub fn store_view(
    library: &[LibraryModel],
    held: &[Held],
    filter: LibraryFilter,
    query: &str,
    limit_gb: Option<f64>,
    sort: LibrarySort,
) -> Vec<LibraryModel> {
    let query = query.trim().to_lowercase();
    let mut rows = store_rows(library, held);
    rows.retain(|row| {
        let named = query.is_empty()
            || row.name.to_lowercase().contains(&query)
            || row.about.to_lowercase().contains(&query);
        named
            && match filter {
                LibraryFilter::All => true,
                LibraryFilter::Installed => row.installed,
                LibraryFilter::Fits => row_fits(row, limit_gb).unwrap_or(false),
                LibraryFilter::Small => row_gb(row).is_some_and(|gb| gb <= 5.0),
            }
    });
    sort_rows(&mut rows, sort);
    rows
}

/// How the model store narrows its list.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum LibraryFilter {
    #[default]
    All,
    Installed,
    /// Fits the machine's memory with the usual 20% headroom.
    Fits,
    /// Five gigabytes or less, whatever this machine holds.
    Small,
}

/// What the model store sorts by.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum LibrarySort {
    #[default]
    Name,
    Size,
}

/// A size badge's parameter count in billions: `7b` -> 7.0, `8x7b` -> 56.0,
/// `270m` -> 0.27, `e2b` -> 2.0 (the effective count Ollama prints for Gemma).
pub fn params_b(size: &str) -> Option<f64> {
    let badge = size.trim().to_ascii_lowercase();
    if badge.is_empty() {
        return None;
    }
    let (experts, rest) = match badge.split_once('x') {
        Some((count, rest)) => (count.trim().parse::<f64>().ok()?, rest),
        None => (1.0, badge.as_str()),
    };
    // `e2b` names an effective parameter count; the `e` is not a number.
    let rest = rest.trim_start_matches('e');
    let (digits, scale) = if let Some(n) = rest.strip_suffix('b') {
        (n, 1.0)
    } else if let Some(n) = rest.strip_suffix('m') {
        (n, 0.001)
    } else {
        return None;
    };
    let count: f64 = digits.trim().parse().ok()?;
    let total = experts * count * scale;
    (total.is_finite() && total > 0.0).then_some(total)
}

/// The download a size badge implies at q4: parameter billions * 0.62 GB,
/// rounded to one decimal (a `7b` badge is about 4.3 GB).
pub fn size_gb(size: &str) -> Option<f64> {
    params_b(size).map(|params| (params * 0.62 * 10.0).round() / 10.0)
}

/// A model name without the default tag, so `llama3` and `llama3:latest`
/// name the same download.
pub(crate) fn bare_model(name: &str) -> String {
    let name = name.trim().to_ascii_lowercase();
    name.strip_suffix(":latest").unwrap_or(&name).to_string()
}

/// Marks the library entries the server already holds, and gives them the
/// size, parameter count and quantisation it reports. Matching is by the name
/// without `:latest` first, then by a sized tag of the same model, so the
/// store's `llama3` row knows about an installed `llama3:8b` as well as an
/// installed `llama3:latest`.
pub fn mark_installed(library: &mut [LibraryModel], held: &[Held]) {
    for model in library.iter_mut() {
        let named = bare_model(&model.name);
        let mut found = held.iter().find(|h| bare_model(&h.name) == named);
        if found.is_none() {
            // a sized tag of the same model: `llama3` offers `llama3:8b`. When
            // several are installed, prefer the one whose parameter count the
            // row itself offers, then the first.
            let tags: Vec<&Held> = held.iter().filter(|h| sized_tag_of(&h.name, &named)).collect();
            found = tags
                .iter()
                .find(|h| {
                    held_params_b(*h).is_some_and(|params| {
                        model
                            .sizes
                            .iter()
                            .any(|size| params_b(size).is_some_and(|badge| (badge - params).abs() < 0.05))
                    })
                })
                .copied()
                .or_else(|| tags.first().copied());
        }
        model.installed = found.is_some();
        model.installed_name = found.map(|h| h.name.clone());
        model.bytes = found.and_then(|h| h.size_bytes);
        model.quant = found.and_then(|h| h.quant.clone());
        if let Some(h) = found {
            model.params_b = held_params_b(h).or(model.params_b);
        }
    }
}

/// A runtime or language choice the reader just made, shown at once while the
/// engine stores it: the value picked, and how many saves of that key are
/// still in flight. See [`local_pick_pref`](Kriko::local_pick_pref).
#[derive(Clone, Default)]
pub struct PendingPick {
    pub value: String,
    pub writes: u32,
}

/// A save starts: the pick shows from now on, and is counted as in flight.
pub fn pick_started(pending: &mut std::collections::HashMap<String, PendingPick>, key: &str, value: &str) {
    let pick = pending.entry(key.to_string()).or_default();
    pick.value = value.to_string();
    pick.writes += 1;
}

/// A save answered. A refused save with none left in flight drops the pick,
/// so the row shows what the engine still holds.
pub fn pick_answered(pending: &mut std::collections::HashMap<String, PendingPick>, key: &str, saved: bool) {
    let Some(pick) = pending.get_mut(key) else { return };
    pick.writes = pick.writes.saturating_sub(1);
    if !saved && pick.writes == 0 {
        pending.remove(key);
    }
}

/// The plane was read again. A pick no save is still in flight for is now the
/// engine's own answer, so it stops showing as pending.
pub fn pick_confirmed(pending: &mut std::collections::HashMap<String, PendingPick>) {
    pending.retain(|_, pick| pick.writes > 0);
}

/// A Remove press: the first arms the tile, a second press on that same tile
/// removes. A press on another tile only moves the arm, so a misclick can
/// never delete a different model than the one whose name it was under.
pub fn remove_pressed(armed: &mut Option<String>, model: &str) -> bool {
    if armed.as_deref() == Some(model) {
        *armed = None;
        true
    } else {
        *armed = Some(model.to_string());
        false
    }
}

/// Whether a plane answer should replace the reader's server/model form.
/// Retry refreshes pass `fill = false`, so the address and model survive a
/// failed request and the subsequent retry.
fn should_fill_plane_form(fill: bool, loaded: bool) -> bool {
    fill || !loaded
}

#[derive(Default)]
pub struct State {
    pub model_focus: Option<String>,
    pub library_view: bool,
    pub advanced_open: bool,
    pub loaded: bool,
    pub plane: Option<Plane>,
    /// The last `/api/local-plane` failure, kept with this slice so the Local
    /// screen can offer a real retry without showing an unrelated global error.
    pub plane_error: Option<String>,
    /// Choices on the runtime and language rows that are being stored.
    pub pref_pending: std::collections::HashMap<String, PendingPick>,
    /// "Refresh device" was pressed and the plane has not answered yet.
    pub device_reading: bool,
    pub machine: Option<Machine>,
    pub held: Option<Vec<Held>>,
    /// Downloadable names from the provider's library.
    pub offered: Vec<String>,
    /// The same models with their sizes; what the model store draws.
    pub library: Vec<LibraryModel>,
    /// The size picked for each library model, by model name.
    pub library_size: std::collections::HashMap<String, String>,
    /// Which slice of the library the store shows, and how it orders it.
    pub library_filter: LibraryFilter,
    pub library_sort: LibrarySort,
    /// True once the store has been opened at all; the library is read on
    /// demand, not on every visit to the screen.
    pub catalogue_open: bool,
    pub catalogue_loading: bool,
    /// A successful read has happened, so an empty list is a real empty store
    /// and not a list still to arrive.
    pub catalogue_loaded: bool,
    pub catalogue_error: String,
    /// The model the picker shows, which Save stores.
    pub model_pick: Option<String>,
    pub timeout: u32,
    pub saving: bool,
    pub note: Option<String>,
    pub checking: bool,
    pub pull: Option<Pull>,
    /// The installed model a Remove is in flight for, so its tile can show
    /// the wait and presses elsewhere do not start a second removal.
    pub removing: Option<String>,
    /// The last Remove refusal, in the engine's own words.
    pub remove_error: String,
    /// The tile whose Remove was pressed once and now asks to confirm.
    pub remove_confirm: Option<String>,
    pub runtime_starting: bool,
    pub bench: Bench,
}

// ---- reading the engine's answers ----

fn opt_s(v: &Value, key: &str) -> Option<String> {
    match v.get(key) {
        Some(Value::String(s)) if !s.is_empty() => Some(s.clone()),
        _ => None,
    }
}

fn strings(v: &Value, key: &str) -> Vec<String> {
    api::arr(v, key)
        .iter()
        .filter_map(|x| x.as_str().map(str::to_string))
        .collect()
}

pub fn plane_from(v: &Value) -> Plane {
    let stored = v.get("stored").cloned().unwrap_or(Value::Null);
    Plane {
        ready: api::b(v, "ready"),
        reason: api::s(v, "reason"),
        line: api::s(v, "line"),
        url: api::s(v, "url"),
        name: api::s(v, "name"),
        model: api::s(v, "model"),
        recommended_model: api::s(v, "recommended_model"),
        models: strings(v, "models"),
        servers: api::arr(v, "servers")
            .iter()
            .map(|s| Server {
                name: api::s(s, "name"),
                url: api::s(s, "url"),
                up: api::b(s, "up"),
                models: strings(s, "models"),
            })
            .collect(),
        search_label: api::s(v, "search_label"),
        timeout: api::n(v, "timeout").unwrap_or(0.0),
        stored_url: api::s(&stored, "local_url"),
        stored_search: api::s(&stored, "local_search_url"),
        stored_output_language: {
            let selected = api::s(v, "output_language");
            if !selected.is_empty() { selected } else {
                let selected = api::s(&stored, "local_output_language");
                if selected.is_empty() { api::s(&stored, "output_language") } else { selected }
            }
        },
        stored_search_language: {
            let selected = api::s(v, "search_language");
            if !selected.is_empty() { selected } else {
                let selected = api::s(&stored, "local_search_language");
                if selected.is_empty() { api::s(&stored, "search_language") } else { selected }
            }
        },
        runtime: v.get("runtime").cloned().unwrap_or(Value::Null),
    }
}

pub fn machine_from(v: &Value) -> Machine {
    let gpu = v.get("gpu").cloned().unwrap_or(Value::Null);
    let cpu = v.get("cpu").cloned().unwrap_or(Value::Null);
    Machine {
        gpu: opt_s(&gpu, "name"),
        vram_total_mb: api::n(&gpu, "vram_total_mb"),
        vram_used_mb: api::n(&gpu, "vram_used_mb"),
        ram_mb: api::n(v, "ram_total_mb"),
        cpu: opt_s(&cpu, "name"),
        cores: api::n(&cpu, "cores"),
        runtimes: api::arr(v, "runtimes")
            .iter()
            .map(|r| RuntimeFound {
                id: api::s(r, "id"),
                installed: api::b(r, "installed"),
                path: opt_s(r, "path"),
            })
            .collect(),
    }
}

pub fn held_from(v: &Value) -> Vec<Held> {
    api::arr(v, "models")
        .iter()
        .map(|m| Held {
            name: api::s(m, "name"),
            size_bytes: api::n(m, "size_bytes"),
            params: opt_s(m, "params"),
            quant: opt_s(m, "quant"),
        })
        .collect()
}

fn run_from(v: &Value) -> BenchRun {
    BenchRun {
        batch_id: api::s(v, "batch_id"),
        at: api::s(v, "at"),
        subject: api::s(v, "subject"),
        plane: api::s(v, "plane"),
        llm: api::s(v, "llm"),
        ms: api::n(v, "ms"),
        tokens: api::n(v, "tokens"),
        usd: api::n(v, "usd"),
        accepted: api::n(v, "accepted").unwrap_or(0.0),
        refused: api::n(v, "refused").unwrap_or(0.0),
        error: api::s(v, "error"),
        raw: v.clone(),
    }
}

// ---- what a benchmark press measured, batch by batch ----

/// One press of Run benchmark: the runs that share a `batch_id`.
#[derive(Clone, Default, Debug, PartialEq)]
pub struct Batch {
    pub id: String,
    pub at: String,
    pub median_ms: Option<f64>,
    pub median_tokens: Option<f64>,
    pub median_usd: Option<f64>,
    pub acceptance: Option<f64>,
}

pub fn median(mut xs: Vec<f64>) -> Option<f64> {
    if xs.is_empty() {
        return None;
    }
    xs.sort_by(|a, b| a.total_cmp(b));
    let n = xs.len();
    Some(if n % 2 == 1 { xs[n / 2] } else { (xs[n / 2 - 1] + xs[n / 2]) / 2.0 })
}

/// Batches, newest first. A run that failed has no answer time worth
/// averaging in, so only clean runs feed the medians.
pub fn batches(runs: &[BenchRun]) -> Vec<Batch> {
    let mut ordered: Vec<&BenchRun> = runs.iter().collect();
    ordered.sort_by(|a, b| b.at.cmp(&a.at));
    let mut ids: Vec<&str> = Vec::new();
    for r in &ordered {
        if !ids.contains(&r.batch_id.as_str()) {
            ids.push(r.batch_id.as_str());
        }
    }
    ids.into_iter()
        .map(|id| {
            let mine: Vec<&&BenchRun> = ordered.iter().filter(|r| r.batch_id == id).collect();
            let clean = mine.iter().filter(|r| r.error.is_empty());
            let accepted: f64 = mine.iter().map(|r| r.accepted).sum();
            let refused: f64 = mine.iter().map(|r| r.refused).sum();
            Batch {
                id: id.to_string(),
                at: mine.first().map(|r| r.at.clone()).unwrap_or_default(),
                median_ms: median(clean.clone().filter_map(|r| r.ms).collect()),
                median_tokens: median(clean.clone().filter_map(|r| r.tokens).collect()),
                median_usd: median(clean.filter_map(|r| r.usd).collect()),
                acceptance: if accepted + refused > 0.0 {
                    Some(accepted / (accepted + refused))
                } else {
                    None
                },
            }
        })
        .collect()
}

/// The change from the previous batch to the latest, in whole percent, when
/// both were measured.
pub fn change(latest: Option<f64>, before: Option<f64>) -> Option<i8> {
    match (latest, before) {
        (Some(a), Some(b)) if b != 0.0 => Some((((a - b) / b) * 100.0).round().clamp(-99.0, 99.0) as i8),
        _ => None,
    }
}

// ---- jobs ----

pub struct JobView {
    pub state: String,
    pub progress: f32,
    pub message: String,
    pub done: bool,
}

impl JobView {
    pub fn succeeded(&self) -> bool {
        self.state == "succeeded"
    }
}

fn job_view(v: &Value) -> JobView {
    JobView {
        state: api::s(v, "state"),
        progress: api::n(v, "progress").unwrap_or(0.0) as f32,
        message: api::s(v, "message"),
        done: api::b(v, "done"),
    }
}

impl Kriko {
    /// Polls a job every 700 ms and hands each answer to `apply`, until the
    /// job is done. A job the engine no longer knows ends the poll with a
    /// failed view, so a screen never waits on a row that is gone.
    pub fn follow_local_job(
        &mut self,
        cx: &mut Context<Self>,
        job_id: String,
        apply: impl Fn(&mut Kriko, &JobView, &mut Context<Kriko>) + 'static,
    ) {
        cx.spawn(async move |this, cx| {
            let mut misses = 0;
            loop {
                cx.background_executor().timer(Duration::from_millis(700)).await;
                let id = job_id.clone();
                let reply = cx
                    .background_executor()
                    .spawn(async move { api::get(&format!("/api/jobs/{}", api::seg(&id))) })
                    .await;
                let finished = this
                    .update(cx, |this, cx| {
                        let view = match &reply {
                            Ok(v) => {
                                misses = 0;
                                job_view(v)
                            }
                            Err(e) => {
                                misses += 1;
                                if e.status != 404 && misses < 5 {
                                    return false;
                                }
                                JobView {
                                    state: "failed".into(),
                                    progress: 0.0,
                                    message: e.message.clone(),
                                    done: true,
                                }
                            }
                        };
                        apply(this, &view, cx);
                        cx.notify();
                        view.done
                    })
                    .unwrap_or(true);
                if finished {
                    break;
                }
            }
        })
        .detach();
    }

    // ---- the local plane ----

    pub fn refresh_local(&mut self, cx: &mut Context<Self>) {
        self.refresh_plane(true, cx);
        self.refresh_machine(false, cx);
        self.refresh_held(cx);
        self.refresh_bench(cx);

    }

    pub fn local_start_ollama(&mut self, cx: &mut Context<Self>) {
        if self.live.local.runtime_starting { return; }
        self.live.local.runtime_starting = true;
        self.fetch(cx, || api::post("/api/local-models/start", serde_json::json!({})), |this, reply, cx| {
            match reply {
                Ok(v) => this.follow_local_job(cx, api::s(&v, "job_id"), |this, job, cx| {
                    this.live.local.note = Some(job.message.clone());
                    if job.done {
                        this.live.local.runtime_starting = false;
                        this.local_check_again(cx);
                    }
                }),
                Err(e) => {
                    this.live.local.runtime_starting = false;
                    this.live.local.note = Some(e.message);
                }
            }
        });
    }

    pub fn refresh_local_catalogue(&mut self, cx: &mut Context<Self>) {
        if self.live.local.catalogue_loading { return; }
        self.live.local.catalogue_loading = true;
        self.fetch(cx, || api::get("/api/local-models?available=true&fresh=true"), |this, reply, cx| {
            this.live.local.catalogue_loading = false;
            match reply {
                Ok(value) => {
                    this.live.local.offered = strings(&value, "available");
                    this.live.local.library = api::arr(&value, "library")
                        .iter()
                        .map(|row| {
                            let sizes = strings(row, "sizes");
                            LibraryModel {
                                name: api::s(row, "name"),
                                listed: true,
                                est_gb: sizes.first().and_then(|size| size_gb(size)),
                                params_b: sizes.first().and_then(|size| params_b(size)),
                                sizes,
                                about: api::s(row, "about"),
                                ..Default::default()
                            }
                        })
                        .filter(|m| !m.name.is_empty())
                        .collect();
                    // an engine that sends only names still fills the store
                    if this.live.local.library.is_empty() {
                        this.live.local.library = this.live.local.offered.iter()
                            .map(|n| LibraryModel { name: n.clone(), listed: true, ..Default::default() })
                            .collect();
                    }
                    // the server's own list may have arrived first, or since
                    let held = this.live.local.held.clone().unwrap_or_default();
                    mark_installed(&mut this.live.local.library, &held);
                    this.live.local.catalogue_error = api::s(&value, "catalogue_error");
                    this.live.local.catalogue_loaded = this.live.local.catalogue_error.is_empty();
                }
                Err(error) => {
                    this.live.local.catalogue_error = error.to_string();
                    this.live.local.catalogue_loaded = false;
                }
            }
            cx.notify();
        });
    }

    /// Reads the plane; `fill` also puts the stored choices into the form,
    /// which only the first read and a Save do, so typing is never undone.
    fn refresh_plane(&mut self, fill: bool, cx: &mut Context<Self>) {
        self.live.local.checking = true;
        self.live.local.plane_error = None;
        self.fetch(cx, || api::get("/api/local-plane"), move |this, reply, _| {
            this.note(&reply);
            this.live.local.checking = false;
            this.live.local.device_reading = false;
            match reply {
                Ok(v) => {
                    this.live.local.plane_error = None;
                    let plane = plane_from(&v);
                    if should_fill_plane_form(fill, this.live.local.loaded) {
                        this.local_url.set_value(plane.stored_url.clone());
                        this.local_search.set_value(plane.stored_search.clone());
                        this.live.local.timeout = plane.timeout.round().max(1.0) as u32;
                        this.live.local.model_pick = if plane.model.is_empty() {
                            None
                        } else {
                            Some(plane.model.clone())
                        };
                    }
                    this.live.local.loaded = true;
                    this.live.local.plane = Some(plane);
                }
                Err(error) => this.live.local.plane_error = Some(error.message),
            }
            pick_confirmed(&mut this.live.local.pref_pending);
        });
    }

    /// Stores one runtime or language choice. The pick shows at once and its
    /// row shows a spinner until the engine's plane answers, so a click is
    /// never silent while the engine works. Only the plane is read again: a
    /// choice changes no machine, model or benchmark fact, and re-reading
    /// those too would probe every model server again and refill the address
    /// field the reader may be typing in.
    pub fn local_pick_pref(&mut self, key: String, value: String, cx: &mut Context<Self>) {
        pick_started(&mut self.live.local.pref_pending, &key, &value);
        cx.notify();
        let body = serde_json::json!({ key.clone(): value });
        self.fetch(cx, move || api::put("/api/prefs", body), move |this, reply, cx| {
            this.note(&reply);
            pick_answered(&mut this.live.local.pref_pending, &key, reply.is_ok());
            this.refresh_plane(false, cx);
        });
    }

    /// "Refresh device": reads the plane and this machine again, with a spinner
    /// on the button until the plane answers. It does not refill the address
    /// and search fields, so a server address typed but not saved survives it.
    pub fn refresh_device(&mut self, cx: &mut Context<Self>) {
        if self.live.local.checking {
            return;
        }
        self.live.local.device_reading = true;
        self.refresh_plane(false, cx);
        self.refresh_machine(false, cx);
        self.refresh_held(cx);
        cx.notify();
    }

    fn refresh_machine(&mut self, fresh: bool, cx: &mut Context<Self>) {
        let path = if fresh { "/api/machine?fresh=true" } else { "/api/machine" };
        self.fetch(cx, move || api::get(path), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.local.machine = Some(machine_from(&v));
            }
        });
    }

    fn refresh_held(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/local-models"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                let held = held_from(&v);
                mark_installed(&mut this.live.local.library, &held);
                this.live.local.held = Some(held);
            }
        });
    }

    /// "Check again": ask the machine and the servers afresh.
    pub fn local_check_again(&mut self, cx: &mut Context<Self>) {
        if self.live.local.checking {
            return;
        }
        self.live.local.checking = true;
        self.refresh_machine(true, cx);
        self.refresh_held(cx);
        self.refresh_plane(false, cx);
        cx.notify();
    }

    /// Stores the form: the address, the model, the search service and the
    /// wait, then reads the plane again so the card says what a run would use.
    pub fn local_save(&mut self, cx: &mut Context<Self>) {
        if self.live.local.saving {
            return;
        }
        self.live.local.saving = true;
        self.live.local.note = None;
        let body = serde_json::json!({
            "local_url": self.local_url.value.trim(),
            "local_model": self.live.local.model_pick.clone().unwrap_or_default(),
            "local_search_url": self.local_search.value.trim(),
            "local_timeout": self.live.local.timeout.to_string(),
        });
        self.fetch(cx, move || api::put("/api/prefs", body), |this, reply, cx| {
            this.note(&reply);
            this.live.local.saving = false;
            this.live.local.note = Some(match &reply {
                Ok(_) => "Saved.".to_string(),
                Err(e) => format!("Not saved: {}", e.message),
            });
            if reply.is_ok() {
                this.refresh_plane(true, cx);
                this.refresh_held(cx);
            }
        });
        cx.notify();
    }

    /// Points the plane at a running server and keeps the choice.
    pub fn local_use_server(&mut self, url: String, cx: &mut Context<Self>) {
        // the card moves to the new server now; the engine's answer, a probe
        // of every server, confirms it a moment later
        if let Some(plane) = self.live.local.plane.as_mut() {
            plane.url = url.clone();
            if let Some(server) = plane.servers.iter().find(|s| s.url == url) {
                plane.name = server.name.clone();
            }
        }
        self.local_url.set_value(url);
        self.live.local.model_pick = None;
        self.local_save(cx);
    }

    pub fn local_use_model(&mut self, name: String, cx: &mut Context<Self>) {
        if let Some(plane) = self.live.local.plane.as_mut() {
            plane.model = name.clone();
        }
        self.live.local.model_pick = Some(name);
        self.local_save(cx);
    }

    pub fn local_timeout_step(&mut self, up: bool, cx: &mut Context<Self>) {
        let t = self.live.local.timeout;
        self.live.local.timeout = if up { (t + 30).min(900) } else { t.saturating_sub(30).max(30) };
        cx.notify();
    }

    // ---- getting a model ----

    pub fn local_pull(&mut self, cx: &mut Context<Self>) {
        let model = self.local_get.value.trim().to_string();
        if model.is_empty() || matches!(&self.live.local.pull, Some(p) if p.phase == PullPhase::Running) {
            return;
        }
        let ask = model.clone();
        self.live.local.pull = Some(Pull {
            model: model.clone(),
            job_id: String::new(),
            progress: 0.0,
            message: "Asking Ollama".to_string(),
            phase: PullPhase::Running,
        });
        // the Downloading state shows on the click, not when the engine answers
        cx.notify();
        self.fetch(
            cx,
            move || api::post("/api/local-models/pull", serde_json::json!({"runtime": "ollama", "model": ask})),
            move |this, reply, cx| {
                this.note(&reply);
                match reply {
                    Ok(v) => {
                        let id = api::s(&v, "job_id");
                        if let Some(p) = this.live.local.pull.as_mut() {
                            p.job_id = id.clone();
                        }
                        this.follow_local_job(cx, id, |this, job, cx| {
                            let Some(p) = this.live.local.pull.as_mut() else { return };
                            p.progress = job.progress * 100.0;
                            p.message = job.message.clone();
                            if job.done {
                                p.phase = if job.succeeded() {
                                    PullPhase::Done
                                } else {
                                    PullPhase::Failed(if job.message.is_empty() {
                                        format!("The download {}.", job.state)
                                    } else {
                                        job.message.clone()
                                    })
                                };
                                if job.succeeded() {
                                    this.local_get.set_value(String::new());
                                    this.refresh_plane(false, cx);
                                    this.refresh_held(cx);
                                }
                            }
                        });
                    }
                    Err(e) => {
                        if let Some(p) = this.live.local.pull.as_mut() {
                            p.phase = PullPhase::Failed(e.message);
                        }
                    }
                }
            },
        );
        cx.notify();
    }

    pub fn local_pull_cancel(&mut self, cx: &mut Context<Self>) {
        let Some(p) = self.live.local.pull.as_ref() else { return };
        if p.phase != PullPhase::Running || p.job_id.is_empty() {
            return;
        }
        let id = p.job_id.clone();
        self.fetch(
            cx,
            move || api::post(&format!("/api/jobs/{}/cancel", api::seg(&id)), serde_json::json!({})),
            |this, reply, _| this.note(&reply),
        );
    }

    /// Deletes an installed model, then reads the server's list again so the
    /// tile stops saying Installed. A refusal stays beside the store rather
    /// than in the shell notice, because it is about one row.
    pub fn remove_local_model(&mut self, model: String, cx: &mut Context<Self>) {
        if self.live.local.removing.is_some() {
            return;
        }
        self.live.local.remove_confirm = None;
        self.live.local.remove_error.clear();
        self.live.local.removing = Some(model.clone());
        cx.notify();
        self.fetch(
            cx,
            move || {
                api::delete_json(
                    "/api/local-models/remove",
                    serde_json::json!({"runtime": "ollama", "model": model}),
                )
            },
            |this, reply, cx| {
                this.live.local.removing = None;
                match reply {
                    Ok(_) => {
                        this.live.local.remove_error.clear();
                        this.refresh_held(cx);
                    }
                    Err(error) => {
                        this.live.local.remove_error = error.message.clone();
                        this.note(&Err::<Value, _>(error));
                    }
                }
            },
        );
    }

    // ---- the benchmark ----

    pub fn refresh_bench(&mut self, cx: &mut Context<Self>) {
        let suite = if self.live.local.bench.suite.is_empty() { "precision".to_string() } else { self.live.local.bench.suite.clone() };
        self.fetch(cx, move || api::get(&format!("/api/bench?limit=100&suite={suite}")), |this, reply, _| {
            this.note(&reply);
            let Ok(v) = reply else { return };
            let b = &mut this.live.local.bench;
            if !b.loaded {
                b.case_count = 3; b.documents = 3; b.repeats = 1;
                b.timeout = 240; b.max_tokens = 1024;
            }
            b.snapshot = v.clone();
            if b.suite.is_empty() { b.suite = "precision".into(); }
            b.runs = api::arr(&v, "runs").iter().map(run_from).collect();
            b.summary = api::arr(&v, "summary")
                .iter()
                .map(|r| BenchRow {
                    plane: api::s(r, "plane"),
                    llm: api::s(r, "llm"),
                    protocol: api::s(r, "protocol"),
                    runs: api::n(r, "runs").unwrap_or(0.0),
                    ms: api::n(r, "ms"),
                    tokens: api::n(r, "tokens"),
                    accepted: api::n(r, "accepted").unwrap_or(0.0),
                    failures: api::n(r, "failures").unwrap_or(0.0),
                })
                .collect();
            b.scored = v
                .get("scored")
                .map(|s| api::arr(s, "groups"))
                .unwrap_or(&[])
                .iter()
                .map(|g| Scored {
                    plane: api::s(g, "plane"),
                    llm: api::s(g, "llm"),
                    hallucination: api::n(g, "hallucination_rate"),
                })
                .collect();
            if let Some(Value::Object(m)) = v.get("plane_meanings") {
                b.planes = m
                    .iter()
                    .filter(|(k, _)| k.as_str() != "agent")
                    .map(|(k, s)| (k.clone(), s.as_str().unwrap_or("").to_string()))
                    .collect();
            }
            if b.picked.is_empty() {
                b.picked = vec!["harness".to_string()];
            }
            let set = v.get("test_set").cloned().unwrap_or(Value::Null);
            b.cases = api::arr(&set, "cases").to_vec();
            b.set_label = format!(
                "{} {} · {} cases",
                api::s(&set, "id"),
                api::s(&set, "version"),
                api::arr(&set, "cases").len()
            );
            b.loaded = true;
        });
    }

    /// The request a press sends, built like the web screen's default: three
    /// cases, three documents each, twenty cents a case, one repetition.
    fn bench_body(&self) -> Value {
        serde_json::json!({
            "suite": if self.live.local.bench.suite.is_empty() { "precision" } else { &self.live.local.bench.suite },
            "planes": self.live.local.bench.picked.join(", "),
            "pack_id": "",
            "cases": self.live.local.bench.case_count.max(1),
            "case_ids": self.live.local.bench.case_ids,
            "max_documents": self.live.local.bench.documents.max(1),
            "budget_usd": 0.2,
            "protocols": "",
            "reps": self.live.local.bench.repeats.max(1),
            "llms": self.live.local.bench.models.join(","),
            "harness": self.live.local.bench.harness,
            "timeout_seconds": self.live.local.bench.timeout.max(10),
            "max_tokens": self.live.local.bench.max_tokens.max(128),
            "temperature": self.live.local.bench.temperature,
            "searches": "",
        })
    }

    pub fn bench_toggle_plane(&mut self, plane: &str, cx: &mut Context<Self>) {
        let b = &mut self.live.local.bench;
        if matches!(b.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) {
            return;
        }
        if let Some(i) = b.picked.iter().position(|p| p == plane) {
            b.picked.remove(i);
        } else {
            b.picked.push(plane.to_string());
        }
        // a different grid is a different price
        b.phase = BenchPhase::Idle;
        cx.notify();
    }

    pub fn bench_pick_suite(&mut self, suite: String, cx: &mut Context<Self>) {
        let b = &mut self.live.local.bench;
        if matches!(b.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
        b.suite = suite;
        b.case_ids.clear();
        b.phase = BenchPhase::Idle;
        if b.suite == "web" { b.picked.retain(|p| p != "api"); }
        self.refresh_bench(cx);
        cx.notify();
    }

    /// The one key: first press prices the grid, the second spends, a press
    /// while it runs stops it.
    pub fn bench_press(&mut self, cx: &mut Context<Self>) {
        let phase = self.live.local.bench.phase.clone();
        match phase {
            BenchPhase::Estimating => {}
            BenchPhase::Running { job_id, .. } => {
                self.fetch(
                    cx,
                    move || api::post(&format!("/api/jobs/{}/cancel", api::seg(&job_id)), serde_json::json!({})),
                    |this, reply, _| this.note(&reply),
                );
            }
            BenchPhase::Idle | BenchPhase::Failed(_) => {
                self.live.local.bench.phase = BenchPhase::Estimating;
                self.live.local.bench.last = None;
                let body = self.bench_body();
                self.fetch(cx, move || api::post("/api/bench/estimate", body), |this, reply, _| {
                    this.note(&reply);
                    this.live.local.bench.phase = match reply {
                        Ok(v) => BenchPhase::Confirm(Estimate {
                            runs: api::n(&v, "runs").unwrap_or(0.0) as i64,
                            usd: api::n(&v, "usd"),
                        }),
                        Err(e) => BenchPhase::Failed(e.message),
                    };
                });
            }
            BenchPhase::Confirm(_) => {
                let body = self.bench_body();
                self.live.local.bench.phase = BenchPhase::Running {
                    job_id: String::new(),
                    progress: 0.0,
                    message: "Starting".to_string(),
                };
                self.fetch(cx, move || api::post("/api/bench", body), |this, reply, cx| {
                    this.note(&reply);
                    match reply {
                        Ok(v) => {
                            let id = api::s(&v, "job_id");
                            this.live.local.bench.phase = BenchPhase::Running {
                                job_id: id.clone(),
                                progress: 0.0,
                                message: "Queued".to_string(),
                            };
                            this.follow_local_job(cx, id, |this, job, cx| {
                                if !job.done {
                                    if let BenchPhase::Running { progress, message, .. } =
                                        &mut this.live.local.bench.phase
                                    {
                                        *progress = job.progress * 100.0;
                                        *message = job.message.clone();
                                    }
                                    return;
                                }
                                let said = if job.message.is_empty() {
                                    format!("The benchmark {}.", job.state)
                                } else {
                                    job.message.clone()
                                };
                                this.live.local.bench.phase = BenchPhase::Idle;
                                this.live.local.bench.last = Some(said.clone());
                                this.dock_feed.push(DockFeedEntry::now(
                                    format!("Benchmark {}: {said}", job.state),
                                    if job.succeeded() { TagState::Done } else { TagState::Block },
                                ));
                                this.refresh_bench(cx);
                            });
                        }
                        Err(e) => this.live.local.bench.phase = BenchPhase::Failed(e.message),
                    }
                });
            }
        }
        cx.notify();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(batch: &str, at: &str, ms: Option<f64>, error: &str) -> BenchRun {
        BenchRun {
            batch_id: batch.into(),
            at: at.into(),
            ms,
            error: error.into(),
            accepted: 2.0,
            refused: 0.0,
            ..Default::default()
        }
    }

    #[test]
    fn a_pick_shows_before_the_engine_answers() {
        let mut pending = std::collections::HashMap::new();
        pick_started(&mut pending, "local_device", "cpu");
        assert_eq!(pending["local_device"].value, "cpu");
        assert_eq!(pending["local_device"].writes, 1);
    }

    #[test]
    fn a_refused_save_drops_the_pick_so_the_row_shows_the_engine_again() {
        let mut pending = std::collections::HashMap::new();
        pick_started(&mut pending, "local_device", "cpu");
        pick_answered(&mut pending, "local_device", false);
        assert!(!pending.contains_key("local_device"));
    }

    #[test]
    fn a_saved_pick_stays_until_the_plane_confirms_it() {
        let mut pending = std::collections::HashMap::new();
        pick_started(&mut pending, "local_output_language", "tr");
        pick_answered(&mut pending, "local_output_language", true);
        // saved, but the plane is not read yet: the row must not flicker back
        assert_eq!(pending["local_output_language"].value, "tr");
        pick_confirmed(&mut pending);
        assert!(pending.is_empty());
    }

    #[test]
    fn a_plane_read_during_a_save_keeps_the_pick() {
        let mut pending = std::collections::HashMap::new();
        pick_started(&mut pending, "local_device", "gpu");
        pick_confirmed(&mut pending);
        assert_eq!(pending["local_device"].value, "gpu");
    }

    #[test]
    fn two_quick_picks_of_one_row_show_the_last_until_both_answer() {
        let mut pending = std::collections::HashMap::new();
        pick_started(&mut pending, "local_gpu_layers", "16");
        pick_started(&mut pending, "local_gpu_layers", "32");
        pick_answered(&mut pending, "local_gpu_layers", true);
        assert_eq!(pending["local_gpu_layers"].value, "32");
        assert_eq!(pending["local_gpu_layers"].writes, 1);
        pick_answered(&mut pending, "local_gpu_layers", true);
        pick_confirmed(&mut pending);
        assert!(pending.is_empty());
    }

    #[test]
    fn a_refused_save_with_a_newer_one_in_flight_keeps_the_newer_pick() {
        let mut pending = std::collections::HashMap::new();
        pick_started(&mut pending, "local_device", "cpu");
        pick_started(&mut pending, "local_device", "gpu");
        pick_answered(&mut pending, "local_device", false);
        assert_eq!(pending["local_device"].value, "gpu");
    }

    #[test]
    fn retry_refresh_preserves_the_reader_server_and_model_form() {
        assert!(!should_fill_plane_form(false, true));
        assert!(should_fill_plane_form(false, false));
        assert!(should_fill_plane_form(true, true));
    }

    #[test]
    fn a_median_is_the_middle() {
        assert_eq!(median(vec![]), None);
        assert_eq!(median(vec![3.0, 1.0, 2.0]), Some(2.0));
        assert_eq!(median(vec![1.0, 2.0, 3.0, 10.0]), Some(2.5));
    }

    #[test]
    fn batches_come_newest_first_and_skip_failures() {
        let runs = vec![
            run("old", "2026-09-01T00:00:00+00:00", Some(100.0), ""),
            run("new", "2026-09-29T00:00:02+00:00", Some(40.0), ""),
            run("new", "2026-09-29T00:00:01+00:00", Some(60.0), ""),
            run("new", "2026-09-29T00:00:00+00:00", Some(5.0), "timeout"),
        ];
        let b = batches(&runs);
        assert_eq!(b.len(), 2);
        assert_eq!(b[0].id, "new");
        assert_eq!(b[0].median_ms, Some(50.0));
        assert_eq!(b[1].median_ms, Some(100.0));
        assert_eq!(b[0].median_usd, None, "unpriced stays unmeasured, not zero");
    }

    #[test]
    fn a_change_needs_both_numbers() {
        assert_eq!(change(Some(50.0), Some(100.0)), Some(-50));
        assert_eq!(change(Some(50.0), None), None);
        assert_eq!(change(None, Some(1.0)), None);
        assert_eq!(change(Some(1.0), Some(0.0)), None);
    }

    #[test]
    fn the_plane_reads_the_engines_shape() {
        let v: Value = serde_json::json!({
            "ready": true, "url": "http://127.0.0.1:11434", "name": "Ollama",
            "model": "m", "models": ["m", "n"], "timeout": 300.0,
            "servers": [{"name": "Ollama", "url": "u", "up": true, "models": ["m"]}],
            "stored": {"local_url": "", "local_model": "m", "local_search_url": "", "local_timeout": "120"}
        });
        let p = plane_from(&v);
        assert!(p.ready && p.models.len() == 2 && p.servers[0].up);
        assert_eq!(p.timeout, 300.0);
    }

    #[test]
    fn the_machine_keeps_unknown_as_none() {
        let v: Value = serde_json::json!({
            "gpu": {"name": null, "vram_total_mb": null, "vram_used_mb": null},
            "ram_total_mb": 16000, "cpu": {"name": "x", "cores": 8}, "runtimes": []
        });
        let m = machine_from(&v);
        assert!(m.gpu.is_none() && m.vram_total_mb.is_none());
        assert_eq!(m.ram_mb, Some(16000.0));
    }

    #[test]
    fn a_size_badge_becomes_a_q4_download_estimate() {
        assert_eq!(size_gb("7b"), Some(4.3));
        assert_eq!(size_gb("8x7b"), Some(34.7));
        assert_eq!(size_gb("270m"), Some(0.2));
        assert_eq!(size_gb("e2b"), Some(1.2));
        assert_eq!(size_gb("1.5b"), Some(0.9));
        assert_eq!(size_gb("latest"), None);
        assert_eq!(size_gb(""), None);
    }

    #[test]
    fn the_size_badge_parses_experts_millions_and_effective_counts() {
        assert_eq!(params_b("7b"), Some(7.0));
        assert_eq!(params_b("8x7b"), Some(56.0));
        assert_eq!(params_b("270m"), Some(0.27));
        assert_eq!(params_b("e2b"), Some(2.0));
    }

    #[test]
    fn a_library_name_matches_the_installed_default_tag() {
        assert_eq!(bare_model("Llama3"), bare_model("llama3:latest"));
        assert_eq!(bare_model(" llama3:latest "), "llama3");
        assert_ne!(bare_model("llama3:8b"), bare_model("llama3"));
    }

    #[test]
    fn the_library_marks_what_the_server_holds_and_its_size() {
        let mut library = vec![
            LibraryModel { name: "llama3".into(), ..Default::default() },
            LibraryModel { name: "qwen3".into(), ..Default::default() },
        ];
        let held = vec![
            Held { name: "llama3:latest".into(), size_bytes: Some(4_700_000_000.0), ..Default::default() },
        ];
        mark_installed(&mut library, &held);
        assert!(library[0].installed);
        assert_eq!(library[0].bytes, Some(4_700_000_000.0));
        assert!(!library[1].installed);
        assert_eq!(library[1].bytes, None);
    }

    #[test]
    fn a_sized_tag_of_a_library_model_marks_it_installed() {
        let mut library = vec![
            LibraryModel { name: "llama3".into(), sizes: vec!["8b".into()], ..Default::default() },
            LibraryModel { name: "llama3.2".into(), ..Default::default() },
        ];
        let held = vec![Held {
            name: "llama3:8b".into(),
            params: Some("8.0B".into()),
            quant: Some("Q4_K_M".into()),
            size_bytes: Some(4_700_000_000.0),
            ..Default::default()
        }];
        mark_installed(&mut library, &held);
        assert!(library[0].installed);
        assert_eq!(library[0].installed_name.as_deref(), Some("llama3:8b"));
        assert_eq!(library[0].params_b, Some(8.0));
        assert_eq!(library[0].quant.as_deref(), Some("Q4_K_M"));
        assert!(!library[1].installed, "llama3.2 is a different model");
    }

    #[test]
    fn an_installed_model_the_library_does_not_list_is_still_a_row() {
        let library = vec![LibraryModel { name: "llama3".into(), listed: true, ..Default::default() }];
        let held = vec![
            Held { name: "llama3:latest".into(), ..Default::default() },
            Held { name: "custom:7b".into(), params: Some("7.0B".into()), ..Default::default() },
        ];
        let mut marked = library.clone();
        mark_installed(&mut marked, &held);
        let rows = store_rows(&marked, &held);
        assert_eq!(rows.len(), 2);
        assert!(rows.iter().any(|r| r.name == "custom:7b" && r.installed && r.params_b == Some(7.0)));
    }

    #[test]
    fn the_store_keeps_only_the_rows_the_filter_names() {
        let library = vec![
            LibraryModel { name: "big".into(), listed: true, est_gb: Some(40.0), ..Default::default() },
            LibraryModel { name: "small".into(), listed: true, est_gb: Some(2.0), ..Default::default() },
            LibraryModel { name: "mid".into(), listed: true, est_gb: Some(9.0), ..Default::default() },
        ];
        let held = vec![Held {
            name: "mid:latest".into(),
            size_bytes: Some(9_000_000_000.0),
            ..Default::default()
        }];
        let mut marked = library.clone();
        mark_installed(&mut marked, &held);
        let names = |rows: Vec<LibraryModel>| rows.into_iter().map(|r| r.name).collect::<Vec<_>>();
        assert_eq!(
            names(store_view(&marked, &held, LibraryFilter::All, "", Some(10.0), LibrarySort::Size)),
            vec!["small", "mid", "big"].into_iter().map(String::from).collect::<Vec<_>>()
        );
        assert_eq!(
            names(store_view(&marked, &held, LibraryFilter::Installed, "", Some(10.0), LibrarySort::Name)),
            vec!["mid"].into_iter().map(String::from).collect::<Vec<_>>()
        );
        assert_eq!(
            names(store_view(&marked, &held, LibraryFilter::Small, "", Some(10.0), LibrarySort::Name)),
            vec!["small"].into_iter().map(String::from).collect::<Vec<_>>()
        );
        assert_eq!(
            names(store_view(&marked, &held, LibraryFilter::Fits, "", Some(10.0), LibrarySort::Name)),
            vec!["mid", "small"].into_iter().map(String::from).collect::<Vec<_>>()
        );
        assert!(
            store_view(&marked, &held, LibraryFilter::Fits, "", None, LibrarySort::Name).is_empty(),
            "a machine that measures nothing claims nothing fits"
        );
    }

    #[test]
    fn the_machines_memory_sets_the_fit_limit() {
        let gpu = Machine { vram_total_mb: Some(8192.0), ram_mb: Some(32768.0), ..Default::default() };
        assert_eq!(fits_limit_gb(&gpu).map(|g| (g * 10.0).round() / 10.0), Some(6.4));
        let cpu_only = Machine { ram_mb: Some(16384.0), ..Default::default() };
        assert_eq!(fits_limit_gb(&cpu_only).map(|g| (g * 10.0).round() / 10.0), Some(12.8));
        assert_eq!(fits_limit_gb(&Machine::default()), None);
    }

    #[test]
    fn a_parameter_count_reads_as_a_model_card_writes_it() {
        assert_eq!(params_label(7.0), "7B");
        assert_eq!(params_label(1.5), "1.5B");
        assert_eq!(params_label(0.27), "270M");
        assert_eq!(held_params_b(&Held { params: Some("8.0B".into()), ..Default::default() }), Some(8.0));
        assert_eq!(held_params_b(&Held { name: "llama3:e2b".into(), ..Default::default() }), Some(2.0));
    }

    #[test]
    fn a_rows_size_is_the_readers_pick_or_the_first_badge() {
        let row = LibraryModel {
            name: "m".into(),
            sizes: vec!["4b".into(), "8b".into()],
            ..Default::default()
        };
        assert_eq!(chosen_size(&row, None), Some("4b"));
        assert_eq!(chosen_size(&row, Some("8b")), Some("8b"));
        assert_eq!(chosen_size(&row, Some("70b")), Some("4b"), "a pick that is not a badge falls back");
    }

    #[test]
    fn a_library_row_links_to_its_page_without_its_tag() {
        assert_eq!(library_url("Llama3:8b"), "https://ollama.com/library/llama3");
    }

    #[test]
    fn removing_takes_two_presses_on_the_same_tile() {
        let mut armed = None;
        assert!(!remove_pressed(&mut armed, "llama3:8b"));
        assert_eq!(armed.as_deref(), Some("llama3:8b"));
        // a press on another tile arms that one instead, so one click can
        // never delete a model the reader did not point at twice
        assert!(!remove_pressed(&mut armed, "qwen3:4b"));
        assert_eq!(armed.as_deref(), Some("qwen3:4b"));
        assert!(remove_pressed(&mut armed, "qwen3:4b"));
        assert_eq!(armed, None);
    }
}
