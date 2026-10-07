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
    pub ts: Option<i64>,
    pub door: String,
    pub kind: String,
    pub name: String,
    pub state: String,
    pub ms: Option<f64>,
    pub note: String,
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
    // Home
    pub drafts_loaded: bool,
    pub drafts: Vec<Draft>,
    pub counts: Option<Counts>,
    pub packs: Option<Vec<PackRow>>,
    // Browse
    pub subjects_loaded: bool,
    pub subjects: Vec<Subject>,
    pub subjects_total: usize,
    pub subjects_asked: String,
    pub filters: Vec<FilterDef>,
    /// Per filter, the picked option (0 is all).
    pub filter_pick: Vec<usize>,
    pub subject_sel: Option<String>,
    pub subject_detail: Option<SubjectDetail>,
    pub subject_evidence: Option<Vec<Evidence>>,
    pub search_seq: u64,
    // Activity
    pub ops_loaded: bool,
    pub ops: Vec<Op>,
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

    /// The next catalog in the cycle: all, then each present one, then all.
    pub fn next_pack(&self) -> Option<String> {
        let options = self.pack_options();
        match &self.pack {
            None => options.first().map(|p| p.0.clone()),
            Some(cur) => {
                let at = options.iter().position(|p| &p.0 == cur)?;
                options.get(at + 1).map(|p| p.0.clone())
            }
        }
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

    /// The label of a check by its lookup id, for a draft's product names.
    pub fn label_of(&self, id: &str) -> Option<&str> {
        self.items.iter().find(|i| i.id == id).map(|i| i.label.as_str())
    }

    /// The query string for `/api/subjects`, from the search text and the
    /// filters picked. It doubles as the key a reply must still match.
    pub fn subjects_url(&self, query: &str, page: usize, page_size: usize) -> String {
        let size = page_size.clamp(1, 200);
        let offset = page.saturating_mul(size);
        let mut url = format!("/api/subjects?paged=true&limit={size}&offset={offset}");
        if !query.trim().is_empty() {
            url.push_str(&format!("&q={}", api::seg(query.trim())));
        }
        for (i, f) in self.filters.iter().enumerate() {
            let pick = self.filter_pick.get(i).copied().unwrap_or(0);
            if pick > 0 {
                if let Some((value, _)) = f.options.get(pick - 1) {
                    url.push_str(&format!("&{}={}", f.param, api::seg(value)));
                }
            }
        }
        url
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
    Op {
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
        self.fetch(cx, || api::get("/api/compare-drafts"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.history.drafts = api::arr(&v, "items")
                    .iter()
                    .map(|d| Draft {
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
        let url = self.live.history.subjects_url(
            &self.browse_search.value,
            self.browse_page,
            self.browse_page_size,
        );
        self.live.history.subjects_asked = url.clone();
        let path = url.clone();
        self.fetch(cx, move || api::get(&path), move |this, reply, _| {
            this.note(&reply);
            // a slower answer to an older search must not overwrite a newer one
            if this.live.history.subjects_asked != url {
                return;
            }
            if let Ok(v) = reply {
                let h = &mut this.live.history;
                h.subjects = api::arr(&v, "items")
                    .iter()
                    .map(|s| Subject {
                        id: api::s(s, "subject_id"),
                        pack_id: api::s(s, "pack_id"),
                        kind: api::s(s, "kind"),
                        label: api::s(s, "label"),
                        claims: api::n(s, "claims").unwrap_or(0.0) as i64,
                    })
                    .collect();
                h.subjects_total = api::n(&v, "total")
                    .unwrap_or(h.subjects.len() as f64)
                    .max(0.0) as usize;
                h.subjects_loaded = true;
            }
        });
    }

    /// Called after every key in the Browse search: asks the server once the
    /// typing has stopped for a quarter of a second.
    pub fn browse_search_typed(&mut self, cx: &mut Context<Self>) {
        self.live.history.search_seq += 1;
        self.browse_page = 0;
        self.clear_browse_selection();
        let seq = self.live.history.search_seq;
        cx.spawn(async move |this, cx| {
            cx.background_executor().timer(Duration::from_millis(250)).await;
            this.update(cx, |this, cx| {
                if this.live.history.search_seq == seq {
                    this.load_subjects(cx);
                }
            })
            .ok();
        })
        .detach();
    }

    /// Select one explicit Browse filter value; 0 means no filter.
    pub fn pick_browse_filter(&mut self, i: usize, pick: usize, cx: &mut Context<Self>) {
        let h = &mut self.live.history;
        let Some(f) = h.filters.get(i) else { return };
        if pick > f.options.len() { return; }
        let Some(current) = h.filter_pick.get_mut(i) else { return };
        if *current == pick { return; }
        *current = pick;
        self.browse_page = 0;
        self.clear_browse_selection();
        self.load_subjects(cx);
    }

    /// Reset every Browse filter, including selections hidden in the drawer.
    pub fn clear_browse_filters(&mut self, cx: &mut Context<Self>) {
        if self.live.history.filter_pick.iter().all(|pick| *pick == 0) {
            return;
        }
        self.live.history.filter_pick.fill(0);
        self.browse_page = 0;
        self.clear_browse_selection();
        self.load_subjects(cx);
    }

    /// Change the Browse page or page size and request only that slice.
    pub fn browse_page_changed(&mut self, page: usize, page_size: usize, cx: &mut Context<Self>) {
        let size = page_size.clamp(1, 200);
        let pages = self.live.history.subjects_total.div_ceil(size).max(1);
        self.browse_page_size = size;
        self.browse_page = page.min(pages - 1);
        self.clear_browse_selection();
        self.load_subjects(cx);
    }

    /// Clear the selected subject when the visible result slice changes.
    fn clear_browse_selection(&mut self) {
        let h = &mut self.live.history;
        h.subject_sel = None;
        h.subject_detail = None;
        h.subject_evidence = None;
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
        self.live.history.ops_inflight = true;
        self.live.history.ops_polled = Some(Instant::now());
        self.fetch(cx, || api::get("/api/operations?limit=100"), |this, reply, _| {
            this.note(&reply);
            let h = &mut this.live.history;
            h.ops_inflight = false;
            if let Ok(v) = reply {
                h.ops = api::arr(&v, "items").iter().map(op_from).collect();
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
        s.pack = s.next_pack();
        assert_eq!(s.pack.as_deref(), Some("x.a"));
        assert_eq!(s.filtered("", u32::MAX, 0), vec![1]);
        s.pack = s.next_pack();
        assert_eq!(s.pack.as_deref(), Some("x.b"));
        s.pack = s.next_pack();
        assert_eq!(s.pack, None);
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
        assert_eq!(s.subjects_url(" k9k engine ", 2, 25), "/api/subjects?paged=true&limit=25&offset=50&q=k9k%20engine&pack_id=a.b");
    }
}
