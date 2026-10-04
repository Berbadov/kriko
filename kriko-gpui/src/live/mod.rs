//! What the engine says, held for the screens. Each area of the app keeps
//! its slice here and refreshes it through [`Kriko::fetch`], so a screen
//! renders from one place and never waits on the network while it draws.
//!
//! A slice starts empty and `loaded == false`; a screen shows its own
//! empty state until then, never sample numbers.
//!
//! One file per area, so the areas can be worked on side by side:
//! `history` (History, Home, Browse, Activity), `compare`, `run` (Run, the
//! dock, Agents), `knowledge` (Overview, Sites, Extension, Settings, About)
//! and `local` (Local LLM, Benchmark).

pub mod compare;
pub mod history;
pub mod knowledge;
pub mod local;
pub mod run;

use gpui::Context;

use crate::api::{self, Value};
use crate::app::Kriko;

/// The engine's own facts, from `/api/health`.
#[derive(Default, Clone)]
pub struct Health {
    pub loaded: bool,
    pub version: String,
    pub schema_version: i64,
    pub store: String,
    pub app_state: String,
    pub log_file: String,
    pub releases_url: String,
    pub extension_port: i64,
    pub port_is_ours: bool,
    pub packs: Vec<(String, String)>,
}

#[derive(Default)]
pub struct Live {
    pub health: Health,
    pub history: history::State,
    pub compare: compare::State,
    pub run: run::State,
    pub knowledge: knowledge::State,
    pub local: local::State,
    /// The last thing that went wrong talking to the engine, for the status
    /// line; cleared by the next success.
    pub problem: Option<String>,
}

impl Kriko {
    /// Runs `work` (blocking HTTP) on the background executor, then `apply`
    /// on the UI thread with its answer, and redraws. The one way a screen
    /// talks to the engine.
    pub fn fetch<R: Send + 'static>(
        &mut self,
        cx: &mut Context<Self>,
        work: impl FnOnce() -> R + Send + 'static,
        apply: impl FnOnce(&mut Kriko, R, &mut Context<Kriko>) + 'static,
    ) {
        cx.spawn(async move |this, cx| {
            let answer = cx.background_executor().spawn(async move { work() }).await;
            this.update(cx, |this, cx| {
                apply(this, answer, cx);
                cx.notify();
            })
            .ok();
        })
        .detach();
    }

    /// Notes a failed call for the status line, or clears the last one.
    pub fn note<T>(&mut self, reply: &Result<T, api::ApiError>) {
        match reply {
            Ok(_) => self.live.problem = None,
            Err(e) => self.live.problem = Some(e.message.clone()),
        }
    }

    /// Everything a fresh window needs, asked for at once when the engine
    /// first answers. Each slice lands on its own; none waits on another.
    pub fn refresh_all(&mut self, cx: &mut Context<Self>) {
        self.refresh_health(cx);
        self.refresh_history(cx);
        self.refresh_compare(cx);
        self.refresh_run(cx);
        self.refresh_knowledge(cx);
        self.refresh_local(cx);
    }

    pub fn refresh_health(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/health"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.health = health_from(&v);
            }
        });
    }
}

fn health_from(v: &Value) -> Health {
    Health {
        loaded: true,
        version: api::s(v, "version"),
        schema_version: api::n(v, "schema_version").unwrap_or(0.0) as i64,
        store: api::s(v, "store"),
        app_state: api::s(v, "app_state"),
        log_file: api::s(v, "log_file"),
        releases_url: api::s(v, "releases_url"),
        extension_port: api::n(v, "extension_port").unwrap_or(0.0) as i64,
        port_is_ours: api::b(v, "port_is_ours"),
        packs: api::arr(v, "packs")
            .iter()
            .map(|p| (api::s(p, "pack_id"), api::s(p, "version")))
            .collect(),
    }
}
