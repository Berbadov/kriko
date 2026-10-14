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

use std::collections::HashSet;
use std::time::Duration;

use gpui::{BackgroundExecutor, Context};
use serde_json::json;

use crate::api::{self, Value};
use crate::app::Kriko;

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
        _ => format!("{} {} · {} ms", step.rows, if step.rows == 1 { "row" } else { "rows" }, step.ms),
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

#[derive(Clone)]
pub struct Message {
    pub message_id: String,
    pub role: Role,
    pub text: String,
    pub steps: Vec<Step>,
    pub sources: Vec<String>,
}

/// The turn in flight, as the job's result holds it so far.
#[derive(Clone, Default, Debug, PartialEq)]
pub struct Partial {
    pub steps: Vec<Step>,
    pub answer: String,
    pub sources: Vec<String>,
    pub agent: String,
}

impl Partial {
    /// Read a job's `result` while it runs. Missing parts are empty, never an error.
    pub fn from_result(result: &Value) -> Partial {
        Partial {
            steps: api::arr(result, "steps").iter().map(Step::from_value).collect(),
            answer: api::s(result, "answer"),
            sources: names(result, "sources"),
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
    }
}

fn thread_from(v: &Value) -> Thread {
    Thread {
        thread_id: api::s(v, "thread_id"),
        title: api::s(v, "title"),
    }
}

/// The source names and meanings the agent may ask for. Names only; no data.
#[derive(Clone)]
pub struct SourceInfo {
    pub name: String,
    pub description: String,
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
    pub sources: Vec<SourceInfo>,
    /// A question is being posted (before its job exists).
    pub sending: bool,
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
}

// ---- reading the engine ----

fn thread_list(v: &Value) -> Vec<Thread> {
    api::arr(v, "items").iter().map(thread_from).collect()
}

async fn bg<T: Send + 'static>(ex: &BackgroundExecutor, work: impl FnOnce() -> T + Send + 'static) -> T {
    ex.spawn(async move { work() }).await
}

impl Kriko {
    /// Everything the Chat screen shows, read when it is opened: the threads,
    /// the agents that can answer, and the names of what the agent may read.
    pub fn refresh_chat(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/chat/threads"), |this, reply, cx| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.chat.threads = thread_list(&v);
                this.live.chat.loaded = true;
                // Only when nothing is open: a conversation just started may not
                // be in this list yet, and must not be replaced by the first one.
                if this.live.chat.thread.is_none() {
                    // The newest conversation, or none: a fresh install shows
                    // the empty state, never a blank conversation.
                    if let Some(id) = this.live.chat.threads.first().map(|t| t.thread_id.clone()) {
                        this.open_chat_thread(id, cx);
                    }
                }
            }
        });
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
                let known = this.live.chat.harnesses.iter().any(|(id, _)| *id == preferred);
                let first = this.live.chat.harnesses.first().map(|(id, _)| id.clone());
                if this.live.chat.harness.is_empty() || !this.live.chat.harnesses.iter().any(|(id, _)| *id == this.live.chat.harness) {
                    this.live.chat.harness = if known { preferred } else { first.unwrap_or_default() };
                }
            },
        );
        if self.live.chat.sources.is_empty() {
            self.fetch(cx, || api::get("/api/chat/sources"), |this, reply, _| {
                if let Ok(v) = reply {
                    this.live.chat.sources = api::arr(&v, "items")
                        .iter()
                        .map(|s| SourceInfo {
                            name: api::s(s, "name"),
                            description: api::s(s, "description"),
                        })
                        .collect();
                }
            });
        }
    }

    /// Reads one conversation's messages and, if a turn is still running in
    /// it, starts following that turn again.
    pub fn open_chat_thread(&mut self, thread_id: String, cx: &mut Context<Self>) {
        self.live.chat.thread = Some(thread_id.clone());
        self.live.chat.messages.clear();
        self.live.chat.failed = None;
        self.live.chat.say = None;
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
                    this.live.chat.messages = api::arr(&v, "items").iter().map(message_from).collect();
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
        self.fetch(cx, || api::post("/api/chat/threads", json!({})), |this, reply, cx| {
            this.note(&reply);
            match reply {
                Ok(v) => {
                    let thread = thread_from(&v);
                    this.live.chat.threads.insert(0, thread.clone());
                    this.open_chat_thread(thread.thread_id, cx);
                }
                Err(e) => this.live.chat.say = Some(e.message),
            }
        });
    }

    /// Forgets the open conversation and its messages, then opens the next one.
    pub fn delete_chat_thread(&mut self, cx: &mut Context<Self>) {
        let Some(id) = self.live.chat.thread.clone() else { return };
        if self.live.chat.in_flight.as_ref().is_some_and(|f| f.thread_id == id) {
            self.live.chat.say = Some("Wait for the answer, or stop it, before deleting this conversation.".into());
            return;
        }
        let path = format!("/api/chat/threads/{}", api::seg(&id));
        self.fetch(cx, move || api::delete(&path), move |this, reply, cx| {
            this.note(&reply);
            if reply.is_ok() {
                this.live.chat.threads.retain(|t| t.thread_id != id);
                this.live.chat.thread = None;
                this.live.chat.messages.clear();
                this.live.chat.partial = None;
                this.live.chat.failed = None;
                this.refresh_chat(cx);
            } else {
                this.live.chat.say = Some("That conversation is already gone.".into());
            }
        });
    }

    /// Sends the composer's question into the open conversation (starting one
    /// if none is open). The reader's message is stored at once by the engine;
    /// the answer arrives as the job finishes.
    pub fn send_chat_message(&mut self, cx: &mut Context<Self>) {
        let text = self.chat_input.value.trim().to_string();
        if text.is_empty() || self.live.chat.sending || self.live.chat.in_flight.is_some() {
            return;
        }
        self.live.chat.sending = true;
        self.live.chat.say = None;
        self.live.chat.failed = None;
        let harness = self.live.chat.harness.clone();
        let backend = if harness == "local" { "local" } else { "harness" };
        let existing = self.live.chat.thread.clone();
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
                let posted = api::post(&path, json!({"text": text, "harness": harness, "backend": backend}))?;
                Ok::<(String, Value), api::ApiError>((thread, posted))
            },
            move |this, reply, cx| {
                this.live.chat.sending = false;
                this.note(&reply);
                match reply {
                    Ok((thread, posted)) => {
                        let job_id = api::s(&posted, "job_id");
                        this.chat_input.set_value(String::new());
                        this.live.chat.thread = Some(thread.clone());
                        this.live.chat.in_flight = Some(InFlight { thread_id: thread.clone(), job_id: job_id.clone() });
                        this.live.chat.partial = Some(Partial::default());
                        this.live.chat.job_message = "queued".into();
                        this.refresh_chat(cx);
                        this.load_chat_messages(thread.clone(), cx);
                        this.watch_chat_job(thread, job_id, cx);
                    }
                    Err(e) => this.live.chat.say = Some(e.message),
                }
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
            cx.background_executor().timer(Duration::from_millis(700)).await;
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
                        this.live.chat.watching.remove(&jid);
                        if this.live.chat.in_flight.as_ref().is_some_and(|f| f.job_id == jid) {
                            this.live.chat.in_flight = None;
                        }
                        this.live.chat.partial = None;
                        this.live.chat.job_message.clear();
                        if api::s(&job, "state") != "succeeded" {
                            let why = api::s(&job, "message");
                            this.live.chat.failed = Some(if why.is_empty() { "The turn did not finish.".into() } else { why });
                        }
                        if this.live.chat.thread.as_deref() == Some(tid.as_str()) {
                            this.load_chat_messages(tid, cx);
                        }
                        this.refresh_chat(cx);
                        true
                    }
                    Err(e) => {
                        this.live.chat.watching.remove(&jid);
                        this.live.chat.in_flight = None;
                        this.live.chat.partial = None;
                        this.live.chat.failed = Some(e.message);
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
            id: "s1".into(), source: "packs".into(), label: "read 2 catalogues".into(),
            state: StepState::Done, rows: 2, ms: 9, detail: String::new(),
        };
        assert_eq!(step_meta(&done), "2 rows · 9 ms");
        let one = Step { rows: 1, ..done.clone() };
        assert_eq!(step_meta(&one), "1 row · 9 ms");
        let running = Step { state: StepState::Running, ..done.clone() };
        assert_eq!(step_meta(&running), "reading");
        let failed = Step { state: StepState::Error, ..done };
        assert_eq!(step_meta(&failed), "failed");
    }

    #[test]
    fn a_thread_with_no_title_has_a_plain_name() {
        let untitled = Thread { thread_id: "t".into(), title: "  ".into() };
        assert_eq!(untitled.name(), "New conversation");
        let named = Thread { title: "Find a widget".into(), ..untitled };
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
