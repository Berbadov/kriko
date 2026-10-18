//! Chat: a conversation with the reader's own agent, over what the app holds.
//!
//! The engine keeps the threads and messages (`/api/chat/...`). A reader's
//! question starts a `chat_ask` job; while it runs, the job's result is the
//! turn so far (its steps, and the answer once written), and this module reads
//! that every 700 ms so the screen can show each record the agent asked for as
//! it is read. When the job ends, the thread is read again from the engine.
//!
//! What follows the pattern of [`crate::live`]: every call goes through
//! `Kriko::fetch`, so the screen draws from this state and never waits on the
//! network.

use std::collections::{HashMap, HashSet};
use std::time::Duration;

use gpui::{BackgroundExecutor, Context};
use serde_json::json;

use crate::api::{self, Value};
use crate::app::{Kriko, Tab};

/// Who wrote a message.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Role {
    Reader,
    Agent,
}

impl Role {
    pub fn from_word(word: &str) -> Role {
        if word == "agent" {
            Role::Agent
        } else {
            Role::Reader
        }
    }
}

/// Where one step of a turn stands. The engine's own words, kept as they are.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum StepState {
    Running,
    Done,
    Empty,
    Error,
}

impl StepState {
    pub fn from_word(word: &str) -> StepState {
        match word {
            "done" => StepState::Done,
            "empty" => StepState::Empty,
            "error" => StepState::Error,
            _ => StepState::Running,
        }
    }

    /// Whether the step has finished, one way or another.
    pub fn is_settled(self) -> bool {
        !matches!(self, StepState::Running)
    }
}

/// One record the agent asked for during a turn.
#[derive(Clone, Debug, PartialEq)]
pub struct Step {
    pub id: String,
    pub source: String,
    /// The engine's words for it: "searching the catalogue for …" while it
    /// runs, "read 4 saved checks" or "no rows from quick looks" once done.
    pub label: String,
    pub state: StepState,
    pub rows: u64,
    pub ms: u64,
    pub detail: String,
}

impl Step {
    fn from_value(v: &Value) -> Step {
        Step {
            id: api::s(v, "id"),
            source: api::s(v, "source"),
            label: api::s(v, "label"),
            state: StepState::from_word(&api::s(v, "state")),
            rows: api::n(v, "rows").unwrap_or(0.0).max(0.0) as u64,
            ms: api::n(v, "ms").unwrap_or(0.0).max(0.0) as u64,
            detail: api::s(v, "detail"),
        }
    }
}

/// The small line under a step: how many rows, how long it took.
pub fn step_meta(step: &Step) -> String {
    match step.state {
        StepState::Running => "reading".to_string(),
        StepState::Error => "failed".to_string(),
        _ => format!(
            "{} {} · {} ms",
            step.rows,
            if step.rows == 1 { "row" } else { "rows" },
            step.ms
        ),
    }
}

#[derive(Clone)]
pub struct Thread {
    pub thread_id: String,
    pub title: String,
}

impl Thread {
    /// What the list calls the conversation: its first question, or a plain
    /// word while nothing has been asked yet.
    pub fn name(&self) -> String {
        if self.title.trim().is_empty() {
            "New conversation".to_string()
        } else {
            self.title.clone()
        }
    }
}

/// One product a turn found in the reader's own catalogs.
///
/// The agent was always given these rows; the reader saw only prose. A card
/// is the same row said plainly: what the catalog calls the product, the
/// identity it is known by, how many risks are recorded, and the id that
/// asks for more.
#[derive(Clone, Debug, PartialEq)]
pub struct Product {
    pub subject_id: String,
    pub pack_id: String,
    pub label: String,
    pub kind: String,
    /// The identity keys the catalog recorded, in its own order.
    pub identity: Vec<(String, String)>,
    pub claims: u64,
    /// Risks whose evidence a source backs, when the engine graded them.
    pub backed: u64,
    pub rank: u64,
    pub found_by: String,
}

impl Product {
    fn from_value(v: &Value) -> Option<Product> {
        let subject_id = api::s(v, "subject_id");
        if subject_id.is_empty() {
            return None;
        }
        let mut identity: Vec<(String, String)> = api::obj(v, "identity")
            .map(|map| {
                map.iter()
                    .filter_map(|(k, val)| {
                        let text = val.as_str().unwrap_or("").trim().to_string();
                        (!text.is_empty()).then(|| (k.clone(), text))
                    })
                    .collect()
            })
            .unwrap_or_default();
        identity.sort_by(|a, b| a.0.cmp(&b.0));
        let coverage = v.get("coverage").unwrap_or(&Value::Null);
        Some(Product {
            subject_id,
            pack_id: api::s(v, "pack_id"),
            label: api::s(v, "label"),
            kind: api::s(v, "kind"),
            identity,
            claims: api::n(v, "claims").unwrap_or(0.0).max(0.0) as u64,
            backed: api::n(coverage, "cited").unwrap_or(0.0).max(0.0) as u64,
            rank: api::n(v, "rank").unwrap_or(0.0).max(0.0) as u64,
            found_by: api::s(v, "found_by"),
        })
    }

    /// What the card calls the product: the catalog's own name, and failing
    /// that the identity it is known by.
    pub fn title(&self) -> String {
        if !self.label.trim().is_empty() {
            return self.label.clone();
        }
        if self.identity.is_empty() {
            return self.subject_id.clone();
        }
        self.identity
            .iter()
            .map(|(_, value)| value.as_str())
            .collect::<Vec<_>>()
            .join(" ")
    }
}

fn products(v: &Value, key: &str) -> Vec<Product> {
    api::arr(v, key)
        .iter()
        .filter_map(Product::from_value)
        .collect()
}

#[derive(Clone)]
pub struct Message {
    pub message_id: String,
    pub role: Role,
    pub text: String,
    pub steps: Vec<Step>,
    pub sources: Vec<String>,
    pub products: Vec<Product>,
}

/// The turn in flight, as the job's result holds it so far.
#[derive(Clone, Default, Debug, PartialEq)]
pub struct Partial {
    pub steps: Vec<Step>,
    pub answer: String,
    pub sources: Vec<String>,
    pub products: Vec<Product>,
    pub agent: String,
}

impl Partial {
    /// Read a job's `result` while it runs. Missing parts are empty, never an error.
    pub fn from_result(result: &Value) -> Partial {
        Partial {
            steps: api::arr(result, "steps")
                .iter()
                .map(Step::from_value)
                .collect(),
            answer: api::s(result, "answer"),
            sources: names(result, "sources"),
            products: products(result, "products"),
            agent: api::s(result.get("agent").unwrap_or(&Value::Null), "label"),
        }
    }
}

fn names(v: &Value, key: &str) -> Vec<String> {
    api::arr(v, key)
        .iter()
        .filter_map(|one| one.as_str().map(str::to_string))
        .collect()
}

fn message_from(v: &Value) -> Message {
    Message {
        message_id: api::s(v, "message_id"),
        role: Role::from_word(&api::s(v, "role")),
        text: api::s(v, "text"),
        steps: api::arr(v, "steps").iter().map(Step::from_value).collect(),
        sources: names(v, "sources"),
        products: products(v, "products"),
    }
}

fn thread_from(v: &Value) -> Thread {
    Thread {
        thread_id: api::s(v, "thread_id"),
        title: api::s(v, "title"),
    }
}

/// Why the Local agent is not offered here, in the engine's own words. The
/// engine lists a local model that is not ready under `unusable` (found) or
/// `missing` (not found), and the agent pickers drop both, so the reason would
/// be lost without this. Empty when the Local agent is ready or not configured.
pub fn local_note(p: &Value) -> String {
    for row in api::arr(p, "unusable")
        .iter()
        .chain(api::arr(p, "missing").iter())
    {
        if api::s(row, "id") == "local" {
            let why = api::s(row, "why");
            return if why.is_empty() {
                api::s(row, "install_hint")
            } else {
                why
            };
        }
    }
    String::new()
}

#[derive(Clone)]
pub struct InFlight {
    pub thread_id: String,
    pub job_id: String,
}

#[derive(Default)]
pub struct State {
    pub threads: Vec<Thread>,
    pub loaded: bool,
    /// The conversation on screen, if any.
    pub thread: Option<String>,
    pub messages: Vec<Message>,
    /// (id, label) of every agent that can answer, the Local model among them.
    pub harnesses: Vec<(String, String)>,
    pub harness: String,
    /// Why the Local agent is not among `harnesses`, when it is not ready.
    pub local_note: String,
    /// A question is being posted (before its job exists).
    pub sending: bool,
    /// A no-match handoff is creating an unsent conversation. Do not auto-open
    /// an older thread while its creation response is in flight.
    pub discovery_pending: bool,
    pub in_flight: Option<InFlight>,
    /// The turn so far, while its job runs.
    pub partial: Option<Partial>,
    /// The job's own last word while it runs ("waiting: …", "running").
    pub job_message: String,
    /// Why the last turn failed, for the thread it failed in.
    pub failed: Option<String>,
    pub say: Option<String>,
    /// Jobs this session is already following, so one turn is watched once.
    pub watching: HashSet<String>,
    /// Jobs belonging to other conversations keep running when the reader switches.
    pub running: HashMap<String, String>,
    pub drafts: HashMap<String, String>,
    pub details: HashSet<String>,
    pub scroll: gpui::ScrollHandle,
    pub rendered_chars: usize,
    /// The product whose saved check is being refreshed right now, by id.
    pub product_busy: Option<String>,
    /// The product just put in the compare queue, by id: the card says so once.
    pub product_queued: Option<String>,
    /// Why a product action failed, and for which product.
    pub product_note: Option<(String, String)>,
}

impl State {
    fn finish_discovery(
        &mut self,
        thread: Thread,
        prompt: String,
        origin: (Option<&str>, &str),
        current_input: &str,
        visible: bool,
    ) -> Option<String> {
        self.discovery_pending = false;
        let id = thread.thread_id.clone();
        self.drafts.insert(id.clone(), prompt.clone());
        self.threads.insert(0, thread);
        if visible && self.thread.as_deref() == origin.0 && current_input == origin.1 {
            self.drafts.insert(
                origin.0.unwrap_or_default().to_string(),
                current_input.to_string(),
            );
            self.select_thread(id);
            Some(prompt)
        } else {
            None
        }
    }

    fn select_thread(&mut self, thread_id: String) {
        self.in_flight = self.running.get(&thread_id).map(|job_id| InFlight {
            thread_id: thread_id.clone(),
            job_id: job_id.clone(),
        });
        self.thread = Some(thread_id);
        self.messages.clear();
        self.partial = None;
        self.job_message.clear();
        self.failed = None;
        self.say = None;
        self.rendered_chars = 0;
    }

    fn finish_job(&mut self, thread_id: &str, job_id: &str, failure: Option<String>) {
        self.watching.remove(job_id);
        if self.running.get(thread_id).is_some_and(|id| id == job_id) {
            self.running.remove(thread_id);
        }
        if self.thread.as_deref() == Some(thread_id)
            && self.in_flight.as_ref().is_some_and(|f| f.job_id == job_id)
        {
            self.in_flight = None;
            self.partial = None;
            self.job_message.clear();
            self.failed = failure;
        }
    }
}

// ---- reading the engine ----

fn thread_list(v: &Value) -> Vec<Thread> {
    api::arr(v, "items").iter().map(thread_from).collect()
}

async fn bg<T: Send + 'static>(
    ex: &BackgroundExecutor,
    work: impl FnOnce() -> T + Send + 'static,
) -> T {
    ex.spawn(async move { work() }).await
}

impl Kriko {
    /// Everything the Chat screen shows, read when it is opened: the threads
    /// and the agents that can answer.
    pub fn refresh_chat(&mut self, cx: &mut Context<Self>) {
        self.fetch(
            cx,
            || api::get("/api/chat/threads"),
            |this, reply, cx| {
                this.note(&reply);
                if let Ok(v) = reply {
                    this.live.chat.threads = thread_list(&v);
                    this.live.chat.loaded = true;
                    // Only when nothing is open: a conversation just started may not
                    // be in this list yet, and must not be replaced by the first one.
                    if this.live.chat.thread.is_none() && !this.live.chat.discovery_pending {
                        // The newest conversation, or none: a fresh install shows
                        // the empty state, never a blank conversation.
                        if let Some(id) =
                            this.live.chat.threads.first().map(|t| t.thread_id.clone())
                        {
                            this.open_chat_thread(id, cx);
                        }
                    }
                }
            },
        );
        self.fetch(
            cx,
            || api::get("/api/prefs"),
            |this, prefs, _| {
                let Ok(p) = prefs else { return };
                let unusable: Vec<String> = api::arr(&p, "unusable")
                    .iter()
                    .map(|u| api::s(u, "id"))
                    .collect();
                this.live.chat.harnesses = api::arr(&p, "harnesses")
                    .iter()
                    .map(|h| (api::s(h, "id"), api::s(h, "label")))
                    .filter(|(id, _)| !unusable.contains(id))
                    .collect();
                let preferred = p
                    .get("chosen")
                    .map(|c| api::s(c, "preferred_harness"))
                    .unwrap_or_default();
                let known = this
                    .live
                    .chat
                    .harnesses
                    .iter()
                    .any(|(id, _)| *id == preferred);
                let first = this.live.chat.harnesses.first().map(|(id, _)| id.clone());
                if this.live.chat.harness.is_empty()
                    || !this
                        .live
                        .chat
                        .harnesses
                        .iter()
                        .any(|(id, _)| *id == this.live.chat.harness)
                {
                    this.live.chat.harness = if known {
                        preferred
                    } else {
                        first.unwrap_or_default()
                    };
                }
                this.live.chat.local_note = local_note(&p);
            },
        );
    }

    /// Reads one conversation's messages and, if a turn is still running in
    /// it, starts following that turn again.
    pub fn open_chat_thread(&mut self, thread_id: String, cx: &mut Context<Self>) {
        let previous = self.live.chat.thread.clone().unwrap_or_default();
        self.live
            .chat
            .drafts
            .insert(previous, self.chat_input.value.clone());
        let draft = self
            .live
            .chat
            .drafts
            .get(&thread_id)
            .cloned()
            .unwrap_or_default();
        self.chat_input.set_value(draft);
        self.live.chat.select_thread(thread_id.clone());
        self.load_chat_messages(thread_id, cx);
    }

    fn load_chat_messages(&mut self, thread_id: String, cx: &mut Context<Self>) {
        let id = thread_id.clone();
        self.fetch(
            cx,
            move || api::get(&format!("/api/chat/threads/{}/messages", api::seg(&id))),
            move |this, reply, cx| {
                this.note(&reply);
                if this.live.chat.thread.as_deref() != Some(thread_id.as_str()) {
                    return;
                }
                if let Ok(v) = reply {
                    this.live.chat.messages =
                        api::arr(&v, "items").iter().map(message_from).collect();
                    let recovered = api::s(&v, "job_id");
                    if !recovered.is_empty() {
                        this.live
                            .chat
                            .running
                            .insert(thread_id.clone(), recovered.clone());
                        this.live.chat.in_flight = Some(InFlight {
                            thread_id: thread_id.clone(),
                            job_id: recovered,
                        });
                    }
                    let running = this
                        .live
                        .chat
                        .in_flight
                        .as_ref()
                        .filter(|f| f.thread_id == thread_id)
                        .map(|f| f.job_id.clone());
                    if let Some(job_id) = running {
                        this.watch_chat_job(thread_id.clone(), job_id, cx);
                    }
                }
            },
        );
    }

    /// A new, empty conversation, opened at once.
    pub fn new_chat_thread(&mut self, cx: &mut Context<Self>) {
        self.fetch(
            cx,
            || api::post("/api/chat/threads", json!({})),
            |this, reply, cx| {
                this.note(&reply);
                match reply {
                    Ok(v) => {
                        let thread = thread_from(&v);
                        this.live.chat.threads.insert(0, thread.clone());
                        this.open_chat_thread(thread.thread_id, cx);
                    }
                    Err(e) => this.live.chat.say = Some(e.message),
                }
            },
        );
    }

    /// Keep a discovery request in its own unsent thread. Existing drafts and
    /// running turns survive; navigation or typing during the request wins.
    pub fn open_discovery_chat(&mut self, prompt: String, cx: &mut Context<Self>) {
        if self.live.chat.discovery_pending {
            return;
        }
        self.live.chat.discovery_pending = true;
        let previous = self.live.chat.thread.clone();
        let typed = self.chat_input.value.clone();
        let title: String = prompt.chars().take(200).collect();
        self.fetch(
            cx,
            move || api::post("/api/chat/threads", json!({"title": title})),
            move |this, reply, cx| {
                this.note(&reply);
                match reply {
                    Ok(v) => {
                        let thread = thread_from(&v);
                        let id = thread.thread_id.clone();
                        let input = this.live.chat.finish_discovery(
                            thread,
                            prompt,
                            (previous.as_deref(), &typed),
                            &this.chat_input.value,
                            this.tab == Tab::Chat,
                        );
                        if let Some(input) = input {
                            this.chat_input.set_value(input);
                            this.load_chat_messages(id, cx);
                            this.refresh_chat(cx);
                        }
                    }
                    Err(e) => {
                        this.live.chat.discovery_pending = false;
                        this.live.chat.say = Some(e.message);
                    }
                }
            },
        );
    }

    /// Forgets the open conversation and its messages, then opens the next one.
    pub fn delete_chat_thread(&mut self, cx: &mut Context<Self>) {
        let Some(id) = self.live.chat.thread.clone() else {
            return;
        };
        if self
            .live
            .chat
            .in_flight
            .as_ref()
            .is_some_and(|f| f.thread_id == id)
        {
            self.live.chat.say =
                Some("Wait for the answer, or stop it, before deleting this conversation.".into());
            return;
        }
        let path = format!("/api/chat/threads/{}", api::seg(&id));
        self.fetch(
            cx,
            move || api::delete(&path),
            move |this, reply, cx| {
                this.note(&reply);
                if reply.is_ok() {
                    this.live.chat.threads.retain(|t| t.thread_id != id);
                    this.live.chat.drafts.remove(&id);
                    this.live.chat.thread = None;
                    this.live.chat.messages.clear();
                    this.live.chat.partial = None;
                    this.live.chat.failed = None;
                    this.refresh_chat(cx);
                } else {
                    this.live.chat.say = Some("That conversation is already gone.".into());
                }
            },
        );
    }

    /// Sends the composer's question into the open conversation (starting one
    /// if none is open). The reader's message is stored at once by the engine;
    /// the answer arrives as the job finishes.
    pub fn send_chat_message(&mut self, cx: &mut Context<Self>) {
        let text = self.chat_input.value.trim().to_string();
        if text.is_empty() || self.live.chat.sending || self.live.chat.in_flight.is_some() {
            return;
        }
        if text.chars().count() > 2000 {
            self.live.chat.say =
                Some("Message too long. Shorten it to 2000 characters before sending.".into());
            return;
        }
        self.live.chat.sending = true;
        self.live.chat.say = None;
        self.live.chat.failed = None;
        let harness = self.live.chat.harness.clone();
        let backend = if harness == "local" {
            "local"
        } else {
            "harness"
        };
        let existing = self.live.chat.thread.clone();
        let selected_at_submit = existing.clone();
        let submitted_text = text.clone();
        self.fetch(
            cx,
            move || {
                let thread = match existing {
                    Some(id) => id,
                    None => api::post("/api/chat/threads", json!({"title": text}))?
                        .get("thread_id")
                        .and_then(|v| v.as_str())
                        .map(str::to_string)
                        .unwrap_or_default(),
                };
                let path = format!("/api/chat/threads/{}/messages", api::seg(&thread));
                let posted = api::post(
                    &path,
                    json!({"text": text, "harness": harness, "backend": backend}),
                )?;
                Ok::<(String, Value), api::ApiError>((thread, posted))
            },
            move |this, reply, cx| {
                this.live.chat.sending = false;
                this.note(&reply);
                match reply {
                    Ok((thread, posted)) => {
                        let job_id = api::s(&posted, "job_id");
                        this.live
                            .chat
                            .running
                            .insert(thread.clone(), job_id.clone());
                        if this
                            .live
                            .chat
                            .drafts
                            .get(&thread)
                            .is_some_and(|draft| draft.trim() == submitted_text)
                        {
                            this.live.chat.drafts.remove(&thread);
                        }
                        if this.live.chat.thread == selected_at_submit {
                            if this.chat_input.value.trim() == submitted_text {
                                this.chat_input.set_value(String::new());
                                this.live.chat.drafts.remove(&thread);
                            }
                            this.live.chat.thread = Some(thread.clone());
                            this.live.chat.in_flight = Some(InFlight {
                                thread_id: thread.clone(),
                                job_id: job_id.clone(),
                            });
                            this.live.chat.partial = Some(Partial::default());
                            this.live.chat.job_message = "queued".into();
                            this.load_chat_messages(thread.clone(), cx);
                        }
                        this.refresh_chat(cx);
                        this.watch_chat_job(thread, job_id, cx);
                    }
                    Err(e) => {
                        if this.live.chat.thread == selected_at_submit {
                            this.live.chat.say = Some(e.message);
                        }
                    }
                }
            },
        );
    }

    pub fn stop_chat_turn(&mut self, cx: &mut Context<Self>) {
        let Some(flight) = self.live.chat.in_flight.clone() else {
            return;
        };
        let job_id = flight.job_id.clone();
        self.fetch(
            cx,
            move || {
                api::post(
                    &format!("/api/jobs/{}/cancel", api::seg(&job_id)),
                    json!({}),
                )
            },
            move |this, reply, _| {
                if this.live.chat.thread.as_deref() != Some(flight.thread_id.as_str()) {
                    return;
                }
                match reply {
                    Ok(_) => this.live.chat.job_message = "Stopping…".into(),
                    Err(e) => this.live.chat.say = Some(e.message),
                }
            },
        );
    }

    pub fn retry_chat_turn(&mut self, cx: &mut Context<Self>) {
        if let Some(message) = self
            .live
            .chat
            .messages
            .iter()
            .rev()
            .find(|m| m.role == Role::Reader)
        {
            self.chat_input.set_value(message.text.clone());
            self.send_chat_message(cx);
        }
    }

    /// Read one product again, now: the engine looks it up by the identity its
    /// catalog records and answers with what is known about it today.
    ///
    /// A chat answer is a reading of the catalog at the moment it was written.
    /// This is the reader saying "and now": the same product, read again, with
    /// the result saved so Browse and Compare see it too.
    pub fn chat_research_product(&mut self, subject_id: String, cx: &mut Context<Self>) {
        if self.live.chat.product_busy.is_some() {
            return;
        }
        self.live.chat.product_busy = Some(subject_id.clone());
        self.live.chat.product_note = None;
        let asked = subject_id.clone();
        self.fetch(
            cx,
            move || api::product_check(&subject_id),
            move |this, reply, cx| {
                this.live.chat.product_busy = None;
                match reply {
                    Ok(v) => {
                        let risks = api::arr(&v, "claims").len();
                        let label = api::s(&v, "label");
                        this.live.chat.product_queued = None;
                        this.live.chat.product_note = Some((
                            asked.clone(),
                            if risks == 0 {
                                format!("{label}: nothing recorded against it.")
                            } else {
                                format!("{label}: {risks} recorded.")
                            },
                        ));
                        // The screen that reads saved checks has new data.
                        this.refresh_history(cx);
                    }
                    Err(e) => {
                        this.live.chat.product_note = Some((asked.clone(), e.message));
                    }
                }
                cx.notify();
            },
        );
    }

    /// Put one product in the compare queue, which is what the Compare screen
    /// reads.
    ///
    /// The saved check comes first, in the same call, and that is the whole
    /// point rather than tidiness: Compare reads *saved checks*, and the queue
    /// resolves a row to a product through the answer it was queued with. A
    /// product queued with neither resolves by its name, which is the guess
    /// `productchecks` exists to avoid — and a product the catalog names but
    /// nothing has read yet has no answer at all. So this makes the check and
    /// then queues it, and a failure to make the check is a failure to queue:
    /// an empty row in Compare is worse than a sentence saying why.
    pub fn chat_compare_product(
        &mut self,
        subject_id: String,
        name: String,
        cx: &mut Context<Self>,
    ) {
        self.live.chat.product_note = None;
        let asked = subject_id.clone();
        self.fetch(
            cx,
            move || {
                let checked = api::product_check(&subject_id)?;
                let queued = api::product_to_compare(&subject_id, &name)?;
                Ok::<_, api::ApiError>((checked, queued))
            },
            move |this, reply, cx| {
                match reply {
                    Ok((_, v)) => {
                        let added = api::b(&v, "added");
                        let requeued = api::b(&v, "requeued");
                        this.live.chat.product_queued = Some(asked.clone());
                        this.live.chat.product_note = Some((
                            asked.clone(),
                            if added {
                                "Added to Compare.".to_string()
                            } else if requeued {
                                "Back in the Compare queue.".to_string()
                            } else {
                                "Already in Compare.".to_string()
                            },
                        ));
                        this.refresh_compare(cx);
                    }
                    Err(e) => {
                        this.live.chat.product_note = Some((asked.clone(), e.message));
                    }
                }
                cx.notify();
            },
        );
    }

    /// Follows one turn's job until it ends: the steps as they are read, then
    /// the conversation as the engine stored it.
    fn watch_chat_job(&mut self, thread_id: String, job_id: String, cx: &mut Context<Self>) {
        if !self.live.chat.watching.insert(job_id.clone()) {
            return;
        }
        cx.spawn(async move |this, cx| loop {
            cx.background_executor()
                .timer(Duration::from_millis(700))
                .await;
            let ex = cx.background_executor().clone();
            let path = format!("/api/jobs/{}", api::seg(&job_id));
            let reply = bg(&ex, move || api::get(&path)).await;
            let (tid, jid) = (thread_id.clone(), job_id.clone());
            let finished = this
                .update(cx, |this, cx| match reply {
                    Ok(job) => {
                        if !api::b(&job, "done") {
                            if this.live.chat.thread.as_deref() == Some(tid.as_str()) {
                                this.live.chat.partial = Some(Partial::from_result(
                                    job.get("result").unwrap_or(&Value::Null),
                                ));
                                this.live.chat.job_message = api::s(&job, "message");
                            }
                            cx.notify();
                            return false;
                        }
                        let failure = if api::s(&job, "state") != "succeeded" {
                            let why = api::s(&job, "message");
                            Some(if why.is_empty() { "The turn did not finish.".into() } else { why })
                        } else { None };
                        this.live.chat.finish_job(&tid, &jid, failure);
                        if this.live.chat.thread.as_deref() == Some(tid.as_str()) {
                            this.load_chat_messages(tid, cx);
                        }
                        this.refresh_chat(cx);
                        true
                    }
                    Err(e) => {
                        // A failed poll says nothing about whether the agent stopped.
                        // Keep the job identity so Stop and a later reconnect still work.
                        this.live.chat.watching.remove(&jid);
                        if this.live.chat.thread.as_deref() == Some(tid.as_str()) {
                            this.live.chat.say = Some(format!("Connection interrupted: {}. Reopen this conversation to reconnect.", e.message));
                        }
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
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn discovery_keeps_the_old_draft_and_job_in_its_original_thread() {
        let mut state = State::default();
        state.running.insert("old".into(), "job-old".into());
        state.select_thread("old".into());
        state.discovery_pending = true;
        let input = state.finish_discovery(
            Thread {
                thread_id: "new".into(),
                title: "Find a device".into(),
            },
            "Find a device".into(),
            (Some("old"), "My unfinished question"),
            "My unfinished question",
            true,
        );
        assert_eq!(input.as_deref(), Some("Find a device"));
        assert_eq!(state.thread.as_deref(), Some("new"));
        assert_eq!(
            state.drafts.get("old").map(String::as_str),
            Some("My unfinished question")
        );
        assert_eq!(
            state.drafts.get("new").map(String::as_str),
            Some("Find a device")
        );
        assert_eq!(
            state.running.get("old").map(String::as_str),
            Some("job-old")
        );
        assert!(state.in_flight.is_none());
        assert!(!state.discovery_pending);
    }

    #[test]
    fn typing_while_discovery_opens_cannot_be_overwritten_by_its_response() {
        let mut state = State::default();
        let input = state.finish_discovery(
            Thread {
                thread_id: "new".into(),
                title: "Find a device".into(),
            },
            "Find a device".into(),
            (None, ""),
            "A question just typed",
            true,
        );
        assert!(input.is_none());
        assert!(state.thread.is_none());
        assert_eq!(
            state.drafts.get("new").map(String::as_str),
            Some("Find a device")
        );
    }

    #[test]
    fn discovery_cannot_switch_back_after_the_reader_leaves_the_thread() {
        let mut state = State::default();
        state.select_thread("other".into());
        let input = state.finish_discovery(
            Thread {
                thread_id: "new".into(),
                title: "Find a device".into(),
            },
            "Find a device".into(),
            (Some("old"), ""),
            "",
            true,
        );
        assert!(input.is_none());
        assert_eq!(state.thread.as_deref(), Some("other"));
        let background_input = state.finish_discovery(
            Thread {
                thread_id: "background".into(),
                title: "Find another".into(),
            },
            "Find another".into(),
            (Some("other"), ""),
            "",
            false,
        );
        assert!(background_input.is_none());
        assert_eq!(state.thread.as_deref(), Some("other"));
    }

    #[test]
    fn changing_threads_keeps_their_independent_jobs() {
        let mut state = State::default();
        state.running.insert("first".into(), "job-a".into());
        state.select_thread("first".into());
        assert_eq!(state.in_flight.as_ref().unwrap().job_id, "job-a");
        state.select_thread("second".into());
        assert!(
            state.in_flight.is_none(),
            "another conversation can send while the first answers"
        );
        state.running.insert("second".into(), "job-b".into());
        state.select_thread("second".into());
        state.partial = Some(Partial {
            answer: "Second answer so far".into(),
            ..Partial::default()
        });
        state.finish_job("first", "job-a", Some("First failed".into()));
        assert_eq!(state.in_flight.as_ref().unwrap().job_id, "job-b");
        assert_eq!(
            state.partial.as_ref().unwrap().answer,
            "Second answer so far"
        );
        assert!(
            state.failed.is_none(),
            "a background failure belongs to its own conversation"
        );
        state.finish_job("second", "job-b", None);
        assert!(state.in_flight.is_none());
        assert!(state.running.is_empty());
    }

    #[test]
    fn an_older_job_cannot_clear_a_newer_turn_in_the_same_thread() {
        let mut state = State::default();
        state.running.insert("thread".into(), "new-job".into());
        state.select_thread("thread".into());
        state.finish_job("thread", "old-job", Some("old failure".into()));
        assert_eq!(
            state.running.get("thread").map(String::as_str),
            Some("new-job")
        );
        assert_eq!(state.in_flight.as_ref().unwrap().job_id, "new-job");
        assert!(state.failed.is_none());
    }

    #[test]
    fn a_step_state_word_maps_to_its_state_and_an_unknown_one_is_still_running() {
        assert_eq!(StepState::from_word("done"), StepState::Done);
        assert_eq!(StepState::from_word("empty"), StepState::Empty);
        assert_eq!(StepState::from_word("error"), StepState::Error);
        assert_eq!(StepState::from_word("running"), StepState::Running);
        assert_eq!(StepState::from_word("something new"), StepState::Running);
        assert!(StepState::Done.is_settled());
        assert!(!StepState::Running.is_settled());
    }

    #[test]
    fn a_turn_so_far_reads_its_steps_and_answer_from_the_job_result() {
        let result = json!({
            "steps": [
                {"id": "s1", "source": "product_match", "label": "read 4 products",
                 "state": "done", "rows": 4, "ms": 12, "detail": "4 candidate(s)"},
                {"id": "s2", "source": "saved_checks", "label": "reading saved checks",
                 "state": "running", "rows": 0, "ms": 0, "detail": ""},
            ],
            "answer": "",
            "sources": ["product_match"],
            "agent": {"id": "local", "label": "Local model"},
        });
        let partial = Partial::from_result(&result);
        assert_eq!(partial.steps.len(), 2);
        assert_eq!(partial.steps[0].state, StepState::Done);
        assert_eq!(partial.steps[0].rows, 4);
        assert_eq!(partial.steps[1].state, StepState::Running);
        assert_eq!(partial.sources, vec!["product_match".to_string()]);
        assert_eq!(partial.agent, "Local model");
        assert!(partial.answer.is_empty());
    }

    #[test]
    fn a_missing_result_is_an_empty_turn_not_an_error() {
        let partial = Partial::from_result(&Value::Null);
        assert_eq!(partial, Partial::default());
    }

    #[test]
    fn a_step_says_how_many_rows_and_how_long_once_it_has_finished() {
        let done = Step {
            id: "s1".into(),
            source: "packs".into(),
            label: "read 2 catalogues".into(),
            state: StepState::Done,
            rows: 2,
            ms: 9,
            detail: String::new(),
        };
        assert_eq!(step_meta(&done), "2 rows · 9 ms");
        let one = Step {
            rows: 1,
            ..done.clone()
        };
        assert_eq!(step_meta(&one), "1 row · 9 ms");
        let running = Step {
            state: StepState::Running,
            ..done.clone()
        };
        assert_eq!(step_meta(&running), "reading");
        let failed = Step {
            state: StepState::Error,
            ..done
        };
        assert_eq!(step_meta(&failed), "failed");
    }

    #[test]
    fn a_thread_with_no_title_has_a_plain_name() {
        let untitled = Thread {
            thread_id: "t".into(),
            title: "  ".into(),
        };
        assert_eq!(untitled.name(), "New conversation");
        let named = Thread {
            title: "Find a widget".into(),
            ..untitled
        };
        assert_eq!(named.name(), "Find a widget");
    }

    #[test]
    fn a_stored_message_keeps_its_steps_and_sources() {
        let message = message_from(&json!({
            "message_id": "m1", "role": "agent", "text": "Done.",
            "steps": [{"id": "s1", "source": "packs", "label": "no rows from catalogues",
                       "state": "empty", "rows": 0, "ms": 3, "detail": ""}],
            "sources": ["packs"],
        }));
        assert_eq!(message.role, Role::Agent);
        assert_eq!(message.steps[0].state, StepState::Empty);
        assert_eq!(message.sources, vec!["packs".to_string()]);
        assert_eq!(Role::from_word("reader"), Role::Reader);
    }
}
