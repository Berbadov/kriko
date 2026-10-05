//! Run, the dock and Agents: jobs, their feed and the agents on this machine,
//! as the engine says it.
//!
//! One shared poll serves all three. The jobs list is read every few seconds
//! (the dock and Run both draw from it), the job being followed is read every
//! 700 ms until it ends, and the agent lists are read when the Agents tab is
//! open. Nothing here starts work on its own: a job starts only from the
//! reader's own press on Start, and every long operation is a job row the
//! engine owns (`POST /api/research` answers with its id).
//!
//! Endpoints: `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/
//! cancel|say|retry`, `GET /api/search`, `POST /api/research`, `GET|PUT
//! /api/prefs`, `GET /api/agent-targets`, `POST /api/agent-targets/{id}/
//! connect|skill`, `POST /api/agent-verify`.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use gpui::Context;

use crate::api::{self, Value};
use crate::app::{DockFeedEntry, Kriko, Tab};
use crate::marks::{self, Mark, Phase};
use crate::theme::TagState;

// ---- what the engine says ----

#[derive(Clone, Debug, PartialEq)]
pub struct FeedLine {
    /// `source`, `search`, `finding`, `problem` or `note`.
    pub kind: String,
    pub text: String,
}

#[derive(Clone, Debug)]
pub struct Question {
    pub id: String,
    pub ask: String,
    pub options: Vec<String>,
    pub default: String,
    pub because: String,
}

#[derive(Clone, Debug)]
pub struct Attention {
    pub say: String,
    pub questions: Vec<Question>,
}

#[derive(Clone, Debug)]
pub struct Job {
    pub id: String,
    pub kind: String,
    pub state: String,
    /// 0..=1.
    pub progress: f32,
    pub message: String,
    pub done: bool,
    pub created_at: String,
    pub finished_at: String,
    pub harness: String,
    pub backend: String,
    pub subject_id: String,
    pub product: String,
    pub question: String,
    pub retry_of: String,
    pub attention: Option<Attention>,
    pub feed: Vec<FeedLine>,
}

/// Where a job stands, in the four phases the stepper shows.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Stage {
    Queued,
    Reading,
    Grounding,
    Stored,
    Failed,
    Cancelled,
}

impl Stage {
    pub fn index(self) -> usize {
        match self {
            Stage::Queued => 0,
            Stage::Reading => 1,
            Stage::Grounding => 2,
            Stage::Stored | Stage::Failed | Stage::Cancelled => 3,
        }
    }
}

impl Job {
    pub fn stage(&self) -> Stage {
        match self.state.as_str() {
            "succeeded" => Stage::Stored,
            "failed" | "interrupted" => Stage::Failed,
            "cancelled" => Stage::Cancelled,
            "queued" => Stage::Queued,
            _ => {
                if self.feed.iter().any(|l| l.kind == "finding") {
                    Stage::Grounding
                } else if self.feed.iter().any(|l| l.kind == "source" || l.kind == "search") {
                    Stage::Reading
                } else {
                    Stage::Queued
                }
            }
        }
    }

    /// What the agent's tile does: reading while sources come in, writing
    /// once findings do, thinking otherwise; idle before it starts.
    pub fn lane_phase(&self) -> Phase {
        if self.done {
            return Phase::Idle;
        }
        if self.state == "queued" {
            return Phase::Idle;
        }
        match self.feed.last().map(|l| l.kind.as_str()) {
            Some("source") | Some("search") => Phase::Reading,
            Some("finding") => Phase::Writing,
            _ => Phase::Thinking,
        }
    }

    pub fn is_research_like(&self) -> bool {
        matches!(
            self.kind.as_str(),
            "research" | "quick_look" | "agenda_run" | "pack_author" | "pack_amend"
        )
    }

    pub fn failed(&self) -> bool {
        matches!(self.state.as_str(), "failed" | "interrupted")
    }
}

/// The engine's own job kinds, said for a reader. A closed vocabulary of
/// operations, not of any category.
pub fn kind_word(kind: &str) -> String {
    match kind {
        "research" => "Research".into(),
        "quick_look" => "Quick check".into(),
        "pack_author" => "Draft a catalog".into(),
        "pack_build" => "Build a catalog".into(),
        "pack_update" => "Update catalogs".into(),
        "pack_amend" => "Amend a catalog".into(),
        "agenda_run" => "Agenda run".into(),
        "bench" => "Benchmark".into(),
        "verify" => "Verify".into(),
        "site_register" => "Register a site".into(),
        "research_undo" => "Undo a run".into(),
        "compare_ask" => "Compare question".into(),
        other => {
            let mut s = other.replace('_', " ");
            if let Some(c) = s.get(0..1) {
                let up = c.to_uppercase();
                s.replace_range(0..1, &up);
            }
            s
        }
    }
}

fn job_from(v: &Value) -> Job {
    let params = v.get("params").cloned().unwrap_or(Value::Null);
    let attention = v
        .get("attention")
        .filter(|a| a.is_object())
        .map(|a| Attention {
            say: api::s(a, "say"),
            questions: api::arr(a, "questions")
                .iter()
                .map(|q| Question {
                    id: api::s(q, "id"),
                    ask: api::s(q, "ask"),
                    options: api::arr(q, "options")
                        .iter()
                        .filter_map(|o| o.as_str().map(str::to_string))
                        .collect(),
                    default: api::s(q, "default"),
                    because: api::s(q, "because"),
                })
                .collect(),
        })
        .filter(|a| !a.questions.is_empty());
    let done = api::b(v, "done");
    let mut feed: Vec<FeedLine> = api::arr(v, "feed")
        .iter()
        .map(|l| FeedLine { kind: api::s(l, "kind"), text: api::s(l, "text") })
        .collect();
    if feed.is_empty() && done {
        // a finished job carries its log, not a feed: the tail is the story
        let log = api::s(v, "log");
        let lines: Vec<&str> = log.lines().map(str::trim).filter(|l| !l.is_empty()).collect();
        let from = lines.len().saturating_sub(10);
        feed = lines[from..]
            .iter()
            .map(|l| FeedLine { kind: "note".into(), text: clip(l, 220) })
            .collect();
    }
    let product = {
        let p = api::s(&params, "product");
        if p.is_empty() {
            api::s(&params, "category")
        } else {
            p
        }
    };
    Job {
        id: api::s(v, "job_id"),
        kind: api::s(v, "kind"),
        state: api::s(v, "state"),
        progress: api::n(v, "progress").unwrap_or(0.0) as f32,
        message: api::s(v, "message"),
        done,
        created_at: api::s(v, "created_at"),
        finished_at: api::s(v, "finished_at"),
        harness: api::s(&params, "harness"),
        backend: api::s(&params, "backend"),
        subject_id: api::s(&params, "subject_id"),
        product,
        question: api::s(&params, "question"),
        retry_of: api::s(&params, "retry_of"),
        attention,
        feed,
    }
}

fn clip(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(max).collect();
        out.push('…');
        out
    }
}

// ---- time ----

fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

/// Seconds since the epoch for the engine's `YYYY-MM-DDTHH:MM:SS` stamps,
/// which are UTC whether or not they carry an offset.
pub fn epoch(ts: &str) -> Option<i64> {
    let (date, time) = ts.split_once('T').or_else(|| ts.split_once(' '))?;
    let mut d = date.split('-');
    let (y, m, day) = (
        d.next()?.parse::<i64>().ok()?,
        d.next()?.parse::<i64>().ok()?,
        d.next()?.parse::<i64>().ok()?,
    );
    let clock = time.split(|c| c == '+' || c == 'Z' || c == '.').next()?;
    let mut t = clock.split(':');
    let (hh, mm, ss) = (
        t.next()?.parse::<i64>().ok()?,
        t.next()?.parse::<i64>().ok()?,
        t.next().and_then(|s| s.parse::<i64>().ok()).unwrap_or(0),
    );
    Some(days_from_civil(y, m, day) * 86400 + hh * 3600 + mm * 60 + ss)
}

fn now_epoch() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// "just now", "4 min ago": relative to the clock, from a UTC stamp.
pub fn ago(ts: &str) -> String {
    match epoch(ts) {
        Some(t) => ago_secs((now_epoch() - t).max(0)),
        None => String::new(),
    }
}

fn ago_secs(s: i64) -> String {
    match s {
        0..=9 => "just now".into(),
        10..=59 => format!("{s} s ago"),
        60..=3599 => format!("{} min ago", s / 60),
        3600..=86399 => format!("{} h ago", s / 3600),
        _ => format!("{} d ago", s / 86400),
    }
}

// ---- agents ----

#[derive(Clone, Debug)]
pub enum RunState {
    Ready,
    /// Found on this machine but not usable; the engine says why.
    Unusable(String),
    /// Not installed; the engine's hint on how.
    Missing { hint: String, url: String },
}

#[derive(Clone, Debug)]
pub struct Harness {
    pub id: String,
    pub label: String,
    pub state: RunState,
}

#[derive(Clone, Debug)]
pub struct Target {
    pub id: String,
    pub label: String,
    pub path: String,
    /// `connected`, `stale`, `absent` or `unreadable`.
    pub state: String,
    pub detail: String,
    pub skill_supported: bool,
    pub skill_present: bool,
    pub skill_stale: bool,
}

/// One row of the Agents table: an agent as a runner of checks, as a
/// connection target for the MCP server, or both (they share an id when the
/// same product is both).
#[derive(Clone, Debug)]
pub struct AgentEntry {
    pub id: String,
    pub label: String,
    pub harness: Option<Harness>,
    pub target: Option<Target>,
}

#[derive(Clone, Debug, Default)]
pub struct Verify {
    pub ok: bool,
    pub steps: Vec<(String, String)>,
    pub detail: String,
}

/// The agent mark for a harness or target id; the engine's own mark when
/// the id is not one the app draws.
pub fn mark_for(id: &str) -> &'static Mark {
    match id {
        "claude-code" => &marks::CLAUDE,
        "claude-desktop" => &marks::CLAUDE_DESKTOP,
        "opencode" => &marks::OPENCODE,
        "antigravity-cli" => &marks::ANTIGRAVITY,
        "mistral-vibe" | "mistral-api" => &marks::MISTRAL,
        "github-copilot" => &marks::COPILOT,
        "cursor" => &marks::CURSOR,
        _ => &marks::BUILTIN,
    }
}

// ---- the subject search that starts a check ----

#[derive(Clone, Debug)]
pub struct Hit {
    pub subject_id: String,
    pub pack_id: String,
    pub label: String,
    pub identity: String,
    pub claims: i64,
}

#[derive(Default)]
pub struct Start {
    pub open: bool,
    pub searching: bool,
    pub searched: bool,
    pub hits: Vec<Hit>,
    pub picked: Option<Hit>,
    /// The agent this check runs with; empty means the preferred one.
    pub harness: String,
    pub note: String,
}

#[derive(Default)]
pub struct State {
    pub loaded: bool,
    pub polling: bool,
    pub jobs: Vec<Job>,
    pub jobs_loaded: bool,
    list_inflight: bool,
    detail_inflight: bool,
    last_list: Option<Instant>,
    last_agents: Option<Instant>,
    /// The job the reader started or retried: followed until they say
    /// otherwise.
    pub pinned: Option<String>,
    /// The followed job as `GET /api/jobs/{id}` last said it.
    pub detail: Option<Job>,
    /// Subject labels, by subject id, for naming a job.
    pub labels: HashMap<String, String>,
    label_asked: HashSet<String>,
    /// The option picked for each question, by question id.
    pub answers: HashMap<String, String>,
    pub start: Start,
    // agents
    pub harnesses: Vec<Harness>,
    pub preferred: String,
    pub prefs_loaded: bool,
    pub targets: Vec<Target>,
    pub targets_loaded: bool,
    pub agent_selected: String,
    pub agent_note: String,
    pub verifying: bool,
    pub verify: Option<Verify>,
}

impl State {
    /// The job on the Run screen: the one the reader started, else the
    /// newest not-done research-like job, else the most recent finished one.
    pub fn current_id(&self) -> Option<String> {
        if let Some(p) = &self.pinned {
            if self.jobs.iter().any(|j| &j.id == p) || self.detail.as_ref().is_some_and(|d| &d.id == p) {
                return Some(p.clone());
            }
        }
        let like = || self.jobs.iter().filter(|j| j.is_research_like());
        like()
            .find(|j| !j.done)
            .or_else(|| like().next())
            .map(|j| j.id.clone())
    }

    pub fn current(&self) -> Option<&Job> {
        let id = self.current_id()?;
        match &self.detail {
            Some(d) if d.id == id => Some(d),
            _ => self.jobs.iter().find(|j| j.id == id),
        }
    }

    pub fn running(&self) -> impl Iterator<Item = &Job> {
        self.jobs.iter().filter(|j| !j.done)
    }

    /// The job a reply goes to: one with a question, else the one being
    /// followed, else the first running.
    pub fn reply_target(&self) -> Option<&Job> {
        self.running()
            .find(|j| j.attention.is_some())
            .or_else(|| self.current().filter(|j| !j.done))
            .or_else(|| self.running().next())
    }

    /// Jobs with something to put to the reader: still running, or ended
    /// within the last half hour, and not already run again.
    pub fn needs_you(&self) -> Vec<&Job> {
        let retried: HashSet<&str> = self
            .jobs
            .iter()
            .filter(|j| !j.retry_of.is_empty())
            .map(|j| j.retry_of.as_str())
            .collect();
        let now = now_epoch();
        self.jobs
            .iter()
            .filter(|j| j.attention.is_some() && !retried.contains(j.id.as_str()))
            .filter(|j| {
                !j.done || epoch(&j.finished_at).is_some_and(|t| now - t < 30 * 60)
            })
            .collect()
    }

    /// What a job is, said short: its kind and, when it has one, its subject.
    pub fn task(&self, job: &Job) -> String {
        let kind = kind_word(&job.kind);
        let subject = if !job.product.is_empty() {
            job.product.clone()
        } else {
            self.labels.get(&job.subject_id).cloned().unwrap_or_default()
        };
        if subject.is_empty() {
            kind
        } else {
            format!("{kind} · {subject}")
        }
    }

    /// Jobs started with this agent, among the ones the engine listed.
    pub fn runs_of(&self, id: &str) -> usize {
        self.jobs.iter().filter(|j| j.harness == id).count()
    }

    pub fn agent_entries(&self) -> Vec<AgentEntry> {
        let mut out: Vec<AgentEntry> = Vec::new();
        for h in &self.harnesses {
            out.push(AgentEntry {
                id: h.id.clone(),
                label: h.label.clone(),
                harness: Some(h.clone()),
                target: None,
            });
        }
        for t in &self.targets {
            match out.iter_mut().find(|e| e.id == t.id) {
                Some(e) => e.target = Some(t.clone()),
                None => out.push(AgentEntry {
                    id: t.id.clone(),
                    label: t.label.clone(),
                    harness: None,
                    target: Some(t.clone()),
                }),
            }
        }
        out
    }

    pub fn selected_agent(&self) -> Option<AgentEntry> {
        let all = self.agent_entries();
        all.iter()
            .find(|e| e.id == self.agent_selected)
            .cloned()
            .or_else(|| all.into_iter().next())
    }

    /// The agent a new check runs with.
    pub fn start_harness(&self) -> String {
        if !self.start.harness.is_empty() {
            return self.start.harness.clone();
        }
        let usable = |id: &str| {
            self.harnesses
                .iter()
                .any(|h| h.id == id && matches!(h.state, RunState::Ready))
        };
        if usable(&self.preferred) {
            return self.preferred.clone();
        }
        self.harnesses
            .iter()
            .find(|h| matches!(h.state, RunState::Ready))
            .map(|h| h.id.clone())
            .unwrap_or_default()
    }

    /// Finished jobs worth a line in the dock feed: the last few, recent.
    pub fn notices(&self) -> Vec<(TagState, String)> {
        let now = now_epoch();
        self.jobs
            .iter()
            .filter(|j| j.done)
            .filter(|j| epoch(&j.finished_at).is_some_and(|t| now - t < 6 * 3600))
            .take(4)
            .map(|j| {
                let state = match j.stage() {
                    Stage::Failed => TagState::Block,
                    Stage::Cancelled => TagState::Queue,
                    _ => TagState::Done,
                };
                let word = match j.stage() {
                    Stage::Cancelled => "stopped".to_string(),
                    _ if j.message.is_empty() => j.state.clone(),
                    _ => clip(&j.message, 80),
                };
                (state, format!("{}: {}", self.task(j), word))
            })
            .collect()
    }
}

// ---- reading the engine ----

fn harnesses_from(v: &Value) -> Vec<Harness> {
    let mut out: Vec<Harness> = api::arr(v, "harnesses")
        .iter()
        .map(|h| Harness { id: api::s(h, "id"), label: api::s(h, "label"), state: RunState::Ready })
        .collect();
    out.extend(api::arr(v, "unusable").iter().map(|h| Harness {
        id: api::s(h, "id"),
        label: api::s(h, "label"),
        state: RunState::Unusable(api::s(h, "why")),
    }));
    out.extend(api::arr(v, "missing").iter().map(|h| Harness {
        id: api::s(h, "id"),
        label: api::s(h, "label"),
        state: RunState::Missing { hint: api::s(h, "install_hint"), url: api::s(h, "download_url") },
    }));
    out
}

fn targets_from(v: &Value) -> Vec<Target> {
    api::arr(v, "targets")
        .iter()
        .map(|t| {
            let skill = t.get("skill").cloned().unwrap_or(Value::Null);
            Target {
                id: api::s(t, "id"),
                label: api::s(t, "label"),
                path: api::s(t, "path"),
                state: api::s(t, "state"),
                detail: api::s(t, "detail"),
                skill_supported: api::b(&skill, "supported"),
                skill_present: api::b(&skill, "present"),
                skill_stale: api::b(&skill, "stale"),
            }
        })
        .collect()
}

fn hits_from(v: &Value) -> Vec<Hit> {
    api::arr(v, "items")
        .iter()
        .map(|h| {
            let identity = h
                .get("identity")
                .and_then(|i| i.as_object())
                .map(|o| {
                    o.values()
                        .filter_map(|x| x.as_str())
                        .filter(|x| !x.is_empty())
                        .collect::<Vec<_>>()
                        .join(" · ")
                })
                .unwrap_or_default();
            Hit {
                subject_id: api::s(h, "subject_id"),
                pack_id: api::s(h, "pack_id"),
                label: api::s(h, "label"),
                identity,
                claims: api::n(h, "claims").unwrap_or(0.0) as i64,
            }
        })
        .collect()
}

impl Kriko {
    /// Called once when the engine first answers: reads everything this area
    /// shows and starts the one poll that keeps it current.
    pub fn refresh_run(&mut self, cx: &mut Context<Self>) {
        if self.live.run.polling {
            return;
        }
        self.live.run.polling = true;
        self.live.run.loaded = true;
        self.refresh_jobs(cx);
        self.refresh_agents(cx);
        cx.spawn(async move |this, cx| loop {
            cx.background_executor().timer(Duration::from_millis(700)).await;
            if this.update(cx, |this, cx| this.run_tick(cx)).is_err() {
                break;
            }
        })
        .detach();
    }

    /// 700 ms: follow the current job while it runs; every 3 s (15 s when
    /// nothing is on screen that shows it) the jobs list; every 10 s the
    /// agent lists while Agents is open.
    fn run_tick(&mut self, cx: &mut Context<Self>) {
        let now = Instant::now();
        let watching = self.dock_open || self.tab == Tab::Run;
        let every = Duration::from_secs(if watching { 3 } else { 15 });
        let due = |last: Option<Instant>, every: Duration| last.is_none_or(|t| now - t >= every);
        if self.tab == Tab::Run || self.dock_open {
            if self.live.run.current().is_some_and(|j| !j.done) {
                self.refresh_current(cx);
            }
        }
        if due(self.live.run.last_list, every) {
            self.refresh_jobs(cx);
        }
        if self.tab == Tab::Agents && due(self.live.run.last_agents, Duration::from_secs(10)) {
            self.refresh_agents(cx);
        }
    }

    pub fn refresh_jobs(&mut self, cx: &mut Context<Self>) {
        if self.live.run.list_inflight {
            return;
        }
        self.live.run.list_inflight = true;
        self.live.run.last_list = Some(Instant::now());
        self.fetch(cx, || api::get("/api/jobs?limit=30"), |this, reply, cx| {
            this.live.run.list_inflight = false;
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.run.jobs = api::arr(&v, "items").iter().map(job_from).collect();
                this.live.run.jobs_loaded = true;
                this.name_subjects(cx);
            }
        });
    }

    fn refresh_current(&mut self, cx: &mut Context<Self>) {
        let Some(id) = self.live.run.current_id() else { return };
        if self.live.run.detail_inflight {
            return;
        }
        self.live.run.detail_inflight = true;
        let path = format!("/api/jobs/{}", api::seg(&id));
        self.fetch(cx, move || api::get(&path), |this, reply, cx| {
            this.live.run.detail_inflight = false;
            this.note(&reply);
            if let Ok(v) = reply {
                let job = job_from(&v);
                // a job that just ended: the list should say so now
                let ended = job.done && this.live.run.detail.as_ref().is_some_and(|d| d.id == job.id && !d.done);
                this.live.run.detail = Some(job);
                if ended {
                    this.refresh_jobs(cx);
                }
            }
        });
    }

    /// Asks the engine for the label of each research subject a job names,
    /// once, so a lane can say what it is working on.
    fn name_subjects(&mut self, cx: &mut Context<Self>) {
        let wanted: Vec<String> = self
            .live
            .run
            .jobs
            .iter()
            .filter(|j| !j.subject_id.is_empty() && j.product.is_empty())
            .map(|j| j.subject_id.clone())
            .filter(|id| !self.live.run.labels.contains_key(id) && !self.live.run.label_asked.contains(id))
            .take(6)
            .collect();
        for id in wanted {
            self.live.run.label_asked.insert(id.clone());
            let path = format!("/api/subjects/{}", api::seg(&id));
            self.fetch(cx, move || api::get(&path), move |this, reply, _| {
                if let Ok(v) = reply {
                    let label = api::s(&v, "label");
                    if !label.is_empty() {
                        this.live.run.labels.insert(id, label);
                    }
                }
            });
        }
    }

    pub fn refresh_agents(&mut self, cx: &mut Context<Self>) {
        self.live.run.last_agents = Some(Instant::now());
        self.fetch(cx, || api::get("/api/prefs"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.apply_prefs(&v);
            }
        });
        self.fetch(cx, || api::get("/api/agent-targets"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.run.targets = targets_from(&v);
                this.live.run.targets_loaded = true;
            }
        });
    }

    fn apply_prefs(&mut self, v: &Value) {
        let run = &mut self.live.run;
        run.harnesses = harnesses_from(v);
        run.preferred = v
            .get("chosen")
            .map(|c| api::s(c, "preferred_harness"))
            .unwrap_or_default();
        run.prefs_loaded = true;
    }

    // ---- what the keys do ----

    /// Stop: ask the engine to cancel; the next reads show where it landed.
    pub fn stop_job(&mut self, id: String, cx: &mut Context<Self>) {
        let path = format!("/api/jobs/{}/cancel", api::seg(&id));
        self.fetch(cx, move || api::post(&path, serde_json::json!({})), |this, reply, cx| {
            this.note(&reply);
            this.refresh_jobs(cx);
            this.refresh_current(cx);
        });
    }

    pub fn pick_answer(&mut self, question: String, option: String) {
        self.live.run.answers.insert(question, option);
    }

    /// Answer a job's questions: a new run that carries the picks (the
    /// engine never paused for them, so the answers make the next run exact).
    pub fn answer_job(&mut self, id: String, cx: &mut Context<Self>) {
        let Some(job) = self.live.run.jobs.iter().find(|j| j.id == id).cloned() else { return };
        let Some(attention) = job.attention else { return };
        let mut answers = serde_json::Map::new();
        for q in &attention.questions {
            if let Some(a) = self.live.run.answers.get(&q.id) {
                answers.insert(q.id.clone(), Value::String(a.clone()));
            }
        }
        let path = format!("/api/jobs/{}/retry", api::seg(&id));
        let body = serde_json::json!({ "answers": answers });
        self.fetch(cx, move || api::post(&path, body), |this, reply, cx| {
            this.note(&reply);
            if let Ok(v) = reply {
                let new = api::s(&v, "job_id");
                if !new.is_empty() {
                    this.live.run.pinned = Some(new);
                    this.live.run.detail = None;
                }
            }
            this.refresh_jobs(cx);
        });
    }

    /// Say a line to the job the dock is answering. `delivered: false` means
    /// it had already ended, and the feed says so rather than pretending.
    pub fn send_reply(&mut self, cx: &mut Context<Self>) {
        let text = self.dock_reply.value.trim().to_string();
        self.dock_reply_open = false;
        let Some(job) = self.live.run.reply_target().cloned() else {
            cx.notify();
            return;
        };
        if text.is_empty() {
            cx.notify();
            return;
        }
        self.dock_reply.value.clear();
        let path = format!("/api/jobs/{}/say", api::seg(&job.id));
        let task = self.live.run.task(&job);
        self.fetch(cx, move || api::post(&path, serde_json::json!({ "text": text.clone() })).map(|v| (v, text)), move |this, reply, _| {
            this.note(&reply.as_ref().map_err(|e| e.clone()).map(|_| ()));
            match reply {
                Ok((v, text)) if api::b(&v, "delivered") => this
                    .dock_feed
                    .push(DockFeedEntry::now(format!("You to {task}: {}", clip(&text, 80)), TagState::Done)),
                Ok(_) => this
                    .dock_feed
                    .push(DockFeedEntry::now(format!("{task} had already ended"), TagState::Queue)),
                Err(e) => this.dock_feed.push(DockFeedEntry::now(e.message, TagState::Block)),
            }
        });
    }

    pub fn search_subjects(&mut self, cx: &mut Context<Self>) {
        let q = self.run_search.value.trim().to_string();
        if q.is_empty() {
            return;
        }
        let start = &mut self.live.run.start;
        start.searching = true;
        start.note.clear();
        let path = format!("/api/search?q={}&limit=8", api::seg(&q));
        self.fetch(cx, move || api::get(&path), |this, reply, _| {
            this.note(&reply);
            let start = &mut this.live.run.start;
            start.searching = false;
            start.searched = true;
            match reply {
                Ok(v) => start.hits = hits_from(&v),
                Err(e) => {
                    start.hits.clear();
                    start.note = e.message;
                }
            }
        });
    }

    /// Start: `POST /api/research` for the picked subject with the chosen
    /// agent, then follow the job it answers with.
    pub fn start_check(&mut self, cx: &mut Context<Self>) {
        let Some(hit) = self.live.run.start.picked.clone() else { return };
        let harness = self.live.run.start_harness();
        if harness.is_empty() {
            self.live.run.start.note = "No agent is ready to run a check. Pick one on the Agents tab.".into();
            return;
        }
        self.live.run.labels.insert(hit.subject_id.clone(), hit.label.clone());
        let body = serde_json::json!({
            "subject_id": hit.subject_id,
            "pack_id": hit.pack_id,
            "harness": harness,
        });
        self.fetch(cx, move || api::post("/api/research", body), |this, reply, cx| {
            this.note(&reply);
            match reply {
                Ok(v) => {
                    let id = api::s(&v, "job_id");
                    let start = &mut this.live.run.start;
                    start.open = false;
                    start.picked = None;
                    start.hits.clear();
                    start.searched = false;
                    start.note.clear();
                    this.run_search.value.clear();
                    this.live.run.pinned = Some(id);
                    this.live.run.detail = None;
                    this.refresh_jobs(cx);
                }
                Err(e) => this.live.run.start.note = e.message,
            }
        });
    }

    pub fn select_agent(&mut self, id: String) {
        self.live.run.agent_selected = id;
        self.live.run.agent_note.clear();
        self.live.run.verify = None;
    }

    /// Connect or Reconnect: write this installation's address into the
    /// agent's own config.
    pub fn connect_target(&mut self, id: String, cx: &mut Context<Self>) {
        let path = format!("/api/agent-targets/{}/connect", api::seg(&id));
        self.fetch(cx, move || api::post(&path, serde_json::json!({})), |this, reply, cx| {
            this.note(&reply);
            this.live.run.agent_note = match &reply {
                Ok(_) => "Connected. Restart the agent so it reads its config.".into(),
                Err(e) => e.message.clone(),
            };
            this.refresh_agents(cx);
        });
    }

    pub fn refresh_skill(&mut self, id: String, cx: &mut Context<Self>) {
        let path = format!("/api/agent-targets/{}/skill", api::seg(&id));
        self.fetch(cx, move || api::post(&path, serde_json::json!({})), |this, reply, cx| {
            this.note(&reply);
            this.live.run.agent_note = match &reply {
                Ok(_) => "The skill is written from what is installed now.".into(),
                Err(e) => e.message.clone(),
            };
            this.refresh_agents(cx);
        });
    }

    /// Use for runs: the single preferred agent, stored by the engine.
    pub fn prefer_agent(&mut self, id: String, cx: &mut Context<Self>) {
        let body = serde_json::json!({ "preferred_harness": id });
        self.fetch(cx, move || api::put("/api/prefs", body), |this, reply, _| {
            this.note(&reply);
            match reply {
                Ok(v) => {
                    this.apply_prefs(&v);
                    this.live.run.agent_note = "Checks will run with this agent.".into();
                }
                Err(e) => this.live.run.agent_note = e.message,
            }
        });
    }

    /// Check connection: the engine starts its own MCP server and reports
    /// each step it passed.
    pub fn verify_agents(&mut self, cx: &mut Context<Self>) {
        if self.live.run.verifying {
            return;
        }
        self.live.run.verifying = true;
        self.live.run.verify = None;
        self.fetch(cx, || api::post("/api/agent-verify", serde_json::json!({})), |this, reply, _| {
            this.note(&reply);
            let run = &mut this.live.run;
            run.verifying = false;
            match reply {
                Ok(v) => {
                    run.verify = Some(Verify {
                        ok: api::b(&v, "ok"),
                        steps: api::arr(&v, "steps")
                            .iter()
                            .map(|s| (api::s(s, "id"), api::s(s, "state")))
                            .collect(),
                        detail: api::s(&v, "detail"),
                    })
                }
                Err(e) => {
                    run.verify = Some(Verify { ok: false, steps: Vec::new(), detail: e.message })
                }
            }
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn recent_local_jobs_keep_their_backend_and_question_for_navigation() {
        let job = job_from(&json!({"job_id": "ask-1", "kind": "compare_ask",
            "state": "succeeded", "done": true,
            "params": {"backend": "local", "harness": "local",
                "question": "Which has the lower known risk?"}}));
        assert_eq!(job.backend, "local");
        assert_eq!(job.question, "Which has the lower known risk?");
    }

    fn running(feed: Value) -> Job {
        job_from(&json!({
            "job_id": "j", "kind": "research", "state": "running", "progress": 0.4,
            "done": false, "feed": feed, "params": {"harness": "claude-code"}
        }))
    }

    #[test]
    fn the_stage_follows_the_feed() {
        assert_eq!(running(json!([])).stage(), Stage::Queued);
        assert_eq!(running(json!([{"kind": "search", "text": "x"}])).stage(), Stage::Reading);
        assert_eq!(
            running(json!([{"kind": "source", "text": "x"}, {"kind": "finding", "text": "y"}])).stage(),
            Stage::Grounding
        );
        let done = job_from(&json!({"job_id": "j", "kind": "research", "state": "succeeded", "done": true}));
        assert_eq!(done.stage(), Stage::Stored);
        let failed = job_from(&json!({"job_id": "j", "kind": "research", "state": "interrupted", "done": true}));
        assert_eq!(failed.stage(), Stage::Failed);
    }

    #[test]
    fn a_job_names_its_agent_and_asks_its_questions() {
        let j = job_from(&json!({
            "job_id": "j", "kind": "quick_look", "state": "succeeded", "done": true,
            "params": {"harness": "opencode", "product": "Some product"},
            "attention": {"kind": "questions", "count": 1, "say": "one",
                "questions": [{"id": "m", "ask": "Which?", "key": "k", "options": ["a", "b"], "default": "a", "because": "x"}]}
        }));
        assert_eq!(j.harness, "opencode");
        let a = j.attention.unwrap();
        assert_eq!(a.questions[0].options, vec!["a", "b"]);
    }

    #[test]
    fn stamps_are_read_as_utc() {
        assert_eq!(epoch("1970-01-02T00:00:00+00:00"), Some(86400));
        assert_eq!(epoch("2026-10-04T16:48:22+00:00"), epoch("2026-10-04T16:48:22.123"));
        assert_eq!(ago_secs(5), "just now");
        assert_eq!(ago_secs(125), "2 min ago");
        assert_eq!(ago_secs(7300), "2 h ago");
    }

    #[test]
    fn the_current_job_is_the_newest_running_one() {
        let mut s = State::default();
        let mk = |id: &str, state: &str, done: bool| {
            job_from(&json!({"job_id": id, "kind": "research", "state": state, "done": done}))
        };
        s.jobs = vec![mk("a", "succeeded", true), mk("b", "running", false), mk("c", "running", false)];
        assert_eq!(s.current_id().as_deref(), Some("b"));
        s.jobs = vec![mk("a", "failed", true)];
        assert_eq!(s.current_id().as_deref(), Some("a"));
    }

    #[test]
    fn agents_merge_by_id() {
        let mut s = State::default();
        s.harnesses = harnesses_from(&json!({"harnesses": [{"id": "claude-code", "label": "Claude Code"}]}));
        s.targets = targets_from(&json!({"targets": [
            {"id": "claude-code", "label": "Claude Code", "state": "connected", "skill": {"supported": true}},
            {"id": "cursor", "label": "Cursor", "state": "absent"}]}));
        let all = s.agent_entries();
        assert_eq!(all.len(), 2);
        assert!(all[0].harness.is_some() && all[0].target.is_some());
        assert!(all[1].harness.is_none());
    }
}
