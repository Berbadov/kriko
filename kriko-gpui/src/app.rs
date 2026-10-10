//! The Kriko app shell: the sidebar, the hero with the page head, and the
//! dispatch to the tab screens. All state that the screens share (settings
//! flags, filters, selections) lives on [`Kriko`], so every screen is a
//! method over one state struct.

use gpui::{
    div, prelude::*, px, rgb, rgba, App, ClickEvent, Context, Div, FocusHandle, IntoElement,
    KeyDownEvent, ParentElement, Render, Stateful, Styled, Window, WindowControlArea,
    Animation, AnimationExt,
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
            Tab::Browse => "knowledge / subjects",
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
            Tab::Run => "Quick Look",
            Tab::Browse => "Subjects",
            _ => self.key(),
        }
    }

    fn lead(self) -> &'static str {
        match self {
            Tab::Home => "Recent work, saved drafts, and where the knowledge stands.",
            Tab::Run => "A fast, sourced product check, researched by the model on this computer.",
            Tab::History => "Every check you have run, with the evidence it was based on.",
            Tab::Compare => "Up to three subjects side by side, attribute by attribute.",
            Tab::Extension => "Send pages from your browser straight into Kriko's knowledge.",
            Tab::Overview => "What the packs know, and where they run thin.",
            Tab::Browse => "Every subject, attribute and claim in the local store.",
            Tab::Sites => "The sites Kriko reads, and how far each one is trusted.",
            Tab::Activity => "What Kriko did today, and what is waiting for you.",
            Tab::Agents => "The coding agents on this machine that can reach Kriko.",
            Tab::Benchmark => "How the agents and planes do on a fixed test set, here.",
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
    KeyValue,
    BrowseSearch,
    DockReply,
    CompareAsk,
    BoardNote,
    RunSearch,
    QuickLookProduct,
    QuickLookQuestion,
    LocalUrl,
    LocalSearch,
    LocalGet,
}

pub struct InputState {
    pub value: String,
    pub handle: FocusHandle,
    /// Character offset from the start; `None` tracks the end after a
    /// programmatic value update.
    pub cursor: Option<usize>,
    /// Character offsets, sorted only when read for drawing/editing.
    pub selection: Option<(usize, usize)>,
}

impl InputState {
    fn new(cx: &mut App) -> Self {
        Self {
            value: String::new(),
            handle: cx.focus_handle(),
            cursor: None,
            selection: None,
        }
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
    // inputs
    pub history_search: InputState,
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
    // run: the subject search that starts a check
    pub run_search: InputState,
    /// Product name for a local-first Quick Look.
    pub quicklook_product: InputState,
    pub quicklook_question: InputState,
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
}


impl Kriko {
    pub fn new(cx: &mut Context<Self>) -> Self {
        let mut app = Self {
            tab: Tab::Home,
            engine: engine::status(),
            live: Live::default(),
            reduce_motion: false,
            history_search: InputState::new(cx),
            activity_filter: InputState::new(cx),
            sites_add: InputState::new(cx),
            key_value: InputState::new(cx),
            browse_search: InputState::new(cx),
            page: 0,
            history_span: SpanFilter::All,
            browse_view: 0,
            browse_view_prev: 0,
            browse_page: 0,
            run_search: InputState::new(cx),
            quicklook_product: InputState::new(cx),
            quicklook_question: InputState::new(cx),
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
        app
    }

    fn pulse(&mut self, cx: &mut Context<Self>) {
        for action in shell::poll_tray() {
            match action {
                shell::TrayAction::Open => shell::show_window(cx),
                shell::TrayAction::Quit => Self::quit(cx),
            }
        }
        for event in engine::take_events() {
            match event {
                engine::ShellEvent::Focus(_route) => shell::show_window(cx),
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
        self.tick_history(cx);
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
            Field::KeyValue => &self.key_value,
            Field::BrowseSearch => &self.browse_search,
            Field::DockReply => &self.dock_reply,
            Field::CompareAsk => &self.compare_question_input,
            Field::BoardNote => &self.compare_note_input,
            Field::RunSearch => &self.run_search,
            Field::QuickLookProduct => &self.quicklook_product,
            Field::QuickLookQuestion => &self.quicklook_question,
            Field::LocalUrl => &self.local_url,
            Field::LocalSearch => &self.local_search,
            Field::LocalGet => &self.local_get,
        }
    }

    fn input_mut(&mut self, field: Field) -> &mut InputState {
        match field {
            Field::HistorySearch => &mut self.history_search,
            Field::ActivityFilter => &mut self.activity_filter,
            Field::SitesAdd => &mut self.sites_add,
            Field::KeyValue => &mut self.key_value,
            Field::BrowseSearch => &mut self.browse_search,
            Field::DockReply => &mut self.dock_reply,
            Field::CompareAsk => &mut self.compare_question_input,
            Field::BoardNote => &mut self.compare_note_input,
            Field::RunSearch => &mut self.run_search,
            Field::QuickLookProduct => &mut self.quicklook_product,
            Field::QuickLookQuestion => &mut self.quicklook_question,
            Field::LocalUrl => &mut self.local_url,
            Field::LocalSearch => &mut self.local_search,
            Field::LocalGet => &mut self.local_get,
        }
    }

    fn selection_bounds(state: &InputState) -> Option<(usize, usize)> {
        let count = state.value.chars().count();
        state.selection.map(|(a, b)| (a.min(b).min(count), a.max(b).min(count)))
            .filter(|(a, b)| a != b)
    }

    fn insert_text(state: &mut InputState, text: &str, limit: usize) {
        let chars: Vec<char> = state.value.chars().collect();
        let (start, end) = Self::selection_bounds(state)
            .unwrap_or_else(|| { let at = state.cursor.unwrap_or(chars.len()).min(chars.len()); (at, at) });
        let room = limit.saturating_sub(chars.len().saturating_sub(end - start));
        let inserted: Vec<char> = text.chars().take(room).collect();
        let mut next = Vec::with_capacity(chars.len() - (end - start) + inserted.len());
        next.extend_from_slice(&chars[..start]);
        next.extend(inserted.iter().copied());
        next.extend_from_slice(&chars[end..]);
        state.value = next.into_iter().collect();
        state.cursor = Some(start + inserted.len());
        state.selection = None;
    }

    fn delete_selection(state: &mut InputState) -> bool {
        let Some((start, end)) = Self::selection_bounds(state) else { return false };
        let chars: Vec<char> = state.value.chars().collect();
        state.value = chars[..start].iter().chain(chars[end..].iter()).collect();
        state.cursor = Some(start);
        state.selection = None;
        true
    }

    fn handle_key(this: &mut Kriko, field: Field, event: &KeyDownEvent, cx: &mut Context<Kriko>) {
        let ks = &event.keystroke;
        let command = ks.modifiers.control || ks.modifiers.platform;
        // Every app field accepts clipboard editing; the custom GPUI field
        // keeps its own cursor and selection so these shortcuts work alike.
        if command && ks.key.as_str() == "v" {
            if let Some(text) = cx.read_from_clipboard().and_then(|c| c.text()) {
                let line = text.lines().next().unwrap_or("").trim().to_string();
                let state = this.input_mut(field);
                let limit = if matches!(field, Field::QuickLookProduct | Field::QuickLookQuestion) { 300 } else { 200 };
                Self::insert_text(state, &line, limit);
                cx.notify();
            }
            return;
        }
        if command && ks.key.as_str() == "a" {
            let state = this.input_mut(field);
            let count = state.value.chars().count();
            state.selection = (count > 0).then_some((0, count));
            state.cursor = Some(count);
            cx.notify();
            return;
        }
        if command && matches!(ks.key.as_str(), "c" | "x") {
            let state = this.input_mut(field);
            if let Some((start, end)) = Self::selection_bounds(state) {
                let chars: Vec<char> = state.value.chars().collect();
                let selected: String = chars[start..end].iter().collect();
                cx.write_to_clipboard(gpui::ClipboardItem::new_string(selected));
                if ks.key.as_str() == "x" {
                    Self::delete_selection(state);
                    cx.notify();
                }
            }
            return;
        }
        if ks.modifiers.control || ks.modifiers.alt || ks.modifiers.platform {
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
        if ks.key.as_str() == "enter" && matches!(field, Field::QuickLookProduct | Field::QuickLookQuestion) {
            if field == Field::QuickLookQuestion {
                this.start_quick_ask(cx);
            } else {
                this.start_quick_look(cx);
            }
            cx.notify();
            return;
        }
        // Enter in the Sites add field adds the site straight away.
        if ks.key.as_str() == "enter" && field == Field::SitesAdd {
            let host = this.input(field).value.trim().to_string();
            if !host.is_empty() {
                this.input_mut(field).value.clear();
                this.register_site(&host, cx);
            }
            cx.notify();
            return;
        }
        // Enter in the key field saves the key for the provider picked.
        if ks.key.as_str() == "enter" && field == Field::KeyValue {
            let value = this.input(field).value.trim().to_string();
            if let Some(provider) = this.live.knowledge.key_provider.clone() {
                this.input_mut(field).value.clear();
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
        // Enter on the compare question asks it, the same as the Ask key.
        if ks.key.as_str() == "enter" && field == Field::CompareAsk {
            this.ask_compare_question(cx);
            cx.notify();
            return;
        }
        let state = this.input_mut(field);
        if matches!(ks.key.as_str(), "left" | "right" | "home" | "end") {
            let count = state.value.chars().count();
            let position = state.cursor.unwrap_or(count).min(count);
            let collapse = Self::selection_bounds(state).map(|(a, b)| {
                if ks.key.as_str() == "left" || ks.key.as_str() == "home" { a } else { b }
            });
            let next = match ks.key.as_str() {
                "left" => collapse.unwrap_or_else(|| position.saturating_sub(1)),
                "right" => collapse.unwrap_or_else(|| (position + 1).min(count)),
                "home" => 0,
                "end" => count,
                _ => position,
            };
            if ks.modifiers.shift {
                let anchor = state.selection.map(|(a, b)| if position == a { b } else { a }).unwrap_or(position);
                state.selection = (anchor != next).then_some((anchor.min(next), anchor.max(next)));
            } else {
                state.selection = None;
            }
            state.cursor = Some(next);
            cx.notify();
            return;
        }
        match ks.key.as_str() {
            "backspace" => {
                if !Self::delete_selection(state) {
                    let count = state.value.chars().count();
                    let at = state.cursor.unwrap_or(count).min(count);
                    if at > 0 {
                        state.cursor = Some(at - 1);
                        state.selection = Some((at - 1, at));
                        Self::delete_selection(state);
                    }
                }
            }
            "delete" => {
                if !Self::delete_selection(state) {
                    let count = state.value.chars().count();
                    let at = state.cursor.unwrap_or(count).min(count);
                    if at < count {
                        state.selection = Some((at, at + 1));
                        Self::delete_selection(state);
                    }
                }
            }
            "space" => Self::insert_text(state, " ", if matches!(field, Field::QuickLookProduct | Field::QuickLookQuestion) { 300 } else { 200 }),
            "escape" => {}
            key if key.chars().count() == 1 => {
                let limit = if matches!(field, Field::QuickLookProduct | Field::QuickLookQuestion) { 300 } else { 200 };
                Self::insert_text(state, key, limit);
            }
            _ => {}
        }
        if field == Field::HistorySearch {
            this.page = 0;
        }
        if field == Field::BrowseSearch {
            this.browse_search_typed(cx);
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
        let shown_value = if field == Field::KeyValue {
            "•".repeat(value.chars().count())
        } else {
            value.clone()
        };
        let chars: Vec<char> = shown_value.chars().collect();
        let position = state.cursor.unwrap_or(chars.len()).min(chars.len());
        let selection = Self::selection_bounds(state);
        let listener = cx.listener(move |this, event: &KeyDownEvent, _w, cx| {
            Self::handle_key(this, field, event, cx);
        });
        let caret = || -> gpui::AnyElement {
            let base = div().w(px(2.0)).h(px(20.0)).bg(rgb(INK));
            if self.reduce_motion {
                base.into_any_element()
            } else {
                base.with_animation(
                    "blink",
                    Animation::new(std::time::Duration::from_millis(1100)).repeat(),
                    |el, t| el.opacity(if t < 0.5 { 1.0 } else { 0.0 }),
                ).into_any_element()
            }
        };
        let mut text = div()
            .flex_1()
            .min_w(px(0.0))
            .flex()
            .items_center()
            .font_family(SANS)
            .text_size(px(16.0));
        if empty {
            if focused { text = text.child(caret()); }
            text = text.child(div().text_color(rgb(DIM)).child(placeholder.to_string()));
        } else if let Some((start, end)) = selection {
            text = text.child(chars[..start].iter().collect::<String>());
            if focused && position == start { text = text.child(caret()); }
            text = text.child(
                div()
                    .rounded(px(2.0))
                    .bg(rgb(ICE))
                    .text_color(rgb(GROUND))
                    .child(chars[start..end].iter().collect::<String>()),
            );
            if focused && position != start { text = text.child(caret()); }
            text = text.child(chars[end..].iter().collect::<String>());
        } else {
            text = text.child(chars[..position].iter().collect::<String>());
            if focused { text = text.child(caret()); }
            text = text.child(chars[position..].iter().collect::<String>());
        }
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
            .child(text)
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
                        this.on_open_tab(cx);
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
        let needs_you = self.live.run.needs_you().len();

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
                            )
                            .when(needs_you > 0, |d| {
                                d.child(tag(
                                    "titlebar-needs-you",
                                    TagState::Need,
                                    &format!("? {needs_you}"),
                                    !self.reduce_motion,
                                ))
                            }),
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
        let api_error_banner: Option<gpui::AnyElement> = self.live.problem.as_ref().map(|problem| {
            let message = problem.clone();
            let retry = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_all(cx));
            div()
                .mx(px(40.0))
                .mt(px(16.0))
                .p(px(12.0))
                .flex()
                .items_center()
                .gap(px(12.0))
                .rounded(px(10.0))
                .bg(rgb(DANGER_WASH))
                .border_1()
                .border_color(rgb(DANGER))
                .child(div().flex_1().min_w(px(0.0)).text_color(rgb(INK)).child(message))
                .child(screens::plate_s("api-error-retry", "Retry").on_click(retry))
                .into_any_element()
        });
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
                            .children(api_error_banner)
                            .child(
                                div()
                                    .flex()
                                    .flex_col()
                                    .flex_none()
                                    .px(px(40.0))
                                    .pt(px(20.0))
                                    .pb(px(48.0))
                                    .child(content),
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
