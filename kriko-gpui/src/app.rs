//! The Kriko app shell: the sidebar, the hero with the page head, and the
//! dispatch to the tab screens. All state that the screens share (settings
//! flags, filters, selections) lives on [`Kriko`], so every screen is a
//! method over one state struct.

use gpui::{
    div, prelude::*, px, rgb, rgba, svg, App, ClickEvent, Context, Div, FocusHandle, IntoElement,
    KeyDownEvent, ParentElement, Render, SharedString, Stateful, Styled, Window, Animation,
    AnimationExt,
};

use crate::data;
use crate::dock;
use crate::screens;
use crate::theme::*;

use gpui::MouseButton;

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
            Tab::Home => "One place to start a check, see what is waiting and read the last result.",
            Tab::Run => "One check, from question to verdict, with every claim grounded.",
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

    fn hero_image(self) -> &'static str {
        match self {
            Tab::Home | Tab::About => "sky-hero.png",
            Tab::Local => "sky-wide.png",
            _ => "sky-dim.png",
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
pub enum VerdictFilter {
    Any,
    Recommended,
    WeighUp,
    Avoid,
}

impl VerdictFilter {
    pub fn word(self) -> &'static str {
        match self {
            VerdictFilter::Any => "ANY",
            VerdictFilter::Recommended => "RECOMMENDED",
            VerdictFilter::WeighUp => "WEIGH UP",
            VerdictFilter::Avoid => "AVOID",
        }
    }

    pub fn next(self) -> Self {
        match self {
            VerdictFilter::Any => VerdictFilter::Recommended,
            VerdictFilter::Recommended => VerdictFilter::WeighUp,
            VerdictFilter::WeighUp => VerdictFilter::Avoid,
            VerdictFilter::Avoid => VerdictFilter::Any,
        }
    }
}

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
/// the agent has finished.
pub struct CompareQuestion {
    pub text: String,
    pub answer: Option<String>,
}

// ---- the app ----

pub struct Kriko {
    pub tab: Tab,
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
    pub verdict_filter: VerdictFilter,
    pub pack_filter: PackFilter,
    pub page: usize,
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
    pub model_loaded: Vec<bool>,
    // extension
    pub extension_linked: bool,
    pub extension_hover: bool,
    // run
    pub run_phase: usize,
    pub running: bool,
    // the live actions dock
    pub dock_reply: InputState,
    pub dock_resolved: Vec<usize>,
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
    // agents: per-agent tool permissions [read, run, answer]
    pub agent_tools: Vec<[bool; 3]>,
}

impl Kriko {
    pub fn new(cx: &mut App) -> Self {
        let mut app = Self {
            tab: Tab::Home,
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
            verdict_filter: VerdictFilter::Any,
            pack_filter: PackFilter::All,
            page: 0,
            added_sites: Vec::new(),
            browse_selected: 0,
            browse_view: 0,
            browse_view_prev: 0,
            agent_selected: 0,
            agent_allowed: data::AGENTS.iter().map(|a| a.allowed).collect(),
            pack_enabled: data::PACKS.iter().map(|p| p.enabled).collect(),
            model_loaded: data::MODELS.iter().map(|m| m.loaded).collect(),
            extension_linked: false,
            extension_hover: false,
            run_phase: 0,
            running: false,
            dock_reply: InputState::new(cx),
            dock_resolved: Vec::new(),
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
            compare_questions: vec![
                CompareQuestion {
                    text: "Which of these has the fewest serious risks?".to_string(),
                    answer: Some(
                        "The Buds2 Pro: one serious risk recorded (the case hinge), \
                         while the Buds Pro carries a measured battery-swelling risk."
                            .to_string(),
                    ),
                },
                CompareQuestion {
                    text: "Is the XM5 worth the higher price?".to_string(),
                    answer: Some(
                        "If noise cancelling is why you buy: yes, 42 dB measured is the \
                         strongest of the three. If not: the Buds2 Pro holds up at mid price."
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
            _ => {}
        }
        app
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

    /// Push the question, then let the agent answer it a moment later.
    /// While the answer is missing the question shows its LIVE tag.
    pub fn ask_compare_question(&mut self, cx: &mut Context<Self>) {
        let text = self.compare_question_input.value.trim().to_string();
        if text.is_empty() {
            return;
        }
        self.compare_question_input.value.clear();
        self.compare_questions.insert(
            0,
            CompareQuestion {
                text,
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
                    q.answer = Some(
                        "On the evidence in this table: the Buds2 Pro carries the fewest \
                         serious risks, the XM5 the strongest noise cancelling, and the \
                         Buds Pro is only worth it if the price drops."
                            .to_string(),
                    );
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
            .w(px(248.0))
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
    /// The merged window top bar: the mark and the crumb drag the window;
    /// the dock toggle and minimize / restore / close sit on the right.
    fn titlebar(&self, maximized: bool, cx: &mut Context<Self>) -> Stateful<Div> {
        let minimize = cx.listener(|_, _: &ClickEvent, window, _| window.minimize_window());
        let zoom = cx.listener(|_, _: &ClickEvent, window, _| window.zoom_window());
        let close = cx.listener(|_, _: &ClickEvent, window, _| window.remove_window());
        let toggle_dock = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.dock_open = !this.dock_open;
            cx.notify();
        });

        let zoom_icon = if maximized { "restore" } else { "maximize" };
        let tab = self.tab;

        titlebar()
            .child(
                // the drag region: mark + app name + crumb
                div()
                    .id("titlebar-drag")
                    .flex()
                    .flex_1()
                    .min_w(px(0.0))
                    .items_center()
                    .gap(px(10.0))
                    .cursor_move()
                    .on_mouse_down(MouseButton::Left, |_, window, _| {
                        window.start_window_move()
                    })
                    .child(
                        svg()
                            .path(SharedString::from("kriko-mark-white.svg"))
                            .size(px(16.0))
                            .text_color(rgb(BRAND_BRIGHT)),
                    )
                    .child(
                        div()
                            .font_family(MONO)
                            .text_size(px(12.0))
                            .text_color(rgb(MUTED))
                            .child("kriko"),
                    )
                    .child(
                        div()
                            .font_family(MONO)
                            .text_size(px(12.0))
                            .text_color(rgb(DIM))
                            .child(format!("/ {}", tab.key())),
                    ),
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
                            .bg(rgba(GLASS_1))
                            .border_1()
                            .border_color(rgba(HAIRLINE))
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
                    .child(titlebar_button("win-min", "minus", false).on_click(minimize))
                    .child(titlebar_button("win-max", zoom_icon, false).on_click(zoom))
                    .child(titlebar_button("win-close", "x", true).on_click(close)),
            )
    }
}

impl Render for Kriko {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let tab = self.tab;
        let maximized = window.is_maximized();
        let titlebar = self.titlebar(maximized, cx);
        let sidebar = self.sidebar(cx);
        let content = screens::screen(self, window, cx);
        let dock = dock::dock(self, window, cx);
        let hero = hero(tab.hero_image(), tab.hero_height())
            .child(page_head(tab.crumb(), tab.title(), tab.lead()));
        let hero = match tab {
            Tab::Home => hero.child(screens::home::frost_start(cx)),
            Tab::Local => hero.child(screens::local::frost_test(cx)),
            _ => hero,
        };
        div()
            .id("kriko-root")
            .size_full()
            .flex()
            .flex_col()
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
            .child(titlebar)
            .child(
                div()
                    .flex()
                    .flex_1()
                    .min_h(px(0.0))
                    .child(sidebar)
                    .child(
                        div()
                            .flex()
                            .flex_1()
                            .flex_col()
                            .min_w(px(0.0))
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
                            ),
                    )
                    .when(self.dock_open, |row| row.child(dock)),
            )
    }
}
