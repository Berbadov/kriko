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
    pub models: Vec<String>,
    pub servers: Vec<Server>,
    pub search_label: String,
    pub timeout: f64,
    pub stored_url: String,
    pub stored_model: String,
    pub stored_search: String,
    pub stored_timeout: String,
    pub runtime: Value,
}

#[derive(Default, Clone)]
pub struct RuntimeFound {
    pub id: String,
    pub name: String,
    pub installed: bool,
    pub path: Option<String>,
    pub can_pull: bool,
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

impl Machine {
    pub fn vram_gb(&self) -> Option<f64> {
        self.vram_total_mb.map(|m| m / 1024.0)
    }
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
    pub recall: Option<f64>,
    pub hallucination: Option<f64>,
}

#[derive(Clone)]
pub struct Estimate {
    pub runs: i64,
    pub usd: Option<f64>,
    pub note: String,
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

/// One downloadable model as the provider's library lists it: its name, the
/// parameter sizes it comes in and a line about it, all read by the engine.
#[derive(Default, Clone)]
pub struct LibraryModel {
    pub name: String,
    pub sizes: Vec<String>,
    pub about: String,
}

#[derive(Default)]
pub struct State {
    pub loaded: bool,
    pub plane: Option<Plane>,
    pub machine: Option<Machine>,
    pub held: Option<Vec<Held>>,
    /// Downloadable names from the provider's library.
    pub offered: Vec<String>,
    /// The same models with their sizes; what the library drawer draws.
    pub library: Vec<LibraryModel>,
    /// The size picked for each library model, by model name.
    pub library_size: std::collections::HashMap<String, String>,
    pub catalogue_open: bool,
    pub catalogue_loading: bool,
    pub catalogue_error: String,
    pub models_open: bool,
    /// The model the picker shows, which Save stores.
    pub model_pick: Option<String>,
    pub timeout: u32,
    pub saving: bool,
    pub note: Option<String>,
    pub checking: bool,
    pub pull: Option<Pull>,
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
        stored_model: api::s(&stored, "local_model"),
        stored_search: api::s(&stored, "local_search_url"),
        stored_timeout: api::s(&stored, "local_timeout"),
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
                name: api::s(r, "name"),
                installed: api::b(r, "installed"),
                path: opt_s(r, "path"),
                can_pull: api::b(r, "can_pull"),
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
    pub result: Value,
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
        result: v.get("result").cloned().unwrap_or(Value::Null),
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
                                    result: Value::Null,
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
                        .map(|row| LibraryModel {
                            name: api::s(row, "name"),
                            sizes: strings(row, "sizes"),
                            about: api::s(row, "about"),
                        })
                        .filter(|m| !m.name.is_empty())
                        .collect();
                    // an engine that sends only names still fills the drawer
                    if this.live.local.library.is_empty() {
                        this.live.local.library = this.live.local.offered.iter()
                            .map(|n| LibraryModel { name: n.clone(), ..Default::default() })
                            .collect();
                    }
                    this.live.local.catalogue_error = api::s(&value, "catalogue_error");
                }
                Err(error) => { this.live.local.catalogue_error = error.to_string(); }
            }
            cx.notify();
        });
    }

    /// Reads the plane; `fill` also puts the stored choices into the form,
    /// which only the first read and a Save do, so typing is never undone.
    fn refresh_plane(&mut self, fill: bool, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/local-plane"), move |this, reply, _| {
            this.note(&reply);
            this.live.local.checking = false;
            if let Ok(v) = reply {
                let plane = plane_from(&v);
                if fill || !this.live.local.loaded {
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
        });
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
                this.live.local.held = Some(held_from(&v));
            }
        });
    }

    /// "Check again": ask the machine and the servers afresh.
    pub fn local_check_again(&mut self, cx: &mut Context<Self>) {
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

    /// The next model the server lists, for the picker.
    pub fn local_cycle_model(&mut self, cx: &mut Context<Self>) {
        let Some(plane) = self.live.local.plane.as_ref() else { return };
        if plane.models.is_empty() {
            return;
        }
        let at = self
            .live
            .local
            .model_pick
            .as_ref()
            .and_then(|m| plane.models.iter().position(|x| x == m))
            .map(|i| (i + 1) % plane.models.len())
            .unwrap_or(0);
        self.live.local.model_pick = Some(plane.models[at].clone());
        cx.notify();
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

    // ---- the benchmark ----

    pub fn refresh_bench(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/bench?limit=100"), |this, reply, _| {
            this.note(&reply);
            let Ok(v) = reply else { return };
            let b = &mut this.live.local.bench;
            if !b.loaded {
                b.case_count = 3; b.documents = 3; b.repeats = 1;
                b.timeout = 240; b.max_tokens = 1024;
            }
            b.snapshot = v.clone();
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
                    recall: api::n(g, "recall"),
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
                            note: api::s(&v, "note"),
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
        assert_eq!(p.stored_timeout, "120");
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
}
