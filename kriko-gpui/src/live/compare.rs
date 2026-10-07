//! Compare: drafts, slots, board, questions and the research queue, as the
//! engine says it.
//!
//! A slot holds a saved check (a `lookup_id`). The check itself is read from
//! `/api/lookup/{id}` and, for the product it matched, `/api/subjects/{id}`;
//! the table is those two answers lined up and nothing else. Drafts, the
//! board, the questions and the queue are the engine's own rows.
//!
//! What follows the pattern of [`crate::live`]: every call goes through
//! `Kriko::fetch`, so a screen draws from this state and never waits on the
//! network.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use gpui::{BackgroundExecutor, Context};
use serde_json::json;

use crate::api::{self, Value};
use crate::app::{Kriko, Tab};
use crate::marks::Phase;

/// The most products that can be lined up at once.
pub const MAX_SLOTS: usize = 8;

// ---- what the engine holds ----

#[derive(Clone)]
pub struct HistoryItem {
    pub lookup_id: String,
    pub label: String,
    pub category: String,
    pub created_at: String,
}

#[derive(Clone)]
pub struct Draft {
    pub draft_id: String,
    pub name: String,
    pub lookup_ids: Vec<String>,
}

/// How serious the engine says a recorded risk is. Its own words are kept:
/// the chip says `high`, not a word of ours for it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Level {
    Critical,
    High,
    Medium,
    Low,
    Unrated,
}

impl Level {
    pub fn from_word(word: &str) -> Level {
        match word.trim().to_lowercase().as_str() {
            "critical" => Level::Critical,
            "high" => Level::High,
            "medium" => Level::Medium,
            "low" => Level::Low,
            _ => Level::Unrated,
        }
    }

    pub fn word(self) -> &'static str {
        match self {
            Level::Critical => "CRITICAL",
            Level::High => "HIGH",
            Level::Medium => "MEDIUM",
            Level::Low => "LOW",
            Level::Unrated => "UNRATED",
        }
    }

    /// Critical and high are the ones a shopper should not skim past.
    pub fn is_grave(self) -> bool {
        matches!(self, Level::Critical | Level::High)
    }
}

#[derive(Clone)]
pub struct Spec {
    pub label: String,
    /// The value and its unit, as the catalog states them.
    pub value: String,
    /// The page the figure was read from, or "" when the catalog names none.
    pub source: String,
}

#[derive(Clone)]
pub struct Risk {
    pub title: String,
    pub body: String,
    pub level: Level,
    pub disputed: bool,
    pub sources: Vec<String>,
}

impl Risk {
    /// BACKED when sources stand behind it, DISPUTED when the engine says
    /// they disagree, None when it carries none.
    pub fn backed(&self) -> Option<bool> {
        if self.disputed {
            Some(false)
        } else if !self.sources.is_empty() {
            Some(true)
        } else {
            None
        }
    }
}

/// One saved check, read for the table.
#[derive(Clone)]
pub struct Check {
    pub name: String,
    pub category: String,
    pub specs: Vec<Spec>,
    pub risks: Vec<Risk>,
}

impl Check {
    /// How many sources stand behind everything this column holds.
    pub fn sources(&self) -> usize {
        self.specs.iter().filter(|s| !s.source.is_empty()).count()
            + self.risks.iter().map(|r| r.sources.len()).sum::<usize>()
    }
}

#[derive(Clone)]
pub enum Loaded {
    Loading,
    Ready(Check),
    Missing(String),
}

#[derive(Clone)]
pub struct Note {
    pub x: f32,
    pub y: f32,
    pub text: String,
}

#[derive(Clone)]
pub struct Question {
    pub question_id: String,
    pub text: String,
    pub answer: Option<String>,
    pub job_id: String,
    pub asked_at: String,
}

#[derive(Clone, Default)]
pub struct QuestionRun {
    pub state: String,
    pub progress: f32,
    pub message: String,
    pub model: String,
    pub tokens_used: Option<u64>,
    pub tokens_in: Option<u64>,
    pub tokens_out: Option<u64>,
    pub brief_chars: Option<u64>,
    pub saved_checks: Vec<(String, usize)>,
    pub no_web_search: bool,
    pub steps: Vec<String>,
}

impl QuestionRun {
    fn from_job(job: &Value) -> Self {
        let result = job.get("result").unwrap_or(&Value::Null);
        Self {
            state: api::s(job, "state"),
            progress: api::n(job, "progress").unwrap_or(0.0) as f32,
            message: api::s(job, "message"),
            model: api::s(result, "model"),
            tokens_used: api::n(result, "tokens_used").map(|n| n as u64),
            tokens_in: api::n(result, "tokens_in").map(|n| n as u64),
            tokens_out: api::n(result, "tokens_out").map(|n| n as u64),
            brief_chars: api::n(result, "brief_chars").map(|n| n as u64),
            saved_checks: api::arr(result, "saved_checks").iter()
                .map(|v| (api::s(v, "name"), api::n(v, "risks").unwrap_or(0.0) as usize))
                .collect(),
            no_web_search: api::n(result, "web_searches") == Some(0.0),
            steps: api::s(job, "log").lines()
                .filter(|line| line.starts_with("local comparison:")
                    || line.starts_with("comparison brief:")
                    || line.ends_with("known risk(s)"))
                .rev().take(6).map(str::to_string).collect::<Vec<_>>()
                .into_iter().rev().collect(),
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum QState {
    Waiting,
    Researching,
    Done,
}

#[derive(Clone)]
pub struct QItem {
    pub queue_id: String,
    pub url: String,
    pub name: String,
    pub lookup_id: String,
    pub origin: String,
    pub state: QState,
    pub added_at: String,
}

impl QItem {
    pub fn title(&self) -> String {
        if !self.name.trim().is_empty() {
            self.name.trim().to_string()
        } else if !self.origin.is_empty() {
            self.origin.clone()
        } else {
            self.url.clone()
        }
    }
}

/// What the window knows about one queued product while it is being worked
/// on or after it was passed over.
#[derive(Clone, Default)]
pub struct QRun {
    /// 0..=100.
    pub progress: f32,
    pub phase: Option<Phase>,
    /// What the agent is doing, in the words the engine's feed gave.
    pub line: String,
    /// Why it was passed over ("not in your catalogs", a failure).
    pub note: Option<String>,
    /// How many claims the fresh answer holds, once done.
    pub claims: Option<usize>,
}

#[derive(Default)]
pub struct State {
    pub loaded: bool,
    /// The engine's last word on a compare action that failed, shown under
    /// the drafts row until the next one succeeds.
    pub say: Option<String>,

    pub history: Vec<HistoryItem>,
    pub history_loaded: bool,
    pub drafts: Vec<Draft>,
    pub drafts_max: usize,
    pub drafts_loaded: bool,
    pub draft: Option<String>,

    pub slots: Vec<Option<String>>,
    pub picker: Option<usize>,
    pub section: usize,
    pub detail: Option<(usize, usize)>,
    pub scroll: f32,
    pub dragging: bool,
    pub checks: HashMap<String, Loaded>,

    pub board_open: bool,
    pub board_tool: usize,
    pub strokes: Vec<Vec<(f32, f32)>>,
    pub stroke_current: Vec<(f32, f32)>,
    pub drawing: bool,
    pub notes: Vec<Note>,
    pub note_open: Option<usize>,
    /// Bumped by every change to the board; a save waits to see it settle.
    pub board_gen: u64,

    /// Rows pinned as preferred, by draft ("" while there is no draft yet).
    pub marks: HashMap<String, Vec<String>>,

    pub questions: Vec<Question>,
    pub asking: bool,
    pub watching: HashSet<String>,
    /// question_id -> why its job did not answer.
    pub failed: HashMap<String, String>,
    /// Durable job detail, including usage when the model server reports it.
    pub question_runs: HashMap<String, QuestionRun>,
    /// Completed jobs fetched once when reopening a draft.
    pub question_jobs_loaded: HashSet<String>,

    /// (id, label) of every agent that can answer or research.
    pub harnesses: Vec<(String, String)>,
    pub harness: String,
    pub queue_harness: String,

    pub queue: Vec<QItem>,
    pub queue_max: usize,
    pub queue_loaded: bool,
    pub queue_running: bool,
    pub queue_auto: bool,
    pub queue_run: HashMap<String, QRun>,
    pub poller: bool,
}

// ---- reading the engine's JSON ----

fn history_from(v: &Value) -> HistoryItem {
    HistoryItem {
        lookup_id: api::s(v, "lookup_id"),
        label: api::s(v, "label"),
        category: api::s(v, "category"),
        created_at: api::s(v, "created_at"),
    }
}

fn draft_from(v: &Value) -> Draft {
    Draft {
        draft_id: api::s(v, "draft_id"),
        name: api::s(v, "name"),
        lookup_ids: api::arr(v, "lookup_ids")
            .iter()
            .filter_map(|x| x.as_str().map(String::from))
            .collect(),
    }
}

fn question_from(v: &Value) -> Question {
    let answer = v.get("answer").and_then(|a| a.as_str()).map(String::from);
    Question {
        question_id: api::s(v, "question_id"),
        text: api::s(v, "question"),
        answer: answer.filter(|a| !a.trim().is_empty()),
        job_id: api::s(v, "job_id"),
        asked_at: api::s(v, "asked_at"),
    }
}

fn queued_from(v: &Value) -> QItem {
    QItem {
        queue_id: api::s(v, "queue_id"),
        url: api::s(v, "url"),
        name: api::s(v, "name"),
        lookup_id: api::s(v, "lookup_id"),
        origin: api::s(v, "origin"),
        state: match api::s(v, "state").as_str() {
            "researching" => QState::Researching,
            "done" => QState::Done,
            _ => QState::Waiting,
        },
        added_at: api::s(v, "added_at"),
    }
}

/// The product a saved check matched: the subject owning the most claims,
/// the first one when none owns any. `subjects` is a list of objects in a
/// stored answer and a list of ids in a fresh one.
fn matched_subject(response: &Value) -> Option<String> {
    let mut best: Option<(String, f64)> = None;
    for s in api::arr(response, "subjects") {
        let (id, claims) = match s {
            Value::String(id) => (id.clone(), 0.0),
            other => (api::s(other, "subject_id"), api::n(other, "claims").unwrap_or(0.0)),
        };
        if id.is_empty() {
            continue;
        }
        if best.as_ref().map(|(_, c)| claims > *c).unwrap_or(true) {
            best = Some((id, claims));
        }
    }
    best.map(|(id, _)| id).or_else(|| {
        api::arr(response, "claims")
            .first()
            .map(|c| api::s(c, "subject_id"))
            .filter(|id| !id.is_empty())
    })
}

fn risk_from(c: &Value) -> Risk {
    Risk {
        title: api::s(c, "title"),
        body: api::s(c, "body"),
        level: Level::from_word(&api::s(c, "severity")),
        disputed: api::b(c, "disputed"),
        sources: api::arr(c, "sources")
            .iter()
            .map(|s| {
                let domain = api::s(s, "domain");
                if domain.is_empty() { api::s(s, "url") } else { domain }
            })
            .collect(),
    }
}

/// One saved check, read for the table: blocking, run on the background
/// executor.
fn load_check(lookup_id: &str, category: &str) -> Result<Check, String> {
    let stored = api::get(&format!("/api/lookup/{}", api::seg(lookup_id))).map_err(|e| e.message)?;
    let response = stored.get("response").cloned().unwrap_or(Value::Null);
    let risks = api::arr(&response, "claims")
        .iter()
        .map(risk_from)
        .filter(|r| !r.title.is_empty())
        .collect();
    let mut specs = Vec::new();
    if let Some(subject_id) = matched_subject(&response) {
        // a subject that cannot be read leaves the column without
        // specifications, never without its risks
        if let Ok(subject) = api::get(&format!("/api/subjects/{}", api::seg(&subject_id))) {
            for a in api::arr(&subject, "attributes") {
                let value = api::s(a, "value_text");
                if api::b(a, "is_identity") || value.trim().is_empty() {
                    continue;
                }
                let unit = api::s(a, "unit");
                let label = api::s(a, "label");
                specs.push(Spec {
                    label: if label.is_empty() { api::s(a, "key") } else { label },
                    value: if unit.is_empty() { value } else { format!("{value} {unit}") },
                    source: api::s(a, "source_url"),
                });
            }
        }
    }
    Ok(Check {
        name: api::s(&stored, "label"),
        category: category.to_string(),
        specs,
        risks,
    })
}

// ---- time ----

/// Seconds since the epoch of an engine timestamp: UTC, with or without an
/// offset on the end.
fn epoch(ts: &str) -> Option<i64> {
    let b = ts.as_bytes();
    if b.len() < 19 {
        return None;
    }
    let num = |a: usize, z: usize| ts.get(a..z)?.parse::<i64>().ok();
    let (y, m, d) = (num(0, 4)?, num(5, 7)?, num(8, 10)?);
    let (h, mi, s) = (num(11, 13)?, num(14, 16)?, num(17, 19)?);
    // days from civil (Howard Hinnant)
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146097 + doe - 719468;
    Some(days * 86400 + h * 3600 + mi * 60 + s)
}

/// "3 min ago", from an engine timestamp.
pub fn ago(ts: &str) -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let Some(then) = epoch(ts) else { return String::new() };
    let secs = (now - then).max(0);
    match secs {
        0..=59 => "just now".to_string(),
        60..=3599 => format!("{} min ago", secs / 60),
        3600..=86399 => format!("{} h ago", secs / 3600),
        _ => format!("{} d ago", secs / 86400),
    }
}

// ---- the lined-up table ----

pub struct SpecRow {
    pub label: String,
    pub cells: Vec<Option<Spec>>,
    pub differs: bool,
}

pub struct RiskRow {
    pub title: String,
    pub cells: Vec<Option<Risk>>,
}

/// One row per label any column states, first-seen order; DIFFERS when the
/// columns that state it do not agree.
pub fn spec_rows(columns: &[Option<&Check>]) -> Vec<SpecRow> {
    let mut labels: Vec<String> = Vec::new();
    for c in columns.iter().flatten() {
        for s in &c.specs {
            if !labels.contains(&s.label) {
                labels.push(s.label.clone());
            }
        }
    }
    labels
        .into_iter()
        .map(|label| {
            let cells: Vec<Option<Spec>> = columns
                .iter()
                .map(|c| c.and_then(|c| c.specs.iter().find(|s| s.label == label).cloned()))
                .collect();
            let values: Vec<&str> = cells.iter().flatten().map(|c| c.value.as_str()).collect();
            let differs = values.windows(2).any(|w| w[0] != w[1]);
            SpecRow { label, cells, differs }
        })
        .collect()
}

/// One row per risk title any column carries, matched across columns by
/// title.
pub fn risk_rows(columns: &[Option<&Check>]) -> Vec<RiskRow> {
    let mut titles: Vec<String> = Vec::new();
    for c in columns.iter().flatten() {
        for r in &c.risks {
            if !titles.contains(&r.title) {
                titles.push(r.title.clone());
            }
        }
    }
    titles
        .into_iter()
        .map(|title| {
            let cells = columns
                .iter()
                .map(|c| c.and_then(|c| c.risks.iter().find(|r| r.title == title).cloned()))
                .collect();
            RiskRow { title, cells }
        })
        .collect()
}

/// The answer, said from the lined-up data and nothing else: what each
/// column records, where they differ. Never a verdict.
pub fn answer_lines(columns: &[Option<&Check>]) -> Vec<String> {
    let ready: Vec<&Check> = columns.iter().flatten().copied().collect();
    if ready.len() < 2 {
        return Vec::new();
    }
    let mut lines = Vec::new();
    let grave: Vec<usize> = ready
        .iter()
        .map(|c| c.risks.iter().filter(|r| r.level.is_grave()).count())
        .collect();
    let fewest = *grave.iter().min().unwrap_or(&0);
    let most = *grave.iter().max().unwrap_or(&0);
    let counts = ready
        .iter()
        .zip(&grave)
        .map(|(c, n)| format!("{} {}", c.name, n))
        .collect::<Vec<_>>()
        .join(", ");
    if fewest == most {
        lines.push(format!("High-severity risks on record: {counts}. The same for each."));
    } else {
        let names: Vec<&str> = ready
            .iter()
            .zip(&grave)
            .filter(|(_, n)| **n == fewest)
            .map(|(c, _)| c.name.as_str())
            .collect();
        lines.push(format!(
            "Fewest high-severity risks on record: {} ({fewest}). All of them: {counts}.",
            names.join(" and ")
        ));
    }
    let disputed: Vec<String> = ready
        .iter()
        .filter_map(|c| {
            let n = c.risks.iter().filter(|r| r.disputed).count();
            (n > 0).then(|| format!("{} {}", c.name, n))
        })
        .collect();
    if !disputed.is_empty() {
        lines.push(format!("Disputed by their sources: {}.", disputed.join(", ")));
    }
    let specs = spec_rows(columns);
    let differing = specs.iter().filter(|r| r.differs).count();
    if !specs.is_empty() {
        lines.push(format!(
            "{} of {} specifications are stated differently between them.",
            differing,
            specs.len()
        ));
    }
    let shared = risk_rows(columns)
        .iter()
        .filter(|r| r.cells.iter().flatten().count() > 1)
        .count();
    if shared > 0 {
        lines.push(format!("{shared} risk(s) are recorded for more than one of them."));
    }
    lines
}

// ---- running things on the background executor ----

async fn bg<T: Send + 'static>(ex: &BackgroundExecutor, work: impl FnOnce() -> T + Send + 'static) -> T {
    ex.spawn(async move { work() }).await
}

/// What the queue's agent is doing, from the job's newest feed event.
fn phase_of(job: &Value) -> Phase {
    if api::n(job, "progress").unwrap_or(0.0) >= 0.85 {
        return Phase::Writing;
    }
    match api::arr(job, "feed").last().map(|e| api::s(e, "kind")).as_deref() {
        Some("source") | Some("search") => Phase::Reading,
        Some("finding") => Phase::Writing,
        _ => Phase::Thinking,
    }
}

fn doing_of(job: &Value) -> String {
    let last = api::arr(job, "feed").last().map(|e| api::s(e, "text")).unwrap_or_default();
    if !last.is_empty() {
        last
    } else if !api::s(job, "message").is_empty() {
        api::s(job, "message")
    } else {
        "Starting".to_string()
    }
}

/// The product a queued row stands for, and how to ask about it afterwards.
struct Target {
    subject_id: String,
    pack_id: String,
    kind: String,
    identity: Value,
}

/// A queued row's subject: the product its stored answer matched, else what
/// the installed catalogs find for its name. `Err` is why there is none.
fn resolve_target(item: &QItem) -> Result<Target, String> {
    let mut subject_id = String::new();
    if !item.lookup_id.is_empty() {
        if let Ok(stored) = api::get(&format!("/api/lookup/{}", api::seg(&item.lookup_id))) {
            let response = stored.get("response").cloned().unwrap_or(Value::Null);
            subject_id = matched_subject(&response).unwrap_or_default();
        }
    }
    if subject_id.is_empty() {
        let name = item.name.trim();
        if name.is_empty() {
            return Err("not in your catalogs".to_string());
        }
        let found = api::get(&format!("/api/search?q={}&limit=5", api::seg(name)))
            .map_err(|e| e.message)?;
        subject_id = api::arr(&found, "items")
            .first()
            .map(|i| api::s(i, "subject_id"))
            .unwrap_or_default();
    }
    if subject_id.is_empty() {
        return Err("not in your catalogs".to_string());
    }
    let subject = api::get(&format!("/api/subjects/{}", api::seg(&subject_id)))
        .map_err(|e| e.message)?;
    let mut identity = serde_json::Map::new();
    for a in api::arr(&subject, "attributes") {
        if api::b(a, "is_identity") {
            identity.insert(api::s(a, "key"), Value::String(api::s(a, "value_text")));
        }
    }
    Ok(Target {
        subject_id,
        pack_id: api::s(&subject, "pack_id"),
        kind: api::s(&subject, "kind"),
        identity: Value::Object(identity),
    })
}

fn say_error<T>(this: &mut Kriko, reply: &Result<T, api::ApiError>) {
    this.note(reply);
    this.live.compare.say = reply.as_ref().err().map(|e| e.message.clone());
}

impl Kriko {
    /// Everything Compare holds, asked for when the engine first answers.
    pub fn refresh_compare(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/history?limit=50"), |this, reply, cx| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.compare.history = api::arr(&v, "items").iter().map(history_from).collect();
                this.live.compare.history_loaded = true;
                // columns read before the history arrived learn their category
                this.ensure_checks(cx);
            }
        });
        self.fetch(
            cx,
            || (api::get("/api/prefs"), api::get("/api/settings")),
            |this, (prefs, settings), _| {
                if let Ok(p) = prefs {
                    let unusable: Vec<String> = api::arr(&p, "unusable")
                        .iter()
                        .map(|u| api::s(u, "id"))
                        .collect();
                    this.live.compare.harnesses = api::arr(&p, "harnesses")
                        .iter()
                        .map(|h| (api::s(h, "id"), api::s(h, "label")))
                        .filter(|(id, _)| !unusable.contains(id))
                        .collect();
                    let preferred = p
                        .get("chosen")
                        .map(|c| api::s(c, "preferred_harness"))
                        .unwrap_or_default();
                    let first = this
                        .live
                        .compare
                        .harnesses
                        .first()
                        .map(|(id, _)| id.clone())
                        .unwrap_or_default();
                    let pick = if this.live.compare.harnesses.iter().any(|(id, _)| *id == preferred) {
                        preferred
                    } else {
                        first
                    };
                    if this.live.compare.harness.is_empty() {
                        this.live.compare.harness = pick.clone();
                    }
                    if this.live.compare.queue_harness.is_empty() {
                        this.live.compare.queue_harness = pick;
                    }
                }
                if let Ok(s) = settings {
                    this.live.compare.queue_auto =
                        s.get("compare.queue_auto").and_then(|v| v.as_bool()).unwrap_or(true);
                    if let Some(map) = s.as_object() {
                        for (key, value) in map {
                            if let Some(id) = key.strip_prefix("compare.marks.") {
                                let keys = value
                                    .as_array()
                                    .map(|a| a.iter().filter_map(|k| k.as_str().map(String::from)).collect())
                                    .unwrap_or_default();
                                this.live.compare.marks.insert(id.to_string(), keys);
                            }
                        }
                    }
                } else {
                    this.live.compare.queue_auto = true;
                }
            },
        );
        self.load_drafts(true, cx);
        self.load_queue(cx);
        // a product queued from the browser extension appears here within
        // seconds, with Compare open
        if !self.live.compare.poller {
            self.live.compare.poller = true;
            cx.spawn(async move |this, cx| loop {
                cx.background_executor().timer(Duration::from_secs(5)).await;
                let alive = this
                    .update(cx, |this, cx| {
                        if this.tab == Tab::Compare && !this.live.compare.queue_running {
                            this.load_queue(cx);
                        }
                    })
                    .is_ok();
                if !alive {
                    break;
                }
            })
            .detach();
        }
    }

    // ---- drafts ----

    /// Reads the saved drafts; on the first read, opens the first one.
    pub fn load_drafts(&mut self, open_first: bool, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/compare-drafts"), move |this, reply, cx| {
            this.note(&reply);
            if let Ok(v) = reply {
                let c = &mut this.live.compare;
                c.drafts = api::arr(&v, "items").iter().map(draft_from).collect();
                c.drafts_max = api::n(&v, "max").unwrap_or(0.0) as usize;
                c.drafts_loaded = true;
                c.loaded = true;
                let keep = c.draft.clone().filter(|id| c.drafts.iter().any(|d| d.draft_id == *id));
                if keep.is_none() {
                    c.draft = None;
                }
                if open_first && c.draft.is_none() {
                    if let Some(first) = c.drafts.first().map(|d| d.draft_id.clone()) {
                        this.select_draft(&first, cx);
                    }
                }
            }
        });
    }

    /// Opens a saved draft: its checks fill the slots, and its board,
    /// questions and pinned rows load. The one entry other screens use.
    pub fn select_draft(&mut self, draft_id: &str, cx: &mut Context<Self>) {
        let Some(draft) = self.live.compare.drafts.iter().find(|d| d.draft_id == draft_id).cloned()
        else {
            return;
        };
        let c = &mut self.live.compare;
        c.draft = Some(draft.draft_id.clone());
        c.slots = draft.lookup_ids.iter().take(MAX_SLOTS).cloned().map(Some).collect();
        c.detail = None;
        c.picker = None;
        c.strokes.clear();
        c.notes.clear();
        c.note_open = None;
        c.questions.clear();
        c.say = None;
        self.ensure_checks(cx);
        self.load_board(draft.draft_id.clone(), cx);
        self.load_questions(draft.draft_id, cx);
    }

    /// The saved checks now in the slots, in order.
    pub fn slot_ids(&self) -> Vec<String> {
        self.live.compare.slots.iter().flatten().cloned().collect()
    }

    /// Reads every slotted check that has not been read yet.
    pub fn ensure_checks(&mut self, cx: &mut Context<Self>) {
        let wanted: Vec<String> = self
            .slot_ids()
            .into_iter()
            .filter(|id| !self.live.compare.checks.contains_key(id))
            .collect();
        for id in wanted {
            self.live.compare.checks.insert(id.clone(), Loaded::Loading);
            let category = self
                .live
                .compare
                .history
                .iter()
                .find(|h| h.lookup_id == id)
                .map(|h| h.category.clone())
                .unwrap_or_default();
            let key = id.clone();
            self.fetch(cx, move || load_check(&id, &category), move |this, reply, _| {
                let loaded = match reply {
                    Ok(check) => Loaded::Ready(check),
                    Err(why) => Loaded::Missing(why),
                };
                this.live.compare.checks.insert(key, loaded);
            });
        }
    }

    pub fn assign_slot(&mut self, i: usize, lookup_id: String, cx: &mut Context<Self>) {
        let c = &mut self.live.compare;
        while c.slots.len() <= i {
            c.slots.push(None);
        }
        c.slots[i] = Some(lookup_id);
        c.picker = None;
        c.detail = None;
        self.ensure_checks(cx);
    }

    pub fn clear_slot(&mut self, i: usize) {
        let c = &mut self.live.compare;
        if i < c.slots.len() {
            c.slots[i] = None;
        }
        c.detail = None;
    }

    /// Whether the slots differ from what the open draft holds.
    pub fn draft_unsaved(&self) -> bool {
        let c = &self.live.compare;
        match c.draft.as_ref().and_then(|id| c.drafts.iter().find(|d| d.draft_id == *id)) {
            Some(d) => d.lookup_ids != self.slot_ids(),
            None => !self.slot_ids().is_empty(),
        }
    }

    fn next_draft_name(&self, stem: &str) -> String {
        let c = &self.live.compare;
        let mut n = c.drafts.len() + 1;
        loop {
            let name = format!("{stem} {n}");
            if !c.drafts.iter().any(|d| d.name == name) {
                return name;
            }
            n += 1;
        }
    }

    /// Runs `then` with the open draft's id, saving the slots as a new
    /// draft first when there is none.
    fn with_draft(
        &mut self,
        cx: &mut Context<Self>,
        then: impl FnOnce(&mut Kriko, String, &mut Context<Kriko>) + 'static,
    ) {
        if let Some(id) = self.live.compare.draft.clone() {
            then(self, id, cx);
            return;
        }
        let name = self.next_draft_name("Draft");
        let ids = self.slot_ids();
        self.fetch(
            cx,
            move || api::post("/api/compare-drafts", json!({"name": name, "lookup_ids": ids})),
            move |this, reply, cx| {
                say_error(this, &reply);
                if let Ok(v) = reply {
                    let d = draft_from(&v);
                    let id = d.draft_id.clone();
                    let c = &mut this.live.compare;
                    c.drafts.push(d);
                    c.draft = Some(id.clone());
                    // rows pinned before there was a draft belong to it now
                    if let Some(pinned) = c.marks.remove("") {
                        if !pinned.is_empty() {
                            c.marks.insert(id.clone(), pinned);
                            this.save_marks(&id, cx);
                        }
                    }
                    then(this, id, cx);
                }
            },
        );
    }

    /// New: the slots as they stand, kept as a fresh draft.
    pub fn new_draft(&mut self, cx: &mut Context<Self>) {
        let name = self.next_draft_name("Draft");
        let ids = self.slot_ids();
        self.fetch(
            cx,
            move || api::post("/api/compare-drafts", json!({"name": name, "lookup_ids": ids})),
            |this, reply, cx| {
                say_error(this, &reply);
                if let Ok(v) = reply {
                    let d = draft_from(&v);
                    let id = d.draft_id.clone();
                    this.live.compare.drafts.push(d);
                    this.live.compare.draft = Some(id.clone());
                    this.load_board(id.clone(), cx);
                    this.load_questions(id, cx);
                }
            },
        );
    }

    /// Save: the open draft takes the slots; with no draft open it is New.
    pub fn save_draft(&mut self, cx: &mut Context<Self>) {
        let Some(id) = self.live.compare.draft.clone() else {
            self.new_draft(cx);
            return;
        };
        let name = self
            .live
            .compare
            .drafts
            .iter()
            .find(|d| d.draft_id == id)
            .map(|d| d.name.clone())
            .unwrap_or_default();
        let ids = self.slot_ids();
        self.fetch(
            cx,
            move || {
                api::put(
                    &format!("/api/compare-drafts/{}", api::seg(&id)),
                    json!({"name": name, "lookup_ids": ids}),
                )
            },
            |this, reply, _| {
                say_error(this, &reply);
                if let Ok(v) = reply {
                    let saved = draft_from(&v);
                    if let Some(d) = this
                        .live
                        .compare
                        .drafts
                        .iter_mut()
                        .find(|d| d.draft_id == saved.draft_id)
                    {
                        *d = saved;
                    }
                }
            },
        );
    }

    pub fn delete_draft(&mut self, cx: &mut Context<Self>) {
        let Some(id) = self.live.compare.draft.clone() else { return };
        self.fetch(
            cx,
            {
                let id = id.clone();
                move || api::delete(&format!("/api/compare-drafts/{}", api::seg(&id)))
            },
            move |this, reply, cx| {
                say_error(this, &reply);
                if reply.is_ok() {
                    let c = &mut this.live.compare;
                    c.drafts.retain(|d| d.draft_id != id);
                    c.draft = None;
                    c.marks.remove(&id);
                    c.strokes.clear();
                    c.notes.clear();
                    c.questions.clear();
                    c.slots.clear();
                    if let Some(first) = c.drafts.first().map(|d| d.draft_id.clone()) {
                        this.select_draft(&first, cx);
                    }
                }
            },
        );
    }

    // ---- marks ----

    pub fn marks_now(&self) -> &[String] {
        let c = &self.live.compare;
        c.marks
            .get(c.draft.as_deref().unwrap_or(""))
            .map(|v| v.as_slice())
            .unwrap_or(&[])
    }

    pub fn toggle_mark(&mut self, key: String, cx: &mut Context<Self>) {
        let id = self.live.compare.draft.clone().unwrap_or_default();
        let list = self.live.compare.marks.entry(id.clone()).or_default();
        if let Some(at) = list.iter().position(|k| *k == key) {
            list.remove(at);
        } else {
            list.push(key);
        }
        if !id.is_empty() {
            self.save_marks(&id, cx);
        }
    }

    fn save_marks(&mut self, draft_id: &str, cx: &mut Context<Self>) {
        let keys = self.live.compare.marks.get(draft_id).cloned().unwrap_or_default();
        let setting = format!("compare.marks.{draft_id}");
        self.fetch(
            cx,
            move || api::post("/api/settings", json!({"values": {setting: keys}})),
            |this, reply, _| this.note(&reply),
        );
    }

    // ---- the board ----

    fn load_board(&mut self, draft_id: String, cx: &mut Context<Self>) {
        let id = draft_id.clone();
        self.fetch(
            cx,
            move || api::get(&format!("/api/compare-drafts/{}/board", api::seg(&id))),
            move |this, reply, _| {
                this.note(&reply);
                let c = &mut this.live.compare;
                if c.draft.as_deref() != Some(draft_id.as_str()) {
                    return;
                }
                if let Ok(v) = reply {
                    c.strokes = api::arr(&v, "strokes")
                        .iter()
                        .map(|s| {
                            s.as_array()
                                .map(|pts| {
                                    pts.iter()
                                        .map(|p| {
                                            (
                                                api::n(p, "x").unwrap_or(0.0) as f32,
                                                api::n(p, "y").unwrap_or(0.0) as f32,
                                            )
                                        })
                                        .collect()
                                })
                                .unwrap_or_default()
                        })
                        .collect();
                    c.notes = api::arr(&v, "notes")
                        .iter()
                        .map(|n| Note {
                            x: api::n(n, "x").unwrap_or(0.0) as f32,
                            y: api::n(n, "y").unwrap_or(0.0) as f32,
                            text: api::s(n, "text"),
                        })
                        .collect();
                    c.note_open = None;
                }
            },
        );
    }

    /// Saves the board once it has settled for a moment: after each stroke,
    /// note, undo or clear, and never once per mouse move.
    pub fn save_board_soon(&mut self, cx: &mut Context<Self>) {
        self.live.compare.board_gen += 1;
        let gen = self.live.compare.board_gen;
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(600)).await;
            let _ = this.update(cx, |this, cx| {
                if this.live.compare.board_gen == gen {
                    this.save_board_now(cx);
                }
            });
        })
        .detach();
    }

    /// Writes the board to the open draft, saving the slots as a draft first
    /// when there is none.
    pub fn save_board_now(&mut self, cx: &mut Context<Self>) {
        self.with_draft(cx, |this, id, cx| {
            let c = &this.live.compare;
            let strokes: Vec<Value> = c
                .strokes
                .iter()
                .map(|s| {
                    Value::Array(
                        s.iter()
                            .map(|(x, y)| json!({"x": round4(*x), "y": round4(*y)}))
                            .collect(),
                    )
                })
                .collect();
            let notes: Vec<Value> = c
                .notes
                .iter()
                .filter(|n| !n.text.trim().is_empty())
                .map(|n| json!({"x": round4(n.x), "y": round4(n.y), "text": n.text}))
                .collect();
            this.fetch(
                cx,
                move || {
                    api::put(
                        &format!("/api/compare-drafts/{}/board", api::seg(&id)),
                        json!({"strokes": strokes, "notes": notes}),
                    )
                },
                |this, reply, _| say_error(this, &reply),
            );
        });
    }

    /// Enter on a note's field: the note keeps its text, and the board saves.
    pub fn commit_board_note(&mut self, cx: &mut Context<Self>) {
        let text = self.compare_note_input.value.trim().to_string();
        let c = &mut self.live.compare;
        if let Some(open) = c.note_open {
            if open < c.notes.len() {
                c.notes[open].text = text;
            }
            c.note_open = None;
        }
        self.compare_note_input.value.clear();
        self.save_board_soon(cx);
    }

    // ---- questions ----

    pub fn load_questions(&mut self, draft_id: String, cx: &mut Context<Self>) {
        let id = draft_id.clone();
        self.fetch(
            cx,
            move || api::get(&format!("/api/compare-drafts/{}/questions", api::seg(&id))),
            move |this, reply, cx| {
                this.note(&reply);
                if this.live.compare.draft.as_deref() != Some(draft_id.as_str()) {
                    return;
                }
                if let Ok(v) = reply {
                    let list: Vec<Question> = api::arr(&v, "items").iter().map(question_from).collect();
                    this.live.compare.questions = list.clone();
                    for q in list {
                        if q.answer.is_none() && !q.job_id.is_empty()
                            && !this.live.compare.question_jobs_loaded.contains(&q.job_id) {
                            this.watch_question(draft_id.clone(), q, cx);
                        } else if !q.job_id.is_empty()
                            && this.live.compare.question_jobs_loaded.insert(q.job_id.clone()) {
                            let path = format!("/api/jobs/{}", api::seg(&q.job_id));
                            let jid = q.job_id.clone();
                            this.fetch(cx, move || api::get(&path), move |this, reply, _| {
                                if let Ok(job) = reply {
                                    this.live.compare.question_runs.insert(jid, QuestionRun::from_job(&job));
                                } else {
                                    this.live.compare.question_jobs_loaded.remove(&jid);
                                }
                            });
                        }
                    }
                }
            },
        );
    }

    /// Follows an unanswered question's job until it is done, then reads the
    /// answer the engine stored beside the draft.
    fn watch_question(&mut self, draft_id: String, q: Question, cx: &mut Context<Self>) {
        if !self.live.compare.watching.insert(q.job_id.clone()) {
            return;
        }
        cx.spawn(async move |this, cx| loop {
            cx.background_executor().timer(Duration::from_millis(700)).await;
            let path = format!("/api/jobs/{}", api::seg(&q.job_id));
            let ex = cx.background_executor().clone();
            let reply = bg(&ex, move || api::get(&path)).await;
            let (draft, qid, jid) = (draft_id.clone(), q.question_id.clone(), q.job_id.clone());
            let finished = this
                .update(cx, |this, cx| match reply {
                    Ok(job) => {
                        this.live.compare.question_runs.insert(jid.clone(), QuestionRun::from_job(&job));
                        if api::b(&job, "done") {
                            if api::s(&job, "state") != "succeeded" {
                                this.live.compare.failed.insert(qid, api::s(&job, "message"));
                            }
                            this.live.compare.question_jobs_loaded.insert(jid.clone());
                            this.live.compare.watching.remove(&jid);
                            this.load_questions(draft, cx);
                            true
                        } else {
                            cx.notify();
                            false
                        }
                    }
                    Err(e) => {
                        this.live.compare.failed.insert(qid, e.message);
                        this.live.compare.watching.remove(&jid);
                        true
                    }
                })
                .unwrap_or(true);
            if finished {
                break;
            }
        })
        .detach();
    }

    /// Ask: the question goes to the open draft (saved first, with the
    /// slots as they stand, so the agent reads what is on screen).
    pub fn ask_compare_question(&mut self, cx: &mut Context<Self>) {
        let text = self.compare_question_input.value.trim().to_string();
        if text.is_empty() || self.live.compare.asking {
            return;
        }
        if self.slot_ids().len() < 2 {
            self.live.compare.say = Some("Line up at least two saved checks to ask about them.".into());
            return;
        }
        self.live.compare.asking = true;
        self.live.compare.say = None;
        let harness = if self.live.compare.harness.is_empty()
            && self.live.local.plane.as_ref().is_some_and(|p| p.ready)
        {
            "local".to_string()
        } else {
            self.live.compare.harness.clone()
        };
        let backend = if harness == "local" { "local" } else { "harness" };
        let ids = self.slot_ids();
        self.with_draft(cx, move |this, id, cx| {
            // the draft holds the slots as they are now
            let name = this
                .live
                .compare
                .drafts
                .iter()
                .find(|d| d.draft_id == id)
                .map(|d| d.name.clone())
                .unwrap_or_default();
            let draft = id.clone();
            this.fetch(
                cx,
                move || {
                    let saved = api::put(
                        &format!("/api/compare-drafts/{}", api::seg(&id)),
                        json!({"name": name, "lookup_ids": ids}),
                    );
                    saved.and_then(|_| {
                        api::post(
                            &format!("/api/compare-drafts/{}/questions", api::seg(&id)),
                            json!({"question": text, "harness": harness, "backend": backend}),
                        )
                    })
                },
                move |this, reply, cx| {
                    this.live.compare.asking = false;
                    say_error(this, &reply);
                    if reply.is_ok() {
                        this.compare_question_input.value.clear();
                        this.load_drafts(false, cx);
                        this.load_questions(draft, cx);
                    }
                },
            );
        });
    }

    // ---- the research queue ----

    pub fn load_queue(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/queue"), |this, reply, cx| {
            this.note(&reply);
            if let Ok(v) = reply {
                let c = &mut this.live.compare;
                let mut items: Vec<QItem> = api::arr(&v, "items").iter().map(queued_from).collect();
                // a row the engine says is researching, with nothing of ours
                // working on it, is one an earlier run left behind
                if !c.queue_running {
                    for item in items.iter_mut().filter(|i| i.state == QState::Researching) {
                        item.state = QState::Waiting;
                        let id = item.queue_id.clone();
                        this.fetch(
                            cx,
                            move || api::request("PATCH", &format!("/api/queue/{}", api::seg(&id)), Some(json!({"state": "waiting"}))),
                            |_, _, _| {},
                        );
                    }
                }
                let c = &mut this.live.compare;
                c.queue_run.retain(|id, _| items.iter().any(|i| i.queue_id == *id));
                c.queue = items;
                c.queue_max = api::n(&v, "max").unwrap_or(0.0) as usize;
                c.queue_loaded = true;
            }
        });
    }

    pub fn queue_remove(&mut self, queue_id: String, cx: &mut Context<Self>) {
        let id = queue_id.clone();
        self.live.compare.queue.retain(|q| q.queue_id != queue_id);
        self.fetch(
            cx,
            move || api::delete(&format!("/api/queue/{}", api::seg(&id))),
            |this, reply, _| say_error(this, &reply),
        );
    }

    pub fn queue_clear_done(&mut self, cx: &mut Context<Self>) {
        let done: Vec<String> = self
            .live
            .compare
            .queue
            .iter()
            .filter(|q| q.state == QState::Done)
            .map(|q| q.queue_id.clone())
            .collect();
        for id in done {
            self.queue_remove(id, cx);
        }
    }

    pub fn set_queue_auto(&mut self, on: bool, cx: &mut Context<Self>) {
        self.live.compare.queue_auto = on;
        self.fetch(
            cx,
            move || api::post("/api/settings", json!({"values": {"compare.queue_auto": on}})),
            |this, reply, _| this.note(&reply),
        );
    }

    /// Stop: the job in flight is cancelled at its next poll, and the
    /// product goes back to waiting.
    pub fn queue_stop(&mut self) {
        self.live.compare.queue_running = false;
    }

    /// Start: each waiting product in order, one research job at a time.
    pub fn queue_start(&mut self, cx: &mut Context<Self>) {
        let c = &mut self.live.compare;
        if c.queue_running || !c.queue.iter().any(|q| q.state == QState::Waiting) {
            return;
        }
        c.queue_running = true;
        c.say = None;
        for run in c.queue_run.values_mut() {
            run.note = None;
        }
        let harness = c.queue_harness.clone();
        cx.spawn(async move |this, cx| {
            let ex = cx.background_executor().clone();
            loop {
                // the next waiting product not already passed over
                let next = this
                    .update(cx, |this, cx| {
                        let c = &mut this.live.compare;
                        if !c.queue_running {
                            return None;
                        }
                        let item = c
                            .queue
                            .iter()
                            .find(|q| {
                                q.state == QState::Waiting
                                    && c.queue_run.get(&q.queue_id).map(|r| r.note.is_none()).unwrap_or(true)
                            })
                            .cloned()?;
                        if let Some(q) = c.queue.iter_mut().find(|q| q.queue_id == item.queue_id) {
                            q.state = QState::Researching;
                        }
                        c.queue_run.insert(
                            item.queue_id.clone(),
                            QRun { line: "finding the product".into(), ..QRun::default() },
                        );
                        cx.notify();
                        Some(item)
                    })
                    .ok()
                    .flatten();
                let Some(item) = next else { break };
                let id = item.queue_id.clone();
                let patch = |state: &'static str, lookup: Option<String>, id: String| {
                    let mut body = json!({"state": state});
                    if let Some(l) = lookup {
                        body["lookup_id"] = Value::String(l);
                    }
                    move || api::request("PATCH", &format!("/api/queue/{}", api::seg(&id)), Some(body))
                };
                let _ = bg(&ex, patch("researching", None, id.clone())).await;

                // 1. which product is it
                let it = item.clone();
                let target = bg(&ex, move || resolve_target(&it)).await;
                let target = match target {
                    Ok(t) => t,
                    Err(why) => {
                        let _ = bg(&ex, patch("waiting", None, id.clone())).await;
                        let qid = id.clone();
                        let _ = this.update(cx, |this, cx| {
                            queue_passed_over(this, &qid, why);
                            cx.notify();
                        });
                        continue;
                    }
                };

                // 2. start the research job
                let body = json!({
                    "subject_id": target.subject_id,
                    "pack_id": target.pack_id,
                    "harness": harness,
                });
                let started = bg(&ex, move || api::post("/api/research", body)).await;
                let job_id = match started {
                    Ok(v) => api::s(&v, "job_id"),
                    Err(e) => {
                        let _ = bg(&ex, patch("waiting", None, id.clone())).await;
                        let qid = id.clone();
                        let _ = this.update(cx, |this, cx| {
                            queue_passed_over(this, &qid, e.message);
                            cx.notify();
                        });
                        continue;
                    }
                };

                // 3. follow it
                let outcome: (String, String);
                loop {
                    cx.background_executor().timer(Duration::from_millis(700)).await;
                    let path = format!("/api/jobs/{}", api::seg(&job_id));
                    let reply = bg(&ex, move || api::get(&path)).await;
                    let qid = id.clone();
                    let stopped = this
                        .update(cx, |this, cx| {
                            if !this.live.compare.queue_running {
                                return true;
                            }
                            if let Ok(job) = &reply {
                                this.live.compare.queue_run.insert(
                                    qid,
                                    QRun {
                                        progress: (api::n(job, "progress").unwrap_or(0.0) * 100.0) as f32,
                                        phase: Some(phase_of(job)),
                                        line: doing_of(job),
                                        ..QRun::default()
                                    },
                                );
                            }
                            cx.notify();
                            false
                        })
                        .unwrap_or(true);
                    if stopped {
                        let path = format!("/api/jobs/{}/cancel", api::seg(&job_id));
                        let _ = bg(&ex, move || api::post(&path, json!({}))).await;
                        outcome = ("cancelled".to_string(), "stopped".to_string());
                        break;
                    }
                    match reply {
                        Ok(job) if api::b(&job, "done") => {
                            outcome = (api::s(&job, "state"), api::s(&job, "message"));
                            break;
                        }
                        Ok(_) => {}
                        Err(e) => {
                            outcome = ("failed".into(), e.message);
                            break;
                        }
                    }
                }

                // 4. the product's fresh answer, so Compare reads what was found
                if outcome.0 == "succeeded" {
                    let lookup = bg(&ex, move || {
                        api::post(
                            "/api/lookup",
                            json!({"kind": target.kind, "identity": target.identity}),
                        )
                    })
                    .await;
                    let (lookup_id, claims) = match &lookup {
                        Ok(v) => (api::s(v, "lookup_id"), Some(api::arr(v, "claims").len())),
                        Err(_) => (item.lookup_id.clone(), None),
                    };
                    let kept = (!lookup_id.is_empty()).then(|| lookup_id.clone());
                    let _ = bg(&ex, patch("done", kept, id.clone())).await;
                    let qid = id.clone();
                    let _ = this.update(cx, |this, cx| {
                        let c = &mut this.live.compare;
                        if let Some(q) = c.queue.iter_mut().find(|q| q.queue_id == qid) {
                            q.state = QState::Done;
                            q.lookup_id = lookup_id;
                        }
                        c.queue_run.insert(qid, QRun { progress: 100.0, claims, ..QRun::default() });
                        // the history now holds a new check
                        this.refresh_history_for_compare(cx);
                        cx.notify();
                    });
                } else {
                    let _ = bg(&ex, patch("waiting", None, id.clone())).await;
                    let qid = id.clone();
                    let why = if outcome.1.is_empty() { outcome.0.clone() } else { outcome.1.clone() };
                    let _ = this.update(cx, |this, cx| {
                        queue_passed_over(this, &qid, why);
                        cx.notify();
                    });
                    if outcome.0 == "cancelled" {
                        break;
                    }
                }
            }
            // finished, or stopped
            let _ = this.update(cx, |this, cx| {
                this.live.compare.queue_running = false;
                let done = this.live.compare.queue.iter().any(|q| q.state == QState::Done && !q.lookup_id.is_empty());
                if this.live.compare.queue_auto && done {
                    this.queue_to_compare(cx);
                }
                this.load_queue(cx);
                cx.notify();
            });
        })
        .detach();
    }

    fn refresh_history_for_compare(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/history?limit=50"), |this, reply, _| {
            if let Ok(v) = reply {
                this.live.compare.history = api::arr(&v, "items").iter().map(history_from).collect();
            }
        });
    }

    /// "Compare N below": the researched products, as a new draft "Queue N".
    pub fn queue_to_compare(&mut self, cx: &mut Context<Self>) {
        let ids: Vec<String> = self
            .live
            .compare
            .queue
            .iter()
            .filter(|q| q.state == QState::Done && !q.lookup_id.is_empty())
            .map(|q| q.lookup_id.clone())
            .take(MAX_SLOTS)
            .collect();
        if ids.is_empty() {
            return;
        }
        let name = self.next_draft_name("Queue");
        let slots = ids.clone();
        self.fetch(
            cx,
            move || api::post("/api/compare-drafts", json!({"name": name, "lookup_ids": ids})),
            move |this, reply, cx| {
                say_error(this, &reply);
                let c = &mut this.live.compare;
                match reply {
                    Ok(v) => {
                        let d = draft_from(&v);
                        let id = d.draft_id.clone();
                        c.drafts.push(d);
                        this.select_draft(&id, cx);
                    }
                    Err(e) => {
                        // the slots still fill; only the saving was refused
                        c.draft = None;
                        c.slots = slots.into_iter().map(Some).collect();
                        c.strokes.clear();
                        c.notes.clear();
                        c.questions.clear();
                        c.say = Some(format!("{} The products are in the slots, not saved as a draft.", e.message));
                        this.ensure_checks(cx);
                    }
                }
            },
        );
    }
}

fn queue_passed_over(this: &mut Kriko, queue_id: &str, why: String) {
    let c = &mut this.live.compare;
    if let Some(q) = c.queue.iter_mut().find(|q| q.queue_id == queue_id) {
        q.state = QState::Waiting;
    }
    c.queue_run.insert(queue_id.to_string(), QRun { note: Some(why), ..QRun::default() });
}

fn round4(v: f32) -> f64 {
    ((v as f64) * 10000.0).round() / 10000.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn question_job_keeps_source_and_usage_facts_without_inventing_missing_tokens() {
        let done = json!({"state": "succeeded", "progress": 1.0, "message": "answered",
            "log": "local comparison: saved checks only\nOne: 2 known risk(s)\ncomparison brief: 2500 characters from saved checks; no web search\nFull answer that should not be doubled in the step trail",
            "result": {"model": "small:4b", "tokens_used": 141, "tokens_in": 100,
                "tokens_out": 41, "brief_chars": 2500, "web_searches": 0,
                "saved_checks": [{"name": "One", "risks": 2}, {"name": "Two", "risks": 0}]}});
        let run = QuestionRun::from_job(&done);
        assert_eq!(run.model, "small:4b");
        assert_eq!(run.tokens_used, Some(141));
        assert_eq!(run.saved_checks, [("One".into(), 2), ("Two".into(), 0)]);
        assert!(run.no_web_search);
        assert_eq!(run.steps.len(), 3);
        let unreported = QuestionRun::from_job(&json!({"state": "succeeded", "result": {}}));
        assert_eq!(unreported.tokens_used, None);
        assert!(!unreported.no_web_search);
    }

    fn check(name: &str, specs: &[(&str, &str)], risks: &[(&str, Level, bool)]) -> Check {
        Check {
            name: name.into(),
            category: String::new(),
            specs: specs
                .iter()
                .map(|(l, v)| Spec { label: l.to_string(), value: v.to_string(), source: String::new() })
                .collect(),
            risks: risks
                .iter()
                .map(|(t, l, d)| Risk {
                    title: t.to_string(),
                    body: String::new(),
                    level: *l,
                    disputed: *d,
                    sources: vec![],
                })
                .collect(),
        }
    }

    #[test]
    fn specifications_are_the_union_of_labels_and_differ_when_values_do() {
        let a = check("A", &[("Chipset", "A16"), ("Display", "6.1")], &[]);
        let b = check("B", &[("Chipset", "A17"), ("Display", "6.1"), ("Weight", "171 g")], &[]);
        let rows = spec_rows(&[Some(&a), Some(&b)]);
        let labels: Vec<&str> = rows.iter().map(|r| r.label.as_str()).collect();
        assert_eq!(labels, ["Chipset", "Display", "Weight"]);
        assert!(rows[0].differs);
        assert!(!rows[1].differs);
        assert!(rows[2].cells[0].is_none(), "missing is not stated, not blank");
    }

    #[test]
    fn risks_match_across_columns_by_title() {
        let a = check("A", &[], &[("Battery", Level::High, false), ("Hinge", Level::Low, false)]);
        let b = check("B", &[], &[("Battery", Level::Medium, true)]);
        let rows = risk_rows(&[Some(&a), Some(&b)]);
        assert_eq!(rows.len(), 2);
        assert!(rows[0].cells[0].is_some() && rows[0].cells[1].is_some());
        assert!(rows[1].cells[1].is_none());
    }

    #[test]
    fn the_answer_names_who_records_the_fewest_grave_risks() {
        let a = check("A", &[], &[("x", Level::High, false), ("y", Level::Critical, false)]);
        let b = check("B", &[], &[("x", Level::High, false)]);
        let said = answer_lines(&[Some(&a), Some(&b)]).join(" ");
        assert!(said.contains("Fewest high-severity risks on record: B (1)"), "{said}");
        assert!(answer_lines(&[Some(&a), None]).is_empty(), "one column has nothing to compare");
    }

    #[test]
    fn a_stored_answer_names_its_subjects_as_objects_and_a_fresh_one_as_ids() {
        let stored = json!({"subjects": [
            {"subject_id": "mac", "claims": 0}, {"subject_id": "phone", "claims": 7}]});
        assert_eq!(matched_subject(&stored).as_deref(), Some("phone"));
        let fresh = json!({"subjects": ["one", "two"]});
        assert_eq!(matched_subject(&fresh).as_deref(), Some("one"));
        assert_eq!(matched_subject(&json!({"subjects": []})), None);
    }

    #[test]
    fn engine_timestamps_read_as_utc_with_or_without_an_offset() {
        assert_eq!(epoch("1970-01-02T00:00:01"), Some(86401));
        assert_eq!(epoch("1970-01-02T00:00:01+00:00"), Some(86401));
        assert_eq!(epoch("nonsense"), None);
    }
}
