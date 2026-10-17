//! Chat: the app's main screen. The reader's own agent, grounded in what this
//! install knows, with its mark alive while it works and every cited page one
//! press away.

use gpui::{div, prelude::*, px, ClickEvent, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data::CHAT_EXAMPLES;
use crate::live::chat::{self as live, Message, Partial, Role, Step, StepState};
use crate::marks::{self, mark_tile, phase_beat, Mark, Phase};
use crate::screens::{mono, row_desc};
use crate::sources::{source_row, Source};
use crate::textfx::{cylinder_status, words_reveal};
use crate::theme::*;

/// Reserve enough width for the conversation rail and a readable transcript.
const NARROW_W: f32 = 620.0;
const THREAD_RAIL_W: f32 = 168.0;
/// A turn header's mark.
const TURN_MARK: f32 = 30.0;
/// The empty state's mark.
const EMPTY_MARK: f32 = 44.0;

pub fn chat(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let viewport_h = f32::from(window.viewport_size().height);
    // The surrounding shell uses 96 px for its page head and about 42 px for
    // content spacing. This keeps the composer on screen in a 640 px window.
    let height = (viewport_h - 200.0).clamp(300.0, 700.0);
    let narrow = app.content_w < NARROW_W;
    let threads = thread_list(app, narrow, cx);
    let conversation = conversation(app, window, cx);

    if narrow {
        div()
            .h(px(height))
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(threads.h(px(68.0)).flex_none())
            .child(
                conversation
                    .h(px((height - 76.0).max(224.0)))
                    .min_h(px(0.0)),
            )
    } else {
        div()
            .h(px(height))
            .flex()
            .gap(px(12.0))
            .child(threads.w(px(THREAD_RAIL_W)).h_full().flex_none())
            .child(conversation.flex_1().h_full().min_w(px(0.0)).min_h(px(0.0)))
    }
}

// ---- the rail ----

fn thread_list(app: &Kriko, compact: bool, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let new_one = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.new_chat_thread(cx);
        cx.notify();
    });
    let mut list = div()
        .flex()
        .flex_col()
        .gap(px(4.0))
        .when(compact, |d| d.flex_row());

    if chat.threads.is_empty() {
        list = list.child(row_desc(if chat.loaded { "No chats" } else { "Loading…" }));
    }
    for (i, thread) in chat.threads.iter().enumerate() {
        let picked = chat.thread.as_deref() == Some(thread.thread_id.as_str());
        let id = thread.thread_id.clone();
        let open = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.open_chat_thread(id.clone(), cx);
            cx.notify();
        });
        let running = chat.running.contains_key(&thread.thread_id);
        let name = thread.name();
        list = list.child(
            div()
                .id(("chat-thread", i))
                .h(px(36.0))
                .px(px(SPACE_M))
                .flex_none()
                .flex()
                .items_center()
                .gap(px(SPACE_S))
                .rounded(px(8.0))
                .cursor_pointer()
                .font_family(SANS)
                .text_size(px(13.0))
                .text_color(paint(if picked { INK } else { INK_2 }))
                .when(compact, |d| d.w(px(190.0)))
                .when(!compact, |d| d.w_full())
                .when(picked, |d| {
                    d.bg(paint_a(GLASS_1)).border_1().border_color(paint_a(HAIRLINE))
                })
                .when(!picked, |d| d.hover(|h| h.bg(paint_a(GLASS_1))))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .overflow_hidden()
                        .whitespace_nowrap()
                        .text_ellipsis()
                        .child(name),
                )
                .when(running, |d| {
                    d.child(
                        div()
                            .flex_none()
                            .size(px(6.0))
                            .rounded_full()
                            .bg(paint(ICE)),
                    )
                })
                .on_click(open),
        );
    }

    let heading = div()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(4.0))
        .child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::MEDIUM)
                .text_size(px(12.0))
                .text_color(paint(MUTED))
                .child("Chats"),
        )
        .child(text_action("chat-new", "New").on_click(new_one));

    if compact {
        div().flex().flex_col().gap(px(4.0)).child(heading).child(
            div()
                .id("chat-thread-list")
                .h(px(36.0))
                .overflow_x_scroll()
                .overflow_y_hidden()
                .child(list),
        )
    } else {
        div()
            .flex()
            .flex_col()
            .gap(px(8.0))
            .h_full()
            .min_h(px(0.0))
            .child(heading)
            .child(
                div()
                    .id("chat-thread-list")
                    .flex_1()
                    .min_h(px(0.0))
                    .overflow_y_scroll()
                    .child(list),
            )
    }
}

// ---- the conversation ----

fn conversation(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let title = chat
        .thread
        .as_ref()
        .and_then(|id| chat.threads.iter().find(|t| t.thread_id == *id))
        .map(|t| t.name())
        .unwrap_or_else(|| "New chat".to_string());
    let running_here = chat
        .in_flight
        .as_ref()
        .is_some_and(|f| chat.thread.as_deref() == Some(f.thread_id.as_str()));

    let mut header = div()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(8.0))
        .pb(px(8.0))
        .border_b_1()
        .border_color(paint_a(HAIRLINE))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .min_w(px(0.0))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .font_family(DISPLAY)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(17.0))
                        .text_color(paint(INK))
                        .overflow_hidden()
                        .whitespace_nowrap()
                        .text_ellipsis()
                        .child(title),
                )
                .when(chat.failed.is_some(), |d| d.child(status_label("Failed"))),
        );

    let can_delete = chat.thread.is_some() && !chat.sending && !running_here;
    if can_delete {
        let delete = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.delete_chat_thread(cx);
            cx.notify();
        });
        header = header.child(text_action("chat-delete", "Delete").on_click(delete));
    }

    let say = chat.say.clone();
    let messages = messages_view(app, cx);
    let composer = composer(app, window, cx);
    let mut column = div()
        .flex()
        .flex_col()
        .gap(px(SPACE_M))
        .h_full()
        .min_h(px(0.0))
        .child(header)
        .child(messages.flex_1().min_h(px(0.0)));
    if let Some(text) = say {
        column = column.child(danger_line(&text));
    }
    column.child(composer.flex_none())
}

fn messages_view(app: &mut Kriko, cx: &mut Context<Kriko>) -> gpui::Stateful<Div> {
    let motion = app.motion;
    // A growing answer (or a new turn) keeps the transcript pinned to its end,
    // unless the reader has scrolled up to read.
    let chars = app
        .live
        .chat
        .messages
        .iter()
        .map(|m| m.text.len())
        .sum::<usize>()
        + app.live.chat.partial.as_ref().map_or(0, |p| p.answer.len());
    {
        let chat = &mut app.live.chat;
        if chars != chat.rendered_chars {
            if chat.rendered_chars == 0
                || (chat.scroll.offset().y + chat.scroll.max_offset().height).abs() < px(60.0)
            {
                chat.scroll.scroll_to_bottom();
            }
            chat.rendered_chars = chars;
        }
    }

    let chat = &app.live.chat;
    let agent = selected_agent(chat);
    let mark = mark_for(&chat.harness);
    let mut transcript = div().flex().flex_col().gap(px(16.0));

    let idle = chat.messages.is_empty() && chat.in_flight.is_none();
    if idle {
        transcript = transcript.child(empty_state(chat, mark, motion, cx));
    }
    for message in chat.messages.iter() {
        transcript = transcript.child(match message.role {
            Role::Reader => reader_line(message),
            Role::Agent => agent_block(
                message,
                &agent,
                mark,
                motion,
                chat.details.contains(&message.message_id),
                cx,
            ),
        });
    }
    let running_here = chat
        .in_flight
        .as_ref()
        .is_some_and(|f| chat.thread.as_deref() == Some(f.thread_id.as_str()));
    if running_here {
        let partial = chat.partial.clone().unwrap_or_default();
        transcript = transcript.child(pending_block(
            &partial,
            &chat.job_message,
            &agent,
            mark,
            motion,
        ));
    }
    if let Some(why) = chat.failed.as_ref() {
        let retry = cx.listener(|this, _: &ClickEvent, _w, cx| this.retry_chat_turn(cx));
        transcript = transcript.child(
            div()
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(danger_line(why))
                .child(text_action("chat-retry", "Retry").on_click(retry)),
        );
    }

    div()
        .id("chat-messages")
        .track_scroll(&chat.scroll)
        .min_h(px(0.0))
        .overflow_y_scroll()
        .occlude()
        .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
        .child(transcript)
}

/// An untouched thread: the agent's mark, a greeting, and a row of prompts
/// that put a question in the composer rather than asking it for the reader.
fn empty_state(chat: &live::State, mark: &Mark, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let busy = chat.sending || chat.in_flight.is_some();
    let phase = if busy { Phase::Thinking } else { Phase::Idle };

    let mut prompts = div().flex().flex_wrap().items_center().gap(px(SPACE_S));
    for (i, text) in CHAT_EXAMPLES.iter().enumerate() {
        let fill = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.chat_input.set_value(text.to_string());
            cx.notify();
        });
        prompts = prompts.child(prompt_chip(("chat-prompt", i), text).on_click(fill));
    }

    div()
        .flex()
        .flex_col()
        .items_start()
        .gap(px(SPACE_L))
        .pt(px(SPACE_XL))
        .child(mark_tile("chat-empty-mark", mark, phase, EMPTY_MARK, motion))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(SPACE_XS))
                .child(
                    div()
                        .font_family(DISPLAY)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(22.0))
                        .text_color(paint(INK))
                        .child("What do you want to know?"),
                )
                .child(row_desc("Ask about a product, or search the web.")),
        )
        .child(prompts)
}

fn prompt_chip(id: impl Into<gpui::ElementId>, text: &str) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .px(px(SPACE_M))
        .py(px(SPACE_S))
        .rounded(px(8.0))
        .cursor_pointer()
        .bg(paint_a(GLASS_1))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .font_family(SANS)
        .text_size(px(13.0))
        .text_color(paint(INK_2))
        .hover(|d| d.bg(paint_a(GLASS_2)).text_color(paint(INK)))
        .child(text.to_string())
}

/// The reader's own turn: right-aligned, in the brand wash, so a question and
/// an answer are told apart by shape and side before either is read.
fn reader_line(message: &Message) -> Div {
    div()
        .flex()
        .justify_end()
        .child(
            div()
                .px(px(SPACE_M))
                .py(px(SPACE_S))
                .max_w(px(560.0))
                .rounded(px(10.0))
                .bg(paint_a(BRAND_WASH))
                .border_1()
                .border_color(paint_a(HAIRLINE))
                .font_family(SANS)
                .text_size(px(14.0))
                .line_height(px(20.0))
                .text_color(paint(INK))
                .child(message.text.clone()),
        )
}

/// The agent's turn: its mark, then the answer, with the pages it cited under
/// it. Research steps stay behind a plain toggle.
fn agent_block(
    message: &Message,
    agent: &str,
    mark: &Mark,
    motion: bool,
    expanded: bool,
    cx: &mut Context<Kriko>,
) -> Div {
    let copied = message.text.clone();
    let mut actions = div().flex().items_center().gap(px(4.0)).child(
        text_action(
            gpui::ElementId::named_usize(format!("chat-copy-{}", message.message_id), 0),
            "Copy",
        )
        .on_click(move |_, _, cx| {
            cx.write_to_clipboard(gpui::ClipboardItem::new_string(copied.clone()))
        }),
    );
    if !message.steps.is_empty() {
        let id = message.message_id.clone();
        actions = actions.child(
            text_action(
                gpui::ElementId::named_usize(format!("chat-steps-{id}"), 0),
                if expanded { "Hide" } else { "Steps" },
            )
            .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                if !this.live.chat.details.remove(&id) {
                    this.live.chat.details.insert(id.clone());
                }
                cx.notify();
            })),
        );
    }

    let turn_id = format!("chat-turn-{}", message.message_id);
    let words_id = format!("chat-words-{}", message.message_id);
    let mut body = div()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(8.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(mark_tile(turn_id.as_str(), mark, Phase::Idle, TURN_MARK, motion))
                        .child(speaker(agent)),
                )
                .child(actions),
        )
        .child(words_reveal(message.text.as_str(), words_id.as_str(), motion));
    if expanded {
        body = body.child(steps_view(&message.steps));
    }
    if !message.sources.is_empty() {
        body = body.child(sources_view(&message.sources, motion));
    }
    body
}

/// A running turn: the mark moving for its phase, the engine's own line for
/// what it is doing, and any answer text already received.
fn pending_block(
    partial: &Partial,
    job_message: &str,
    agent: &str,
    mark: &Mark,
    motion: bool,
) -> Div {
    let who = if partial.agent.is_empty() {
        agent.to_string()
    } else {
        partial.agent.clone()
    };
    let phase = step_phase(partial);
    let line = turn_status(Some(partial), job_message);
    let mut body = div().flex().flex_col().gap(px(8.0)).child(
        div()
            .flex()
            .items_center()
            .justify_between()
            .gap(px(8.0))
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(mark_tile("chat-turn-pending", mark, phase, TURN_MARK, motion))
                    .child(speaker(&who))
                    .child(phase_beat("chat-pending-beat", phase, motion)),
            )
            .child(cylinder_status("chat-pending-status", line.as_str(), motion)),
    );
    if !partial.steps.is_empty() {
        body = body.child(steps_view(&partial.steps));
    }
    if !partial.answer.is_empty() {
        body = body.child(words_reveal(partial.answer.as_str(), "chat-words-pending", motion));
    }
    if !partial.sources.is_empty() {
        body = body.child(sources_view(&partial.sources, motion));
    }
    body
}

/// What the agent's mark does on a running turn. The engine has a step for
/// every source it reads; the newest running one decides the phase, and a
/// partly written answer is writing.
fn step_phase(partial: &Partial) -> Phase {
    if !partial.answer.is_empty() {
        return Phase::Writing;
    }
    if let Some(step) = partial
        .steps
        .iter()
        .rev()
        .find(|step| step.state == StepState::Running)
    {
        let kind = format!("{} {}", step.source, step.label).to_ascii_lowercase();
        if kind.contains("writ") || kind.contains("finding") {
            return Phase::Writing;
        }
        return Phase::Reading;
    }
    Phase::Thinking
}

/// The line under a running mark: the step in flight, or the job's last word.
fn turn_status(partial: Option<&Partial>, job_message: &str) -> String {
    if let Some(step) = partial.and_then(|turn| {
        turn.steps
            .iter()
            .rev()
            .find(|step| step.state == StepState::Running)
    }) {
        return step.label.clone();
    }
    match job_message.trim() {
        "" => "Thinking".to_string(),
        "queued" => "Queued".to_string(),
        "running" => "Working".to_string(),
        message => message.to_string(),
    }
}

fn steps_view(steps: &[Step]) -> Div {
    let mut rows = div().flex().flex_col().gap(px(SPACE_S));
    for step in steps {
        let mark: gpui::AnyElement = match step.state {
            StepState::Running => div()
                .w(px(7.0))
                .h(px(7.0))
                .rounded(px(4.0))
                .bg(paint(ICE))
                .into_any_element(),
            StepState::Done => icon("check", 12.0).text_color(paint(ICE)).into_any_element(),
            StepState::Error => icon("x", 12.0).text_color(paint(DANGER)).into_any_element(),
            StepState::Empty => div()
                .w(px(6.0))
                .h(px(6.0))
                .rounded(px(3.0))
                .bg(paint(MUTED))
                .into_any_element(),
        };
        rows = rows.child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(div().w(px(14.0)).flex().justify_center().child(mark))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(paint(INK_2))
                        .child(step.label.clone()),
                )
                .child(mono(&live::step_meta(step), MUTED)),
        );
    }
    rows
}

/// The pages behind an answer, each one a source row that opens it.
fn sources_view(names: &[String], motion: bool) -> Div {
    let mut rows = div()
        .flex()
        .flex_col()
        .gap(px(4.0))
        .pt(px(SPACE_XS))
        .child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::MEDIUM)
                .text_size(px(12.0))
                .text_color(paint(MUTED))
                .child("Sources"),
        );
    for name in names.iter() {
        rows = rows.child(source_row(&citation(name), motion));
    }
    rows
}

/// A cited source string as a source row: a URL keeps the page it opens, an
/// engine source name becomes a plain tag with nothing behind it.
fn citation(name: &str) -> Source {
    let url = if name.starts_with("http://") || name.starts_with("https://") {
        name.to_string()
    } else {
        String::new()
    };
    let raw = if url.is_empty() {
        readable_name(name)
    } else {
        url.split('/').nth(2).unwrap_or("").to_string()
    };
    let host = raw.strip_prefix("www.").unwrap_or(raw.as_str()).to_string();
    Source {
        host,
        title: String::new(),
        url,
        // The chat answer carries no per-source trust grade today.
        backed: None,
    }
}

fn readable_name(name: &str) -> String {
    match name {
        "web_search" => "Web search".to_string(),
        _ => name
            .split('_')
            .map(|part| {
                let mut chars = part.chars();
                chars
                    .next()
                    .map(|first| first.to_uppercase().collect::<String>() + chars.as_str())
                    .unwrap_or_default()
            })
            .collect::<Vec<_>>()
            .join(" "),
    }
}

/// The agent's own mark, by the id the engine knows it by.
fn mark_for(id: &str) -> &'static Mark {
    match id {
        "claude-code" => &marks::CLAUDE,
        "codex" => &marks::CODEX,
        "opencode" => &marks::OPENCODE,
        "antigravity-cli" => &marks::ANTIGRAVITY,
        "mistral-vibe" => &marks::MISTRAL,
        "github-copilot" => &marks::COPILOT,
        _ => &marks::BUILTIN,
    }
}

fn selected_agent(chat: &live::State) -> String {
    chat.harnesses
        .iter()
        .find(|(id, _)| id == &chat.harness)
        .map(|(_, name)| name.clone())
        .unwrap_or_else(|| "Kriko".to_string())
}

fn speaker(name: &str) -> Div {
    div()
        .font_family(SANS)
        .font_weight(FontWeight::MEDIUM)
        .text_size(px(13.0))
        .text_color(paint(INK))
        .child(name.to_string())
}

fn status_label(value: &str) -> Div {
    div()
        .px(px(8.0))
        .py(px(SPACE_XS))
        .max_w(px(280.0))
        .overflow_hidden()
        .whitespace_nowrap()
        .text_ellipsis()
        .rounded(px(6.0))
        .bg(paint_a(GLASS_1))
        .font_family(SANS)
        .text_size(px(11.0))
        .text_color(paint(ICE))
        .child(value.to_string())
}

fn danger_line(text: &str) -> Div {
    div()
        .font_family(SANS)
        .text_size(px(13.0))
        .line_height(px(18.0))
        .text_color(paint(DANGER))
        .child(text.to_string())
}

fn text_action(id: impl Into<gpui::ElementId>, label: &str) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(28.0))
        .px(px(8.0))
        .flex_none()
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(6.0))
        .cursor_pointer()
        .font_family(SANS)
        .text_size(px(12.0))
        .text_color(paint(MUTED))
        .hover(|d| d.bg(paint_a(GLASS_1)).text_color(paint(INK)))
        .child(label.to_string())
}

// ---- the composer ----

fn composer(app: &Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let busy = chat.sending || chat.in_flight.is_some();
    let has_text = !app.chat_input.value.trim().is_empty();

    let picker = model_picker(chat, cx);
    let note = (!chat.local_note.is_empty()).then(|| row_desc(&chat.local_note));
    let input = app.input_field(
        Field::ChatAsk,
        "chat-input",
        "Ask Kriko…",
        None,
        window,
        cx,
    );
    let send = cx.listener(|this, _: &ClickEvent, _w, cx| {
        if this.live.chat.in_flight.is_some() {
            this.stop_chat_turn(cx);
        } else {
            this.send_chat_message(cx);
        }
        cx.notify();
    });

    let control = if chat.sending {
        div()
            .id("chat-sending")
            .h(px(40.0))
            .px(px(SPACE_L))
            .flex_none()
            .flex()
            .items_center()
            .rounded(px(10.0))
            .bg(paint_a(GLASS_1))
            .font_family(SANS)
            .text_size(px(13.0))
            .text_color(paint(MUTED))
            .child("Sending")
    } else if busy {
        div()
            .id("chat-stop")
            .h(px(40.0))
            .px(px(SPACE_L))
            .flex_none()
            .flex()
            .items_center()
            .justify_center()
            .rounded(px(10.0))
            .cursor_pointer()
            .bg(paint_a(DANGER_WASH))
            .border_1()
            .border_color(paint_a(DANGER_EDGE))
            .font_family(SANS)
            .font_weight(FontWeight::MEDIUM)
            .text_size(px(13.0))
            .text_color(paint(DANGER))
            .hover(|d| d.bg(paint_a(0xff6b5e3d)))
            .child("Stop")
            .on_click(send)
    } else {
        div()
            .id("chat-send")
            .h(px(40.0))
            .px(px(SPACE_L))
            .flex_none()
            .flex()
            .items_center()
            .justify_center()
            .gap(px(SPACE_S))
            .rounded(px(10.0))
            .cursor_pointer()
            .font_family(SANS)
            .font_weight(FontWeight::MEDIUM)
            .text_size(px(13.0))
            .text_color(if has_text { fixed(0xffffff) } else { paint(MUTED) })
            .bg(if has_text { paint(BRAND) } else { paint_a(GLASS_1) })
            .border_1()
            .border_color(if has_text {
                fixed_a(0xffffff40)
            } else {
                paint_a(HAIRLINE)
            })
            .when(has_text, |d| d.hover(|s| s.bg(paint(BRAND_HOVER))))
            .child("Send")
            .on_click(send)
    };

    div()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .pt(px(SPACE_M))
        .border_t_1()
        .border_color(paint_a(HAIRLINE))
        .child(picker)
        .children(note)
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(8.0))
                .child(div().flex_1().min_w(px(0.0)).child(input))
                .child(control),
        )
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(8.0))
                .child(row_desc("Enter sends · Shift+Enter adds a line"))
                .child(row_desc(&format!(
                    "{} / 2000",
                    app.chat_input.value.chars().count()
                ))),
        )
}

/// The small picker that names the agent answering, so the reader can change
/// it without leaving the composer.
fn model_picker(chat: &live::State, cx: &mut Context<Kriko>) -> Div {
    let mut row = div()
        .flex()
        .flex_wrap()
        .items_center()
        .gap(px(SPACE_S))
        .child(
            div()
                .mr(px(SPACE_XS))
                .font_family(SANS)
                .text_size(px(12.0))
                .text_color(paint(MUTED))
                .child("Model"),
        );
    if chat.harnesses.is_empty() {
        row = row.child(row_desc("None ready"));
    }
    for (i, (id, name)) in chat.harnesses.iter().enumerate() {
        let selected = id == &chat.harness;
        let id = id.clone();
        row = row.child(
            div()
                .id(("chat-model", i))
                .h(px(26.0))
                .px(px(SPACE_S))
                .flex_none()
                .flex()
                .items_center()
                .rounded(px(7.0))
                .cursor_pointer()
                .font_family(SANS)
                .text_size(px(12.0))
                .text_color(paint(if selected { ICE } else { MUTED }))
                .when(selected, |d| {
                    d.bg(paint_a(GLASS_1))
                        .border_1()
                        .border_color(paint_a(BORDER_CONTROL))
                })
                .when(!selected, |d| {
                    d.hover(|s| s.bg(paint_a(GLASS_1)).text_color(paint(INK)))
                })
                .child(name.clone())
                .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    if !this.live.chat.sending && this.live.chat.in_flight.is_none() {
                        this.live.chat.harness = id.clone();
                    }
                    cx.notify();
                })),
        );
    }
    row
}
