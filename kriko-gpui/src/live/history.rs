//! History, Home, Browse and Activity, as the engine says it.
//!
//! One slice for four screens, because they read the same few endpoints:
//! `/api/history` (History, Home), `/api/compare-drafts` and `/api/status`
//! and `/api/packs` (Home), `/api/subjects` (Browse), `/api/operations` and
//! `/api/jobs` (Activity). The engine's timestamps are UTC with no offset,
//! so they are read here and shown relative to now.

use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use gpui::Context;

use crate::api::{self, Value};
use crate::app::{Kriko, Tab};
use crate::engine;

// ---- time, without a date crate ----

/// Days since 1970-01-01 of a civil date (proleptic Gregorian).
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

/// The civil date (year, month 1..=12, day) of a day count since 1970.
fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// Seconds since the epoch of the engine's `2026-10-01T15:21:51+00:00`
/// (the fraction and the offset are ignored: the engine speaks UTC).
pub fn parse_utc(text: &str) -> Option<i64> {
    let b = text.as_bytes();
    if b.len() < 19 {
        return None;
    }
    let num = |from: usize, to: usize| -> Option<i64> { text.get(from..to)?.parse().ok() };
    let (y, mo, d) = (num(0, 4)?, num(5, 7)?, num(8, 10)?);
    let (h, mi, s) = (num(11, 13)?, num(14, 16)?, num(17, 19)?);
    if !(1..=12).contains(&mo) || !(1..=31).contains(&d) {
        return None;
    }
    Some(days_from_civil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s)
}

pub fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

const MONTHS: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/// "just now", "2 min ago", "3 h ago", "Yesterday", "5 days ago", then the
/// date. `None` (a stamp that would not parse) says nothing.
pub fn ago(ts: Option<i64>, now: i64) -> String {
    let Some(ts) = ts else { return String::new() };
    let secs = now - ts;
    if secs < 60 {
        return "just now".to_string();
    }
    if secs < 3600 {
        return format!("{} min ago", secs / 60);
    }
    if secs < 86400 {
        return format!("{} h ago", secs / 3600);
    }
    // calendar days, not 24 h blocks, so 23:50 last night is "Yesterday"
    let days = now.div_euclid(86400) - ts.div_euclid(86400);
    if days == 1 {
        return "Yesterday".to_string();
    }
    if days < 7 {
        return format!("{days} days ago");
    }
    let (y, m, d) = civil_from_days(ts.div_euclid(86400));
    let (ny, _, _) = civil_from_days(now.div_euclid(86400));
    if y == ny {
        format!("{d} {}", MONTHS[(m - 1) as usize])
    } else {
        format!("{d} {} {y}", MONTHS[(m - 1) as usize])
    }
}

/// How many stamps fall in each of the last `n` calendar months, oldest
/// first, with the month's short name. The newest bar is the current month.
pub fn month_buckets(stamps: impl Iterator<Item = i64>, now: i64, n: usize) -> Vec<(String, u32)> {
    let (ny, nm, _) = civil_from_days(now.div_euclid(86400));
    let current = ny * 12 + (nm - 1);
    let mut counts = vec![0u32; n];
    for ts in stamps {
        let (y, m, _) = civil_from_days(ts.div_euclid(86400));
        let back = current - (y * 12 + (m - 1));
        if back >= 0 && (back as usize) < n {
            counts[n - 1 - back as usize] += 1;
        }
    }
    (0..n)
        .map(|i| {
            let idx = current - (n - 1 - i) as i64;
            (MONTHS[idx.rem_euclid(12) as usize].to_string(), counts[i])
        })
        .collect()
}

// ---- what the engine says ----

/// One finished check, a row of `/api/history`.
#[derive(Clone)]
pub struct Item {
    pub id: String,
    pub ts: Option<i64>,
    pub label: String,
    pub source: String,
    pub claims: usize,
    pub category: String,
    /// (pack_id, name)
    pub packs: Vec<(String, String)>,
}

impl Item {
    /// The catalogs this check touched, by name; the category when the
    /// engine named none.
    pub fn pack_line(&self) -> String {
        if self.packs.is_empty() {
            return self.category.clone();
        }
        self.packs
            .iter()
            .map(|(_, n)| n.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    }
}

#[derive(Clone)]
pub struct Source {
    pub domain: String,
    pub url: String,
    pub quote: String,
    pub stance: String,
}

#[derive(Clone)]
pub struct ClaimView {
    pub title: String,
    pub severity: String,
    pub sources: Vec<Source>,
}

/// An opened check: what it grounded, and the page it read.
#[derive(Clone)]
pub struct Detail {
    pub id: String,
    pub url: String,
    pub claims: Vec<ClaimView>,
}

#[derive(Clone)]
pub struct Draft {
    pub id: String,
    pub name: String,
    pub lookup_ids: Vec<String>,
}

#[derive(Clone, Default)]
pub struct Counts {
    pub subjects: i64,
    pub claims: i64,
    pub evidence: i64,
}

#[derive(Clone)]
pub struct PackRow {
    pub name: String,
    pub claims: i64,
    pub enabled: bool,
}

#[derive(Clone)]
pub struct Subject {
    pub id: String,
    pub pack_id: String,
    pub kind: String,
    pub label: String,
    pub claims: i64,
}

#[derive(Clone)]
pub struct Attr {
    pub label: String,
    pub value: String,
}

#[derive(Clone)]
pub struct SubjectClaim {
    pub title: String,
    pub severity: String,
    pub domain: String,
}

#[derive(Clone)]
pub struct SubjectDetail {
    pub id: String,
    pub label: String,
    pub kind: String,
    pub attrs: Vec<Attr>,
    pub claims: Vec<SubjectClaim>,
}

/// One piece of evidence behind a claim of the picked subject.
#[derive(Clone)]
pub struct Evidence {
    pub claim: String,
    pub domain: String,
    pub quote: String,
    pub refutes: bool,
}

/// One of `/api/subjects/filters`: a parameter and its options.
#[derive(Clone)]
pub struct FilterDef {
    pub param: String,
    pub label: String,
    /// (value, label)
    pub options: Vec<(String, String)>,
}

#[derive(Clone)]
pub struct Op {
    pub op_id: i64,
    pub ts: Option<i64>,
    pub door: String,
    pub kind: String,
    pub name: String,
    pub state: String,
    pub ms: Option<f64>,
    pub note: String,
    pub job_id: String,
    pub harness: String,
    pub model: String,
}

#[derive(Clone, Copy, PartialEq, Eq, Default, Debug)]
pub enum Kind {
    #[default]
    Check,
    Run,
    Queue,
    Build,
}

impl Kind {
    pub const ALL: [Kind; 4] = [Kind::Check, Kind::Run, Kind::Queue, Kind::Build];

    pub fn word(self) -> &'static str {
        match self {
            Kind::Check => "CHECKS",
            Kind::Run => "RUNS",
            Kind::Queue => "QUEUE-UPS",
            Kind::Build => "PACK BUILDS",
        }
    }
}

#[derive(Clone)]
pub struct JobRow {
    pub id: String,
    pub kind: String,
    pub state: String,
    pub done: bool,
    pub label: String,
    pub message: String,
    pub ts: Option<i64>,
}

impl JobRow {
    pub fn state_word(&self) -> &'static str {
        if !self.done {
            return "RUNNING";
        }
        match self.state.as_str() {
            "succeeded" => "SUCCEEDED",
            "failed" | "interrupted" => "FAILED",
            "cancelled" => "CANCELLED",
            _ => "DONE",
        }
    }
}

#[derive(Clone)]
pub struct QueueRow {
    pub id: String,
    pub name: String,
    pub url: String,
    pub origin: String,
    pub state: String,
    pub ts: Option<i64>,
}

fn job_row_from(v: &Value) -> JobRow {
    let params = v.get("params").cloned().unwrap_or(Value::Null);
    let mut label = api::s(&params, "product");
    if label.is_empty() {
        label = api::s(&params, "category");
    }
    if label.is_empty() {
        label = api::s(&params, "pack_id");
    }
    if label.is_empty() {
        label = api::s(&params, "name");
    }
    JobRow {
        id: api::s(v, "job_id"),
        kind: api::s(v, "kind"),
        state: api::s(v, "state"),
        done: api::b(v, "done"),
        label,
        message: api::s(v, "message"),
        ts: parse_utc(&api::s(v, "created_at")),
    }
}

fn queue_row_from(v: &Value) -> QueueRow {
    QueueRow {
        id: api::s(v, "queue_id"),
        name: api::s(v, "name"),
        url: api::s(v, "url"),
        origin: api::s(v, "origin"),
        state: api::s(v, "state"),
        ts: parse_utc(&api::s(v, "added_at")),
    }
}

fn within_span(ts: Option<i64>, span_days: u32, now: i64) -> bool {
    let Some(ts) = ts else { return false };
    span_days == u32::MAX || now - ts <= span_days as i64 * 86400
}

#[derive(Default)]
pub struct State {
    pub loaded: bool,
    pub items: Vec<Item>,
    // History's own controls
    /// The catalog History is narrowed to; None is all of them.
    pub pack: Option<String>,
    pub open: Option<String>,
    pub detail: Option<Detail>,
    /// The check whose Forget key was pressed once.
    pub forget_armed: Option<String>,
    /// Which history is shown: checks, runs, queue-ups or pack builds.
    pub kind: Kind,
    /// The job/queue state History is narrowed to; None is all of them.
    pub status: Option<String>,
    /// Which filter drawer is open; None is all closed.
    pub drawer: Option<&'static str>,
    /// Every job the engine kept, newest first; runs and builds are picked
    /// out of this by kind.
    pub jobs: Vec<JobRow>,
    /// The research queue, oldest first, every state it holds.
    pub queue: Vec<QueueRow>,
    // Home
    pub drafts_loaded: bool,
    pub drafts: Vec<Draft>,
    pub counts: Option<Counts>,
    pub packs: Option<Vec<PackRow>>,
    // Browse
    pub subjects_loaded: bool,
    pub subjects: Vec<Subject>,
    pub subjects_total: i64,
    pub subjects_asked: String,
    pub subjects_count_asked: String,
    pub filters: Vec<FilterDef>,
    /// Per filter, the picked option (0 is all).
    pub filter_pick: Vec<usize>,
    /// Which Browse filter's drawer is open; None is all closed.
    pub filter_drawer: Option<usize>,
    pub subject_sel: Option<String>,
    pub subject_detail: Option<SubjectDetail>,
    pub subject_evidence: Option<Vec<Evidence>>,
    pub search_seq: u64,
    // Activity
    pub ops_loaded: bool,
    pub ops: Vec<Op>,
    pub ops_has_older: bool,
    pub ops_older_inflight: bool,
    /// The Activity row whose job log is expanded, and the logs fetched for
    /// the rows that have been.
    pub op_open: Option<i64>,
    pub op_logs: std::collections::HashMap<i64, Vec<crate::live::run::FeedLine>>,
    /// What the first job that put a question to the reader says.
    pub attention: Option<String>,
    pub ops_polled: Option<Instant>,
    pub ops_inflight: bool,
    /// The tab seen last by the pulse, to refresh on arrival.
    pub last_tab: Option<Tab>,
}

impl State {
    /// The catalogs present in the history, by name, for the pack filter.
    pub fn pack_options(&self) -> Vec<(String, String)> {
        let mut out: Vec<(String, String)> = Vec::new();
        for item in &self.items {
            for p in &item.packs {
                if !out.iter().any(|(id, _)| *id == p.0) {
                    out.push(p.clone());
                }
            }
        }
        out.sort_by(|a, b| a.1.to_lowercase().cmp(&b.1.to_lowercase()));
        out
    }

    /// The word the pack plate shows.
    pub fn pack_word(&self) -> String {
        match &self.pack {
            None => "ALL".to_string(),
            Some(id) => self
                .items
                .iter()
                .flat_map(|i| i.packs.iter())
                .find(|p| &p.0 == id)
                .map(|p| p.1.clone())
                .unwrap_or_else(|| id.clone()),
        }
    }

    /// Indices into `items` that the search, the catalog and the span admit,
    /// newest first (the engine already sorts them so).
    pub fn filtered(&self, query: &str, span_days: u32, now: i64) -> Vec<usize> {
        let query = query.to_lowercase();
        self.items
            .iter()
            .enumerate()
            .filter(|(_, c)| {
                let ok_query = query.is_empty()
                    || c.label.to_lowercase().contains(&query)
                    || c.category.to_lowercase().contains(&query)
                    || c.pack_line().to_lowercase().contains(&query);
                let ok_pack = match &self.pack {
                    None => true,
                    Some(id) => c.packs.iter().any(|p| &p.0 == id),
                };
                let ok_span = span_days == u32::MAX
                    || c.ts
                        .map(|ts| now - ts <= span_days as i64 * 86400)
                        .unwrap_or(true);
                ok_query && ok_pack && ok_span
            })
            .map(|(i, _)| i)
            .collect()
    }

    pub fn job_rows(&self, kinds: &[&str], query: &str, span_days: u32, now: i64) -> Vec<usize> {
        let query = query.to_lowercase();
        self.jobs
            .iter()
            .enumerate()
            .filter(|(_, j)| {
                let ok_kind = kinds.contains(&j.kind.as_str());
                let ok_status = self
                    .status
                    .as_deref()
                    .map_or(true, |want| j.state_word() == want);
                let ok_query = query.is_empty()
                    || j.label.to_lowercase().contains(&query)
                    || j.message.to_lowercase().contains(&query);
                ok_kind && ok_status && ok_query && within_span(j.ts, span_days, now)
            })
            .map(|(i, _)| i)
            .collect()
    }

    pub fn queue_rows(&self, query: &str, span_days: u32, now: i64) -> Vec<usize> {
        let query = query.to_lowercase();
        self.queue
            .iter()
            .enumerate()
            .filter(|(_, q)| {
                let ok_status = self.status.as_deref().map_or(true, |want| {
                    q.state.to_uppercase() == want
                });
                let ok_query = query.is_empty()
                    || q.name.to_lowercase().contains(&query)
                    || q.origin.to_lowercase().contains(&query);
                ok_status && ok_query && within_span(q.ts, span_days, now)
            })
            .map(|(i, _)| i)
            .collect()
    }

    /// The rows of the history the screen is on, already filtered: checks,
    /// runs, queue-ups or pack builds, one list per kind.
    pub fn rows_now(&self, kind: Kind, query: &str, span_days: u32, now: i64) -> Vec<usize> {
        match kind {
            Kind::Check => self.filtered(query, span_days, now),
            Kind::Run => self.job_rows(&["research", "agenda_run"], query, span_days, now),
            Kind::Build => {
                self.job_rows(&["pack_build", "pack_author", "pack_amend"], query, span_days, now)
            }
            Kind::Queue => self.queue_rows(query, span_days, now),
        }
    }

    /// The label of a check by its lookup id, for a draft's product names.
    pub fn label_of(&self, id: &str) -> Option<&str> {
        self.items.iter().find(|i| i.id == id).map(|i| i.label.as_str())
    }

    /// The search text and every picked filter, as `/api/subjects` query
    /// arguments.
    fn subject_args(&self, query: &str) -> String {
        let mut args = String::new();
        if !query.trim().is_empty() {
            args.push_str(&format!("&q={}", api::seg(query.trim())));
        }
        for (i, f) in self.filters.iter().enumerate() {
            let pick = self.filter_pick.get(i).copied().unwrap_or(0);
            if pick > 0 {
                if let Some((value, _)) = f.options.get(pick - 1) {
                    args.push_str(&format!("&{}={}", f.param, api::seg(value)));
                }
            }
        }
        args
    }

    /// One page of `/api/subjects`. It doubles as the key a reply must still
    /// match.
    pub fn subjects_url(&self, query: &str, page: usize) -> String {
        format!(
            "/api/subjects?limit={}&offset={}{}",
            crate::data::BROWSE_PAGE_SIZE,
            page * crate::data::BROWSE_PAGE_SIZE,
            self.subject_args(query)
        )
    }

    /// How many subjects the same search and filters match, for the page
    /// controls.
    pub fn subjects_count_url(&self, query: &str) -> String {
        format!("/api/subjects/count{}", self.subject_args(query).replacen('&', "?", 1))
    }
}

fn item_from(v: &Value) -> Item {
    Item {
        id: api::s(v, "lookup_id"),
        ts: parse_utc(&api::s(v, "created_at")),
        label: api::s(v, "label"),
        source: api::s(v, "source"),
        claims: api::n(v, "claim_count").unwrap_or(0.0) as usize,
        category: api::s(v, "category"),
        packs: api::arr(v, "packs")
            .iter()
            .map(|p| (api::s(p, "pack_id"), api::s(p, "name")))
            .collect(),
    }
}

fn detail_from(id: &str, v: &Value) -> Detail {
    let response = v.get("response").cloned().unwrap_or(Value::Null);
    let request = v.get("request").cloned().unwrap_or(Value::Null);
    Detail {
        id: id.to_string(),
        url: api::s(&request, "url"),
        claims: api::arr(&response, "claims")
            .iter()
            .map(|c| ClaimView {
                title: api::s(c, "title"),
                severity: api::s(c, "severity"),
                sources: api::arr(c, "sources")
                    .iter()
                    .map(|s| Source {
                        domain: api::s(s, "domain"),
                        url: api::s(s, "url"),
                        quote: api::s(s, "quote"),
                        stance: api::s(s, "stance"),
                    })
                    .collect(),
            })
            .collect(),
    }
}

fn subject_detail_from(v: &Value) -> SubjectDetail {
    SubjectDetail {
        id: api::s(v, "subject_id"),
        label: api::s(v, "label"),
        kind: api::s(v, "kind"),
        attrs: api::arr(v, "attributes")
            .iter()
            .map(|a| {
                let unit = api::s(a, "unit");
                let value = api::s(a, "value_text");
                Attr {
                    label: api::s(a, "label"),
                    value: if unit.is_empty() { value } else { format!("{value} {unit}") },
                }
            })
            .collect(),
        claims: api::arr(v, "claims")
            .iter()
            .map(|c| SubjectClaim {
                title: api::s(c, "title"),
                severity: api::s(c, "severity"),
                domain: api::s(c, "domain"),
            })
            .collect(),
    }
}

fn evidence_from(v: &Value) -> Vec<Evidence> {
    let mut out = Vec::new();
    for c in api::arr(v, "claims") {
        let title = c
            .get("health")
            .map(|h| api::s(h, "title"))
            .unwrap_or_default();
        for e in api::arr(c, "evidence") {
            out.push(Evidence {
                claim: title.clone(),
                domain: api::s(e, "domain"),
                quote: api::s(e, "quote"),
                refutes: api::s(e, "stance") == "refutes",
            });
        }
    }
    out
}

/// What an operation's row says in the feed's own kinds. These are the
/// feed's filter words, not a category: the engine's doors and verbs map to
/// them, whichever catalog the work was about.
pub fn feed_kind(op: &Op) -> &'static str {
    match (op.door.as_str(), op.kind.as_str(), op.name.as_str()) {
        ("mcp", _, _) => "agents",
        (_, _, "site_register") => "sites",
        (_, "lookup", _) => "history",
        (_, "write", _) => "knowledge",
        (_, "research", _) | (_, "author", _) | (_, "read", _) => "run",
        _ => "system",
    }
}

fn op_from(v: &Value) -> Op {
    let params = serde_json::from_str::<Value>(&api::s(v, "job_params")).unwrap_or(Value::Null);
    Op {
        op_id: api::n(v, "op_id").unwrap_or(0.0) as i64,
        ts: parse_utc(&api::s(v, "started_at")),
        door: api::s(v, "door"),
        kind: api::s(v, "kind"),
        name: api::s(v, "name"),
        state: api::s(v, "state"),
        ms: api::n(v, "ms"),
        note: {
            let note = api::s(v, "note");
            if note.is_empty() { api::s(v, "error") } else { note }
        },
        job_id: api::s(v, "job_id"),
        harness: api::s(&params, "harness"),
        model: api::s(&params, "model"),
    }
}

impl Kriko {
    /// History, Home's drafts, status and catalogs: everything the checks
    /// screens draw from, asked for at once.
    pub fn refresh_history(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/history?limit=200"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                let h = &mut this.live.history;
                h.items = api::arr(&v, "items").iter().map(item_from).collect();
                h.loaded = true;
                // an opened check that is gone (forgotten elsewhere) closes
                if let Some(open) = h.open.clone() {
                    if !h.items.iter().any(|i| i.id == open) {
                        h.open = None;
                        h.detail = None;
                    }
                }
            }
        });
        self.fetch(cx, || api::get("/api/jobs?limit=200"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.history.jobs =
                    api::arr(&v, "items").iter().map(job_row_from).collect();
            }
        });
        self.fetch(cx, || api::get("/api/queue"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.history.queue =
                    api::arr(&v, "items").iter().map(queue_row_from).collect();
            }
        });
        self.fetch(cx, || api::get("/api/compare-drafts"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.history.drafts = api::arr(&v, "items")
                    .iter()
                    .map(|d| Draft {
                        id: api::s(d, "draft_id"),
                        name: api::s(d, "name"),
                        lookup_ids: api::arr(d, "lookup_ids").iter().filter_map(|x| x.as_str().map(String::from)).collect(),
                    })
                    .collect();
                this.live.history.drafts_loaded = true;
            }
        });
        self.fetch(cx, || api::get("/api/status"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                let c = v.get("counts_enabled").cloned().unwrap_or(Value::Null);
                this.live.history.counts = Some(Counts {
                    subjects: api::n(&c, "subjects").unwrap_or(0.0) as i64,
                    claims: api::n(&c, "claims").unwrap_or(0.0) as i64,
                    evidence: api::n(&c, "evidence").unwrap_or(0.0) as i64,
                });
            }
        });
        self.fetch(cx, || api::get("/api/packs"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.history.packs = Some(
                    api::arr(&v, "")
                        .iter()
                        .map(|p| PackRow {
                            name: api::s(p, "name"),
                            claims: api::n(p, "claims").unwrap_or(0.0) as i64,
                            enabled: api::b(p, "enabled"),
                        })
                        .collect(),
                );
            }
        });
    }

    /// Opens a check's row, or closes it; opening reads its stored lookup.
    pub fn toggle_history_open(&mut self, id: String, cx: &mut Context<Self>) {
        let h = &mut self.live.history;
        h.forget_armed = None;
        if h.open.as_deref() == Some(id.as_str()) {
            h.open = None;
            h.detail = None;
            return;
        }
        h.open = Some(id.clone());
        h.detail = None;
        let path = format!("/api/lookup/{}", api::seg(&id));
        self.fetch(cx, move || api::get(&path), move |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                if this.live.history.open.as_deref() == Some(id.as_str()) {
                    this.live.history.detail = Some(detail_from(&id, &v));
                }
            }
        });
    }

    /// Forget a check: the first press arms the key, the second deletes.
    pub fn forget_check(&mut self, id: String, cx: &mut Context<Self>) {
        if self.live.history.forget_armed.as_deref() != Some(id.as_str()) {
            self.live.history.forget_armed = Some(id);
            cx.notify();
            return;
        }
        self.live.history.forget_armed = None;
        let path = format!("/api/history/{}", api::seg(&id));
        self.fetch(cx, move || api::delete(&path), move |this, reply, cx| {
            this.note(&reply);
            if reply.is_ok() {
                let h = &mut this.live.history;
                h.items.retain(|i| i.id != id);
                h.open = None;
                h.detail = None;
                this.refresh_history(cx);
            }
        });
    }

    // ---- Browse ----

    /// The filters first (once), then the subjects they and the search ask for.
    pub fn refresh_subjects(&mut self, cx: &mut Context<Self>) {

        if self.live.history.filters.is_empty() {
            self.fetch(cx, || api::get("/api/subjects/filters"), |this, reply, cx| {
                this.note(&reply);
                if let Ok(v) = reply {
                    let h = &mut this.live.history;
                    h.filters = api::arr(&v, "filters")
                        .iter()
                        .map(|f| FilterDef {
                            param: api::s(f, "param"),
                            label: api::s(f, "label"),
                            options: api::arr(f, "options")
                                .iter()
                                .map(|o| (api::s(o, "value"), api::s(o, "label")))
                                .collect(),
                        })
                        .collect();
                    h.filter_pick = vec![0; h.filters.len()];
                }
                this.load_subjects(cx);
            });
        } else {
            self.load_subjects(cx);
        }
    }

    fn load_subjects(&mut self, cx: &mut Context<Self>) {
        let url = self.live.history.subjects_url(&self.browse_search.value, self.browse_page);
        let count = self.live.history.subjects_count_url(&self.browse_search.value);
        self.live.history.subjects_asked = url.clone();
        self.live.history.subjects_count_asked = count.clone();
        let count_path = count.clone();
        let path = url.clone();
        self.fetch(cx, move || api::get(&path), move |this, reply, _| {
            this.note(&reply);
            // a slower answer to an older search must not overwrite a newer one
            if this.live.history.subjects_asked != url {
                return;
            }
            if let Ok(v) = reply {
                let h = &mut this.live.history;
                h.subjects = api::arr(&v, "")
                    .iter()
                    .map(|s| Subject {
                        id: api::s(s, "subject_id"),
                        pack_id: api::s(s, "pack_id"),
                        kind: api::s(s, "kind"),
                        label: api::s(s, "label"),
                        claims: api::n(s, "claims").unwrap_or(0.0) as i64,
                    })
                    .collect();
                h.subjects_loaded = true;
            }
        });
        self.fetch(cx, move || api::get(&count_path), move |this, reply, _| {
            this.note(&reply);
            if this.live.history.subjects_count_asked != count {
                return;
            }
            if let Ok(v) = reply {
                this.live.history.subjects_total = api::n(&v, "count").unwrap_or(0.0) as i64;
            }
        });
    }

    /// Turn the Browse list one page, then read that page from the engine.
    pub fn turn_browse_page(&mut self, step: i64, cx: &mut Context<Self>) {
        let total = self.live.history.subjects_total.max(0) as usize;
        let pages = (total + crate::data::BROWSE_PAGE_SIZE - 1) / crate::data::BROWSE_PAGE_SIZE;
        let want = (self.browse_page as i64 + step).clamp(0, pages.saturating_sub(1) as i64) as usize;
        if want != self.browse_page {
            self.browse_page = want;
            self.load_subjects(cx);
        }
    }

    /// Called after every key in the Browse search: asks the server once the
    /// typing has stopped for a quarter of a second.
    pub fn browse_search_typed(&mut self, cx: &mut Context<Self>) {
        self.live.history.search_seq += 1;
        let seq = self.live.history.search_seq;
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(250)).await;
            this.update(cx, |this, cx| {
                if this.live.history.search_seq == seq {
                    this.browse_page = 0;
                    this.load_subjects(cx);
                }
            })
            .ok();
        })
        .detach();
    }

    /// Open or close one Browse filter's drawer.
    pub fn open_browse_filter(&mut self, i: usize, cx: &mut Context<Self>) {
        self.live.history.filter_drawer = if self.live.history.filter_drawer == Some(i) {
            None
        } else {
            Some(i)
        };
        cx.notify();
    }

    /// Pick an option in one Browse filter (0 is all), close its drawer and
    /// ask the engine for the narrowed subjects.
    pub fn pick_browse_filter(&mut self, i: usize, pick: usize, cx: &mut Context<Self>) {
        if let Some(p) = self.live.history.filter_pick.get_mut(i) {
            *p = pick;
        }
        self.live.history.filter_drawer = None;
        self.browse_page = 0;
        self.load_subjects(cx);
    }

    /// Picks a subject for the drawer and reads it and its evidence.
    pub fn select_subject(&mut self, id: String, cx: &mut Context<Self>) {
        let h = &mut self.live.history;
        if h.subject_sel.as_deref() == Some(id.as_str()) {
            return;
        }
        h.subject_sel = Some(id.clone());
        h.subject_detail = None;
        h.subject_evidence = None;
        let path = format!("/api/subjects/{}", api::seg(&id));
        let sel = id.clone();
        self.fetch(cx, move || api::get(&path), move |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                if this.live.history.subject_sel.as_deref() == Some(sel.as_str()) {
                    this.live.history.subject_detail = Some(subject_detail_from(&v));
                }
            }
        });
        let path = format!("/api/health/subject/{}", api::seg(&id));
        self.fetch(cx, move || api::get(&path), move |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                if this.live.history.subject_sel.as_deref() == Some(id.as_str()) {
                    this.live.history.subject_evidence = Some(evidence_from(&v));
                }
            }
        });
    }

    // ---- Activity ----

    pub fn refresh_activity(&mut self, cx: &mut Context<Self>) {
        if self.live.history.ops_inflight {
            return;
        }
        self.live.history.ops_inflight = true;
        self.live.history.ops_polled = Some(Instant::now());
        self.fetch(cx, || api::get("/api/operations?limit=100"), |this, reply, _| {
            this.note(&reply);
            let h = &mut this.live.history;
            h.ops_inflight = false;
            if let Ok(v) = reply {
                let incoming: Vec<Op> = api::arr(&v, "items").iter().map(op_from).collect();
                if h.ops_loaded {
                    let mut merged: std::collections::HashMap<i64, Op> =
                        std::mem::take(&mut h.ops).into_iter().map(|op| (op.op_id, op)).collect();
                    for op in incoming {
                        merged.insert(op.op_id, op);
                    }
                    h.ops = merged.into_values().collect();
                    h.ops.sort_by(|a, b| b.op_id.cmp(&a.op_id));
                } else {
                    h.ops_has_older = incoming.len() == 100;
                    h.ops = incoming;
                }
                h.ops_loaded = true;
            }
        });
        self.fetch(cx, || api::get("/api/jobs?limit=30"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.history.attention = api::arr(&v, "items")
                    .iter()
                    .filter_map(|j| j.get("attention").filter(|a| !a.is_null()))
                    .map(|a| api::s(a, "say"))
                    .find(|s| !s.is_empty());
            }
        });
    }

    /// Load the next older page, keeping the rows already visible in place.
    pub fn load_older_activity(&mut self, cx: &mut Context<Self>) {
        let h = &mut self.live.history;
        if h.ops_older_inflight || !h.ops_has_older {
            return;
        }
        let Some(before) = h.ops.iter().map(|op| op.op_id).min() else { return };
        h.ops_older_inflight = true;
        let path = format!("/api/operations?limit=100&before_id={before}");
        self.fetch(cx, move || api::get(&path), |this, reply, _| {
            this.note(&reply);
            let h = &mut this.live.history;
            h.ops_older_inflight = false;
            if let Ok(v) = reply {
                let older: Vec<Op> = api::arr(&v, "items").iter().map(op_from).collect();
                h.ops_has_older = older.len() == 100;
                let mut merged: std::collections::HashMap<i64, Op> =
                    std::mem::take(&mut h.ops).into_iter().map(|op| (op.op_id, op)).collect();
                for op in older {
                    merged.entry(op.op_id).or_insert(op);
                }
                h.ops = merged.into_values().collect();
                h.ops.sort_by(|a, b| b.op_id.cmp(&a.op_id));
            }
        });
    }

    /// Expand one Activity row into the log of the job behind it; the same
    /// press on the open row folds it back.
    pub fn open_op_log(&mut self, op_id: i64, job_id: String, cx: &mut Context<Self>) {
        if self.live.history.op_open == Some(op_id) {
            self.live.history.op_open = None;
            cx.notify();
            return;
        }
        self.live.history.op_open = Some(op_id);
        cx.notify();
        let path = format!("/api/jobs/{}", api::seg(&job_id));
        self.fetch(cx, move || api::get(&path), move |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                let log = api::s(&v, "log");
                let lines: Vec<crate::live::run::FeedLine> = log
                    .lines()
                    .flat_map(|r| r.split("; "))
                    .map(str::trim)
                    .filter(|l| !l.is_empty())
                    .map(|l| crate::live::run::FeedLine {
                        kind: crate::live::run::event_kind(l),
                        text: crate::live::run::clip(l, 220),
                    })
                    .collect();
                this.live.history.op_logs.insert(op_id, lines);
            }
        });
    }

    /// Run by the window's pulse: refreshes what a screen shows when you
    /// arrive on it, and polls the Activity feed every five seconds while
    /// (and only while) that tab is open.
    pub fn tick_history(&mut self, cx: &mut Context<Self>) {
        if !matches!(self.engine, engine::Status::Ready { .. }) {
            return;
        }
        let tab = self.tab;
        let first = self.live.history.last_tab.is_none();
        if self.live.history.last_tab != Some(tab) {
            self.live.history.last_tab = Some(tab);
            match tab {
                // the first tick coincides with the startup refresh
                Tab::Home | Tab::History if !first => self.refresh_history(cx),
                Tab::Browse => self.refresh_subjects(cx),
                _ => {}
            }
            if tab != Tab::Activity {
                self.live.history.ops_polled = None;
            }
        }
        if tab == Tab::Activity {
            let h = &self.live.history;
            let due = h
                .ops_polled
                .map_or(true, |t| t.elapsed() >= Duration::from_secs(5));
            if due && !h.ops_inflight {
                self.refresh_activity(cx);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_engines_stamps_parse_to_utc_seconds() {
        assert_eq!(parse_utc("1970-01-01T00:00:00+00:00"), Some(0));
        assert_eq!(parse_utc("2026-10-01T15:21:51+00:00"), Some(1_790_868_111));
        assert_eq!(parse_utc("2026-10-01T15:21:51.123456+00:00"), Some(1_790_868_111));
        assert_eq!(parse_utc("soon"), None);
    }

    #[test]
    fn relative_time_reads_like_a_person() {
        let now = parse_utc("2026-10-04T12:00:00").unwrap();
        let at = |s: &str| ago(parse_utc(s), now);
        assert_eq!(at("2026-10-04T11:59:40"), "just now");
        assert_eq!(at("2026-10-04T11:58:00"), "2 min ago");
        assert_eq!(at("2026-10-04T09:00:00"), "3 h ago");
        assert_eq!(at("2026-10-03T06:00:00"), "Yesterday");
        assert_eq!(at("2026-10-01T06:00:00"), "3 days ago");
        assert_eq!(at("2026-08-12T06:00:00"), "12 Aug");
        assert_eq!(at("2025-08-12T06:00:00"), "12 Aug 2025");
    }

    #[test]
    fn months_bucket_across_a_year_boundary() {
        let now = parse_utc("2026-02-10T00:00:00").unwrap();
        let stamps = ["2026-02-01T00:00:00", "2026-02-09T00:00:00", "2025-12-30T00:00:00", "2025-01-01T00:00:00"]
            .iter()
            .filter_map(|s| parse_utc(s));
        let b = month_buckets(stamps, now, 4);
        let words: Vec<&str> = b.iter().map(|(m, _)| m.as_str()).collect();
        assert_eq!(words, ["Nov", "Dec", "Jan", "Feb"]);
        let counts: Vec<u32> = b.iter().map(|(_, c)| *c).collect();
        assert_eq!(counts, [0, 1, 0, 2]);
    }

    #[test]
    fn the_pack_plate_cycles_through_what_is_present() {
        let item = |id: &str, pack: &str| Item {
            id: id.into(),
            ts: None,
            label: id.into(),
            source: String::new(),
            claims: 0,
            category: String::new(),
            packs: vec![(pack.into(), pack.to_uppercase())],
        };
        let mut s = State { items: vec![item("a", "x.b"), item("b", "x.a")], ..Default::default() };
        assert_eq!(s.pack_word(), "ALL");
        s.pack = Some("x.a".into());
        assert_eq!(s.filtered("", u32::MAX, 0), vec![1]);
        s.pack = Some("x.b".into());
        assert_eq!(s.filtered("", u32::MAX, 0), vec![0]);
        s.pack = None;
        assert_eq!(s.filtered("", u32::MAX, 0), vec![0, 1]);
    }

    #[test]
    fn the_kinds_are_held_apart() {
        let job = |kind: &str, state: &str, done: bool| JobRow {
            id: format!("{kind}-{state}"),
            kind: kind.into(),
            state: state.into(),
            done,
            label: format!("{kind} {state}"),
            message: String::new(),
            ts: Some(0),
        };
        let queued = |name: &str, state: &str| QueueRow {
            id: name.into(),
            name: name.into(),
            url: String::new(),
            origin: String::new(),
            state: state.into(),
            ts: Some(0),
        };
        let mut s = State::default();
        s.jobs = vec![
            job("research", "succeeded", true),
            job("pack_build", "failed", true),
            job("agenda_run", "running", false),
        ];
        s.queue = vec![queued("one", "waiting"), queued("two", "done")];
        assert_eq!(s.rows_now(Kind::Run, "", u32::MAX, 0), vec![0, 2]);
        assert_eq!(s.rows_now(Kind::Build, "", u32::MAX, 0), vec![1]);
        assert_eq!(s.rows_now(Kind::Queue, "", u32::MAX, 0), vec![0, 1]);
        s.status = Some("RUNNING".into());
        assert_eq!(s.rows_now(Kind::Run, "", u32::MAX, 0), vec![2]);
        assert_eq!(s.rows_now(Kind::Build, "", u32::MAX, 0), Vec::<usize>::new());
        s.status = Some("DONE".into());
        assert_eq!(s.rows_now(Kind::Queue, "", u32::MAX, 0), vec![1]);
        s.status = None;
        s.jobs[2].label = "the second run".into();
        assert_eq!(s.rows_now(Kind::Run, "second", u32::MAX, 0), vec![2]);
    }

    #[test]
    fn the_subject_query_carries_search_and_filters() {
        let mut s = State::default();
        s.filters = vec![FilterDef {
            param: "pack_id".into(),
            label: "Catalog".into(),
            options: vec![("a.b".into(), "A".into())],
        }];
        s.filter_pick = vec![1];
        assert_eq!(
            s.subjects_url(" k9k engine ", 2),
            "/api/subjects?limit=8&offset=16&q=k9k%20engine&pack_id=a.b"
        );
        assert_eq!(
            s.subjects_count_url(" k9k engine "),
            "/api/subjects/count?q=k9k%20engine&pack_id=a.b"
        );
        s.filter_pick = vec![0];
        assert_eq!(s.subjects_count_url(""), "/api/subjects/count");
    }
}
