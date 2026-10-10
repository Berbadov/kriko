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
    pub id: String,
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
    pub configuration: String,
    pub tokens_in: Option<f64>,
    pub tokens_out: Option<f64>,
    pub usage_complete: bool,
    pub score: Value,
    pub stages: Vec<Value>,
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
    pub set_label: String,
    pub search: String,
    pub p95_ms: Option<f64>,
    pub counted_runs: f64,
    pub recall: Option<f64>,
    pub hallucination: Option<f64>,
    pub spec_recall: Option<f64>,
    pub abstention: Option<f64>,
    pub cost_per_claim: Option<f64>,
    pub tokens_in: Option<f64>,
    pub tokens_out: Option<f64>,
    pub partial_runs: f64,
    pub passed: f64,
    pub graded: f64,
    pub raw_produced: f64,
    pub spec_errors: f64,
}

#[derive(Default, Clone)]
pub struct BenchSuite {
    pub id: String,
    pub label: String,
    pub description: String,
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

#[derive(Default)]
pub struct Bench {
    pub loaded: bool,
    pub runs: Vec<BenchRun>,
    pub summary: Vec<BenchRow>,
    pub scored: Vec<Scored>,
    /// (plane, what it is), from the engine's own vocabulary.
    pub planes: Vec<(String, String)>,
    pub picked: Vec<String>,
    pub set_label: String,
    pub suite: String,
    pub suites: Vec<BenchSuite>,
    pub api_models: Vec<String>,
    pub open_run: Option<String>,
    pub phase: BenchPhase,
    /// How the last job ended, in the engine's words.
    pub last: Option<String>,
    /// The grid's knobs: cases from the set, documents per case,
    /// repetitions of each measurement, and the spend ceiling per case.
    pub cases: i64,
    pub docs: i64,
    pub reps: i64,
    pub budget: f64,
    /// The models the sweep is narrowed to; empty is whichever each plane
    /// would pick.
    pub models: Vec<String>,
    /// Which of the grid's drawers is open.
    pub drawer: Option<&'static str>,
}

impl Bench {
    pub fn controlled(&self) -> bool {
        self.suite != "web"
    }

    pub fn body(&self) -> Value {
        let planes: Vec<&str> = self.picked.iter().map(String::as_str)
            .filter(|p| self.controlled() || *p != "api").collect();
        serde_json::json!({
            "suite": if self.controlled() { "precision" } else { "web" },
            "planes": planes.join(", "), "pack_id": "", "cases": self.cases,
            "max_documents": self.docs, "budget_usd": self.budget,
            "protocols": "", "reps": self.reps,
            "llms": self.models.join(", "), "searches": "",
        })
    }

    /// What a run of this grid will bench, as one sentence for the screen.
    pub fn grid_word(&self) -> String {
        let planes = if self.picked.is_empty() { "no plane".to_string() } else { self.picked.join(" and ") };
        let models = if self.models.is_empty() {
            "whichever model each plane would pick".to_string()
        } else {
            self.models.join(", ")
        };
        format!(
            "{} case{} from {}, {}, {} time{}, on {} — {}",
            self.cases,
            if self.cases == 1 { "" } else { "s" },
            if self.controlled() { self.set_label.split(" · ").next().unwrap_or("configuration accuracy").trim() } else { "live web research" },
            if self.controlled() { "complete supplied documents".to_string() } else { format!("up to {} documents each", self.docs) },
            self.reps,
            if self.reps == 1 { "" } else { "s" },
            planes,
            models
        )
    }
}

#[derive(Default)]
pub struct State {
    pub loaded: bool,
    pub plane: Option<Plane>,
    pub machine: Option<Machine>,
    pub held: Option<Vec<Held>>,
    /// Local models the engine's own catalogue offers (none ship today).
    pub offered: Vec<String>,
    /// The model the picker shows, which Save stores.
    pub model_pick: Option<String>,
    pub timeout: u32,
    pub saving: bool,
    pub note: Option<String>,
    pub checking: bool,
    pub pull: Option<Pull>,
    pub delete_armed: Option<String>,
    pub deleting: Option<String>,
    pub models_note: Option<String>,
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
    let measurement = v.get("measurement").cloned().unwrap_or(Value::Null);
    BenchRun {
        id: api::s(v, "bench_id"),
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
        configuration: format!("{} {} · {} · {} · {} · {}", api::s(v, "set_id"),
            api::s(v, "set_version"), api::s(v, "plane"), api::s(v, "llm"),
            api::s(v, "protocol"), api::s(v, "search_provider")),
        tokens_in: api::n(&measurement, "tokens_in"),
        tokens_out: api::n(&measurement, "tokens_out"),
        usage_complete: measurement.get("usage_complete").and_then(Value::as_bool).unwrap_or(true),
        score: v.get("gold").cloned().unwrap_or(Value::Null),
        stages: api::arr(&measurement, "stages").to_vec(),
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
    pub hallucination: Option<f64>,
    pub configuration: Vec<String>,
}

pub fn median(mut xs: Vec<f64>) -> Option<f64> {
    if xs.is_empty() {
        return None;
    }
    xs.sort_by(|a, b| a.total_cmp(b));
    let n = xs.len();
    Some(if n % 2 == 1 { xs[n / 2] } else { (xs[n / 2 - 1] + xs[n / 2]) / 2.0 })
}

/// Batches, newest first. Attempt time includes failures; incomplete token
/// counts are omitted. Configuration signatures keep unlike grids apart.
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
            let mut configuration: Vec<String> = mine.iter().map(|r| format!("{} · {}", r.configuration, r.subject)).collect();
            configuration.sort();
            let graded: Vec<_> = mine.iter().filter(|r| r.error.is_empty() && r.score.is_object()).collect();
            let produced: f64 = graded.iter().filter_map(|r| api::n(&r.score, "raw_produced")).sum();
            let unsupported: usize = graded.iter().map(|r| api::arr(&r.score, "hallucinated").len()).sum();
            let accepted: f64 = mine.iter().map(|r| r.accepted).sum();
            let refused: f64 = mine.iter().map(|r| r.refused).sum();
            Batch {
                id: id.to_string(),
                at: mine.first().map(|r| r.at.clone()).unwrap_or_default(),
                median_ms: median(mine.iter().filter_map(|r| r.ms).collect()),
                median_tokens: median(mine.iter().filter(|r| r.usage_complete).filter_map(|r| r.tokens).collect()),
                median_usd: median(mine.iter().filter_map(|r| r.usd).collect()),
                hallucination: if produced > 0.0 { Some(unsupported as f64 / produced) } else { None },
                configuration,
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
        self.fetch(cx, || api::get("/api/prefs"), |this, reply, _| {
            if let Ok(v) = reply {
                this.live.local.bench.api_models = v.get("models")
                    .map(|m| api::arr(m, "offered")).unwrap_or(&[]).iter()
                    .filter(|o| api::s(o, "unusable").is_empty()
                        && !matches!(api::s(o, "provider").as_str(), "ollama" | "local"))
                    .map(|o| api::s(o, "id")).collect();
                let offered = v
                    .get("models")
                    .map(|m| api::arr(m, "offered"))
                    .unwrap_or(&[])
                    .iter()
                    .filter(|o| matches!(api::s(o, "provider").as_str(), "ollama" | "local"))
                    .map(|o| api::s(o, "id"))
                    .collect();
                this.live.local.offered = offered;
            }
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
                    this.local_url.value = plane.stored_url.clone();
                    this.local_search.value = plane.stored_search.clone();
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
        self.local_url.value = url;
        self.live.local.model_pick = None;
        self.local_save(cx);
    }

    pub fn local_use_model(&mut self, name: String, cx: &mut Context<Self>) {
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
                                    this.local_get.value.clear();
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

    /// Remove a model held by Ollama. The first press arms the exact model;
    /// the second sends the DELETE. The engine refuses removal of the model
    /// currently selected for Quick Look.
    pub fn local_remove_model(&mut self, model: String, cx: &mut Context<Self>) {
        if self.live.local.deleting.is_some() {
            return;
        }
        if self.live.local.delete_armed.as_deref() != Some(model.as_str()) {
            self.live.local.delete_armed = Some(model);
            self.live.local.models_note = None;
            cx.notify();
            return;
        }
        if self.live.local.plane.as_ref().is_some_and(|plane| plane.model == model) {
            self.live.local.models_note = Some("Choose another model for Quick Look before removing this one.".into());
            self.live.local.delete_armed = None;
            cx.notify();
            return;
        }
        self.live.local.deleting = Some(model.clone());
        self.live.local.models_note = None;
        let path = format!("/api/local-models/{}", api::seg(&model));
        self.fetch(cx, move || api::delete(&path), move |this, reply, cx| {
            this.note(&reply);
            this.live.local.deleting = None;
            this.live.local.delete_armed = None;
            this.live.local.models_note = Some(match &reply {
                Ok(_) => format!("Removed {model} from Ollama."),
                Err(e) => format!("Could not remove {model}: {}", e.message),
            });
            if reply.is_ok() {
                this.refresh_held(cx);
                this.refresh_plane(false, cx);
            }
        });
        cx.notify();
    }

    // ---- the benchmark ----

    pub fn refresh_bench(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/bench?limit=100"), |this, reply, _| {
            this.note(&reply);
            let Ok(v) = reply else { return };
            let b = &mut this.live.local.bench;
            b.runs = api::arr(&v, "runs").iter().map(run_from).collect();
            // The engine's readout keeps test versions, planes, protocols and
            // search providers separate. Legacy summary summed tokens while
            // averaging time, which made the displayed throughput grow with
            // the number of repetitions.
            b.summary = api::arr(&v, "readout")
                .iter()
                .map(|r| BenchRow {
                    plane: api::s(r, "plane"),
                    llm: api::s(r, "llm"),
                    protocol: api::s(r, "protocol"),
                    runs: api::n(r, "runs").unwrap_or(0.0),
                    ms: api::n(r, "latency_p50_ms"),
                    tokens: api::n(r, "tokens_mean"),
                    accepted: api::n(r, "accepted").unwrap_or(0.0),
                    failures: api::n(r, "failed_runs").unwrap_or(0.0),
                    set_label: format!("{} {}", api::s(r, "set_id"), api::s(r, "set_version")),
                    search: api::s(r, "search_provider"),
                    p95_ms: api::n(r, "latency_p95_ms"),
                    counted_runs: api::n(r, "counted_runs").unwrap_or(0.0),
                    recall: api::n(r, "recall"),
                    hallucination: api::n(r, "hallucination_rate"),
                    spec_recall: api::n(r, "spec_recall"),
                    abstention: api::n(r, "abstention_accuracy"),
                    cost_per_claim: api::n(r, "usd_per_accepted_claim"),
                    tokens_in: api::n(r, "tokens_in"), tokens_out: api::n(r, "tokens_out"),
                    partial_runs: api::n(r, "partial_usage_runs").unwrap_or(0.0),
                    passed: api::n(r, "passed").unwrap_or(0.0),
                    graded: api::n(r, "graded_runs").unwrap_or(0.0),
                    raw_produced: api::n(r, "raw_produced").unwrap_or(0.0),
                    spec_errors: api::n(r, "spec_errors").unwrap_or(0.0),
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
            if b.cases == 0 {
                b.cases = 9;
                b.docs = 3;
                b.reps = 2;
                b.budget = 0.2;
            }
            if b.suite.is_empty() { b.suite = "precision".into(); }
            b.suites = api::arr(&v, "suites").iter().map(|s| BenchSuite {
                id: api::s(s, "id"), label: api::s(s, "label"), description: api::s(s, "description"),
            }).collect();
            let set = v.get("test_set").cloned().unwrap_or(Value::Null);
            b.set_label = format!(
                "{} {} · {} cases",
                api::s(&set, "id"),
                api::s(&set, "version"),
                api::arr(&set, "cases").len()
            );
            b.loaded = true;
        });
    }

    /// The request a press sends: the grid the reader drew on the screen.
    fn bench_body(&self) -> Value {
        self.live.local.bench.body()
    }

    pub fn bench_pick_suite(&mut self, suite: String, cx: &mut Context<Self>) {
        let b = &mut self.live.local.bench;
        if matches!(b.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
        b.suite = suite;
        if !b.controlled() { b.picked.retain(|p| p != "api"); }
        b.drawer = None;
        b.phase = BenchPhase::Idle;
        cx.notify();
    }

    pub fn bench_open_run(&mut self, id: String, cx: &mut Context<Self>) {
        let b = &mut self.live.local.bench;
        b.open_run = if b.open_run.as_ref() == Some(&id) { None } else { Some(id) };
        cx.notify();
    }

    /// What a run of this grid will bench, as one sentence for the screen.
    pub fn bench_grid_word(&self) -> String {
        self.live.local.bench.grid_word()
    }

    /// The models the sweep can be narrowed to: what the local plane holds
    /// and what each ready harness says it serves, nothing typed by hand.
    pub fn bench_model_choices(&self) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        let b = &self.live.local.bench;
        if b.picked.iter().any(|p| p == "local") {
            if let Some(p) = &self.live.local.plane { out.extend(p.models.iter().cloned()); }
        }
        if b.controlled() && b.picked.iter().any(|p| p == "api") {
            out.extend(b.api_models.iter().cloned());
        }
        if b.picked.iter().any(|p| p == "harness") {
            for h in &self.live.run.harnesses {
                if matches!(h.state, crate::live::run::RunState::Ready) {
                    out.extend(h.llms.iter().cloned());
                }
            }
        }
        out.retain(|m| !m.is_empty());
        out.sort();
        out.dedup();
        out
    }

    /// Open or close one of the grid's drawers.
    pub fn bench_open_drawer(&mut self, name: &'static str, cx: &mut Context<Self>) {
        if matches!(self.live.local.bench.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
        self.live.local.bench.drawer = if self.live.local.bench.drawer == Some(name) {
            None
        } else {
            Some(name)
        };
        cx.notify();
    }

    /// Set one of the grid's numeric knobs; a different grid is a different
    /// price.
    pub fn bench_set_knob(&mut self, knob: &'static str, value: f64, cx: &mut Context<Self>) {
        if matches!(self.live.local.bench.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
        {
            let b = &mut self.live.local.bench;
            match knob {
                "cases" => b.cases = value as i64,
                "docs" => b.docs = value as i64,
                "reps" => b.reps = value as i64,
                "budget" => b.budget = value,
                _ => {}
            }
            b.drawer = None;
            b.phase = BenchPhase::Idle;
        }
        cx.notify();
    }

    /// Narrow the model sweep to the picked ones; empty is whichever each
    /// plane would pick.
    pub fn bench_pick_model(&mut self, model: String, cx: &mut Context<Self>) {
        if matches!(self.live.local.bench.phase, BenchPhase::Running { .. } | BenchPhase::Estimating) { return; }
        {
            let b = &mut self.live.local.bench;
            if let Some(i) = b.models.iter().position(|m| m == &model) {
                b.models.remove(i);
            } else {
                b.models.push(model);
            }
            b.phase = BenchPhase::Idle;
        }
        cx.notify();
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
    fn batches_come_newest_first_and_include_failed_attempt_time() {
        let runs = vec![
            run("old", "2026-09-01T00:00:00+00:00", Some(100.0), ""),
            run("new", "2026-09-29T00:00:02+00:00", Some(40.0), ""),
            run("new", "2026-09-29T00:00:01+00:00", Some(60.0), ""),
            run("new", "2026-09-29T00:00:00+00:00", Some(5.0), "timeout"),
        ];
        let b = batches(&runs);
        assert_eq!(b.len(), 2);
        assert_eq!(b[0].id, "new");
        assert_eq!(b[0].median_ms, Some(40.0));
        assert_eq!(b[1].median_ms, Some(100.0));
        assert_eq!(b[0].median_usd, None, "unpriced stays unmeasured, not zero");
    }

    #[test]
    fn a_real_source_quote_can_still_fail_configuration_accuracy() {
        let r = run_from(&serde_json::json!({
            "bench_id": "case-1", "batch_id": "b", "llm": "small", "plane": "local",
            "set_id": "configuration", "set_version": "v1", "protocol": "extractive",
            "search_provider": "supplied-corpus", "accepted": 2, "refused": 0, "tokens": 100,
            "measurement": {"tokens_in": 80, "tokens_out": 20, "usage_complete": false,
                "stages": [{"stage": "answer", "ms": 123, "tokens_used": 100}]},
            "gold": {"raw_produced": 2, "hallucinated": ["sibling revision"],
                "proposed_risks": [{"title": "Sibling fault"}]}
        }));
        assert_eq!(r.id, "case-1");
        assert_eq!(r.tokens_out, Some(20.0));
        assert_eq!(r.stages.len(), 1);
        let b = batches(&[r]);
        assert_eq!(b[0].hallucination, Some(0.5));
        assert_eq!(b[0].median_tokens, None, "partial counts must not appear as full usage");
        assert!(b[0].configuration[0].contains("v1"));
    }

    #[test]
    fn live_search_cannot_send_the_direct_completion_plane() {
        let mut b = Bench::default();
        b.suite = "precision".into();
        b.picked = vec!["local".into(), "api".into()];
        assert_eq!(b.body()["suite"], "precision");
        assert_eq!(b.body()["planes"], "local, api");
        b.suite = "web".into();
        assert_eq!(b.body()["suite"], "web");
        assert_eq!(b.body()["planes"], "local");
        assert!(b.grid_word().contains("live web research"));
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

    #[test]
    fn the_grid_says_what_a_run_will_bench() {
        let mut b = Bench::default();
        b.cases = 5;
        b.docs = 3;
        b.reps = 2;
        b.budget = 0.5;
        b.picked = vec!["local".into(), "api".into()];
        b.models = vec!["m1".into()];
        b.set_label = "kriko.check v3 · 40 cases".into();
        let word = b.grid_word();
        assert!(word.contains("5 cases"), "{word}");
        assert!(word.contains("kriko.check"), "{word}");
        assert!(word.contains("2 times"), "{word}");
        assert!(word.contains("local and api"), "{word}");
        assert!(word.contains("m1"), "{word}");
        b.models.clear();
        assert!(b.grid_word().contains("whichever model each plane would pick"));
    }
}
