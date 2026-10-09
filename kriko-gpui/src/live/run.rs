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
    /// The complete agent output, shown in the dock's optional log drawer.
    pub log: String,
    pub done: bool,
    pub created_at: String,
    pub finished_at: String,
    pub harness: String,
    pub backend: String,
    pub model: String,
    pub subject_id: String,
    pub product: String,
    pub question: String,
    pub result: Value,
    pub retry_of: String,
    pub attention: Option<Attention>,
    pub feed: Vec<FeedLine>,
    pub answer: String,
    pub no_answer_why: String,
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
        if self.attention.is_some() {
            return Phase::Waiting;
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

    /// The whole log as events, newest line last, the same shapes the engine
    /// reads (`livefeed`): the server's feed carries only the live tail, so
    /// the full story is classified here.
    pub fn log_events(&self) -> Vec<FeedLine> {
        if self.log.is_empty() {
            return self.feed.clone();
        }
        self.log
            .lines()
            .flat_map(|raw| raw.split("; "))
            .map(|l| l.trim())
            .filter(|l| !l.is_empty())
            .map(|l| FeedLine { kind: event_kind(l), text: l.to_string() })
            .collect()
    }

    /// How long the run took, or has been running, from its own stamps.
    pub fn duration_word(&self) -> String {
        let (Some(start), end) = (epoch(&self.created_at), if self.done {
            epoch(&self.finished_at)
        } else {
            Some(now_epoch())
        }) else {
            return String::new();
        };
        let Some(end) = end else { return String::new() };
        let s = (end - start).max(0);
        let word = match s {
            0..=59 => format!("{s} s"),
            60..=3599 => format!("{} min {:02} s", s / 60, s % 60),
            3600..=86399 => format!("{} h {} min", s / 3600, (s % 3600) / 60),
            _ => format!("{} d {} h", s / 86400, (s % 86400) / 3600),
        };
        if self.done {
            format!("ran for {word}")
        } else {
            format!("{word} in")
        }
    }
}

/// One log line's event kind, in the engine's closed vocabulary.
pub fn event_kind(line: &str) -> String {
    let l = line.to_lowercase();
    let starts = |head: &str| l.starts_with(head);
    if starts("a tool call failed") || starts("refused") || starts("left out") || starts("stopped:") {
        "problem".into()
    } else if starts("kept") || starts("wrote") {
        "finding".into()
    } else if starts("fetched") || starts("read through the page reader") {
        "source".into()
    } else if starts("searched") || starts("query:") {
        "search".into()
    } else {
        "note".into()
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
    let result = v.get("result").cloned().unwrap_or(Value::Null);
    let answer = {
        let said = api::s(&result, "answer");
        if !said.is_empty() {
            said
        } else {
            api::s(&result, "outcome")
        }
    };
    let no_answer_why = if let Some(diagnostic) = result.get("diagnostic") {
        api::s(diagnostic, "message")
    } else { api::s(&result, "note") };
    Job {
        id: api::s(v, "job_id"),
        kind: api::s(v, "kind"),
        state: api::s(v, "state"),
        progress: api::n(v, "progress").unwrap_or(0.0) as f32,
        message: api::s(v, "message"),
        log: api::s(v, "log"),
        done,
        created_at: api::s(v, "created_at"),
        finished_at: api::s(v, "finished_at"),
        harness: api::s(&params, "harness"),
        backend: api::s(&params, "backend"),
        model: api::s(&params, "model"),
        subject_id: api::s(&params, "subject_id"),
        product,
        question: api::s(&params, "question"),
        result: v.get("result").cloned().unwrap_or(Value::Null),
        retry_of: api::s(&params, "retry_of"),
        attention,
        feed,
        answer,
        no_answer_why,
    }
}

pub(crate) fn clip(s: &str, max: usize) -> String {
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
    /// The model chosen for this harness; empty means its own default.
    pub llm: String,
    /// The models this provider says it serves, asked for at refresh.
    pub llms: Vec<String>,
    pub llms_note: String,
    pub llm_selectable: bool,
    /// The effort chosen for this harness; empty means its own default.
    pub effort: String,
    /// The effort levels this CLI's `--help` declares; empty means no dial.
    pub efforts: Vec<String>,
    pub effort_hint: String,
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
    /// The engine's own transcript of the check: the command, each step,
    /// the answer, and the error text on failure.
    pub log: String,
    /// How long the whole check took, in milliseconds.
    pub ms: i64,
}

/// The agent mark for a harness or target id; the engine's own mark when
/// the id is not one the app draws.
pub fn mark_for(id: &str) -> &'static Mark {
    match id {
        "claude-code" => &marks::CLAUDE,
        "claude-desktop" => &marks::CLAUDE_DESKTOP,
        "codex" => &marks::CODEX,
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
    /// The Activity entry whose complete agent log is open.
    pub activity_log_open: Option<String>,
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
    /// The Run screen's log level filter: 0 is all, then search, source,
    /// finding, problem.
    pub log_level: usize,
    /// When the log's Copy plate was pressed, for its "Copied" flash.
    pub log_copied_at: Option<Instant>,
    pub start: Start,
    // agents
    pub harnesses: Vec<Harness>,
    pub preferred: String,
    pub prefs_loaded: bool,
    pub targets: Vec<Target>,
    pub targets_loaded: bool,
    pub agent_selected: String,
    pub agent_note: String,
    /// The reader's own arrangement of the agents, as the engine stored it.
    pub agent_order: Vec<String>,
    /// The detail card's model drawer.
    pub model_drawer: bool,
    /// Every kind of source a run can be pointed at, `(id, words)`, in the
    /// engine's order.
    pub source_kinds: Vec<(String, String)>,
    /// The kinds the reader picked, and the most sources a run reads (0 is
    /// "the run decides"). Both stored by the engine, read by every agent.
    pub research_kinds: Vec<String>,
    pub research_sources: u32,
    pub verifying: bool,
    pub verify: Option<Verify>,
    pub verify_log_open: bool,
    /// Preference saves sent and not yet answered; see `put_prefs`.
    pub prefs_pending: usize,
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
        } else if !job.question.is_empty() {
            job.question.clone()
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
        // the reader's arrangement wins: the named ones first in that order,
        // anything unnamed after, where the engine listed it
        let place = |id: &str| self.agent_order.iter().position(|o| o == id);
        out.retain(|e| matches!(e.id.as_str(), "local" | "claude-code" | "codex" | "antigravity-cli" | "mistral-vibe"));
        out.sort_by_key(|e| (place(&e.id).unwrap_or(usize::MAX), e.label.clone()));
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
        // A picked Local model stays the pick when its server is down: the
        // engine fails the run with the reason rather than this screen
        // quietly handing it to a CLI. With nothing picked, a ready local
        // model goes first, as the engine's own default does (B172).
        if self.preferred == "local" || (self.preferred.is_empty() && usable("local")) {
            return "local".to_string();
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
    let from_row = |h: &Value, state: RunState| Harness {
        id: api::s(h, "id"),
        label: api::s(h, "label"),
        state,
        llm: api::s(h, "llm"),
        llms: api::arr(h, "llms")
            .iter()
            .filter_map(|m| m.as_str().map(str::to_string))
            .collect(),
        llms_note: api::s(h, "llms_note"),
        llm_selectable: api::b(h, "llm_selectable"),
        effort: api::s(h, "effort"),
        efforts: api::arr(h, "efforts")
            .iter()
            .filter_map(|m| m.as_str().map(str::to_string))
            .collect(),
        effort_hint: api::s(h, "effort_hint"),
    };
    let mut out: Vec<Harness> = api::arr(v, "harnesses")
        .iter()
        .map(|h| from_row(h, RunState::Ready))
        .collect();
    out.extend(api::arr(v, "unusable").iter().map(|h| from_row(h, RunState::Unusable(api::s(h, "why")))));
    out.extend(api::arr(v, "missing").iter().map(|h| {
        from_row(h, RunState::Missing { hint: api::s(h, "install_hint"), url: api::s(h, "download_url") })
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
        run.agent_order = v
            .get("chosen")
            .map(|c| api::s(c, "agent_order"))
            .unwrap_or_default()
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(str::to_string)
            .collect();
        run.source_kinds = api::arr(v, "source_kinds")
            .iter()
            .map(|k| (api::s(k, "id"), api::s(k, "label")))
            .collect();
        let research = v.get("research").cloned().unwrap_or(Value::Null);
        run.research_kinds = api::arr(&research, "kinds")
            .iter()
            .filter_map(|k| k.as_str().map(str::to_string))
            .collect();
        run.research_sources = research
            .get("sources")
            .and_then(|n| n.as_u64())
            .unwrap_or(0) as u32;
        run.prefs_loaded = true;
    }

    /// Turn one kind of source on or off for every agent run.
    pub fn toggle_source_kind(&mut self, kind: String, cx: &mut Context<Self>) {
        let mut kinds = self.live.run.research_kinds.clone();
        if let Some(at) = kinds.iter().position(|k| *k == kind) {
            kinds.remove(at);
        } else {
            kinds.push(kind);
        }
        self.live.run.research_kinds = kinds.clone();
        let body = serde_json::json!({ "research_source_kinds": kinds.join(",") });
        self.put_prefs(body, "Saved. Every agent run reads these.", cx);
    }

    /// Set the most sources an agent run reads; 0 leaves it to the run.
    pub fn pick_source_count(&mut self, count: u32, cx: &mut Context<Self>) {
        self.live.run.research_sources = count;
        let body = serde_json::json!({ "research_sources": count.to_string() });
        self.put_prefs(body, "Saved. Every agent run reads these.", cx);
    }

    /// Store one preference. The screen already shows the choice, so the click
    /// is felt at once; this tells the engine. Only the last of several quick
    /// answers redraws from the engine's copy, so a second click is never
    /// undone by the first one's reply, and a refusal puts the screen back to
    /// what the engine holds.
    fn put_prefs(&mut self, body: Value, saved: &'static str, cx: &mut Context<Self>) {
        self.live.run.prefs_pending += 1;
        cx.notify();
        self.fetch(cx, move || api::put("/api/prefs", body), move |this, reply, cx| {
            this.note(&reply);
            this.live.run.prefs_pending = this.live.run.prefs_pending.saturating_sub(1);
            match reply {
                Ok(v) => {
                    if this.live.run.prefs_pending == 0 {
                        this.apply_prefs(&v);
                    }
                    this.live.run.agent_note = saved.into();
                }
                Err(e) => {
                    this.live.run.agent_note = format!("Not saved: {}", e.message);
                    this.refresh_agents(cx);
                }
            }
        });
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
        self.dock_reply.set_value(String::new());
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
                    this.run_search.set_value(String::new());
                    this.live.run.pinned = Some(id);
                    this.live.run.detail = None;
                    this.refresh_jobs(cx);
                }
                Err(e) => this.live.run.start.note = e.message,
            }
        });
    }

    pub fn select_agent(&mut self, id: String) {
        self.model_search.set_value(String::new());
        self.live.run.agent_selected = id;
        self.live.run.agent_note.clear();
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
        let body = serde_json::json!({ "preferred_harness": id.clone() });
        self.live.run.preferred = id;
        self.put_prefs(body, "Checks will run with this agent.", cx);
    }

    /// Move one agent up or down in the reader's arrangement, and keep it.
    pub fn order_agent(&mut self, id: String, step: i64, cx: &mut Context<Self>) {
        let ids: Vec<String> = self.live.run.agent_entries().iter().map(|e| e.id.clone()).collect();
        let mut order: Vec<String> = self
            .live
            .run
            .agent_order
            .iter()
            .filter(|o| ids.contains(o))
            .cloned()
            .collect();
        for e in &ids {
            if !order.contains(e) {
                order.push(e.clone());
            }
        }
        let Some(at) = order.iter().position(|o| o == &id) else { return };
        let to = at as i64 + step;
        if to < 0 || to >= order.len() as i64 {
            return;
        }
        order.swap(at, to as usize);
        let body = serde_json::json!({ "agent_order": order.join(",") });
        self.live.run.agent_order = order;
        self.put_prefs(body, "Saved. The agents keep this order.", cx);
    }

    /// The model drawer: the provider's own list, asked for when it opens.
    pub fn open_agent_models(&mut self, cx: &mut Context<Self>) {
        let opening = self.live.run.model_drawer;
        self.live.run.model_drawer = !opening;
        cx.notify();
        if !opening {
            self.fetch(cx, move || api::get("/api/prefs"), |this, reply, _| {
                this.note(&reply);
                if let Ok(v) = reply {
                    this.apply_prefs(&v);
                }
            });
        }
    }

    /// Pick the model one provider runs with; empty is its own default.
    pub fn pick_agent_model(&mut self, id: String, model: String, cx: &mut Context<Self>) {
        // The local row's model is the Local LLM page's own setting.
        let key = if id == "local" {
            "local_model".to_string()
        } else {
            format!("harness_model_{}", id.replace('-', "_"))
        };
        let body = serde_json::json!({ key: model.clone() });
        if let Some(h) = self.live.run.harnesses.iter_mut().find(|h| h.id == id) {
            h.llm = model;
        }
        self.put_prefs(body, "Saved. New runs use this model.", cx);
    }

    /// Pick how hard one provider thinks; empty is its own default.
    pub fn pick_agent_effort(&mut self, id: String, effort: String, cx: &mut Context<Self>) {
        let key = format!("harness_effort_{}", id.replace('-', "_"));
        let body = serde_json::json!({ key: effort.clone() });
        if let Some(h) = self.live.run.harnesses.iter_mut().find(|h| h.id == id) {
            h.effort = effort;
        }
        self.put_prefs(body, "Saved. New runs use this effort.", cx);
    }

    /// Check connection: the engine starts its own MCP server and reports
    /// each step it passed.
    pub fn verify_agents(&mut self, cx: &mut Context<Self>) {
        if self.live.run.verifying {
            return;
        }
        self.live.run.verifying = true;
        self.live.run.verify = None;
        let started = Instant::now();
        self.fetch(cx, || api::post("/api/agent-verify", serde_json::json!({})), move |this, reply, _| {
            this.note(&reply);
            let run = &mut this.live.run;
            run.verifying = false;
            let elapsed_ms = started.elapsed().as_millis() as i64;
            match reply {
                Ok(v) => {
                    run.verify = Some(Verify {
                        ok: api::b(&v, "ok"),
                        steps: api::arr(&v, "steps")
                            .iter()
                            .map(|s| (api::s(s, "id"), api::s(s, "state")))
                            .collect(),
                        detail: api::s(&v, "detail"),
                        log: api::s(&v, "log"),
                        ms: elapsed_ms,
                    })
                }
                Err(e) => {
                    run.verify = Some(Verify { ok: false, steps: Vec::new(), detail: e.message, ms: elapsed_ms, ..Default::default() })
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
    fn the_local_model_is_an_agent_row_with_its_dials() {
        // The reader: "Local agent cannot be chosen in agents tab" and "No
        // model and effort selection just agents tab".
        let v = json!({"harnesses": [
            {"id": "local", "label": "Local model", "llm": "small:4b",
             "llms": ["small:4b", "big:27b"], "llm_selectable": true, "efforts": []},
            {"id": "claude-code", "label": "Claude Code", "llm": "", "llms": ["a", "b"],
             "llm_selectable": true, "effort": "high", "efforts": ["low", "high"]}
        ]});
        let found = harnesses_from(&v);
        assert_eq!(found[0].id, "local");
        assert!(matches!(found[0].state, RunState::Ready));
        assert_eq!(found[0].llms, vec!["small:4b", "big:27b"]);
        assert!(found[0].efforts.is_empty());
        assert_eq!(found[1].effort, "high");
        assert_eq!(found[1].efforts, vec!["low", "high"]);
    }

    #[test]
    fn a_check_runs_on_the_local_model_when_it_is_picked_or_nothing_is() {
        let mut st = State::default();
        st.harnesses = harnesses_from(&json!({"harnesses": [
            {"id": "claude-code", "label": "Claude Code"},
            {"id": "local", "label": "Local model"}
        ]}));
        assert_eq!(st.start_harness(), "local");
        st.preferred = "claude-code".into();
        assert_eq!(st.start_harness(), "claude-code");
        // picked, but its server is down: still the pick, never a CLI
        st.preferred = "local".into();
        st.harnesses.retain(|h| h.id != "local");
        assert_eq!(st.start_harness(), "local");
    }

    #[test]
    fn recent_local_jobs_keep_their_backend_and_question_for_navigation() {
        let job = job_from(&json!({"job_id": "ask-1", "kind": "compare_ask",
            "state": "succeeded", "done": true,
            "params": {"backend": "local", "harness": "local",
                "question": "Which has the lower known risk?"}}));
        assert_eq!(job.backend, "local");
        assert_eq!(job.question, "Which has the lower known risk?");
        assert!(job.result.is_null());
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
    fn a_done_job_carries_its_answer() {
        let said = job_from(&json!({
            "job_id": "j", "kind": "research", "state": "succeeded", "done": true,
            "result": {"outcome": "kept 3 claim(s)", "note": ""}
        }));
        assert_eq!(said.answer, "kept 3 claim(s)");
        let replied = job_from(&json!({
            "job_id": "q", "kind": "compare_ask", "state": "succeeded", "done": true,
            "result": {"answer": "the reply"}
        }));
        assert_eq!(replied.answer, "the reply");
        let silent = job_from(&json!({
            "job_id": "s", "kind": "research", "state": "succeeded", "done": true,
            "result": {"outcome": "", "note": "the CLI answered without a findings list"}
        }));
        assert_eq!(silent.answer, "");
        assert_eq!(silent.no_answer_why, "the CLI answered without a findings list");
    }

    #[test]
    fn a_running_job_keeps_its_full_log_for_the_dock_drawer() {
        let log = "Starting research\nReading two sources\n";
        let job = job_from(&json!({
            "job_id": "j", "kind": "research", "state": "running",
            "done": false, "log": log,
        }));
        assert_eq!(job.log, log);
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
    fn the_log_is_read_as_the_engines_events() {
        let j = job_from(&json!({
            "job_id": "j", "kind": "research", "state": "succeeded", "done": true,
            "log": "planned the queries\nsearched one; fetched a\nread through the page reader b\nkept c\ncould not say\na tool call failed d"
        }));
        let events = j.log_events();
        let kinds: Vec<&str> = events.iter().map(|e| e.kind.as_str()).collect();
        assert_eq!(kinds, vec!["note", "search", "source", "source", "finding", "note", "problem"]);
        assert!(running(json!([])).log_events().is_empty());
    }

    #[test]
    fn the_run_says_how_long_it_took() {
        let j = job_from(&json!({
            "job_id": "j", "kind": "research", "state": "succeeded", "done": true,
            "created_at": "2026-10-04T16:48:00+00:00",
            "finished_at": "2026-10-04T16:51:12+00:00",
            "params": {"backend": "api", "model": "mistral-large"}
        }));
        assert_eq!(j.duration_word(), "ran for 3 min 12 s");
        assert_eq!(j.backend, "api");
        assert_eq!(j.model, "mistral-large");
    }

    #[test]
    fn agents_merge_by_id() {
        let mut s = State::default();
        s.harnesses = harnesses_from(&json!({"harnesses": [{"id": "claude-code", "label": "Claude Code"}]}));
        s.targets = targets_from(&json!({"targets": [
            {"id": "claude-code", "label": "Claude Code", "state": "connected", "skill": {"supported": true}},
            {"id": "codex", "label": "Codex", "state": "absent"}]}));
        let all = s.agent_entries();
        assert_eq!(all.len(), 2);
        assert!(all[0].harness.is_some() && all[0].target.is_some());
        assert!(all[1].harness.is_none());
    }

    #[test]
    fn the_readers_arrangement_of_the_agents_wins() {
        let mut s = State::default();
        s.harnesses = harnesses_from(&json!({"harnesses": [
            {"id": "claude-code", "label": "Claude Code"}, {"id": "codex", "label": "Codex"}]}));
        let ids = |s: &State| s.agent_entries().iter().map(|e| e.id.clone()).collect::<Vec<_>>();
        assert_eq!(ids(&s), vec!["claude-code", "codex"]);
        s.agent_order = vec!["codex".to_string()];
        assert_eq!(ids(&s), vec!["codex", "claude-code"]);
        s.agent_order = vec!["ghost".to_string()];
        assert_eq!(ids(&s), vec!["claude-code", "codex"]);
    }

    #[test]
    fn provider_model_lists_are_kept_on_the_agent() {
        let rows = harnesses_from(&json!({"harnesses": [{
            "id": "opencode", "label": "OpenCode", "llm": "provider/model-a",
            "llms": ["provider/model-a", "provider/model-b"],
            "llms_note": "current list", "llm_selectable": true
        }]}));
        assert_eq!(rows[0].llm, "provider/model-a");
        assert_eq!(rows[0].llms, ["provider/model-a", "provider/model-b"]);
        assert_eq!(rows[0].llms_note, "current list");
        assert!(rows[0].llm_selectable);
    }

    #[test]
    fn saved_agent_order_spans_runner_and_connection_rows() {
        let mut s = State::default();
        s.harnesses = harnesses_from(&json!({"harnesses": [
            {"id": "claude-code", "label": "Claude Code"},
            {"id": "mistral-vibe", "label": "Mistral"}
        ]}));
        s.targets = targets_from(&json!({"targets": [
            {"id": "codex", "label": "Codex", "state": "absent"}
        ]}));
        s.agent_order = vec!["codex".into(), "mistral-vibe".into()];
        let ids: Vec<String> = s.agent_entries().into_iter().map(|e| e.id).collect();
        assert_eq!(ids, ["codex", "mistral-vibe", "claude-code"]);
    }

}
