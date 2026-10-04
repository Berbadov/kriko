//! The Kriko app shell: the sidebar, the hero with the page head, and the
//! dispatch to the tab screens. All state that the screens share (settings
//! flags, filters, selections) lives on [`Kriko`], so every screen is a
//! method over one state struct.

use gpui::{
    div, prelude::*, px, rgb, rgba, App, ClickEvent, Context, Div, FocusHandle, IntoElement,
    KeyDownEvent, MouseButton, ParentElement, Render, Stateful, Styled, Window, WindowControlArea,
    Animation, AnimationExt,
};

use crate::data;
use crate::dock;
use crate::engine;
use crate::live::Live;
use crate::shell;
use crate::screens;
use crate::theme::*;

// ---- native window drag ----
//
// GPUI 0.2.2 has no `start_window_move` on Windows, and the platform's
// HTCAPTION fall-through only works when nothing swallows the non-client
// button press — anything focusable nearby calls `prevent_default` and the
// drag dies. So the drag strip starts the native move loop itself.

#[cfg(windows)]
mod win {
    #[link(name = "user32")]
    extern "system" {
        fn GetActiveWindow() -> isize;
        fn FindWindowW(class: *const u16, title: *const u16) -> isize;
        fn ReleaseCapture() -> i32;
        fn SendMessageW(hwnd: isize, msg: u32, wparam: usize, lparam: isize) -> isize;
        fn GetCursorPos(point: *mut POINT) -> i32;
    }

    #[repr(C)]
    struct POINT {
        x: i32,
        y: i32,
    }

    const WM_NCLBUTTONDOWN: u32 = 0x00A1;
    const HTCAPTION: usize = 0x2;

    /// Hand the press to the system as a caption press: the native move
    /// loop starts, exactly as if the strip were a real titlebar.
    pub fn drag_window() {
        unsafe {
            let mut title: Vec<u16> = "Kriko".encode_utf16().chain(std::iter::once(0)).collect();
            let hwnd = {
                let active = GetActiveWindow();
                if active != 0 {
                    active
                } else {
                    FindWindowW(std::ptr::null(), title.as_mut_ptr())
                }
            };
            if hwnd == 0 {
                return;
            }
            let mut point = POINT { x: 0, y: 0 };
            if GetCursorPos(&mut point) == 0 {
                return;
            }
            let lparam = ((point.y as isize & 0xffff) << 16) | (point.x as isize & 0xffff);
            ReleaseCapture();
            SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, lparam);
        }
    }
}

/// The fallback every platform takes: the drag strip calls this on press.
fn drag_window_fallback() {
    #[cfg(windows)]
    win::drag_window();
}

// ---- keyboard actions (bound in main.rs) ----
gpui::actions!(kriko, [NewCheck, SearchKnowledge, JumpBrowse]);

// ---- tabs ----

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Home,
    Run,
    History,
    Compare,
    Extension,
    Overview,
    Browse,
    Sites,
    Activity,
    Agents,
    Benchmark,
    Local,
    Settings,
    About,
}

impl Tab {
    pub fn key(self) -> &'static str {
        match self {
            Tab::Home => "home",
            Tab::Run => "run",
            Tab::History => "history",
            Tab::Compare => "compare",
            Tab::Extension => "extension",
            Tab::Overview => "overview",
            Tab::Browse => "browse",
            Tab::Sites => "sites",
            Tab::Activity => "activity",
            Tab::Agents => "agents",
            Tab::Benchmark => "benchmark",
            Tab::Local => "local",
            Tab::Settings => "settings",
            Tab::About => "about",
        }
    }

    pub fn from_key(key: &str) -> Tab {
        match key {
            "run" => Tab::Run,
            "history" => Tab::History,
            "compare" => Tab::Compare,
            "extension" => Tab::Extension,
            "overview" => Tab::Overview,
            "browse" => Tab::Browse,
            "sites" => Tab::Sites,
            "activity" => Tab::Activity,
            "agents" => Tab::Agents,
            "benchmark" => Tab::Benchmark,
            "local" => Tab::Local,
            "settings" => Tab::Settings,
            "about" => Tab::About,
            _ => Tab::Home,
        }
    }

    fn crumb(self) -> &'static str {
        match self {
            Tab::Home => "check / home",
            Tab::Run => "check / run",
            Tab::History => "history",
            Tab::Compare => "check / compare",
            Tab::Extension => "check / browser extension",
            Tab::Overview => "knowledge / overview",
            Tab::Browse => "knowledge / browse",
            Tab::Sites => "system / sites",
            Tab::Activity => "system / activity",
            Tab::Agents => "system / agents",
            Tab::Benchmark => "system / benchmark",
            Tab::Local => "this install / local llm",
            Tab::Settings => "this install / settings",
            Tab::About => "this install / about",
        }
    }

    fn title(self) -> &'static str {
        match self {
            Tab::Extension => "Browser extension",
            Tab::Local => "Local LLM",
            _ => self.key(),
        }
    }

    fn lead(self) -> &'static str {
        match self {
            Tab::Home => "Recent work, saved drafts, and where the knowledge stands.",
            Tab::Run => "One check, from question to stored claims, every step in the open.",
            Tab::History => "Every check you have run, with the evidence it was based on.",
            Tab::Compare => "Up to three subjects side by side, attribute by attribute.",
            Tab::Extension => "Send pages from your browser straight into Kriko's knowledge.",
            Tab::Overview => "What the packs know, and where they run thin.",
            Tab::Browse => "Every subject, attribute and claim in the local store.",
            Tab::Sites => "The sites Kriko reads, and how far each one is trusted.",
            Tab::Activity => "What Kriko did today, and what is waiting for you.",
            Tab::Agents => "The coding agents on this machine that can reach Kriko.",
            Tab::Benchmark => "How long the parts of a check take on this machine.",
            Tab::Local => "A local model, for checks that never leave this machine.",
            Tab::Settings => "Control how Kriko starts, reads and stores things.",
            Tab::About => "Kriko. Local product knowledge.",
        }
    }

    fn hero_sky(self) -> Sky {
        match self {
            Tab::Home | Tab::About => Sky::Bright,
            Tab::Local => Sky::Wide,
            _ => Sky::Dim,
        }
    }

    fn hero_height(self) -> f32 {
        match self {
            Tab::Home | Tab::About => 280.0,
            Tab::Local => 220.0,
            _ => 264.0,
        }
    }
}

// ---- text fields ----

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Field {
    HistorySearch,
    ActivityFilter,
    SitesAdd,
    BrowseSearch,
    DockReply,
    CompareAsk,
    BoardNote,
    LocalUrl,
    LocalSearch,
}

pub struct InputState {
    pub value: String,
    pub handle: FocusHandle,
}

impl InputState {
    fn new(cx: &mut App) -> Self {
        Self {
            value: String::new(),
            handle: cx.focus_handle(),
        }
    }
}

// ---- filters ----

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum PackFilter {
    All,
    Samsung,
    Apple,
    Volkswagen,
}

impl PackFilter {
    pub fn word(self) -> &'static str {
        match self {
            PackFilter::All => "ALL",
            PackFilter::Samsung => "SAMSUNG",
            PackFilter::Apple => "APPLE",
            PackFilter::Volkswagen => "VOLKSWAGEN",
        }
    }

    pub fn next(self) -> Self {
        match self {
            PackFilter::All => PackFilter::Samsung,
            PackFilter::Samsung => PackFilter::Apple,
            PackFilter::Apple => PackFilter::Volkswagen,
            PackFilter::Volkswagen => PackFilter::All,
        }
    }
}

/// The date span History is narrowed to: how far back checks are shown.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum SpanFilter {
    All,
    Month,
    Quarter,
    Half,
}

impl SpanFilter {
    pub fn word(self) -> &'static str {
        match self {
            SpanFilter::All => "ALL TIME",
            SpanFilter::Month => "30 DAYS",
            SpanFilter::Quarter => "90 DAYS",
            SpanFilter::Half => "180 DAYS",
        }
    }

    /// The span in days; All admits everything.
    pub fn days(self) -> u32 {
        match self {
            SpanFilter::All => u32::MAX,
            SpanFilter::Month => 30,
            SpanFilter::Quarter => 90,
            SpanFilter::Half => 180,
        }
    }

    pub fn next(self) -> Self {
        match self {
            SpanFilter::All => SpanFilter::Month,
            SpanFilter::Month => SpanFilter::Quarter,
            SpanFilter::Quarter => SpanFilter::Half,
            SpanFilter::Half => SpanFilter::All,
        }
    }
}

/// One line in the dock's own feed.
pub struct DockFeedEntry {
    pub text: String,
    pub state: TagState,
}

impl DockFeedEntry {
    pub fn now(text: String, state: TagState) -> Self {
        Self { text, state }
    }
}

/// One sticky note on the compare board. The position is a fraction of the
/// board's own box, so the note lands on the same column whatever the width.
#[derive(Clone)]
pub struct CompareNote {
    pub x: f32,
    pub y: f32,
    pub text: String,
}

/// A saved, named comparison: which checks sit in which slots.
pub struct CompareDraftDef {
    pub name: String,
    pub slots: Vec<Option<usize>>,
}

/// A follow-up question asked about the comparison, with its answer once
/// the agent has finished. `agent` names which one answered, by index
/// into AGENTS.
pub struct CompareQuestion {
    pub text: String,
    pub agent: usize,
    pub answer: Option<String>,
}

/// Where one product stands in the research queue on Compare.
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum QueueState {
    Waiting,
    Researching,
    Done,
}

/// One product in the research queue: the check it researches, how far the
/// agent has got, and how many claims it found once done.
pub struct QueueItem {
    pub check: usize,
    /// The site the extension queued it from, as the panel posted it.
    pub origin: &'static str,
    pub state: QueueState,
    pub progress: f32,
    pub claims: u16,
}

/// Percent of one product the queue's agent researches per 100 ms tick:
/// about four seconds a product, so the demo walks while you watch.
pub const QUEUE_STEP: f32 = 2.5;

/// Percent of the benchmark per 100 ms tick, through every stage.
pub const BENCH_STEP: f32 = 1.4;

// ---- the app ----

pub struct Kriko {
    pub tab: Tab,
    /// Where the engine is: starting, answering, or failed with its words.
    pub engine: engine::Status,
    /// What the engine said, per area, for the screens to draw.
    pub live: Live,
    // settings
    pub launch_at_login: bool,
    pub menu_bar_icon: bool,
    pub reduce_motion: bool,
    pub ask_before_reading: bool,
    pub keep_raw_pages: bool,
    pub erase_confirm: bool,
    pub erased: bool,
    // inputs
    pub history_search: InputState,
    pub activity_filter: InputState,
    pub sites_add: InputState,
    pub browse_search: InputState,
    // history
    pub pack_filter: PackFilter,
    pub page: usize,
    pub history_span: SpanFilter,
    /// The check whose evidence is unfolded on History, by index into
    /// CHECKS. None: the table rests closed.
    pub history_open: Option<usize>,
    // activity
    // sites: hosts added this session
    pub added_sites: Vec<String>,
    // browse / agents / packs / models
    pub browse_selected: usize,
    pub browse_view: usize,
    pub browse_view_prev: usize,
    pub agent_selected: usize,
    pub agent_allowed: Vec<bool>,
    pub pack_enabled: Vec<bool>,
    /// The coverage gap unfolded on Overview, by index into KNOWLEDGE.
    /// None: every gap rests closed.
    pub knowledge_open: Option<usize>,
    pub model_loaded: Vec<bool>,
    // extension
    pub extension_linked: bool,
    pub extension_hover: bool,
    // run
    pub run_phase: usize,
    // the live actions dock
    pub dock_reply: InputState,
    pub dock_resolved: Vec<usize>,
    /// Which dock requests an agent is asking right now: the needs-you block
    /// only exists while one is asking, and pops in when it starts.
    pub dock_request_active: Vec<bool>,
    /// The reply drawer: closed unless you are answering an agent.
    pub dock_reply_open: bool,
    pub dock_feed: Vec<DockFeedEntry>,
    pub dock_lane_bump: usize,
    pub dock_reply_sent: usize,
    pub dock_open: bool,
    // compare: the slots, the draft, the board, the questions
    pub compare_slots: Vec<Option<usize>>,
    pub compare_picker: Option<usize>,
    pub compare_section: usize,
    pub compare_detail: Option<(usize, usize)>,
    pub compare_draft: usize,
    pub compare_drafts: Vec<CompareDraftDef>,
    pub compare_board_open: bool,
    pub compare_board_tool: usize,
    pub compare_strokes: Vec<Vec<(f32, f32)>>,
    pub compare_stroke_current: Vec<(f32, f32)>,
    pub compare_drawing: bool,
    pub compare_notes: Vec<CompareNote>,
    pub compare_note_open: Option<usize>,
    pub compare_note_input: InputState,
    pub compare_question_input: InputState,
    pub compare_questions: Vec<CompareQuestion>,
    /// Which agent the questions on Compare go to, by index into AGENTS.
    pub compare_agent: usize,
    /// The rows pinned as preferred on Compare: (section, row). The agent
    /// reads them with everything else on the board.
    pub compare_marks: Vec<(usize, usize)>,
    /// The column slider's thumb, 0..=1. Only moves when more products are
    /// lined up than fit on screen.
    pub compare_scroll: f32,
    pub compare_dragging: bool,
    // research queue (Compare)
    pub queue: Vec<QueueItem>,
    /// The agent the queue researches with, by index into AGENTS.
    pub queue_agent: usize,
    pub queue_running: bool,
    /// When on, a finished queue fills the compare slots by itself.
    pub queue_auto: bool,
    // benchmark
    /// 0..=100 while a benchmark runs, None when idle.
    pub bench_progress: Option<f32>,
    /// Benchmarks finished this session, on top of the sample history.
    pub bench_done: u32,
    // local llm
    pub local_url: InputState,
    pub local_search: InputState,
    pub local_model_pick: usize,
    pub local_timeout: u32,
    pub local_temp: u16,
    pub local_max_tokens: u16,
    pub local_gpu_layers: u16,
    pub local_auto_unload: bool,
    pub local_cpu_fallback: bool,
    pub local_test: usize,
    /// Which runtime serves the local model, by index into RUNTIMES.
    pub local_runtime: usize,
    pub runtime_state: Vec<data::RuntimeState>,
    /// The runtime being installed, and how far along, 0..=100.
    pub runtime_install: Option<(usize, f32)>,
    /// Where Get fetches from, by index into MODEL_SOURCES.
    pub local_source: usize,
    pub local_source_prev: usize,
    /// Per catalogue model: download progress while fetching.
    pub pull_progress: Vec<Option<f32>>,
    pub pulled: Vec<bool>,
    /// The fetched model in use, by index into CATALOGUE.
    pub catalogue_loaded: Option<usize>,
    // agents: per-agent tool permissions [read, run, answer]
    pub agent_tools: Vec<[bool; 3]>,
}

/// The line rate a model download runs at, in GB/s, in the sample app.
pub const PULL_GBPS: f32 = 0.6;

impl Kriko {
    pub fn new(cx: &mut Context<Self>) -> Self {
        let mut app = Self {
            tab: Tab::Home,
            engine: engine::status(),
            live: Live::default(),
            launch_at_login: true,
            menu_bar_icon: false,
            reduce_motion: false,
            ask_before_reading: true,
            keep_raw_pages: true,
            erase_confirm: false,
            erased: false,
            history_search: InputState::new(cx),
            activity_filter: InputState::new(cx),
            sites_add: InputState::new(cx),
            browse_search: InputState::new(cx),
            pack_filter: PackFilter::All,
            page: 0,
            history_span: SpanFilter::All,
            history_open: None,
            added_sites: Vec::new(),
            browse_selected: 0,
            browse_view: 0,
            browse_view_prev: 0,
            agent_selected: 0,
            agent_allowed: data::AGENTS.iter().map(|a| a.allowed).collect(),
            pack_enabled: data::PACKS.iter().map(|p| p.enabled).collect(),
            knowledge_open: None,
            model_loaded: data::MODELS.iter().map(|m| m.loaded).collect(),
            extension_linked: false,
            extension_hover: false,
            run_phase: 0,
            dock_reply: InputState::new(cx),
            dock_resolved: Vec::new(),
            dock_request_active: data::DOCK_REQUESTS.iter().map(|_| false).collect(),
            dock_reply_open: false,
            dock_feed: vec![
                DockFeedEntry::now(
                    "Claude Code: read 4 pages of rtings.com".to_string(),
                    TagState::Done,
                ),
                DockFeedEntry::now(
                    "opencode: settled the battery dispute".to_string(),
                    TagState::Done,
                ),
            ],
            dock_lane_bump: 0,
            dock_reply_sent: 0,
            dock_open: true,
            compare_slots: data::COMPARE_DEFAULT_SLOTS
                .iter()
                .map(|i| Some(*i))
                .collect(),
            compare_picker: None,
            compare_section: 0,
            compare_detail: None,
            compare_draft: 0,
            compare_drafts: data::COMPARE_DRAFTS
                .iter()
                .map(|d| CompareDraftDef {
                    name: d.name.to_string(),
                    slots: d.slots.iter().map(|i| Some(*i)).collect(),
                })
                .collect(),
            compare_board_open: false,
            compare_board_tool: 0,
            compare_strokes: Vec::new(),
            compare_stroke_current: Vec::new(),
            compare_drawing: false,
            compare_notes: Vec::new(),
            compare_note_open: None,
            compare_note_input: InputState::new(cx),
            compare_question_input: InputState::new(cx),
            compare_agent: 0,
            compare_marks: Vec::new(),
            compare_scroll: 0.0,
            compare_dragging: false,
            // what the extension's Add to queue key sent, oldest first
            queue: [(7usize, "apple.com"), (14, "sennheiser-hearing.com"), (10, "jbl.com")]
                .into_iter()
                .map(|(check, origin)| QueueItem {
                    check,
                    origin,
                    state: QueueState::Waiting,
                    progress: 0.0,
                    claims: 0,
                })
                .collect(),
            queue_agent: 0,
            queue_running: false,
            queue_auto: true,
            bench_progress: None,
            bench_done: 0,
            compare_questions: vec![
                CompareQuestion {
                    text: "What does each one's knowledge rest on?".to_string(),
                    agent: 0,
                    answer: Some(
                        "On record: the Buds2 Pro's ANC rests on 5 sources, the Buds Pro's \
                         battery on 4 that disagree, the XM5's noise cancelling on 5 that \
                         agree. Nothing here is ranked — the counts are the knowledge."
                            .to_string(),
                    ),
                },
                CompareQuestion {
                    text: "What does the XM5's higher price buy?".to_string(),
                    agent: 1,
                    answer: Some(
                        "Measured: 42 dB of noise cancelling, the strongest of the three, \
                         from 5 agreeing sources. The board records that and nothing beyond it."
                            .to_string(),
                    ),
                },
            ],
            local_url: InputState::new(cx),
            local_search: InputState::new(cx),
            local_model_pick: 0,
            local_timeout: 300,
            local_temp: 7,
            local_max_tokens: 4096,
            local_gpu_layers: 33,
            local_auto_unload: true,
            local_cpu_fallback: false,
            local_test: 0,
            local_runtime: 1,
            runtime_state: data::RUNTIMES.iter().map(|r| r.state).collect(),
            runtime_install: None,
            local_source: 0,
            local_source_prev: 0,
            pull_progress: data::CATALOGUE.iter().map(|_| None).collect(),
            pulled: data::CATALOGUE.iter().map(|_| false).collect(),
            catalogue_loaded: None,
            agent_tools: data::AGENTS
                .iter()
                .map(|a| [a.can_read, a.can_run, a.can_answer])
                .collect(),
        };
        app.local_url.value = "http://127.0.0.1:7400".to_string();
        app.local_search.value = "http://127.0.0.1:7400/search".to_string();
        // A verification hook: KRIKO_VERIFY seeds one page's state so it can
        // be captured without driving the mouse on a busy desktop.
        match std::env::var("KRIKO_VERIFY").as_deref() {
            Ok("compare") => {
                app.tab = Tab::Compare;
                app.compare_board_open = true;
                app.compare_strokes = vec![
                    vec![(0.12, 0.30), (0.30, 0.38), (0.48, 0.30)],
                    vec![(0.62, 0.62), (0.70, 0.70), (0.78, 0.62)],
                ];
                app.compare_notes = vec![CompareNote {
                    x: 0.20,
                    y: 0.18,
                    text: "this one, if the price drops".to_string(),
                }];
                app.compare_detail = Some((0, 0));
            }
            Ok("risks") => {
                app.tab = Tab::Compare;
                app.compare_section = 1;
                app.compare_detail = Some((1, 0));
            }
            Ok("local") => {
                app.tab = Tab::Local;
                app.local_test = 2;
            }
            Ok("agents") => {
                app.tab = Tab::Agents;
            }
            Ok("dock") => {
                app.dock_request_active[1] = true;
                app.dock_reply_open = true;
            }
            _ => {}
        }
        // The pulse: the engine's state, the tray, and what the engine asks
        // of the window, read ten times a second. Each read is a lock and a
        // channel peek, so the pulse costs nothing while nothing happens.
        cx.spawn(async move |this, cx| loop {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(100))
                .await;
            let alive = this.update(cx, |this, cx| this.pulse(cx)).is_ok();
            if !alive {
                break;
            }
        })
        .detach();
        // The needs-you block is not part of the dock's resting state: an
        // agent asks, and only then does it pop in. Simulate one asking.
        cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(std::time::Duration::from_secs(7))
                .await;
            let _ = this.update(cx, |this, cx| {
                if !this.dock_request_active[1] {
                    this.dock_request_active[1] = true;
                    this.dock_feed.push(DockFeedEntry::now(
                        "Claude Code: asks about rtings.com".to_string(),
                        TagState::Need,
                    ));
                    // an agent asking you is the one moment the reply
                    // drawer opens itself
                    this.dock_reply_open = true;
                    cx.notify();
                }
            });
        })
        .detach();
        // The run plays itself while Run is on screen: one phase every few
        // beats, then it holds at stored. Reduce motion keeps it still, and
        // the Replay control on the page winds it back to the start.
        cx.spawn(async move |this, cx| {
            loop {
                cx.background_executor()
                    .timer(std::time::Duration::from_millis(2400))
                    .await;
                if this
                    .update(cx, |this, cx| {
                        if this.tab == Tab::Run
                            && !this.reduce_motion
                            && this.run_phase < screens::run::PHASES.len()
                        {
                            this.run_phase += 1;
                            cx.notify();
                        }
                    })
                    .is_err()
                {
                    break;
                }
            }
        })
        .detach();
        app
    }

    fn pulse(&mut self, cx: &mut Context<Self>) {
        for action in shell::poll_tray() {
            match action {
                shell::TrayAction::Open => shell::show_window(),
                shell::TrayAction::Quit => Self::quit(cx),
            }
        }
        for event in engine::take_events() {
            match event {
                engine::ShellEvent::Focus(_route) => shell::show_window(),
                engine::ShellEvent::Hide => shell::hide_window(),
                engine::ShellEvent::Quit => Self::quit(cx),
            }
        }
        let now = engine::status();
        if now != self.engine {
            let became_ready = matches!(now, engine::Status::Ready { .. })
                && !matches!(self.engine, engine::Status::Ready { .. });
            self.engine = now;
            if became_ready {
                self.refresh_all(cx);
            }
            cx.notify();
        }
    }

    /// Quit Kriko: the engine first (its exit frees the store's lock), then
    /// the app.
    pub fn quit(cx: &mut Context<Self>) {
        engine::stop();
        shell::remove_tray();
        cx.quit();
    }

    fn input(&self, field: Field) -> &InputState {
        match field {
            Field::HistorySearch => &self.history_search,
            Field::ActivityFilter => &self.activity_filter,
            Field::SitesAdd => &self.sites_add,
            Field::BrowseSearch => &self.browse_search,
            Field::DockReply => &self.dock_reply,
            Field::CompareAsk => &self.compare_question_input,
            Field::BoardNote => &self.compare_note_input,
            Field::LocalUrl => &self.local_url,
            Field::LocalSearch => &self.local_search,
        }
    }

    fn input_mut(&mut self, field: Field) -> &mut InputState {
        match field {
            Field::HistorySearch => &mut self.history_search,
            Field::ActivityFilter => &mut self.activity_filter,
            Field::SitesAdd => &mut self.sites_add,
            Field::BrowseSearch => &mut self.browse_search,
            Field::DockReply => &mut self.dock_reply,
            Field::CompareAsk => &mut self.compare_question_input,
            Field::BoardNote => &mut self.compare_note_input,
            Field::LocalUrl => &mut self.local_url,
            Field::LocalSearch => &mut self.local_search,
        }
    }

    fn handle_key(this: &mut Kriko, field: Field, event: &KeyDownEvent, cx: &mut Context<Kriko>) {
        let ks = &event.keystroke;
        if ks.modifiers.control || ks.modifiers.alt || ks.modifiers.platform {
            return;
        }
        // Enter in the dock reply sends it straight to the feed.
        if ks.key.as_str() == "enter" && field == Field::DockReply {
            let text = this.input(field).value.trim().to_string();
            if !text.is_empty() {
                this.input_mut(field).value.clear();
                this.dock_feed.push(DockFeedEntry::now(
                    format!("You: {text}"),
                    TagState::Done,
                ));
                this.dock_lane_bump = (this.dock_lane_bump + 1) % data::DOCK_LANES.len();
                this.dock_reply_sent += 1;
            }
            this.dock_reply_open = false;
            cx.notify();
            return;
        }
        // Enter in the Sites add field adds the site straight away.
        if ks.key.as_str() == "enter" && field == Field::SitesAdd {
            let host = this.input(field).value.trim().to_string();
            if !host.is_empty() {
                this.added_sites.push(host);
                this.input_mut(field).value.clear();
            }
            cx.notify();
            return;
        }
        // Enter on the compare board commits the note being edited.
        if ks.key.as_str() == "enter" && field == Field::BoardNote {
            let text = this.input(field).value.trim().to_string();
            if let Some(open) = this.compare_note_open {
                if open < this.compare_notes.len() {
                    this.compare_notes[open].text = text;
                }
                this.compare_note_open = None;
            }
            this.input_mut(field).value.clear();
            cx.notify();
            return;
        }
        // Enter on the compare question asks it, the same as the Ask key.
        if ks.key.as_str() == "enter" && field == Field::CompareAsk {
            this.ask_compare_question(cx);
            cx.notify();
            return;
        }
        let state = this.input_mut(field);
        match ks.key.as_str() {
            "backspace" => {
                state.value.pop();
            }
            "space" => state.value.push(' '),
            "escape" => {}
            key if key.chars().count() == 1 => {
                if state.value.len() < 200 {
                    state.value.push_str(key);
                }
            }
            _ => {}
        }
        if field == Field::HistorySearch {
            this.page = 0;
        }
        cx.notify();
    }

    /// A well input with an optional leading icon, live text and a blinking caret.
    pub fn input_field(
        &self,
        field: Field,
        id: &'static str,
        placeholder: &str,
        icon_name: Option<&str>,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) -> Stateful<Div> {
        let state = self.input(field);
        let focused = state.handle.is_focused(window);
        let value = state.value.clone();
        let empty = value.is_empty();
        let listener = cx.listener(move |this, event: &KeyDownEvent, _w, cx| {
            Self::handle_key(this, field, event, cx);
        });
        let caret_base = div().w(px(2.0)).h(px(20.0)).bg(rgb(INK));
        let caret: gpui::AnyElement = if self.reduce_motion {
            caret_base.into_any_element()
        } else {
            caret_base
                .with_animation(
                    "blink",
                    Animation::new(std::time::Duration::from_millis(1100)).repeat(),
                    |el, t| el.opacity(if t < 0.5 { 1.0 } else { 0.0 }),
                )
                .into_any_element()
        };
        div()
            .id(id)
            .track_focus(&state.handle)
            .h(px(48.0))
            .min_w(px(0.0))
            .flex()
            .flex_1()
            .items_center()
            .gap(px(12.0))
            .px(px(16.0))
            .rounded(px(12.0))
            .bg(rgb(WELL))
            .border_1()
            .border_color(rgba(BORDER_CONTROL))
            .when(focused, |d| d.border_color(rgb(ICE)))
            .on_key_down(listener)
            .children(icon_name.map(|n| {
                icon(n, 18.0)
                    .flex_none()
                    .text_color(rgb(if empty { DIM } else { MUTED }))
            }))
            .child(if empty {
                div()
                    .font_family(SANS)
                    .text_size(px(16.0))
                    .text_color(rgb(DIM))
                    .child(placeholder.to_string())
                    .into_any_element()
            } else {
                div()
                    .font_family(SANS)
                    .text_size(px(16.0))
                    .text_color(rgb(INK))
                    .child(value)
                    .into_any_element()
            })
            .when(focused, |d| d.child(caret))
    }

    // ---- simulated agent work ----

    /// Push the question, then let the chosen agent answer it a moment
    /// later. The answer is read back from the board — subjects, marks,
    /// notes — and never ranks anything.
    pub fn ask_compare_question(&mut self, cx: &mut Context<Self>) {
        let text = self.compare_question_input.value.trim().to_string();
        if text.is_empty() {
            return;
        }
        let agent = self.compare_agent;
        // what the agent sees: the board, read back
        let subjects: Vec<usize> = self.compare_slots.iter().flatten().copied().collect();
        let names: Vec<&str> = subjects
            .iter()
            .map(|&c| data::CHECKS[c].name)
            .collect();
        let marks = self.compare_marks.len();
        let notes: Vec<String> = self
            .compare_notes
            .iter()
            .map(|n| n.text.trim().to_string())
            .filter(|t| !t.is_empty())
            .collect();
        let strokes = self.compare_strokes.len();
        let mut answer = format!(
            "Read straight from your board: {} lined up",
            if names.len() > 1 {
                format!("{} and {}", names[..names.len() - 1].join(", "), names[names.len() - 1])
            } else {
                names.first().copied().unwrap_or("nothing").to_string()
            },
        );
        if marks > 0 {
            answer.push_str(&format!(
                ", {} row{} marked as preferred",
                marks,
                if marks > 1 { "s" } else { "" }
            ));
        }
        if !notes.is_empty() {
            answer.push_str(&format!(
                ". Your notes read: \"{}\"",
                notes.join("\"; \"")
            ));
        }
        if strokes > 0 {
            answer.push_str(&format!(
                ", {} stroke{} on the board",
                strokes,
                if strokes > 1 { "s" } else { "" }
            ));
        }
        answer.push_str(
            ". Every cell keeps its own sources; this is the table read back, not a ranking.",
        );
        self.compare_question_input.value.clear();
        self.compare_questions.insert(
            0,
            CompareQuestion {
                text,
                agent,
                answer: None,
            },
        );
        cx.notify();
        cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(1500))
                .await;
            let _ = this.update(cx, |this, cx| {
                if let Some(q) = this
                    .compare_questions
                    .iter_mut()
                    .rev()
                    .find(|q| q.answer.is_none())
                {
                    q.answer = Some(answer);
                }
                cx.notify();
            });
        })
        .detach();
    }

    /// Run the local model test: LIVE for a moment, then the result lines.
    pub fn run_local_test(&mut self, cx: &mut Context<Self>) {
        if self.local_test == 1 {
            return;
        }
        self.local_test = 1;
        cx.notify();
        cx.spawn(async move |this, cx| {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(2400))
                .await;
            let _ = this.update(cx, |this, cx| {
                this.local_test = 2;
                cx.notify();
            });
        })
        .detach();
    }

    /// Install a runtime: the bar fills, then it sits installed, ready to use.
    pub fn install_runtime(&mut self, i: usize, cx: &mut Context<Self>) {
        if self.runtime_install.is_some() {
            return;
        }
        self.runtime_install = Some((i, 0.0));
        cx.notify();
        cx.spawn(async move |this, cx| loop {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(90))
                .await;
            let done = this
                .update(cx, |this, cx| {
                    let finished = match this.runtime_install.as_mut() {
                        Some((_, p)) => {
                            *p += 3.5;
                            *p >= 100.0
                        }
                        None => true,
                    };
                    if finished {
                        this.runtime_install = None;
                        this.runtime_state[i] = data::RuntimeState::Installed;
                    }
                    cx.notify();
                    finished
                })
                .unwrap_or(true);
            if done {
                break;
            }
        })
        .detach();
    }

    /// Use a runtime: start it if it is off, and point the server address at it.
    pub fn use_runtime(&mut self, i: usize, cx: &mut Context<Self>) {
        if self.runtime_state[i] == data::RuntimeState::Missing {
            return;
        }
        self.runtime_state[i] = data::RuntimeState::Running;
        self.local_runtime = i;
        self.local_url.value = format!("http://127.0.0.1:{}", data::RUNTIMES[i].port);
        self.local_test = 0;
        cx.notify();
    }

    /// Fetch a catalogue model: the meter fills at a steady line rate, so a
    /// bigger model takes visibly longer, then it is on disk and loadable.
    // ---- research queue ----

    /// Researches the waiting products one after another with the queue's
    /// agent: reading, then thinking, then writing claims, a product at a
    /// time. A finished queue says so in the dock and, with Auto on, fills
    /// the compare slots.
    pub fn queue_start(&mut self, cx: &mut Context<Self>) {
        let left = self.queue.iter().filter(|q| q.state != QueueState::Done).count();
        if self.queue_running || left == 0 {
            return;
        }
        self.queue_running = true;
        let agent = data::AGENTS[self.queue_agent].name;
        self.dock_feed.push(DockFeedEntry::now(
            format!("{agent}: queue started, {left} to research"),
            TagState::Live,
        ));
        cx.notify();
        let mut last = std::time::Instant::now();
        cx.spawn(async move |this, cx| loop {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(100))
                .await;
            // ticks arrive late on a busy frame; step by the time that passed
            let ticks = last.elapsed().as_secs_f32() / 0.1;
            last = std::time::Instant::now();
            let done = this
                .update(cx, |this, cx| {
                    if !this.queue_running {
                        return true;
                    }
                    let Some(item) = this
                        .queue
                        .iter_mut()
                        .find(|q| q.state != QueueState::Done)
                    else {
                        this.queue_running = false;
                        let n = this.queue.len();
                        this.dock_feed.push(DockFeedEntry::now(
                            format!("Queue done: {n} products researched"),
                            TagState::Done,
                        ));
                        if this.queue_auto {
                            this.queue_to_compare();
                        }
                        cx.notify();
                        return true;
                    };
                    item.state = QueueState::Researching;
                    item.progress += QUEUE_STEP * ticks;
                    if item.progress >= 100.0 {
                        item.progress = 100.0;
                        item.state = QueueState::Done;
                        // what the agent found, derived from what the store
                        // already holds for that product, so it is stable
                        let ev = data::evidence_for(&data::CHECKS[item.check]).claims.len();
                        item.claims = (ev as u16) * 3 + (item.check as u16 % 5) + 4;
                    }
                    cx.notify();
                    false
                })
                .unwrap_or(true);
            if done {
                break;
            }
        })
        .detach();
    }

    /// Puts the researched products into the compare slots as a new draft.
    pub fn queue_to_compare(&mut self) {
        let slots: Vec<Option<usize>> = self
            .queue
            .iter()
            .filter(|q| q.state == QueueState::Done)
            .map(|q| Some(q.check))
            .take(8)
            .collect();
        if slots.is_empty() {
            return;
        }
        let n = self.compare_drafts.len() + 1;
        self.compare_drafts.push(CompareDraftDef {
            name: format!("Queue {n}"),
            slots: slots.clone(),
        });
        self.compare_draft = self.compare_drafts.len() - 1;
        self.compare_slots = slots;
        self.compare_detail = None;
        self.compare_picker = None;
    }

    // ---- benchmark ----

    /// Walks every stage of a check once, timing it; the screen lights the
    /// stage under way and lands the run in the history when it ends. A
    /// second press stops it.
    pub fn bench_start(&mut self, cx: &mut Context<Self>) {
        if self.bench_progress.is_some() {
            self.bench_progress = None;
            cx.notify();
            return;
        }
        self.bench_progress = Some(0.0);
        cx.notify();
        let mut last = std::time::Instant::now();
        cx.spawn(async move |this, cx| loop {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(100))
                .await;
            // ticks arrive late on a busy frame; step by the time that passed
            let ticks = last.elapsed().as_secs_f32() / 0.1;
            last = std::time::Instant::now();
            let done = this
                .update(cx, |this, cx| {
                    let finished = match this.bench_progress.as_mut() {
                        Some(p) => {
                            *p += BENCH_STEP * ticks;
                            *p >= 100.0
                        }
                        None => return true,
                    };
                    if finished {
                        this.bench_progress = None;
                        this.bench_done += 1;
                        this.dock_feed.push(DockFeedEntry::now(
                            "Benchmark finished: full check in 3 min 01".to_string(),
                            TagState::Done,
                        ));
                    }
                    cx.notify();
                    finished
                })
                .unwrap_or(true);
            if done {
                break;
            }
        })
        .detach();
    }

    pub fn pull_model(&mut self, i: usize, cx: &mut Context<Self>) {
        if self.pull_progress[i].is_some() || self.pulled[i] {
            return;
        }
        self.pull_progress[i] = Some(0.0);
        cx.notify();
        // percent per 100 ms tick at PULL_GBPS
        let step = 100.0 * PULL_GBPS * 0.1 / data::CATALOGUE[i].size_gb.max(0.1);
        cx.spawn(async move |this, cx| loop {
            cx.background_executor()
                .timer(std::time::Duration::from_millis(100))
                .await;
            let done = this
                .update(cx, |this, cx| {
                    let finished = match this.pull_progress[i].as_mut() {
                        Some(p) => {
                            *p += step;
                            *p >= 100.0
                        }
                        None => true,
                    };
                    if finished {
                        this.pull_progress[i] = None;
                        this.pulled[i] = true;
                    }
                    cx.notify();
                    finished
                })
                .unwrap_or(true);
            if done {
                break;
            }
        })
        .detach();
    }

    // ---- sidebar ----

    fn sidebar(&self, cx: &mut Context<Self>) -> Div {
        let mut nav = div()
            .id("nav-scroll")
            .flex()
            .flex_col()
            .px(px(12.0))
            .pt(px(4.0))
            .pb(px(20.0))
            .gap(px(2.0))
            .flex_1()
            .min_h(px(0.0))
            .overflow_y_scroll();
        for (gi, group) in data::NAV.iter().enumerate() {
            nav = nav.child(
                div()
                    .mt(px(if gi == 0 { 8.0 } else { 18.0 }))
                    .mb(px(4.0))
                    .px(px(12.0))
                    .flex_none()
                    .child(eyebrow(group.label)),
            );
            for item in group.items {
                let key = item.key;
                let current = self.tab.key() == key;
                let row = nav_item(key, item.icon, item.label, current, item.count, item.badge)
                    .flex_none()
                    .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                        this.tab = Tab::from_key(key);
                        cx.notify();
                    }));
                nav = nav.child(row);
            }
        }
        div()
            .w(px(SIDEBAR_W))
            .flex_none()
            .bg(rgb(SURFACE_1))
            .border_r_1()
            .border_color(rgba(HAIRLINE))
            .flex()
            .flex_col()
            .child(brand_block("kriko-wordmark-white.svg", "local product knowledge"))
            .child(nav)
    }
}

impl Kriko {
    /// The floating top bar. The strip between the sidebar and the LIVE
    /// toggle is the drag area: a plain client strip that hands its press
    /// to Windows as a caption press, because GPUI 0.2.2 cannot start a
    /// move itself and the platform caption area gets swallowed. It
    /// carries no brand: the sidebar says kriko once, the page head says
    /// where you are.
    /// What the window shows until the engine answers, and instead of a
    /// blank window when it cannot: the engine's own stderr, a retry, and a
    /// way out.
    fn boot_screen(&mut self, maximized: bool, cx: &mut Context<Self>) -> Div {
        let titlebar = self.titlebar(maximized, cx);
        let motion = !self.reduce_motion;
        let body = match self.engine.clone() {
            engine::Status::Failed { title, detail } => div()
                .flex()
                .flex_col()
                .gap(px(16.0))
                .w_full()
                .max_w(px(820.0))
                .child(
                    div()
                        .font_family(DISPLAY)
                        .text_size(px(30.0))
                        .text_color(rgb(DANGER))
                        .child(title),
                )
                .child(div().text_size(px(15.0)).text_color(rgb(MUTED)).child(
                    "This is what the engine said. Try again, or quit and start Kriko from the Start menu.",
                ))
                .child(
                    well()
                        .id("boot-stderr")
                        .max_h(px(360.0))
                        .overflow_y_scroll()
                        .p(px(16.0))
                        .font_family(MONO)
                        .text_size(px(12.0))
                        .text_color(rgb(INK))
                        .child(detail),
                )
                .child(
                    div()
                        .flex()
                        .gap(px(12.0))
                        .child(key("boot-retry", "Try again").on_click(cx.listener(
                            |this, _: &ClickEvent, _w, cx| {
                                engine::restart();
                                this.engine = engine::status();
                                cx.notify();
                            },
                        )))
                        .child(danger("boot-quit", "Quit Kriko").on_click(cx.listener(
                            |_this, _: &ClickEvent, _w, cx| Self::quit(cx),
                        ))),
                ),
            engine::Status::Starting(said) | engine::Status::Ready { base: said, .. } => div()
                .flex()
                .flex_col()
                .items_center()
                .gap(px(18.0))
                .child(led_ripple("boot-ripple", motion))
                .child(
                    div()
                        .font_family(DISPLAY)
                        .text_size(px(30.0))
                        .text_color(rgb(INK))
                        .child("Starting Kriko"),
                )
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(12.0))
                        .text_color(rgb(DIM))
                        .child(said),
                ),
        };
        div()
            .size_full()
            .relative()
            .flex()
            .flex_col()
            .bg(rgb(GROUND))
            .text_color(rgb(INK))
            .font_family(SANS)
            .child(
                div()
                    .flex_1()
                    .flex()
                    .items_center()
                    .justify_center()
                    .p(px(40.0))
                    .child(body),
            )
            .child(titlebar)
    }

    fn titlebar(&self, maximized: bool, cx: &mut Context<Self>) -> Stateful<Div> {
        let toggle_dock = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.dock_open = !this.dock_open;
            cx.notify();
        });

        let zoom_icon = if maximized { "restore" } else { "maximize" };

        titlebar()
            .child(
                // the drag strip: the whole sky span left of the controls
                div()
                    .id("titlebar-drag")
                    .flex()
                    .flex_1()
                    .min_w(px(0.0))
                    .h_full()
                    .cursor_move()
                    .on_mouse_down(MouseButton::Left, |_, _, _| drag_window_fallback()),
            )
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(
                        div()
                            .id("titlebar-dock-toggle")
                            .h(px(28.0))
                            .px(px(12.0))
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .rounded(px(8.0))
                            .cursor_pointer()
                            .when(self.dock_open, |d| d.bg(rgba(GLASS_1)))
                            .on_click(toggle_dock)
                            .child(icon("agents", 14.0).text_color(rgb(if self.dock_open {
                                ICE
                            } else {
                                MUTED
                            })))
                            .child(
                                div()
                                    .font_family(MONO)
                                    .text_size(px(11.0))
                                    .text_color(rgb(if self.dock_open {
                                        ICE
                                    } else {
                                        MUTED
                                    }))
                                    .child(if self.dock_open { "LIVE ON" } else { "LIVE OFF" }),
                            ),
                    )
                    .child(
                        titlebar_button("win-min", "minus", false)
                            .window_control_area(WindowControlArea::Min),
                    )
                    .child(
                        titlebar_button("win-max", zoom_icon, false)
                            .window_control_area(WindowControlArea::Max),
                    )
                    .child(
                        titlebar_button("win-close", "x", true)
                            .window_control_area(WindowControlArea::Close),
                    ),
            )
    }
}

impl Render for Kriko {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        if !matches!(self.engine, engine::Status::Ready { .. }) {
            let maximized = window.is_maximized();
            return self.boot_screen(maximized, cx).into_any_element();
        }
        let tab = self.tab;
        let maximized = window.is_maximized();
        let titlebar = self.titlebar(maximized, cx);
        let sidebar = self.sidebar(cx);
        let content = screens::screen(self, window, cx);
        let dock = dock::dock(self, window, cx);
        let hero = hero(tab.hero_sky(), tab.hero_height(), !self.reduce_motion)
            .child(page_head(tab.crumb(), tab.title(), tab.lead()));
        div()
            .id("kriko-root")
            .size_full()
            .flex()
            .bg(rgb(GROUND))
            .text_color(rgb(INK))
            .font_family(SANS)
            .on_action(cx.listener(|this, _: &NewCheck, _w, cx| {
                this.tab = Tab::Run;
                cx.notify();
            }))
            .on_action(cx.listener(|this, _: &SearchKnowledge, _w, cx| {
                this.tab = Tab::Browse;
                cx.notify();
            }))
            .on_action(cx.listener(|this, _: &JumpBrowse, _w, cx| {
                this.tab = Tab::Browse;
                cx.notify();
            }))
            .child(sidebar)
            .child(
                div()
                    .relative()
                    .flex()
                    .flex_1()
                    .flex_col()
                    .min_w(px(0.0))
                    .min_h(px(0.0))
                    // One scroll for the whole page: the hero scrolls
                    // away with the content, so short windows still
                    // reach everything, and nothing wide ever paints
                    // over the dock.
                    .child(
                        div()
                            .id("main-scroll")
                            .flex()
                            .flex_1()
                            .min_h(px(0.0))
                            .flex_col()
                            .overflow_y_scroll()
                            .overflow_x_hidden()
                            // flex_none keeps the hero and the content
                            // at their natural heights, so the column
                            // overflows and scrolls instead of every
                            // child being squeezed to fit.
                            .child(hero.flex_none())
                            .child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .flex_none()
                                    .px(px(40.0))
                                    .pt(px(20.0))
                                    .pb(px(48.0))
                                    .child(content)
                                    .child(
                                        div()
                                            .mt(px(24.0))
                                            .mb(px(8.0))
                                            .font_family(MONO)
                                            .text_size(px(12.0))
                                            .text_color(rgb(DIM))
                                            .child(data::FOOTER_NOTE),
                                    ),
                            ),
                    )
                    // The bar floats on the sky, after the page so it
                    // paints on top of the hero it blends into.
                    .child(titlebar),
            )
            .when(self.dock_open, |row| row.child(dock))
            .into_any_element()
    }
}
