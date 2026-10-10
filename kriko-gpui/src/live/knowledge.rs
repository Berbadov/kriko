//! Overview, Sites, Browser extension, Settings and About, as the engine says it.
//!
//! Every slice starts empty; a screen shows its own note until the answer
//! lands. Long work (a pack update, teaching Kriko a site) is a job: the POST
//! returns an id and [`Kriko::follow_job`] polls it until it is done.

use std::time::{Duration, SystemTime, UNIX_EPOCH};

use gpui::Context;

use crate::api::{self, Value};
use crate::app::{Kriko, Tab};
use crate::engine;
use crate::startup::{self, Mode as StartupMode};

// ---- the shapes the screens draw ----

#[derive(Clone, Default)]
pub struct PackRow {
    pub id: String,
    pub name: String,
    pub version: String,
    pub enabled: bool,
    pub subjects: i64,
    pub claims: i64,
}

#[derive(Clone, Default)]
pub struct Totals {
    pub subjects: i64,
    pub claims: i64,
    pub evidence: i64,
    pub packs: i64,
    pub enabled_packs: i64,
}

#[derive(Clone)]
pub struct Gap {
    pub label: String,
    pub kind: String,
    pub pack_id: String,
}

#[derive(Clone)]
pub struct Thin {
    pub pack_id: String,
    pub claim_id: String,
    pub subject_id: String,
    pub subject: String,
    pub title: String,
    pub sources: i64,
    pub refuted_by: i64,
}

#[derive(Clone)]
pub struct Quote {
    pub quote: String,
    pub domain: String,
    pub stance: String,
    pub tier: String,
}

#[derive(Clone)]
pub struct Offer {
    pub pack_id: String,
    pub name: String,
    pub installed: String,
    pub offered: String,
}

/// A job as the polling loop last saw it.
#[derive(Clone, Default)]
pub struct JobView {
    pub state: String,
    pub message: String,
    pub done: bool,
}

#[derive(Clone)]
pub struct SiteReg {
    pub host: String,
    pub pack_id: String,
    pub local: bool,
    pub activation: String,
    pub detail: String,
}

#[derive(Clone)]
pub struct SiteReq {
    pub host: String,
    pub asks: i64,
    pub state: String,
    pub detail: String,
    pub last_at: String,
}

#[derive(Clone, Default)]
pub struct Browser {
    pub name: String,
    pub url: String,
}

#[derive(Clone, Default)]
pub struct ExtStatus {
    pub available: bool,
    pub version: String,
    pub staged: bool,
    pub staged_version: String,
    pub path: String,
    pub firefox_path: String,
    pub firefox_staged: bool,
    pub port: i64,
    pub port_is_ours: bool,
    pub browsers: Vec<Browser>,
    pub hits: i64,
    pub connected: bool,
    pub ever_connected: bool,
    pub seconds_since_seen: Option<f64>,
    pub compat_state: String,
    pub compat_detail: String,
}

#[derive(Clone)]
pub struct KeyRow {
    pub id: String,
    pub label: String,
    pub present: bool,
    pub source: String,
    pub hint: String,
}

#[derive(Default)]
pub struct State {
    pub loaded: bool,
    // Overview
    pub packs_loaded: bool,
    pub packs: Vec<PackRow>,
    pub totals: Totals,
    pub gaps: Vec<Gap>,
    pub thin_loaded: bool,
    pub thin: Vec<Thin>,
    pub thin_open: Option<String>,
    pub thin_quotes: Vec<Quote>,
    pub thin_quotes_loaded: bool,
    pub offers: Vec<Offer>,
    pub update_job: Option<JobView>,
    /// A pack the reader just switched, until the engine confirms.
    pub switching: Option<String>,
    // Sites
    pub sites_loaded: bool,
    pub registered: Vec<SiteReg>,
    pub requested: Vec<SiteReq>,
    pub site_job: Option<(String, JobView)>,
    pub sites_notice: Option<String>,
    // Extension
    pub ext: Option<ExtStatus>,
    pub ext_notice: Option<String>,
    // Settings
    pub settings_loaded: bool,
    pub keys_loaded: bool,
    pub keys: Vec<KeyRow>,
    pub keys_path: String,
    pub startup_mode: StartupMode,
    pub startup_busy: bool,
    pub startup_revision: u64,
    pub settings_notice: Option<String>,
    /// The provider the key field is being typed for.
    pub key_provider: Option<String>,
    pub erase_confirm: bool,
    pub erase_busy: bool,
    // App updates (`/api/app-update`)
    pub app_update: Option<AppUpdate>,
    pub app_update_note: Option<String>,
    pub app_update_busy: bool,
    /// The agent being installed for the reader, and how the job stands.
    pub agent_install: Option<(String, JobView)>,
}

/// What the releases page says about the app itself.
#[derive(Clone, Default)]
pub struct AppUpdate {
    pub newer: bool,
    pub version: String,
    pub notes: String,
    pub error: String,
}

/// The engine's own ceiling (`prefs.MAX_RUN_CONCURRENCY`); it clamps too.
pub const RUNS_MAX: usize = 4;

const REG_VALUE: &str = "Kriko";

impl Kriko {
    pub fn refresh_knowledge(&mut self, cx: &mut Context<Self>) {
        self.refresh_packs(cx);
        self.refresh_thin(cx);
        self.refresh_updates(cx);
        self.check_app_update(cx);
        self.refresh_sites(cx);
        self.refresh_extension(cx);
        self.refresh_settings(cx);
        self.refresh_keys(cx);
        self.refresh_startup(cx);
        self.live.knowledge.loaded = true;
    }

    /// A screen of this area came to the front: ask again for what it shows,
    /// so it never reads older than the last visit. Other areas' tabs are
    /// left alone.
    pub fn on_open_tab(&mut self, cx: &mut Context<Self>) {
        match self.tab {
            Tab::About => self.refresh_health(cx),
            Tab::Overview => {
                self.refresh_packs(cx);
                self.refresh_thin(cx);
                self.refresh_updates(cx);
            }
            Tab::Local => {
                self.refresh_local(cx);
                self.refresh_jobs(cx);
            }
            Tab::Sites => self.refresh_sites(cx),
            Tab::Extension => self.refresh_extension(cx),
            Tab::Settings => {
                self.refresh_local(cx);
                self.refresh_settings(cx);
                self.refresh_keys(cx);
                self.refresh_health(cx);
                self.refresh_startup(cx);
            }
            _ => {}
        }
    }

    // ---- Overview ----

    /// Packs, the totals of what is switched on, and the gaps of those packs.
    pub fn refresh_packs(&mut self, cx: &mut Context<Self>) {
        self.fetch(
            cx,
            || {
                let packs = api::get("/api/packs");
                let status = api::get("/api/status");
                let mut gaps = Vec::new();
                if let Ok(list) = &packs {
                    for p in api::arr(list, "") {
                        if !api::b(p, "enabled") {
                            continue;
                        }
                        let id = api::s(p, "pack_id");
                        if let Ok(g) = api::get(&format!("/api/packs/{}/gaps?limit=100", api::seg(&id))) {
                            for row in api::arr(&g, "") {
                                gaps.push(Gap {
                                    label: api::s(row, "label"),
                                    kind: api::s(row, "kind"),
                                    pack_id: id.clone(),
                                });
                            }
                        }
                    }
                }
                (packs, status, gaps)
            },
            |this, (packs, status, gaps), _| {
                this.note(&packs);
                let k = &mut this.live.knowledge;
                k.switching = None;
                if let Ok(list) = packs {
                    k.packs = api::arr(&list, "")
                        .iter()
                        .map(|p| PackRow {
                            id: api::s(p, "pack_id"),
                            name: api::s(p, "name"),
                            version: api::s(p, "version"),
                            enabled: api::b(p, "enabled"),
                            subjects: int(p, "subjects"),
                            claims: int(p, "claims"),
                        })
                        .collect();
                    k.gaps = gaps;
                    k.packs_loaded = true;
                }
                if let Ok(s) = status {
                    let on = s.get("counts_enabled").cloned().unwrap_or(Value::Null);
                    let all = s.get("counts").cloned().unwrap_or(Value::Null);
                    k.totals = Totals {
                        subjects: int(&on, "subjects"),
                        claims: int(&on, "claims"),
                        evidence: int(&on, "evidence"),
                        packs: int(&all, "packs"),
                        enabled_packs: int(&s, "enabled_packs"),
                    };
                }
            },
        );
    }

    /// The pack switch: `POST /api/packs/{id}/enabled?enabled=` with no body.
    pub fn set_pack_enabled(&mut self, pack_id: String, enabled: bool, cx: &mut Context<Self>) {
        self.live.knowledge.switching = Some(pack_id.clone());
        self.fetch(
            cx,
            move || {
                api::request(
                    "POST",
                    &format!("/api/packs/{}/enabled?enabled={}", api::seg(&pack_id), enabled),
                    None,
                )
            },
            |this, reply, cx| {
                this.note(&reply);
                this.live.knowledge.switching = None;
                this.refresh_packs(cx);
                this.refresh_thin(cx);
            },
        );
    }

    pub fn refresh_thin(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/health/weakest?limit=12"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                let k = &mut this.live.knowledge;
                k.thin = api::arr(&v, "claims")
                    .iter()
                    .map(|c| Thin {
                        pack_id: api::s(c, "pack_id"),
                        claim_id: api::s(c, "claim_id"),
                        subject_id: api::s(c, "subject_id"),
                        subject: api::s(c, "subject_label"),
                        title: api::s(c, "title"),
                        sources: int(c, "independent_sources"),
                        refuted_by: int(c, "refuted_by"),
                    })
                    .collect();
                k.thin_loaded = true;
            }
        });
    }

    /// Unfold one thin claim: its own evidence, from the subject's tree.
    pub fn toggle_thin(&mut self, claim_id: String, subject_id: String, cx: &mut Context<Self>) {
        let k = &mut self.live.knowledge;
        if k.thin_open.as_deref() == Some(claim_id.as_str()) {
            k.thin_open = None;
            return;
        }
        k.thin_open = Some(claim_id.clone());
        k.thin_quotes.clear();
        k.thin_quotes_loaded = false;
        self.fetch(
            cx,
            move || api::get(&format!("/api/health/subject/{}", api::seg(&subject_id))),
            move |this, reply, _| {
                this.note(&reply);
                let k = &mut this.live.knowledge;
                if k.thin_open.as_deref() != Some(claim_id.as_str()) {
                    return;
                }
                if let Ok(v) = reply {
                    k.thin_quotes = api::arr(&v, "claims")
                        .iter()
                        .filter(|c| {
                            c.get("health").map(|h| api::s(h, "claim_id")) == Some(claim_id.clone())
                        })
                        .flat_map(|c| api::arr(c, "evidence"))
                        .map(|e| Quote {
                            quote: api::s(e, "quote"),
                            domain: api::s(e, "domain"),
                            stance: api::s(e, "stance"),
                            tier: api::s(e, "tier"),
                        })
                        .collect();
                    k.thin_quotes_loaded = true;
                }
            },
        );
    }

    /// Which installed packs have a newer version offered. An index that
    /// cannot be reached offers nothing, and that is not an error here.
    pub fn refresh_updates(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/packs/updates"), |this, reply, _| {
            if let Ok(v) = reply {
                this.live.knowledge.offers = api::arr(&v, "packs")
                    .iter()
                    .filter(|p| api::s(p, "state") == "available" && !api::s(p, "installed_version").is_empty())
                    .map(|p| Offer {
                        pack_id: api::s(p, "pack_id"),
                        name: api::s(p, "name"),
                        installed: api::s(p, "installed_version"),
                        offered: api::s(p, "offered_version"),
                    })
                    .collect();
            }
        });
    }

    /// `POST /api/packs/update` is a job: follow it, then refresh.
    pub fn update_pack(&mut self, pack_id: String, cx: &mut Context<Self>) {
        self.live.knowledge.update_job = Some(JobView {
            state: "queued".into(),
            message: "Asking for the update.".into(),
            ..Default::default()
        });
        self.fetch(
            cx,
            move || api::post("/api/packs/update", serde_json::json!({ "pack_id": pack_id })),
            |this, reply, cx| {
                this.note(&reply);
                match reply {
                    Ok(v) => this.follow_job(api::s(&v, "job_id"), Followed::PackUpdate, cx),
                    Err(e) => {
                        this.live.knowledge.update_job = Some(JobView {
                            state: "failed".into(),
                            message: e.message,
                            done: true,
                            ..Default::default()
                        })
                    }
                }
            },
        );
    }

    /// Install an agent for the reader (for `local`: Ollama and a small model).
    pub fn install_agent(&mut self, agent_id: String, cx: &mut Context<Self>) {
        let pending = |message: &str, state: &str, done: bool| JobView {
            state: state.into(),
            message: message.into(),
            done,
        };
        self.live.knowledge.agent_install = Some((agent_id.clone(), pending("Starting the install.", "queued", false)));
        let id = agent_id.clone();
        self.fetch(
            cx,
            move || api::post(&format!("/api/agents/{}/install", api::seg(&id)), serde_json::json!({})),
            move |this, reply, cx| {
                this.note(&reply);
                match reply {
                    Ok(v) => this.follow_job(api::s(&v, "job_id"), Followed::AgentInstall(agent_id), cx),
                    Err(e) => {
                        this.live.knowledge.agent_install = Some((agent_id, pending(&e.message, "failed", true)))
                    }
                }
            },
        );
    }

    // ---- jobs ----

    /// Polls `GET /api/jobs/{id}` every ~700 ms until it is done, keeping
    /// the last view where the screen reads it, then refreshes what the job
    /// may have changed.
    pub fn follow_job(&mut self, job_id: String, which: Followed, cx: &mut Context<Self>) {
        if job_id.is_empty() {
            return;
        }
        cx.spawn(async move |this, cx| loop {
            cx.background_executor().timer(Duration::from_millis(700)).await;
            let id = job_id.clone();
            let reply = cx
                .background_executor()
                .spawn(async move { api::get(&format!("/api/jobs/{}", api::seg(&id))) })
                .await;
            let finished = this
                .update(cx, |this, cx| {
                    let view = match &reply {
                        Ok(v) => JobView {
                            state: api::s(v, "state"),
                            message: api::s(v, "message"),
                            done: api::b(v, "done"),
                        },
                        // a poll that failed is not a job that failed: ask again
                        Err(_) => return false,
                    };
                    let done = view.done;
                    match &which {
                        Followed::PackUpdate => this.live.knowledge.update_job = Some(view),
                        Followed::SiteRegister(host) => {
                            this.live.knowledge.site_job = Some((host.clone(), view))
                        }
                        Followed::AgentInstall(id) => {
                            this.live.knowledge.agent_install = Some((id.clone(), view))
                        }
                    }
                    if done {
                        match which {
                            Followed::AgentInstall(_) => {
                                this.refresh_run(cx);
                                this.refresh_local(cx);
                            }
                            Followed::PackUpdate => {
                                this.refresh_packs(cx);
                                this.refresh_thin(cx);
                                this.refresh_updates(cx);
                                this.refresh_health(cx);
                            }
                            Followed::SiteRegister(_) => {
                                this.refresh_sites(cx);
                                this.refresh_extension(cx);
                            }
                        }
                    }
                    cx.notify();
                    done
                })
                .unwrap_or(true);
            if finished {
                break;
            }
        })
        .detach();
    }

    // ---- Sites ----

    pub fn refresh_sites(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/sites"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                let k = &mut this.live.knowledge;
                k.registered = api::arr(&v, "registered")
                    .iter()
                    .map(|r| {
                        let act = r.get("activation").cloned().unwrap_or(Value::Null);
                        SiteReg {
                            host: api::s(r, "site"),
                            pack_id: api::s(r, "pack_id"),
                            local: api::s(r, "source") == "local",
                            activation: api::s(&act, "state"),
                            detail: api::s(&act, "detail"),
                        }
                    })
                    .collect();
                k.requested = api::arr(&v, "requested")
                    .iter()
                    .map(|r| SiteReq {
                        host: api::s(r, "host"),
                        asks: int(r, "asks"),
                        state: api::s(r, "state"),
                        detail: api::s(r, "detail"),
                        last_at: api::s(r, "last_at"),
                    })
                    .collect();
                k.sites_loaded = true;
            }
        });
    }

    /// Teach Kriko to read a site: `POST /api/sites/{host}/register`, a job.
    /// `input` is a host or a page address.
    pub fn register_site(&mut self, input: &str, cx: &mut Context<Self>) {
        let (host, url) = host_and_url(input);
        if host.is_empty() {
            return;
        }
        self.live.knowledge.sites_notice = None;
        self.live.knowledge.site_job = Some((
            host.clone(),
            JobView { state: "queued".into(), message: "Asking an agent to read the site.".into(), ..Default::default() },
        ));
        let name = host.clone();
        self.fetch(
            cx,
            move || {
                let body = if url.is_empty() { serde_json::json!({}) } else { serde_json::json!({ "url": url }) };
                api::post(&format!("/api/sites/{}/register", api::seg(&host)), body)
            },
            move |this, reply, cx| {
                this.note(&reply);
                match reply {
                    Ok(v) => {
                        this.refresh_sites(cx);
                        this.follow_job(api::s(&v, "job_id"), Followed::SiteRegister(name), cx);
                    }
                    Err(e) => {
                        this.live.knowledge.site_job = None;
                        this.live.knowledge.sites_notice = Some(e.message);
                    }
                }
            },
        );
    }

    /// Forget an adapter this install learned; packs are untouched.
    pub fn forget_site(&mut self, host: String, cx: &mut Context<Self>) {
        self.fetch(
            cx,
            move || api::delete(&format!("/api/sites/{}", api::seg(&host))),
            |this, reply, cx| {
                this.note(&reply);
                if let Err(e) = &reply {
                    this.live.knowledge.sites_notice = Some(e.message.clone());
                }
                this.refresh_sites(cx);
            },
        );
    }

    // ---- Browser extension ----

    pub fn refresh_extension(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/extension"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                let compat = v.get("compatibility").cloned().unwrap_or(Value::Null);
                let firefox = v.get("firefox").cloned().unwrap_or(Value::Null);
                let hits = api::arr(&v, "sightings").iter().map(|s| int(s, "hits")).sum();
                this.live.knowledge.ext = Some(ExtStatus {
                    available: api::b(&v, "available"),
                    version: api::s(&v, "version"),
                    staged: api::b(&v, "staged"),
                    staged_version: api::s(&v, "staged_version"),
                    path: api::s(&v, "path"),
                    firefox_path: api::s(&firefox, "manifest_path"),
                    firefox_staged: api::b(&firefox, "staged"),
                    port: int(&v, "port"),
                    port_is_ours: api::b(&v, "port_is_ours"),
                    browsers: api::arr(&v, "browsers")
                        .iter()
                        .map(|b| Browser { name: api::s(b, "name"), url: api::s(b, "url") })
                        .collect(),
                    hits,
                    connected: api::b(&v, "connected"),
                    ever_connected: api::b(&v, "ever_connected"),
                    seconds_since_seen: api::n(&v, "seconds_since_seen"),
                    compat_state: api::s(&compat, "state"),
                    compat_detail: api::s(&compat, "detail"),
                });
            }
        });
    }

    /// One of the three extension actions: `stage`, `reveal` or `launch`.
    pub fn extension_action(&mut self, action: &'static str, cx: &mut Context<Self>) {
        self.live.knowledge.ext_notice = Some(match action {
            "stage" | "firefox/stage" => "Preparing the extension.",
            "reveal" | "firefox/reveal" => "Showing the extension files.",
            _ => "Opening a browser.",
        }
        .to_string());
        self.fetch(
            cx,
            move || {
                // The engine only names the folder; this process opens it, because
                // a window the background engine opens is not the foreground one and
                // Windows leaves it behind the app.
                let url = if action == "reveal" { "/api/extension/reveal?spawn=false".to_string() } else { format!("/api/extension/{action}") };
                api::post(&url, serde_json::json!({}))
            },
            move |this, reply, cx| {
                this.note(&reply);
                this.live.knowledge.ext_notice = Some(match reply {
                    Ok(v) => match action {
                        "firefox/stage" => format!("{}. Package: {}", api::s(&v, "note"), api::s(&v, "package_path")),
                        "stage" => format!("Staged version {} at {}.", api::s(&v, "version"), api::s(&v, "path")),
                        "reveal" | "firefox/reveal" => {
                            let e = api::s(&v, "error");
                            let path = api::s(&v, "path");
                            if !e.is_empty() {
                                e
                            } else if let Err(cause) = std::process::Command::new("explorer.exe").arg(&path).spawn() {
                                format!("Could not open {path}: {cause}")
                            } else {
                                format!("Opened {path}.")
                            }
                        }
                        _ => {
                            let e = api::s(&v, "error");
                            if e.is_empty() { api::s(&v, "note") } else { e }
                        }
                    },
                    Err(e) => e.message,
                });
                this.refresh_extension(cx);
            },
        );
    }

    /// Ask whether a newer app exists. Quiet on failure: the About screen says why.
    pub fn check_app_update(&mut self, cx: &mut Context<Self>) {
        self.live.knowledge.app_update_note = Some("Checking for updates.".into());
        self.fetch(cx, || api::get("/api/app-update"), |this, reply, _| {
            this.live.knowledge.app_update_note = None;
            if let Ok(v) = reply {
                this.live.knowledge.app_update = Some(AppUpdate {
                    newer: api::b(&v, "newer"),
                    version: api::s(&v, "version"),
                    notes: api::s(&v, "notes"),
                    error: api::s(&v, "error"),
                });
            }
        });
    }

    /// Download the verified installer, run it and step aside: the installer
    /// stops this app and the engine, replaces them, and the Start menu opens the new one.
    pub fn install_app_update(&mut self, cx: &mut Context<Self>) {
        if self.live.knowledge.app_update_busy {
            return;
        }
        self.live.knowledge.app_update_busy = true;
        self.live.knowledge.app_update_note = Some("Downloading the update and checking it.".into());
        self.fetch(cx, || api::post("/api/app-update/download", serde_json::json!({})), |this, reply, cx| {
            this.live.knowledge.app_update_busy = false;
            match reply {
                Ok(v) => {
                    let path = api::s(&v, "path");
                    match run_installer_then_reopen(&path) {
                        Ok(()) => Self::quit(cx),
                        Err(cause) => this.live.knowledge.app_update_note = Some(format!("Could not start the installer: {cause}")),
                    }
                }
                Err(e) => this.live.knowledge.app_update_note = Some(e.message),
            }
        });
    }

    pub fn save_extension_port(&mut self, cx: &mut Context<Self>) {
        let text = self.extension_port_input.value.trim();
        let Ok(port) = text.parse::<u16>() else {
            self.live.knowledge.ext_notice = Some("Choose a port from 1 to 65535.".into());
            cx.notify();
            return;
        };
        if std::env::var_os("KRIKO_URL").is_some() {
            self.live.knowledge.ext_notice = Some(
                "This window is attached to another engine. Change that engine's extension port instead.".into(),
            );
            cx.notify();
            return;
        }
        match engine::set_extension_port(port) {
            Ok(()) => {
                self.live.knowledge.ext_notice = Some(format!(
                    "Restarting the engine on port {port}. In the browser extension settings, set the app address to http://127.0.0.1:{port}."
                ));
                self.live.knowledge.ext = None;
                engine::restart();
            }
            Err(error) => self.live.knowledge.ext_notice = Some(error),
        }
        cx.notify();
    }

    // ---- Settings ----

    pub fn refresh_settings(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/settings"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                if let Some(on) = v.get("app.reduce_motion").and_then(|x| x.as_bool()) {
                    this.reduce_motion = on;
                }
                // A number from this screen, a string from `/api/prefs`.
                let runs = v.get("run_concurrency").and_then(|x| {
                    x.as_u64().or_else(|| x.as_str().and_then(|s| s.trim().parse().ok()))
                });
                if let Some(n) = runs {
                    let n = (n as usize).clamp(1, RUNS_MAX);
                    if n != this.run_concurrency {
                        this.run_concurrency_prev = this.run_concurrency - 1;
                        this.run_concurrency = n;
                    }
                }
                this.live.knowledge.settings_loaded = true;
            }
        });
    }

    /// Saves one of the app's own preferences (merged into `/api/settings`).
    pub fn save_setting(&mut self, key: &'static str, value: Value, cx: &mut Context<Self>) {
        self.fetch(
            cx,
            move || api::post("/api/settings", serde_json::json!({ "values": { key: value } })),
            |this, reply, _| {
                this.note(&reply);
                if let Err(e) = reply {
                    this.live.knowledge.settings_notice = Some(format!("Not saved: {}", e.message));
                }
            },
        );
    }

    /// How many agent runs the engine may have going at once. Two on one
    /// pack still take turns; that is the engine's rule, not this screen's.
    pub fn set_run_concurrency(&mut self, n: usize, cx: &mut Context<Self>) {
        let n = n.clamp(1, RUNS_MAX);
        self.run_concurrency_prev = self.run_concurrency - 1;
        self.run_concurrency = n;
        self.save_setting("run_concurrency", Value::from(n as u64), cx);
    }

    pub fn set_reduce_motion(&mut self, on: bool, cx: &mut Context<Self>) {
        self.reduce_motion = on;
        self.save_setting("app.reduce_motion", Value::Bool(on), cx);
    }

    /// Writes or removes the Run value, then reads it back so the switch
    /// shows what Windows holds.
    pub fn refresh_startup(&mut self, cx: &mut Context<Self>) {
        if self.live.knowledge.startup_busy { return; }
        let revision = self.live.knowledge.startup_revision;
        self.fetch(cx, || startup::read(REG_VALUE), move |this, reply, _| {
            if this.live.knowledge.startup_busy || this.live.knowledge.startup_revision != revision { return; }
            match reply {
                Ok(mode) => this.live.knowledge.startup_mode = mode,
                Err(error) => this.live.knowledge.settings_notice = Some(error),
            }
        });
    }

    pub fn set_startup_mode(&mut self, mode: StartupMode, cx: &mut Context<Self>) {
        if self.live.knowledge.startup_busy { return; }
        self.live.knowledge.startup_busy = true;
        self.live.knowledge.startup_revision += 1;
        cx.notify();
        self.fetch(
            cx,
            move || {
                let done = startup::write(REG_VALUE, mode);
                (done, startup::read(REG_VALUE))
            },
            |this, (done, now), _| {
                this.live.knowledge.startup_busy = false;
                let read_error = now.as_ref().err().cloned();
                match now {
                    Ok(mode) => this.live.knowledge.startup_mode = mode,
                    Err(error) => this.live.knowledge.settings_notice = Some(error),
                }
                this.live.knowledge.settings_notice = done.err().or(read_error);
            },
        );
    }

    pub fn refresh_keys(&mut self, cx: &mut Context<Self>) {
        self.fetch(cx, || api::get("/api/keys"), |this, reply, _| {
            this.note(&reply);
            if let Ok(v) = reply {
                this.live.knowledge.set_keys(&v);
            }
        });
    }

    pub fn save_key(&mut self, provider: String, key: String, cx: &mut Context<Self>) {
        if key.trim().is_empty() {
            return;
        }
        self.fetch(
            cx,
            move || api::put("/api/keys", serde_json::json!({ "values": { provider: key } })),
            |this, reply, _| {
                this.note(&reply);
                match reply {
                    Ok(v) => {
                        this.live.knowledge.set_keys(&v);
                        this.live.knowledge.settings_notice = None;
                    }
                    Err(e) => this.live.knowledge.settings_notice = Some(e.message),
                }
            },
        );
    }

    pub fn remove_key(&mut self, provider: String, cx: &mut Context<Self>) {
        self.fetch(
            cx,
            move || api::delete(&format!("/api/keys/{}", api::seg(&provider))),
            |this, reply, _| {
                this.note(&reply);
                match reply {
                    Ok(v) => this.live.knowledge.set_keys(&v),
                    Err(e) => this.live.knowledge.settings_notice = Some(e.message),
                }
            },
        );
    }

    /// `POST /api/packs/reset`: every pack and draft goes, history stays.
    pub fn erase_packs(&mut self, cx: &mut Context<Self>) {
        self.live.knowledge.erase_busy = true;
        self.fetch(cx, || api::post("/api/packs/reset", serde_json::json!({})), |this, reply, cx| {
            this.note(&reply);
            let k = &mut this.live.knowledge;
            k.erase_busy = false;
            k.erase_confirm = false;
            k.settings_notice = Some(match reply {
                Ok(_) => "Every pack and draft is removed. History is kept.".to_string(),
                Err(e) => e.message,
            });
            this.refresh_packs(cx);
            this.refresh_thin(cx);
            this.refresh_updates(cx);
            this.refresh_sites(cx);
            this.refresh_health(cx);
        });
    }
}

impl State {
    fn set_keys(&mut self, v: &Value) {
        self.keys = api::arr(v, "providers")
            .iter()
            .map(|p| KeyRow {
                id: api::s(p, "id"),
                label: api::s(p, "label"),
                present: api::b(p, "present"),
                source: api::s(p, "source"),
                hint: api::s(p, "hint"),
            })
            .collect();
        self.keys_path = api::s(v, "path");
        self.keys_loaded = true;
    }
}

/// Which job a poll belongs to, and so what to refresh when it ends.
pub enum Followed {
    PackUpdate,
    SiteRegister(String),
    AgentInstall(String),
}

// ---- small helpers ----

fn int(v: &Value, key: &str) -> i64 {
    api::n(v, key).unwrap_or(0.0) as i64
}

/// `reviews.example` or `https://reviews.example/p/1` to a host and, when a
/// page was given, its address.
fn host_and_url(input: &str) -> (String, String) {
    let t = input.trim();
    let url = if t.contains("://") { t.to_string() } else { String::new() };
    let rest = t.split("://").last().unwrap_or("");
    let host = rest
        .split(['/', '?', '#'])
        .next()
        .unwrap_or("")
        .split('@')
        .last()
        .unwrap_or("")
        .split(':')
        .next()
        .unwrap_or("")
        .trim_start_matches("www.")
        .to_lowercase();
    (host, url)
}

/// "5 min ago" from a UTC timestamp without an offset
/// (`2026-09-19T14:45:23+00:00` or `2026-09-19 14:45:23`).
pub fn ago(iso: &str) -> String {
    match epoch_seconds(iso) {
        Some(then) => {
            let now = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(then);
            ago_seconds((now - then).max(0) as f64)
        }
        None => String::new(),
    }
}

/// Runs the installer, then opens the app again from the same place. One
/// hidden shell does both, because this process is about to quit and the MSI
/// does not relaunch what it replaced.
#[cfg(windows)]
fn run_installer_then_reopen(msi: &str) -> std::io::Result<()> {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let exe = std::env::current_exe()?;
    std::process::Command::new("cmd.exe")
        .raw_arg(format!(
            "/C msiexec.exe /i \"{msi}\" /passive /norestart && start \"\" \"{}\"",
            exe.display()
        ))
        .creation_flags(CREATE_NO_WINDOW)
        .spawn()
        .map(|_| ())
}

#[cfg(not(windows))]
fn run_installer_then_reopen(_msi: &str) -> std::io::Result<()> {
    Err(std::io::Error::new(std::io::ErrorKind::Unsupported, "the installer is for Windows"))
}

pub fn ago_seconds(s: f64) -> String {
    let s = s.max(0.0) as i64;
    match s {
        0..=44 => "just now".into(),
        45..=3599 => format!("{} min ago", (s / 60).max(1)),
        3600..=86_399 => format!("{} h ago", s / 3600),
        _ => format!("{} d ago", s / 86_400),
    }
}

fn epoch_seconds(iso: &str) -> Option<i64> {
    let b = iso.as_bytes();
    if b.len() < 19 {
        return None;
    }
    let num = |a: usize, z: usize| iso.get(a..z)?.parse::<i64>().ok();
    let (y, m, d) = (num(0, 4)?, num(5, 7)?, num(8, 10)?);
    let (hh, mm, ss) = (num(11, 13)?, num(14, 16)?, num(17, 19)?);
    // days from civil, proleptic Gregorian
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some(days * 86_400 + hh * 3600 + mm * 60 + ss)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_host_comes_out_of_whatever_was_typed() {
        assert_eq!(host_and_url("Reviews.Example").0, "reviews.example");
        let (h, u) = host_and_url("https://www.shop.test:8080/p/1?x=2");
        assert_eq!(h, "shop.test");
        assert_eq!(u, "https://www.shop.test:8080/p/1?x=2");
    }

    #[test]
    fn timestamps_read_as_utc() {
        assert_eq!(epoch_seconds("1970-01-02T00:00:00+00:00"), Some(86_400));
        assert_eq!(epoch_seconds("2000-03-01 00:00:00"), Some(951_868_800));
        assert_eq!(ago_seconds(30.0), "just now");
        assert_eq!(ago_seconds(7200.0), "2 h ago");
        assert_eq!(ago_seconds(3.0 * 86_400.0), "3 d ago");
    }


}
