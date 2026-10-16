//! The Kriko app shell: the sidebar, the hero with the page head, and the
//! dispatch to the tab screens. All state that the screens share (settings
//! flags, filters, selections) lives on [`Kriko`], so every screen is a
//! method over one state struct.

use gpui::{
    div, prelude::*, px, rgb, rgba, App, ClickEvent, Context, Div, FocusHandle,
    IntoElement, KeyDownEvent, ParentElement, Render, ScrollDelta, ScrollWheelEvent, Stateful,
    Styled, Window, WindowControlArea,
};

use crate::dock;
use crate::engine;
use crate::live::Live;
use crate::screens;
use crate::shell;
use crate::theme::*;

// ---- keyboard actions (bound in main.rs) ----
gpui::actions!(kriko, [NewCheck, SearchKnowledge, JumpBrowse]);

// ---- the window's room ----

/// The live dock's width. Its open width is reserved from page content.
const DOCK_W: f32 = DOCK_WIDTH;
/// The titlebar's height; the floating dock starts under it so the window
/// controls on the titlebar stay under the reader's pointer.
const TITLEBAR_H: f32 = 40.0;

/// Below this window width the sidebar shows icons only, unless the reader
/// chose otherwise with its toggle.
const SIDEBAR_FOLD_BELOW: f32 = 1100.0;
/// At narrower widths, the Live panel and expanded sidebar cannot leave a
/// useful page column. Fold the sidebar temporarily so the page can wrap.
const MIN_COMFORTABLE_CONTENT_W: f32 = 380.0;

// ---- tabs ----

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Tab {
    Home,
    Run,
    History,
    Compare,
    Chat,
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

const CHAT_PAGES: &[Tab] = &[Tab::Chat, Tab::Home, Tab::Run, Tab::History];
const COMPARE_PAGES: &[Tab] = &[Tab::Compare, Tab::Overview, Tab::Browse, Tab::Sites];
const AGENT_PAGES: &[Tab] = &[
    Tab::Agents,
    Tab::Local,
    Tab::Activity,
    Tab::Benchmark,
    Tab::Extension,
    Tab::Settings,
];

impl Tab {
    pub fn key(self) -> &'static str {
        match self {
            Tab::Home => "home",
            Tab::Run => "run",
            Tab::History => "history",
            Tab::Compare => "compare",
            Tab::Chat => "chat",
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
            "chat" => Tab::Chat,
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

    /// The screen an extension route names. A route is `<screen>[/<id>]` in
    /// the extension's words (`packs`, `sites`, `check`, `jobs/<id>`,
    /// `subject/<id>`, `result/<id>`, `questions/<id>`, `compare/<id>`), so
    /// its first segment decides; a word it does not know
    /// opens Home, never whatever happened to be on screen.
    pub fn from_route(route: &str) -> Tab {
        let head = route
            .trim_start_matches(['#', '/'])
            .split('/')
            .next()
            .unwrap_or("");
        match head {
            "packs" | "knowledge" => Tab::Overview,
            "subject" => Tab::Browse,
            "result" => Tab::History,
            "questions" => Tab::Compare,
            "jobs" => Tab::Activity,
            "check" => Tab::Home,
            other => Tab::from_key(other),
        }
    }

    fn crumb(self) -> &'static str {
        match self {
            Tab::Home => "check / home",
            Tab::Run => "check / run",
            Tab::History => "history",
            Tab::Compare => "check / compare",
            Tab::Chat => "check / chat",
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
            Tab::Home => "Home",
            Tab::Run => "New check",
            Tab::History => "History",
            Tab::Compare => "Compare",
            Tab::Chat => "New chat",
            Tab::Extension => "Browser extension",
            Tab::Overview => "Overview",
            Tab::Browse => "Browse",
            Tab::Sites => "Sites",
            Tab::Activity => "Activity",
            Tab::Agents => "Agents",
            Tab::Benchmark => "Benchmarks",
            Tab::Local => "Local models",
            Tab::Settings => "Settings",
            Tab::About => "About",
        }
    }

    fn lead(self) -> &'static str {
        match self {
            Tab::Home => "Recent work and saved research.",
            Tab::Run => "Follow a check from question to evidence.",
            Tab::History => "Completed and active research.",
            Tab::Compare => "Compare products and their evidence.",
            Tab::Chat => "",
            Tab::Extension => "Send pages from your browser to Kriko.",
            Tab::Overview => "Catalog coverage and updates.",
            Tab::Browse => "Stored subjects, claims, and evidence.",
            Tab::Sites => "Sources and their trust settings.",
            Tab::Activity => "Recent jobs and database updates.",
            Tab::Agents => "Research agents on this machine.",
            Tab::Benchmark => "Agent results on a fixed test set.",
            Tab::Local => "Local models and their sources.",
            Tab::Settings => "Kriko's behavior on this machine.",
            Tab::About => "Kriko · local product knowledge.",
        }
    }

    fn group(self) -> usize {
        match self {
            Tab::Chat | Tab::Home | Tab::Run | Tab::History => 0,
            Tab::Compare | Tab::Overview | Tab::Browse | Tab::Sites => 1,
            _ => 2,
        }
    }

    fn group_pages(self) -> &'static [Tab] {
        match self.group() {
            0 => CHAT_PAGES,
            1 => COMPARE_PAGES,
            _ => AGENT_PAGES,
        }
    }

    fn hero_sky(self) -> Sky {
        match self {
            Tab::Home | Tab::About => Sky::Bright,
            Tab::Local => Sky::Wide,
            _ => Sky::Dim,
        }
    }

    /// A bar, not a banner: the sky stays, the page head sits in it, and the
    /// content starts right under. Home and About keep a little more of it.
    fn hero_height(self) -> f32 {
        match self {
            Tab::Chat => 184.0,
            Tab::Home => 256.0,
            Tab::About => 220.0,
            Tab::Local => 204.0,
            _ => 184.0,
        }
    }
}

// ---- text fields ----

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Field {
    HistorySearch,
    OverviewSearch,
    ActivityFilter,
    SitesAdd,
    KeyValue,
    BrowseSearch,
    DockReply,
    CompareAsk,
    ChatAsk,
    BoardNote,
    RunSearch,
    LocalUrl,
    LocalSearch,
    LocalGet,
    ExtensionPort,
    ModelSearch,
    BenchModelSearch,
    LibrarySearch,
    QuickAsk,
}

pub struct InputState {
    pub value: String,
    pub handle: FocusHandle,
    pub cursor: Option<usize>,
    pub anchor: Option<usize>,
    pub layout: Option<gpui::ShapedLine>,
    pub wrapped: Vec<(usize, gpui::WrappedLine, gpui::Pixels)>,
    pub bounds: Option<gpui::Bounds<gpui::Pixels>>,
    pub scroll_x: gpui::Pixels,
    pub scroll_y: gpui::Pixels,
    pub selecting: bool,
}

impl InputState {
    fn new(cx: &mut App) -> Self {
        Self {
            value: String::new(),
            handle: cx.focus_handle(),
            cursor: None,
            anchor: None,
            layout: None,
            wrapped: Vec::new(),
            bounds: None,
            scroll_x: px(0.0),
            scroll_y: px(0.0),
            selecting: false,
        }
    }

    pub fn set_value(&mut self, value: String) {
        self.value = value;
        self.cursor = None;
        self.anchor = None;
        self.layout = None;
        self.wrapped.clear();
        self.scroll_x = px(0.0);
        self.scroll_y = px(0.0);
        self.selecting = false;
    }

    pub fn position(&self) -> usize {
        text_boundary(&self.value, self.cursor.unwrap_or(self.value.len()))
    }

    pub fn selection(&self) -> std::ops::Range<usize> {
        text_selection(&self.value, self.position(), self.anchor)
    }

    pub fn replace_selection(&mut self, text: &str) {
        let range = self.selection();
        self.cursor = Some(range.start + text.len());
        self.anchor = None;
        self.value.replace_range(range, text);
    }

    pub fn move_cursor(&mut self, at: usize, extend_selection: bool) {
        self.anchor = if extend_selection {
            Some(self.anchor.unwrap_or(self.position()))
        } else {
            None
        };
        self.cursor = Some(at);
    }
}

// ---- filters ----

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

// ---- the app ----

pub struct Kriko {
    pub tab: Tab,
    /// Where the engine is: starting, answering, or failed with its words.
    pub engine: engine::Status,
    /// What the engine said, per area, for the screens to draw.
    pub live: Live,
    // settings
    pub reduce_motion: bool,
    /// Whether this frame may move: the reader allows motion *and* the window
    /// is the one in front. Set once per frame in `render`. A looping GPUI
    /// animation asks for the next frame forever and every frame redraws the
    /// whole window, so a window behind others or minimized never loops; the
    /// activation change itself redraws, so the loops resume on focus (#184).
    pub motion: bool,
    /// Agent runs at once, 1..=4 (#133): the engine reads it at every start.
    pub run_concurrency: usize,
    pub run_concurrency_prev: usize,
    // inputs
    pub history_search: InputState,
    pub overview_search: InputState,
    pub overview_filters_open: bool,
    pub overview_pack: String,
    pub overview_status: String,
    pub overview_product: String,
    pub log_views: std::collections::HashMap<String, screens::logs::View>,
    pub activity_filter: InputState,
    pub sites_add: InputState,
    pub key_value: InputState,
    pub browse_search: InputState,
    // history
    pub page: usize,
    pub history_span: SpanFilter,
    // activity
    // browse / agents / packs / models
    pub browse_view: usize,
    pub browse_view_prev: usize,
    pub browse_page: usize,
    pub browse_page_size: usize,
    pub browse_filters_open: bool,
    // run: the subject search that starts a check
    pub run_search: InputState,
    // the live actions dock
    pub dock_reply: InputState,
    /// The reply drawer: closed unless you are answering an agent.
    pub dock_reply_open: bool,
    /// The first-run tutorial's open step; `None` while it is closed.
    pub tutorial: Option<usize>,
    /// A route KRIKO_VERIFY asked for, opened once the engine answers.
    pub pending_route: Option<String>,
    /// A saved check a route asked for: History turns to its page.
    pub history_focus: Option<String>,
    /// The full live agent logs drawer in the dock.
    pub dock_logs_open: bool,
    pub dock_feed: Vec<DockFeedEntry>,
    pub dock_open: bool,
    pub extension_advanced_open: bool,
    pub extension_firefox_open: bool,
    pub agents_options_open: bool,
    pub history_insights_open: bool,
    // compare: the engine's own rows live in `live.compare`
    pub compare_note_input: InputState,
    pub compare_question_input: InputState,
    pub chat_input: InputState,
    // local llm: the address, the search service and the model to get; the
    // rest of this area is `live::local`
    pub local_url: InputState,
    pub local_search: InputState,
    pub local_get: InputState,
    pub extension_port_input: InputState,
    pub model_search: InputState,
    pub bench_model_search: InputState,
    pub library_search: InputState,
    pub quick_ask_input: InputState,
    pub sidebar_collapsed: bool,
    /// The reader's own open or closed; None follows the window's width.
    pub sidebar_choice: Option<bool>,
    /// True while the Live panel temporarily folds an otherwise expanded
    /// sidebar to preserve a useful page width.
    sidebar_folded_for_live: bool,
    /// The width the page column has this frame, measured in `render` before
    /// any screen lays out, so a screen can choose side-by-side panels or a
    /// stacked column for the room it really has.
    pub content_w: f32,
    /// The page's scroll, eased. A wheel notch moves `scroll_target`; each
    /// frame `scroll_shown` closes on it and is what the page is drawn at.
    /// Both are offsets (zero at the top, negative further down).
    pub main_scroll: gpui::ScrollHandle,
    pub scroll_target: f32,
    pub scroll_shown: f32,
    pub scroll_moving: bool,
    pub scroll_tick: std::time::Instant,
}

impl Kriko {
    pub fn new(cx: &mut Context<Self>) -> Self {
        let mut extension_port_input = InputState::new(cx);
        extension_port_input.set_value(engine::configured_extension_port().to_string());
        let mut app = Self {
            tab: Tab::Chat,
            engine: engine::status(),
            live: Live::default(),
            reduce_motion: false,
            motion: false,
            run_concurrency: 1,
            run_concurrency_prev: 0,
            history_search: InputState::new(cx),
            overview_search: InputState::new(cx),
            overview_filters_open: false,
            overview_pack: String::new(),
            overview_status: String::new(),
            overview_product: String::new(),
            log_views: std::collections::HashMap::new(),
            activity_filter: InputState::new(cx),
            sites_add: InputState::new(cx),
            key_value: InputState::new(cx),
            browse_search: InputState::new(cx),
            page: 0,
            history_span: SpanFilter::All,
            browse_view: 0,
            browse_view_prev: 0,
            browse_page: 0,
            browse_page_size: 25,
            browse_filters_open: false,
            run_search: InputState::new(cx),
            dock_reply: InputState::new(cx),
            dock_reply_open: false,
            tutorial: None,
            pending_route: None,
            history_focus: None,
            dock_logs_open: false,
            dock_feed: Vec::new(),
            // Every launch starts with the live dock closed.
            dock_open: false,
            extension_advanced_open: false,
            extension_firefox_open: false,
            agents_options_open: false,
            history_insights_open: false,
            compare_note_input: InputState::new(cx),
            compare_question_input: InputState::new(cx),
            chat_input: InputState::new(cx),
            local_url: InputState::new(cx),
            local_search: InputState::new(cx),
            local_get: InputState::new(cx),
            extension_port_input,
            model_search: InputState::new(cx),
            bench_model_search: InputState::new(cx),
            library_search: InputState::new(cx),
            quick_ask_input: InputState::new(cx),
            sidebar_collapsed: false,
            sidebar_choice: None,
            sidebar_folded_for_live: false,
            content_w: 0.0,
            main_scroll: gpui::ScrollHandle::new(),
            scroll_target: 0.0,
            scroll_shown: 0.0,
            scroll_moving: false,
            scroll_tick: std::time::Instant::now(),
        };
        // A verification hook: KRIKO_VERIFY seeds one page's state so it can
        // be captured without driving the mouse on a busy desktop.
        match std::env::var("KRIKO_VERIFY").as_deref() {
            Ok("compare") | Ok("risks") => {
                app.tab = Tab::Compare;
            }
            Ok("local") => {
                app.tab = Tab::Local;
            }
            Ok("agents") => {
                app.tab = Tab::Agents;
            }
            Ok("benchmark") => {
                app.tab = Tab::Benchmark;
            }
            Ok("dock") => {
                app.dock_reply_open = true;
            }
            // The tour itself, captured for review: no screen changes.
            Ok("tutorial") => {}
            // Any other screen by the name the extension uses for it; a route
            // with an id is opened once the engine answers.
            Ok(other) => {
                app.tab = Tab::from_route(other);
                app.pending_route = Some(other.to_string());
            }
            Err(_) => {}
        }
        // The tour: on a first run, or asked for by name in review. A review
        // launch is otherwise exactly the page asked for (above), so its
        // screenshots never carry an unasked-for overlay.
        if matches!(std::env::var("KRIKO_VERIFY").as_deref(), Ok("tutorial")) {
            app.tutorial = Some(0);
        } else if screens::tutorial::due_for_tour() {
            app.tutorial = Some(0);
        }
        shell::set_tray_status(
            matches!(app.engine, engine::Status::Ready { .. }),
            matches!(app.engine, engine::Status::Failed { .. }),
        );
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
        // An engine that answered before the window existed (an attach, or a
        // quick restart) never shows the pulse a change to Ready, so the first
        // read of everything happens here instead of never.
        if matches!(app.engine, engine::Status::Ready { .. }) {
            app.refresh_all(cx);
        }
        app
    }

    /// Show what a route names: the screen (`Tab::from_route`), and the
    /// product or saved check when the route carries its id. One place for
    /// the extension's "open in Kriko" and for KRIKO_VERIFY.
    pub fn open_route(&mut self, route: &str, cx: &mut Context<Self>) {
        let route = route.trim().trim_start_matches(['#', '/']);
        if route.is_empty() {
            return;
        }
        self.tab = Tab::from_route(route);
        if let Some(id) = route.strip_prefix("subject/").filter(|id| !id.is_empty()) {
            self.select_subject(id.to_string(), cx);
        }
        // A saved check opens in History, already unfolded.
        if let Some(id) = route.strip_prefix("result/").filter(|id| !id.is_empty()) {
            if self.live.history.open.as_deref() != Some(id) {
                self.toggle_history_open(id.to_string(), cx);
            }
            // Wherever it sits: no search or span hides it, and History
            // turns to its page once the list is there.
            self.history_search.set_value(String::new());
            self.history_span = SpanFilter::All;
            self.history_focus = Some(id.to_string());
        }
        self.on_open_tab(cx);
        cx.notify();
    }

    fn pulse(&mut self, cx: &mut Context<Self>) {
        #[cfg(any(windows, target_os = "macos"))]
        for action in shell::poll_tray() {
            match action {
                shell::TrayAction::Open => shell::show_window(cx),
                shell::TrayAction::Quit => Self::quit(cx),
            }
        }
        for event in engine::take_events() {
            match event {
                engine::ShellEvent::Focus(route) => {
                    // The extension asked for a screen, not just the window.
                    self.open_route(&route, cx);
                    shell::show_window(cx);
                }
            }
        }
        let now = engine::status();
        if matches!(now, engine::Status::Ready { .. }) {
            if let Some(route) = self.pending_route.take() {
                self.open_route(&route, cx);
            }
        }
        if now != self.engine {
            shell::set_tray_status(
                matches!(now, engine::Status::Ready { .. }),
                matches!(now, engine::Status::Failed { .. }),
            );
            let became_ready = matches!(now, engine::Status::Ready { .. })
                && !matches!(self.engine, engine::Status::Ready { .. });
            self.engine = now;
            if became_ready {
                self.refresh_all(cx);
            }
            cx.notify();
        }
        self.tick_history(cx);
    }

    /// Quit Kriko: the engine first (its exit frees the store's lock), then
    /// the app.
    pub fn quit(cx: &mut Context<Self>) {
        engine::stop();
        shell::remove_tray();
        cx.quit();
    }

    // ---- the first-run tutorial ----

    /// Offer the tour from its first step (Settings' "Show the tour").
    pub fn start_tour(&mut self, cx: &mut Context<Self>) {
        self.tutorial = Some(0);
        cx.notify();
    }

    /// The tour is finished or skipped, and is not offered again unasked.
    pub fn close_tour(&mut self, cx: &mut Context<Self>) {
        screens::tutorial::mark_seen();
        self.tutorial = None;
        cx.notify();
    }

    /// One step forward. The last step's key is its own exit, so this never
    /// runs past the end.
    pub fn advance_tour(&mut self, cx: &mut Context<Self>) {
        let Some(step) = self.tutorial else { return };
        if step + 1 >= screens::tutorial::STEPS_LEN {
            self.close_tour(cx);
        } else {
            self.tutorial = Some(step + 1);
            cx.notify();
        }
    }

    /// Retry the data shown by the screen under the persistent shell error.
    /// Clear first so an error from this retry can replace it, while ordinary
    /// background successes remain unable to hide a still-relevant failure.
    fn retry_current_screen(&mut self, cx: &mut Context<Self>) {
        self.live.problem = None;
        match self.tab {
            Tab::Home => {
                self.refresh_history(cx);
                self.refresh_jobs(cx);
                self.refresh_agents(cx);
                self.refresh_updates(cx);
                self.check_app_update(cx);
            }
            Tab::Run => {
                self.refresh_jobs(cx);
                self.refresh_agents(cx);
            }
            Tab::History => self.refresh_history(cx),
            Tab::Compare => self.refresh_compare(cx),
            Tab::Chat => self.refresh_chat(cx),
            Tab::Extension => self.refresh_extension(cx),
            Tab::Overview => {
                self.refresh_packs(cx);
                self.refresh_thin(cx);
                self.refresh_updates(cx);
            }
            Tab::Browse => self.refresh_subjects(cx),
            Tab::Sites => self.refresh_sites(cx),
            Tab::Activity => self.refresh_activity(cx),
            Tab::Agents => self.refresh_agents(cx),
            Tab::Benchmark => {
                self.refresh_bench(cx);
                self.refresh_jobs(cx);
            }
            Tab::Local => {
                self.refresh_local(cx);
                self.refresh_jobs(cx);
            }
            Tab::Settings => {
                self.refresh_local(cx);
                self.refresh_settings(cx);
                self.refresh_keys(cx);
                self.refresh_health(cx);
                self.refresh_startup(cx);
            }
            Tab::About => self.refresh_health(cx),
        }
        cx.notify();
    }

    pub(crate) fn input(&self, field: Field) -> &InputState {
        match field {
            Field::HistorySearch => &self.history_search,
            Field::OverviewSearch => &self.overview_search,
            Field::ActivityFilter => &self.activity_filter,
            Field::SitesAdd => &self.sites_add,
            Field::KeyValue => &self.key_value,
            Field::BrowseSearch => &self.browse_search,
            Field::DockReply => &self.dock_reply,
            Field::CompareAsk => &self.compare_question_input,
            Field::ChatAsk => &self.chat_input,
            Field::BoardNote => &self.compare_note_input,
            Field::RunSearch => &self.run_search,
            Field::LocalUrl => &self.local_url,
            Field::LocalSearch => &self.local_search,
            Field::LocalGet => &self.local_get,
            Field::ExtensionPort => &self.extension_port_input,
            Field::ModelSearch => &self.model_search,
            Field::BenchModelSearch => &self.bench_model_search,
            Field::LibrarySearch => &self.library_search,
            Field::QuickAsk => &self.quick_ask_input,
        }
    }

    pub(crate) fn input_mut(&mut self, field: Field) -> &mut InputState {
        match field {
            Field::HistorySearch => &mut self.history_search,
            Field::OverviewSearch => &mut self.overview_search,
            Field::ActivityFilter => &mut self.activity_filter,
            Field::SitesAdd => &mut self.sites_add,
            Field::KeyValue => &mut self.key_value,
            Field::BrowseSearch => &mut self.browse_search,
            Field::DockReply => &mut self.dock_reply,
            Field::CompareAsk => &mut self.compare_question_input,
            Field::ChatAsk => &mut self.chat_input,
            Field::BoardNote => &mut self.compare_note_input,
            Field::RunSearch => &mut self.run_search,
            Field::LocalUrl => &mut self.local_url,
            Field::LocalSearch => &mut self.local_search,
            Field::LocalGet => &mut self.local_get,
            Field::ExtensionPort => &mut self.extension_port_input,
            Field::ModelSearch => &mut self.model_search,
            Field::BenchModelSearch => &mut self.bench_model_search,
            Field::LibrarySearch => &mut self.library_search,
            Field::QuickAsk => &mut self.quick_ask_input,
        }
    }

    pub(crate) fn handle_key(
        this: &mut Kriko,
        field: Field,
        event: &KeyDownEvent,
        cx: &mut Context<Kriko>,
    ) {
        let ks = &event.keystroke;
        if ks.modifiers.control || ks.modifiers.platform {
            let selected = this.input(field).selection();
            match ks.key.as_str() {
                "a" => {
                    let len = this.input(field).value.len();
                    let input = this.input_mut(field);
                    input.anchor = Some(0);
                    input.cursor = Some(len);
                }
                "c" | "x" if !selected.is_empty() => {
                    cx.write_to_clipboard(gpui::ClipboardItem::new_string(
                        this.input(field).value[selected].to_string(),
                    ));
                    if ks.key == "x" {
                        this.input_mut(field).replace_selection("");
                    }
                }
                "v" => {
                    if let Some(text) = cx.read_from_clipboard().and_then(|c| c.text()) {
                        let text = if field == Field::ChatAsk {
                            text.replace("\r\n", "\n").replace('\r', "\n")
                        } else {
                            text.replace(['\r', '\n'], " ")
                        };
                        this.input_mut(field).replace_selection(&text);
                    }
                }
                _ => return,
            }
            this.input_changed(field, cx);
            return;
        }
        if ks.modifiers.alt {
            return;
        }
        // Enter in the dock reply says it to the running job.
        if ks.key.as_str() == "enter" && field == Field::DockReply {
            this.send_reply(cx);
            cx.notify();
            return;
        }
        // Enter in the Run search looks the subject up.
        if ks.key.as_str() == "enter" && field == Field::RunSearch {
            this.search_subjects(cx);
            cx.notify();
            return;
        }
        // Enter in the Sites add field adds the site straight away.
        if ks.key.as_str() == "enter" && field == Field::SitesAdd {
            let host = this.input(field).value.trim().to_string();
            if !host.is_empty() {
                this.input_mut(field).set_value(String::new());
                this.register_site(&host, cx);
            }
            cx.notify();
            return;
        }
        // Enter in the key field saves the key for the provider picked.
        if ks.key.as_str() == "enter" && field == Field::KeyValue {
            let value = this.input(field).value.trim().to_string();
            if let Some(provider) = this.live.knowledge.key_provider.clone() {
                this.input_mut(field).set_value(String::new());
                this.save_key(provider, value, cx);
            }
            cx.notify();
            return;
        }
        // Enter on the compare board commits the note being edited.
        if ks.key.as_str() == "enter" && field == Field::BoardNote {
            this.commit_board_note(cx);
            cx.notify();
            return;
        }
        // Enter in the Get field starts the download.
        if ks.key.as_str() == "enter" && field == Field::LocalGet {
            this.local_pull(cx);
            return;
        }
        if ks.key.as_str() == "enter" && field == Field::ExtensionPort {
            this.save_extension_port(cx);
            return;
        }
        // Enter on the compare question asks it, the same as the Ask key.
        if ks.key.as_str() == "enter" && field == Field::CompareAsk {
            this.ask_compare_question(cx);
            cx.notify();
            return;
        }
        // Enter in the chat composer sends the message.
        if ks.key.as_str() == "enter" && field == Field::ChatAsk {
            if ks.modifiers.shift {
                this.chat_input.replace_selection("\n");
            } else {
                this.send_chat_message(cx);
            }
            cx.notify();
            return;
        }
        let input = this.input_mut(field);
        if field == Field::ChatAsk && matches!(ks.key.as_str(), "up" | "down") {
            crate::text_input::move_chat_line(input, ks.key == "down", ks.modifiers.shift);
            cx.notify();
            return;
        }
        let at = input.position();
        let previous = input.value[..at]
            .char_indices()
            .last()
            .map(|(i, _)| i)
            .unwrap_or(0);
        let next = input.value[at..]
            .chars()
            .next()
            .map(|c| at + c.len_utf8())
            .unwrap_or(at);
        match ks.key.as_str() {
            "left" => {
                let to = if !ks.modifiers.shift && !input.selection().is_empty() {
                    input.selection().start
                } else {
                    previous
                };
                input.move_cursor(to, ks.modifiers.shift);
            }
            "right" => {
                let to = if !ks.modifiers.shift && !input.selection().is_empty() {
                    input.selection().end
                } else {
                    next
                };
                input.move_cursor(to, ks.modifiers.shift);
            }
            "home" => input.move_cursor(0, ks.modifiers.shift),
            "end" => input.move_cursor(input.value.len(), ks.modifiers.shift),
            "backspace" => {
                if input.selection().is_empty() {
                    input.anchor = Some(previous);
                }
                input.replace_selection("");
            }
            "delete" => {
                if input.selection().is_empty() {
                    input.anchor = Some(next);
                }
                input.replace_selection("");
            }
            "escape" => {}
            "space" => input.replace_selection(" "),
            _ => {
                let text = ks.key_char.as_deref().unwrap_or(ks.key.as_str());
                let max_chars = if matches!(field, Field::ChatAsk | Field::CompareAsk) {
                    2000
                } else {
                    200
                };
                if text.chars().count() == 1 && input.value.chars().count() < max_chars {
                    input.replace_selection(text);
                }
            }
        }
        this.input_changed(field, cx);
    }

    pub(crate) fn input_changed(&mut self, field: Field, cx: &mut Context<Self>) {
        if field == Field::HistorySearch {
            self.page = 0;
        }
        if field == Field::BrowseSearch {
            self.browse_search_typed(cx);
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
        crate::text_input::field(self, field, id, placeholder, icon_name, window, cx)
    }

    // ---- smooth scroll ----

    /// A mouse-wheel notch moves where the page is *going*, not where it is.
    /// A touchpad already sends a smooth stream of pixels, so those pass
    /// through to the page untouched.
    fn wheel(&mut self, event: &ScrollWheelEvent, window: &mut Window, cx: &mut Context<Self>) {
        if self.reduce_motion || !matches!(event.delta, ScrollDelta::Lines(_)) {
            self.scroll_moving = false;
            return;
        }
        let step = f32::from(event.delta.pixel_delta(window.line_height()).y);
        let floor = -f32::from(self.main_scroll.max_offset().height);
        if !self.scroll_moving {
            self.scroll_target = self.scroll_shown;
            self.scroll_tick = std::time::Instant::now();
        }
        self.scroll_target = (self.scroll_target + step).clamp(floor, 0.0);
        self.scroll_moving = true;
        cx.notify();
    }

    /// One frame of the ease: the page is drawn a fraction of the way to
    /// where the wheel sent it (about 90 ms to settle), and asks for the next
    /// frame until it arrives. Idle, it just follows wherever the page is.
    fn step_scroll(&mut self, window: &mut Window) {
        if !self.scroll_moving {
            let at = f32::from(self.main_scroll.offset().y);
            self.scroll_shown = at;
            self.scroll_target = at;
            return;
        }
        let now = std::time::Instant::now();
        let dt = now.duration_since(self.scroll_tick).as_secs_f32().min(0.05);
        self.scroll_tick = now;
        let floor = -f32::from(self.main_scroll.max_offset().height);
        self.scroll_target = self.scroll_target.clamp(floor, 0.0);
        self.scroll_shown += (self.scroll_target - self.scroll_shown) * (1.0 - (-dt / 0.09).exp());
        if (self.scroll_target - self.scroll_shown).abs() < 0.4 {
            self.scroll_shown = self.scroll_target;
            self.scroll_moving = false;
        } else {
            window.request_animation_frame();
        }
        self.main_scroll
            .set_offset(gpui::point(px(0.0), px(self.scroll_shown)));
    }

    // ---- sidebar ----

    fn sidebar(&self, height: f32, cx: &mut Context<Self>) -> Div {
        let group = self.tab.group();
        let primary = [
            (Tab::Chat, "chat", "Chat"),
            (Tab::Compare, "compare", "Compare"),
            (Tab::Agents, "agents", "Agents & settings"),
        ];
        let mut main_nav = div()
            .flex()
            .flex_col()
            .gap(px(6.0))
            .px(px(0.0))
            .pt(px(10.0));
        for (index, (tab, glyph, label)) in primary.iter().copied().enumerate() {
            let row = nav_item(
                gpui::ElementId::Name(format!("primary-tab-{index}").into()),
                glyph,
                if self.sidebar_collapsed { "" } else { label },
                group == index,
                None,
                None,
            )
            .h(px(50.0))
            .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.tab = tab;
                this.on_open_tab(cx);
                cx.notify();
            }));
            main_nav = main_nav.child(row);
        }

        let new_research = div()
            .id("sidebar-new-research")
            .h(px(46.0))
            .mx(px(0.0))
            .mt(px(12.0))
            .px(px(12.0))
            .flex()
            .items_center()
            .justify_center()
            .gap(px(8.0))
            .rounded(px(12.0))
            .bg(rgb(BRAND))
            .text_color(rgb(0xffffff))
            .font_family(SANS)
            .font_weight(gpui::FontWeight::SEMIBOLD)
            .text_size(px(16.0))
            .cursor_pointer()
            .hover(|s| s.bg(rgb(BRAND_HOVER)))
            .active(|s| s.bg(rgb(BRAND_LOW)))
            .when(self.sidebar_collapsed, |d| d.px(px(0.0)))
            .child(icon("plus", 18.0).text_color(rgb(0xffffff)))
            .when(!self.sidebar_collapsed, |d| d.child("New research"))
            .on_click(cx.listener(|this, _: &ClickEvent, _w, cx| {
                this.tab = Tab::Run;
                this.on_open_tab(cx);
                cx.notify();
            }));

        let mut support = div()
            .id("sidebar-support")
            .flex()
            .flex_col()
            .gap(px(2.0))
            .px(px(12.0))
            .pt(px(24.0))
            .flex_1()
            .min_h(px(0.0))
            .overflow_y_scroll()
            .occlude();

        if !self.sidebar_collapsed {
            let subject_count = self.live.knowledge.totals.subjects.max(0);
            support = support.child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .pb(px(7.0))
                    .child(eyebrow("Products"))
                    .child(screens::mono(&subject_count.to_string(), DIM)),
            );
            if self.live.history.subjects.is_empty() {
                support = support.child(
                    nav_item(
                        "sidebar-files",
                        "file",
                        "Open product files",
                        false,
                        None,
                        None,
                    )
                    .h(px(40.0))
                    .text_size(px(15.0))
                    .on_click(cx.listener(|this, _: &ClickEvent, _w, cx| {
                        this.tab = Tab::Browse;
                        this.on_open_tab(cx);
                        cx.notify();
                    })),
                );
            } else {
                for subject in self.live.history.subjects.iter().take(4) {
                    let id = subject.id.clone();
                    let mut label: String = subject.label.chars().take(25).collect();
                    if subject.label.chars().count() > 25 {
                        label.push('…');
                    }
                    support = support.child(
                        div()
                            .id(gpui::ElementId::Name(
                                format!("sidebar-subject-{id}").into(),
                            ))
                            .h(px(40.0))
                            .px(px(8.0))
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .rounded(px(8.0))
                            .text_color(rgb(INK_2))
                            .font_family(SANS)
                            .text_size(px(15.0))
                            .cursor_pointer()
                            .hover(|s| s.bg(rgba(GLASS_3)))
                            .child(icon("file", 14.0).text_color(rgb(MUTED)))
                            .child(div().flex_1().overflow_hidden().child(label))
                            .child(screens::mono(&subject.claims.to_string(), DIM))
                            .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                                this.tab = Tab::Browse;
                                this.on_open_tab(cx);
                                this.select_subject(id.clone(), cx);
                                cx.notify();
                            })),
                    );
                }
            }

            let active: Vec<_> = self.live.run.jobs.iter().filter(|job| !job.done).collect();
            if !active.is_empty() {
            support = support.child(
                div()
                    .mt(px(20.0))
                    .pb(px(7.0))
                    .flex()
                    .items_center()
                    .justify_between()
                    .child(eyebrow("Live now"))
                    .child(screens::mono(&active.len().to_string(), DIM)),
            );
                for job in active.iter().take(2) {
                    let task: String = if job.product.is_empty() {
                        job.kind.chars().take(26).collect()
                    } else {
                        job.product.chars().take(26).collect()
                    };
                    let label = if job.attention.is_some() {
                        "NEEDS YOU"
                    } else {
                        "LIVE"
                    };
                    support = support.child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .py(px(5.0))
                            .child(icon("term", 16.0).text_color(rgb(BRAND_BRIGHT)))
                            .child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .min_w(px(0.0))
                                    .child(
                                        div()
                                            .font_family(SANS)
                                            .text_size(px(12.0))
                                            .text_color(rgb(INK_2))
                                            .child(task),
                                    )
                                    .child(tag(
                                        format!("sidebar-job-{}", job.id),
                                        if job.attention.is_some() {
                                            TagState::Need
                                        } else {
                                            TagState::Live
                                        },
                                        label,
                                        self.motion,
                                    )),
                            ),
                    );
                }
            }


        }

        let footer = div()
            .px(px(12.0))
            .pt(px(10.0))
            .flex()
            .items_center()
            .justify_between()
            .border_t_1()
            .border_color(rgba(HAIRLINE))
            .when(!self.sidebar_collapsed, |d| {
                d.child(
                    div()
                        .id("footer-about")
                        .font_family(MONO)
                        .text_size(px(12.0))
                        .text_color(rgb(DIM))
                        .cursor_pointer()
                        .hover(|d| d.text_color(rgb(INK)))
                        .on_click(cx.listener(|this, _: &ClickEvent, _w, cx| {
                            this.tab = Tab::About;
                            this.on_open_tab(cx);
                            cx.notify();
                        }))
                        .child(format!("v{} · no account", env!("CARGO_PKG_VERSION"))),
                )
            })
            .child(
                titlebar_button("sidebar-minimise", "sidebar", false).on_click(cx.listener(
                    |this, _: &ClickEvent, _w, cx| {
                        if this.sidebar_folded_for_live {
                            this.dock_open = false;
                            this.sidebar_choice = Some(false);
                            this.sidebar_collapsed = false;
                            this.sidebar_folded_for_live = false;
                        } else {
                            this.sidebar_choice = Some(!this.sidebar_collapsed);
                            this.sidebar_collapsed = !this.sidebar_collapsed;
                        }
                        cx.notify();
                    },
                )),
            );

        div()
            .w(px(if self.sidebar_collapsed {
                76.0
            } else {
                SIDEBAR_W
            }))
            .h(px((height - 24.0).max(0.0)))
            .mt(px(12.0))
            .mb(px(12.0))
            .ml(px(12.0))
            .mr(px(8.0))
            .px(px(12.0))
            .pt(px(20.0))
            .pb(px(14.0))
            .overflow_hidden()
            .flex_none()
            .bg(rgb(SURFACE_1))
            .border_1()
            .border_color(rgba(HAIRLINE))
            .rounded(px(24.0))
            .flex()
            .flex_col()
            .when(!self.sidebar_collapsed, |d| {
                d.child(brand_block(
                    "kriko-wordmark-white.svg",
                    "local product knowledge",
                ))
            })
            .child(main_nav)
            .child(new_research)
            .child(support)
            .child(footer)
    }

    fn page_subnav(&self, cx: &mut Context<Self>) -> Div {
        let mut row = div()
            .flex()
            .flex_wrap()
            .items_center()
            .gap(px(6.0))
            .pb(px(10.0))
            .border_b_1()
            .border_color(rgba(HAIRLINE));
        for tab in self.tab.group_pages() {
            let current = self.tab == *tab;
            let name = if *tab == Tab::Chat {
                "Chat"
            } else {
                tab.title()
            };
            let target = *tab;
            let item = div()
                .id(gpui::ElementId::Name(
                    format!("page-subnav-{}", target.key()).into(),
                ))
                .h(px(40.0))
                .px(px(14.0))
                .flex()
                .items_center()
                .justify_center()
                .rounded(px(12.0))
                .font_family(SANS)
                .font_weight(gpui::FontWeight::SEMIBOLD)
                .text_size(px(15.0))
                .text_color(rgb(if current { ICE } else { MUTED }))
                .bg(rgba(if current { BRAND_WASH } else { 0x00000000 }))
                .cursor_pointer()
                .hover(|s| s.bg(rgba(GLASS_3)).text_color(rgb(INK)))
                .child(name.to_string())
                .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.tab = target;
                    this.on_open_tab(cx);
                    cx.notify();
                }));
            row = row.child(item);
        }
        row
    }

    fn working_rail(&self, cx: &mut Context<Self>) -> Div {
        let jobs: Vec<_> = self.live.run.jobs.iter().filter(|job| !job.done).collect();
        let mut rail = div()
            .w(px(340.0))
            .h_full()
            .px(px(16.0))
            .pt(px(64.0))
            .pb(px(18.0))
            .flex_none()
            .flex()
            .flex_col()
            .gap(px(12.0))
            .bg(rgb(SURFACE_1))
            .border_l_1()
            .border_color(rgba(HAIRLINE));
        rail = rail.child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .pb(px(4.0))
                .child(eyebrow("WORKING AGENTS"))
                .child(
                    div()
                        .min_w(px(28.0))
                        .h(px(28.0))
                        .px(px(8.0))
                        .flex()
                        .items_center()
                        .justify_center()
                        .rounded(px(8.0))
                        .bg(rgb(WELL))
                        .border_1()
                        .border_color(rgba(HAIRLINE))
                        .font_family(MONO)
                        .text_size(px(12.0))
                        .text_color(rgb(ICE))
                        .child(jobs.len().to_string()),
                ),
        );
        if jobs.is_empty() {
            rail = rail.child(
                card()
                    .flex()
                    .flex_col()
                    .gap(px(10.0))
                    .child(icon("term", 20.0).text_color(rgb(BRAND_BRIGHT)))
                    .child(
                        div()
                            .font_family(SANS)
                            .font_weight(gpui::FontWeight::SEMIBOLD)
                            .text_size(px(14.0))
                            .text_color(rgb(INK_2))
                            .child("No active work"),
                    )
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(12.0))
                            .text_color(rgb(MUTED))
                            .child("New research appears here while it runs."),
                    ),
            );
        } else {
            for job in jobs.iter().take(5) {
                let label = if job.attention.is_some() {
                    "NEEDS YOU"
                } else if job.state == "queued" {
                    "QUEUED"
                } else {
                    "LIVE"
                };
                let state = if job.attention.is_some() {
                    TagState::Need
                } else if job.state == "queued" {
                    TagState::Queue
                } else {
                    TagState::Live
                };
                let name = if !job.model.is_empty() {
                    job.model.clone()
                } else if !job.harness.is_empty() {
                    job.harness.clone()
                } else {
                    "Research agent".to_string()
                };
                let task = if !job.product.is_empty() {
                    job.product.clone()
                } else if !job.message.is_empty() {
                    job.message.clone()
                } else {
                    job.kind.clone()
                };
                let job_id = job.id.clone();
                let progress = job.progress.clamp(0.0, 1.0) * 100.0;
                let action = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.tab = Tab::Run;
                    this.on_open_tab(cx);
                    cx.notify();
                });
                rail = rail.child(
                    card()
                        .flex()
                        .flex_col()
                        .gap(px(10.0))
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .gap(px(10.0))
                                .child(
                                    well()
                                        .size(px(40.0))
                                        .flex()
                                        .items_center()
                                        .justify_center()
                                        .child(icon("term", 18.0).text_color(rgb(BRAND_BRIGHT))),
                                )
                                .child(
                                    div()
                                        .flex()
                                        .flex_col()
                                        .min_w(px(0.0))
                                        .child(
                                            div()
                                                .font_family(SANS)
                                                .font_weight(gpui::FontWeight::SEMIBOLD)
                                                .text_size(px(14.0))
                                                .text_color(rgb(INK_2))
                                                .child(name),
                                        )
                                        .child(
                                            div()
                                                .font_family(MONO)
                                                .text_size(px(11.0))
                                                .text_color(rgb(MUTED))
                                                .child(task),
                                        ),
                                ),
                        )
                        .child(tag(format!("rail-job-{job_id}"), state, label, self.motion))
                        .child(progress_bar(
                            &format!("rail-meter-{job_id}"),
                            progress / 100.0,
                            self.motion,
                        ))
                        .child(ghost("rail-open-run", "Open run").on_click(action)),
                );
            }
        }
        rail.child(div().flex_1()).child(
            div()
                .font_family(MONO)
                .text_size(px(10.0))
                .text_color(rgb(DIM))
                .child("Research saved on this machine"),
        )
    }
}

impl Kriko {
    /// The floating top bar. The strip between the sidebar and the LIVE
    /// toggle is the drag area. GPUI maps its Drag hitbox to the native
    /// caption hit test, so Windows owns the move gesture. It
    /// carries no brand: the sidebar says kriko once, the page head says
    /// where you are.
    /// What the window shows until the engine answers, and instead of a
    /// blank window when it cannot: the engine's own stderr, a retry, and a
    /// way out.
    fn boot_screen(&mut self, maximized: bool, cx: &mut Context<Self>) -> Div {
        let titlebar = self.titlebar(maximized, cx);
        let motion = self.motion;
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
        let needs_you = self.live.run.needs_you().len();

        titlebar()
            .child(
                // The system drag area avoids synthesizing native mouse messages.
                div()
                    .id("titlebar-drag")
                    .flex()
                    .flex_1()
                    .min_w(px(0.0))
                    .h_full()
                    .cursor_move()
                    .window_control_area(WindowControlArea::Drag),
            )
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(
                        div()
                            .id("titlebar-dock-toggle")
                            .h(px(32.0))
                            .px(px(12.0))
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .rounded(px(8.0))
                            .cursor_pointer()
                            .bg(rgba(GLASS_1))
                            .border_1()
                            .border_color(rgba(HAIRLINE))
                            .when(self.dock_open, |d| {
                                d.bg(rgba(GLASS_2)).border_color(rgba(BRAND_BRIGHT))
                            })
                            .on_click(toggle_dock)
                            .child(icon("activity", 18.0).text_color(rgb(if self.dock_open {
                                ICE
                            } else {
                                MUTED
                            })))
                            .child(
                                div()
                                    .font_family(SANS)
                                    .font_weight(gpui::FontWeight::SEMIBOLD)
                                    .text_size(px(13.0))
                                    .text_color(rgb(if self.dock_open { ICE } else { MUTED }))
                                    .child("Live"),
                            ),
                    )
                    .when(needs_you > 0, |d| {
                        d.child(tag(
                            "titlebar-needs-you",
                            TagState::Need,
                            &format!("? {needs_you}"),
                            self.motion,
                        ))
                    })
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
        self.motion = !self.reduce_motion && window.is_window_active();
        // A job's bar eases a frame at a time. Ask for the next frame while
        // one still moves (a job is running, in front, motion on), and nowhere
        // else: the idle guard in test_the_idle_window_does_not_draw.py.
        if self.live.run.advance_bars(self.motion) {
            window.request_animation_frame();
        }
        if !matches!(self.engine, engine::Status::Ready { .. }) {
            let maximized = window.is_maximized();
            return self.boot_screen(maximized, cx).into_any_element();
        }
        let tab = self.tab;
        self.step_scroll(window);
        // The page uses compact side padding in a narrow window. While Live
        // is open, reserve its width plus a gutter from the content column so
        // buttons and text stay clear of the floating panel.
        let viewport_w = f32::from(window.viewport_size().width);
        let viewport_h = f32::from(window.viewport_size().height);
        // Narrow windows give the page the room: the sidebar folds to its
        // icons below this width unless the reader opened it themselves.
        let open = self.dock_open;
        let preferred_sidebar_collapsed = self
            .sidebar_choice
            .unwrap_or(viewport_w < SIDEBAR_FOLD_BELOW);
        let page_pad = if viewport_w < SIDEBAR_FOLD_BELOW {
            20.0
        } else {
            40.0
        };
        let dock_inset = if open { DOCK_W + 24.0 } else { 0.0 };
        // Live work is available on demand; an idle rail need not occupy the page.
        let rail_w = 0.0;
        let rail_inset = if rail_w > 0.0 { rail_w + 8.0 } else { 0.0 };
        let expanded_content_w =
            viewport_w - SIDEBAR_W - 20.0 - 2.0 * page_pad - dock_inset - rail_inset;
        self.sidebar_folded_for_live =
            open && !preferred_sidebar_collapsed && expanded_content_w < MIN_COMFORTABLE_CONTENT_W;
        self.sidebar_collapsed = preferred_sidebar_collapsed || self.sidebar_folded_for_live;
        let sidebar_w = if self.sidebar_collapsed {
            76.0
        } else {
            SIDEBAR_W
        };
        self.content_w =
            (viewport_w - sidebar_w - 20.0 - 2.0 * page_pad - dock_inset - rail_inset).max(0.0);
        let maximized = window.is_maximized();
        let titlebar = self.titlebar(maximized, cx);
        let sidebar = self.sidebar(viewport_h, cx);
        let rail = if rail_w > 0.0 {
            Some(self.working_rail(cx))
        } else {
            None
        };
        let content = screens::screen(self, window, cx);
        // A closed panel has no element tree. Opening it lays out the page
        // once instead of animating the widths of two entire columns.
        let dock_wrap = if open {
            Some(div()
                .absolute()
                .top(px(TITLEBAR_H + 8.0))
                .bottom(px(12.0))
                .right(px(12.0))
                .w(px(DOCK_W))
                .overflow_hidden()
                .child(dock::dock(self, window, cx)))
        } else {
            None
        };
        // The tour paints over everything, so it is built last.
        let tour = self
            .tutorial
            .is_some()
            .then(|| screens::tutorial::overlay(self, cx));
        let mut page_content = div().flex().flex_col().flex_none().w_full().gap(px(24.0));
        if tab != Tab::About {
            page_content = page_content.child(self.page_subnav(cx));
        }
        if let Some(problem) = self.live.problem.clone() {
            let retry = cx.listener(|this, _: &ClickEvent, _w, cx| {
                this.retry_current_screen(cx);
            });
            let dismiss = cx.listener(|this, _: &ClickEvent, _w, cx| {
                this.live.problem = None;
                cx.notify();
            });
            page_content =
                page_content.child(
                    card()
                        .bg(rgba(DANGER_WASH))
                        .border_color(rgba(DANGER_EDGE))
                        .flex()
                        .flex_col()
                        .gap(px(10.0))
                        .child(
                            div()
                                .flex()
                                .flex_wrap()
                                .items_center()
                                .justify_between()
                                .gap(px(12.0))
                                .child(tag(
                                    "engine-request-failed",
                                    TagState::Block,
                                    "Engine request failed",
                                    self.motion,
                                ))
                                .child(ghost("engine-error-dismiss", "Dismiss").on_click(dismiss)),
                        )
                        .child(screens::row_desc(&problem))
                        .child(div().flex().flex_wrap().gap(px(8.0)).child(
                            key("engine-error-retry", "Refresh this screen").on_click(retry),
                        )),
                );
        }
        let content = if tab == Tab::Chat {
            content
        } else {
            arrive(content, format!("page-{}", tab.key()), self.motion)
        };
        page_content = page_content.child(content);
        if tab == Tab::Chat {
            page_content = page_content.flex_1().min_h(px(0.0));
        }
        let root = div()
            .id("kriko-root")
            .size_full()
            .relative()
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
                            .w_full()
                            .flex()
                            .flex_1()
                            .min_h(px(0.0))
                            .flex_col()
                            .overflow_y_scroll()
                            .overflow_x_hidden()
                            .track_scroll(&self.main_scroll)
                            .on_scroll_wheel(cx.listener(Self::wheel))
                            // Reserve only the native window controls; page
                            // navigation replaces the old sky and title banner.
                            .child(div().h(px(TITLEBAR_H)).flex_none())
                            .child(
                                page_content
                                    .pl(px(page_pad))
                                    .pr(px(page_pad + dock_inset))
                                    .pt(px(16.0))
                                    .pb(px(32.0)),
                            ),
                    )
                    // The bar floats on the sky, after the page so it
                    // paints on top of the hero it blends into.
                    .child(titlebar),
            );
        let root = if let Some(rail) = rail {
            root.child(rail)
        } else {
            root
        };
        root.children(dock_wrap)
            // The tour's scrim, above the dock and the titlebar.
            .children(tour)
            .into_any_element()
    }
}

fn text_boundary(value: &str, requested: usize) -> usize {
    let mut at = requested.min(value.len());
    while !value.is_char_boundary(at) {
        at -= 1;
    }
    at
}

fn text_selection(value: &str, cursor: usize, anchor: Option<usize>) -> std::ops::Range<usize> {
    let at = text_boundary(value, cursor);
    let anchor = text_boundary(value, anchor.unwrap_or(at));
    at.min(anchor)..at.max(anchor)
}

#[cfg(test)]
mod route_tests {
    use super::Tab;

    #[test]
    fn an_extension_route_opens_the_screen_it_names() {
        assert!(Tab::from_route("packs") == Tab::Overview);
        assert!(Tab::from_route("sites") == Tab::Sites);
        assert!(Tab::from_route("subject/abc123") == Tab::Browse);
        assert!(Tab::from_route("jobs/j-1") == Tab::Activity);
        assert!(Tab::from_route("check") == Tab::Home);
        assert!(Tab::from_route("result/abc123") == Tab::History);
        assert!(Tab::from_route("questions/abc123") == Tab::Compare);
        assert!(Tab::from_route("compare/abc123") == Tab::Compare);
        assert!(Tab::from_route("#/history") == Tab::History);
        assert!(Tab::from_route("no-such-screen") == Tab::Home);
    }
}

#[cfg(test)]
mod input_tests {
    use super::{text_boundary, text_selection};

    #[test]
    fn unicode_selection_clamps_stale_positions_and_replaces_whole_characters() {
        let mut value = "Şımart 🤖".to_string();
        assert_eq!(text_boundary(&value, 1), 0);
        let emoji = value.find('🤖').unwrap();
        let range = text_selection(&value, value.len() + 100, Some(emoji + 1));
        value.replace_range(range, "Katya");
        assert_eq!(value, "Şımart Katya");
        assert_eq!(text_selection(&value, 0, Some(2)), 0..2);
        assert_eq!(text_selection("", 42, Some(10)), 0..0);
    }
}
