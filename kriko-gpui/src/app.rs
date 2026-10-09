//! The Kriko app shell: the sidebar, the hero with the page head, and the
//! dispatch to the tab screens. All state that the screens share (settings
//! flags, filters, selections) lives on [`Kriko`], so every screen is a
//! method over one state struct.

use gpui::{
    AnimationExt, div, prelude::*, px, rgb, rgba, App, ClickEvent, Context, Div, FocusHandle, IntoElement,
    KeyDownEvent, ParentElement, Render, Stateful, Styled, Window, WindowControlArea,
};

use crate::data;
use crate::dock;
use crate::engine;
use crate::live::Live;
use crate::shell;
use crate::screens;
use crate::theme::*;

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
            Tab::Benchmark => "How the agents and planes do on a fixed test set, here.",
            Tab::Local => "Choose a model on this machine and see where its answers come from.",
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
    OverviewSearch,
    ActivityFilter,
    SitesAdd,
    KeyValue,
    BrowseSearch,
    DockReply,
    CompareAsk,
    BoardNote,
    RunSearch,
    LocalUrl,
    LocalSearch,
    LocalGet,
    ExtensionPort,
    ModelSearch,
    BenchModelSearch,
    LibrarySearch,
}

pub struct InputState {
    pub value: String,
    pub handle: FocusHandle,
    pub cursor: Option<usize>,
    pub anchor: Option<usize>,
    pub layout: Option<gpui::ShapedLine>,
    pub bounds: Option<gpui::Bounds<gpui::Pixels>>,
    pub scroll_x: gpui::Pixels,
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
            bounds: None,
            scroll_x: px(0.0),
            selecting: false,
        }
    }

    pub fn set_value(&mut self, value: String) {
        self.value = value;
        self.cursor = None;
        self.anchor = None;
        self.layout = None;
        self.scroll_x = px(0.0);
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
        self.anchor = if extend_selection { Some(self.anchor.unwrap_or(self.position())) } else { None };
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

// ---- the app ----

pub struct Kriko {
    pub tab: Tab,
    /// Where the engine is: starting, answering, or failed with its words.
    pub engine: engine::Status,
    /// What the engine said, per area, for the screens to draw.
    pub live: Live,
    // settings
    pub reduce_motion: bool,
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
    /// The full live agent logs drawer in the dock.
    pub dock_logs_open: bool,
    pub dock_feed: Vec<DockFeedEntry>,
    pub dock_open: bool,
    // compare: the engine's own rows live in `live.compare`
    pub compare_note_input: InputState,
    pub compare_question_input: InputState,
    // local llm: the address, the search service and the model to get; the
    // rest of this area is `live::local`
    pub local_url: InputState,
    pub local_search: InputState,
    pub local_get: InputState,
    pub extension_port_input: InputState,
    pub model_search: InputState,
    pub bench_model_search: InputState,
    pub library_search: InputState,
    pub sidebar_collapsed: bool,
}


impl Kriko {
    pub fn new(cx: &mut Context<Self>) -> Self {
        let mut extension_port_input = InputState::new(cx);
        extension_port_input.set_value(engine::configured_extension_port().to_string());
        let mut app = Self {
            tab: Tab::Home,
            engine: engine::status(),
            live: Live::default(),
            reduce_motion: false,
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
            dock_logs_open: false,
            dock_feed: Vec::new(),
            dock_open: true,
            compare_note_input: InputState::new(cx),
            compare_question_input: InputState::new(cx),
            local_url: InputState::new(cx),
            local_search: InputState::new(cx),
            local_get: InputState::new(cx),
            extension_port_input,
            model_search: InputState::new(cx),
            bench_model_search: InputState::new(cx),
            library_search: InputState::new(cx),
            sidebar_collapsed: false,
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
            Ok("dock") => {
                app.dock_reply_open = true;
            }
            _ => {}
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
            Field::BoardNote => &self.compare_note_input,
            Field::RunSearch => &self.run_search,
            Field::LocalUrl => &self.local_url,
            Field::LocalSearch => &self.local_search,
            Field::LocalGet => &self.local_get,
            Field::ExtensionPort => &self.extension_port_input,
            Field::ModelSearch => &self.model_search,
            Field::BenchModelSearch => &self.bench_model_search,
            Field::LibrarySearch => &self.library_search,
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
            Field::BoardNote => &mut self.compare_note_input,
            Field::RunSearch => &mut self.run_search,
            Field::LocalUrl => &mut self.local_url,
            Field::LocalSearch => &mut self.local_search,
            Field::LocalGet => &mut self.local_get,
            Field::ExtensionPort => &mut self.extension_port_input,
            Field::ModelSearch => &mut self.model_search,
            Field::BenchModelSearch => &mut self.bench_model_search,
            Field::LibrarySearch => &mut self.library_search,
        }
    }

    pub(crate) fn handle_key(this: &mut Kriko, field: Field, event: &KeyDownEvent, cx: &mut Context<Kriko>) {
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
                    cx.write_to_clipboard(gpui::ClipboardItem::new_string(this.input(field).value[selected].to_string()));
                    if ks.key == "x" { this.input_mut(field).replace_selection(""); }
                }
                "v" => {
                    if let Some(text) = cx.read_from_clipboard().and_then(|c| c.text()) {
                        this.input_mut(field).replace_selection(&text.replace(['\r', '\n'], " "));
                    }
                }
                _ => return,
            }
            this.input_changed(field, cx);
            return;
        }
        if ks.modifiers.alt { return; }
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
        let input = this.input_mut(field);
        let at = input.position();
        let previous = input.value[..at].char_indices().last().map(|(i, _)| i).unwrap_or(0);
        let next = input.value[at..].chars().next().map(|c| at + c.len_utf8()).unwrap_or(at);
        match ks.key.as_str() {
            "left" => {
                let to = if !ks.modifiers.shift && !input.selection().is_empty() { input.selection().start } else { previous };
                input.move_cursor(to, ks.modifiers.shift);
            }
            "right" => {
                let to = if !ks.modifiers.shift && !input.selection().is_empty() { input.selection().end } else { next };
                input.move_cursor(to, ks.modifiers.shift);
            }
            "home" => input.move_cursor(0, ks.modifiers.shift),
            "end" => input.move_cursor(input.value.len(), ks.modifiers.shift),
            "backspace" => {
                if input.selection().is_empty() { input.anchor = Some(previous); }
                input.replace_selection("");
            }
            "delete" => {
                if input.selection().is_empty() { input.anchor = Some(next); }
                input.replace_selection("");
            }
            "escape" => {}
            "space" => input.replace_selection(" "),
            _ => {
                let text = ks.key_char.as_deref().unwrap_or(ks.key.as_str());
                if text.chars().count() == 1 && input.value.chars().count() < 200 {
                    input.replace_selection(text);
                }
            }
        }
        this.input_changed(field, cx);
    }

    pub(crate) fn input_changed(&mut self, field: Field, cx: &mut Context<Self>) {
        if field == Field::HistorySearch { self.page = 0; }
        if field == Field::BrowseSearch { self.browse_search_typed(cx); }
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
            .overflow_y_scroll().occlude();
        for (gi, group) in data::NAV.iter().enumerate() {
            nav = nav.child(
                div()
                    .mt(px(if gi == 0 { 8.0 } else { 18.0 }))
                    .mb(px(4.0))
                    .px(px(12.0))
                    .flex_none()
                    .when(!self.sidebar_collapsed, |d| d.child(eyebrow(group.label))),
            );
            for item in group.items {
                let key = item.key;
                let current = self.tab.key() == key;
                let row = nav_item(key, item.icon, if self.sidebar_collapsed { "" } else { item.label }, current, if self.sidebar_collapsed { None } else { item.count }, if self.sidebar_collapsed { None } else { item.badge })
                    .flex_none()
                    .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                        this.tab = Tab::from_key(key);
                        this.on_open_tab(cx);
                        cx.notify();
                    }));
                nav = nav.child(row);
            }
        }
        div()
            .w(px(if self.sidebar_collapsed { 76.0 } else { SIDEBAR_W }))
            .overflow_hidden()
            .flex_none()
            .bg(rgb(SURFACE_1))
            .border_r_1()
            .border_color(rgba(HAIRLINE))
            .flex()
            .flex_col()
            .when(!self.sidebar_collapsed, |d| d.child(brand_block("kriko-wordmark-white.svg", "local product knowledge")))
            .child(div().p(px(8.0)).flex().justify_center().child(ghost("sidebar-minimise", if self.sidebar_collapsed { ">" } else { "Minimise sidebar" }).when(self.sidebar_collapsed, |d| d.w(px(52.0)).px(px(0.0)))
                .on_click(cx.listener(|this, _: &ClickEvent, _w, cx| { this.sidebar_collapsed = !this.sidebar_collapsed; cx.notify(); }))))
            .child(nav)
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
                    .when(needs_you > 0, |d| {
                        d.child(tag(
                            "titlebar-needs-you",
                            TagState::Need,
                            &format!("? {needs_you}"),
                            !self.reduce_motion,
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
        if !matches!(self.engine, engine::Status::Ready { .. }) {
            let maximized = window.is_maximized();
            return self.boot_screen(maximized, cx).into_any_element();
        }
        let tab = self.tab;
        let maximized = window.is_maximized();
        let titlebar = self.titlebar(maximized, cx);
        let sidebar = self.sidebar(cx);
        let collapsed = self.sidebar_collapsed;
        let sidebar = if !self.reduce_motion {
            sidebar.with_animation(gpui::ElementId::named_usize("sidebar-slide", collapsed as usize),
                gpui::Animation::new(std::time::Duration::from_millis(260)), move |d,t| {
                    let t = t * t * (3.0 - 2.0 * t);
                    d.w(px(if collapsed { SIDEBAR_W + (76.0 - SIDEBAR_W) * t } else { 76.0 + (SIDEBAR_W - 76.0) * t }))
                }).into_any_element()
        } else { sidebar.into_any_element() };
        let content = screens::screen(self, window, cx);
        let dock = dock::dock(self, window, cx);
        let open = self.dock_open;
        let dock_wrap = div().flex_none().h_full().overflow_hidden().w(px(if open { 300.0 } else { 0.0 })).child(dock);
        let dock_wrap = if !self.reduce_motion {
            dock_wrap.with_animation(gpui::ElementId::named_usize("live-slide", open as usize),
                gpui::Animation::new(std::time::Duration::from_millis(260)), move |d,t| {
                    let t = t * t * (3.0 - 2.0 * t); d.w(px(300.0 * if open { t } else { 1.0 - t }))
                }).into_any_element()
        } else { dock_wrap.into_any_element() };
        let hero = hero(tab.hero_sky(), tab.hero_height(), !self.reduce_motion)
            .child(page_head(tab.hero_sky(), tab.crumb(), tab.title(), tab.lead(), !self.reduce_motion));
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
                                    .child(arrive(content, format!("page-{}", tab.key()), !self.reduce_motion)),
                            ),
                    )
                    // The bar floats on the sky, after the page so it
                    // paints on top of the hero it blends into.
                    .child(titlebar),
            )
            .child(dock_wrap)
            .into_any_element()
    }
}

fn text_boundary(value: &str, requested: usize) -> usize {
    let mut at = requested.min(value.len());
    while !value.is_char_boundary(at) { at -= 1; }
    at
}

fn text_selection(value: &str, cursor: usize, anchor: Option<usize>) -> std::ops::Range<usize> {
    let at = text_boundary(value, cursor);
    let anchor = text_boundary(value, anchor.unwrap_or(at));
    at.min(anchor)..at.max(anchor)
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
