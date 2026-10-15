//! Chat: a conversation with the agent you already have, over what the app
//! has generated. The agent is told the names of the records it may read and
//! reads each one only when it asks; the steps are drawn as it reads them, and
//! the answer names the sources it used.
//!
//! The conversation comes first and the composer sits at its foot, with the
//! agent picker beside the input. The conversations list sits beside it, and
//! below it when the window is narrow.

use gpui::{div, prelude::*, px, rgb, rgba, ClickEvent, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data::CHAT_EXAMPLES;
use crate::live::chat::{self as live, Message, Partial, Role, Step, StepState};
use crate::screens::local::pill;
use crate::screens::{empty_note, mono, plate_s, row_desc};
use crate::theme::*;

/// Below this content width the conversations list stacks under the conversation.
const NARROW_W: f32 = 760.0;

pub fn chat(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    let narrow = app.content_w > 0.0 && app.content_w < NARROW_W;
    let threads = thread_list(app, cx);
    let conversation = conversation(app, motion, window, cx);
    let body = if narrow {
        div().flex().flex_col().gap(px(8.0)).child(threads).child(conversation)
    } else {
        div()
            .flex()
            .items_start()
            .gap(px(8.0))
            .child(threads.w(px(196.0)).flex_none())
            .child(conversation.flex_1().min_w(px(0.0)))
    };
    div().flex().flex_col().gap(px(8.0)).child(body)
}

// ---- the conversations ----

fn thread_list(app: &Kriko, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let new_one = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.new_chat_thread(cx);
        cx.notify();
    });
    let mut list = div().flex().flex_col().gap(px(2.0));
    if chat.threads.is_empty() {
        list = list.child(empty_note(if chat.loaded {
            "No conversations yet."
        } else {
            "Loading..."
        }));
    }
    for (i, thread) in chat.threads.iter().enumerate() {
        let picked = chat.thread.as_deref() == Some(thread.thread_id.as_str());
        let id = thread.thread_id.clone();
        let open = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.open_chat_thread(id.clone(), cx);
            cx.notify();
        });
        list = list.child(
            div()
                .id(("chat-thread", i))
                .px(px(12.0))
                .py(px(8.0))
                .rounded(px(10.0))
                .cursor_pointer()
                .font_family(SANS)
                .text_size(px(13.0))
                .text_color(rgb(if picked { INK } else { INK_2 }))
                .when(picked, |d| d.bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL)))
                .when(!picked, |d| d.hover(|h| h.bg(rgba(GLASS_1))))
                .overflow_hidden()
                .child(thread.name())
                .when(chat.running.contains_key(&thread.thread_id), |d| d.child(mono("Answering…", ICE)))
                .on_click(open),
        );
    }
    card()
        .p(px(10.0))
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(div().flex().items_center().justify_between().child(eyebrow("Conversations")).child(plate_s("chat-new", "New chat").on_click(new_one)))
        .child(div().id("chat-thread-list").max_h(px(if app.content_w < NARROW_W { 112.0 } else { 480.0 })).overflow_y_scroll().child(list))
}

// ---- the conversation ----

fn conversation(app: &mut Kriko, motion: bool, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let mut column = card().p(px(16.0)).flex().flex_col().gap(px(10.0));
    if let Some(name) = chat
        .thread
        .as_ref()
        .and_then(|id| chat.threads.iter().find(|t| t.thread_id == *id))
        .map(|t| t.name())
    {
        let delete = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.delete_chat_thread(cx);
            cx.notify();
        });
        column = column.child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(8.0))
                .child(
                    div()
                        .min_w(px(0.0))
                        .font_family(DISPLAY)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(18.0))
                        .text_color(rgb(INK))
                        .child(name),
                )
                .child(plate_s("chat-delete", "Delete").on_click(delete)),
        );
    }
    let say = chat.say.clone();
    let messages = messages_view(app, motion, cx);
    let composer = composer(app, window, cx);
    column = column.child(messages);
    if let Some(text) = say {
        column = column.child(danger_line(&text));
    }
    column.child(composer)
}

fn messages_view(app: &mut Kriko, motion: bool, cx: &mut Context<Kriko>) -> gpui::Stateful<Div> {
    let chars = app.live.chat.messages.iter().map(|m| m.text.len()).sum::<usize>()
        + app.live.chat.partial.as_ref().map_or(0, |p| p.answer.len());
    let chat = &mut app.live.chat;
    if chars != chat.rendered_chars {
        if chat.rendered_chars == 0 || (chat.scroll.offset().y + chat.scroll.max_offset().height).abs() < px(60.0) {
            chat.scroll.scroll_to_bottom();
        }
        chat.rendered_chars = chars;
    }
    let chat = &app.live.chat;
    let mut column = div().flex().flex_col().gap(px(10.0));
    if chat.messages.is_empty() && chat.in_flight.is_none() {
        column = column.child(examples(cx));
    }
    for message in chat.messages.iter() {
        column = column.child(match message.role {
            Role::Reader => reader_line(message),
            Role::Agent => agent_block(message, chat.details.contains(&message.message_id), cx),
        });
    }
    let running_here = chat
        .in_flight
        .as_ref()
        .is_some_and(|f| chat.thread.as_deref() == Some(f.thread_id.as_str()));
    if running_here {
        let partial = chat.partial.clone().unwrap_or_default();
        column = column.child(pending_block(&partial, &chat.job_message, motion));
    }
    if let Some(why) = chat.failed.as_ref() {
        column = column.child(danger_line(why));
        let retry = cx.listener(|this, _: &ClickEvent, _w, cx| { this.retry_chat_turn(cx); });
        column = column.child(plate_s("chat-retry", "Retry last message").on_click(retry));
    }
    div()
        .id("chat-messages")
        .track_scroll(&chat.scroll)
        .min_h(px(220.0))
        .max_h(px(520.0))
        .overflow_y_scroll()
        .occlude()
        .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
        .child(column)
}

/// An empty conversation starts from one of these questions. Nothing else: the
/// first look is the question box and what it can be asked.
fn examples(cx: &mut Context<Kriko>) -> Div {
    let mut column = div().flex().flex_col().gap(px(10.0))
        .child(div().font_family(DISPLAY).text_size(px(24.0)).text_color(rgb(INK)).child("What can I help you find?"))
        .child(row_desc("Ask a question, find products on the web, or explore your saved research."));
    for (i, text) in CHAT_EXAMPLES.iter().enumerate() {
        let fill = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.chat_input.set_value(text.to_string());
            cx.notify();
        });
        column = column.child(
            div()
                .id(("chat-example", i))
                .px(px(12.0))
                .py(px(8.0))
                .rounded(px(10.0))
                .cursor_pointer()
                .bg(rgb(WELL))
                .border_1()
                .border_color(rgba(HAIRLINE))
                .hover(|s| s.border_color(rgba(BORDER_CONTROL)))
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(INK_2))
                .child(text.to_string())
                .on_click(fill),
        );
    }
    column
}

fn reader_line(message: &Message) -> Div {
    div().flex().justify_end().child(
        well()
            .px(px(14.0))
            .py(px(4.0))
            .max_w(px(560.0))
            .font_family(SANS)
            .text_size(px(14.0))
            .text_color(rgb(INK))
            .child(message.text.clone()),
    )
}

fn agent_block(message: &Message, expanded: bool, cx: &mut Context<Kriko>) -> Div {
    let mut body = div().flex().flex_col().gap(px(8.0)).child(text_block(&message.text));
    let copied = message.text.clone();
    let mut actions = div().flex().items_center().gap(px(6.0))
        .child(plate_s(gpui::ElementId::named_usize(format!("chat-copy-{}", message.message_id), 0), "Copy")
            .on_click(move |_, _, cx| cx.write_to_clipboard(gpui::ClipboardItem::new_string(copied.clone()))));
    if !message.steps.is_empty() {
        let id = message.message_id.clone();
        actions = actions.child(plate_s(gpui::ElementId::named_usize(format!("chat-details-{id}"), 0), if expanded { "Hide research" } else { "Research details" })
            .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                if !this.live.chat.details.remove(&id) { this.live.chat.details.insert(id.clone()); }
                cx.notify();
            })));
    }
    if expanded {
        body = body.child(steps_view(&format!("chat-done-{}", message.message_id), &message.steps, false));
    }
    if !message.sources.is_empty() {
        body = body.child(sources_view(&message.message_id, &message.sources));
    }
    div().px(px(4.0)).py(px(10.0)).child(body.child(actions))
}

/// The turn in flight: its steps as they are read, and the answer once written.
fn pending_block(partial: &Partial, job_message: &str, motion: bool) -> Div {
    let total = partial.steps.len().max(1) as f32;
    let settled = partial.steps.iter().filter(|s| s.state.is_settled()).count() as f32;
    let share = if partial.steps.is_empty() {
        0.08
    } else {
        (settled / total).clamp(0.08, 1.0)
    };
    let who = if partial.agent.is_empty() { "Agent" } else { partial.agent.as_str() };
    let mut body = div()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(eyebrow(&format!("{who} · working")));
    if partial.steps.is_empty() {
        let words = if job_message.is_empty() { "Starting..." } else { job_message };
        body = body.child(row_desc(words));
    } else {
        body = body.child(steps_view("chat-live", &partial.steps, motion));
    }
    body = body.child(progress_bar("chat-turn", share, motion));
    if !partial.answer.is_empty() {
        body = body.child(text_block(&partial.answer));
    }
    if !partial.sources.is_empty() {
        body = body.child(sources_view("pending", &partial.sources));
    }
    card().p(px(16.0)).child(body)
}

/// Each record the agent asked for, one row: its state, the engine's words, and
/// how many rows and how long it took.
fn steps_view(key: &str, steps: &[Step], motion: bool) -> Div {
    let mut rows = well().p(px(12.0)).flex().flex_col().gap(px(6.0));
    for step in steps {
        rows = rows.child(step_row(format!("{key}-{}", step.id), step, motion));
    }
    rows
}

fn step_row(key: String, step: &Step, motion: bool) -> Div {
    let mark: gpui::AnyElement = match step.state {
        StepState::Running => spinner(key.clone(), 12.0, motion),
        StepState::Done => icon("check", 12.0).text_color(rgb(ICE)).into_any_element(),
        StepState::Error => icon("x", 12.0).text_color(rgb(DANGER)).into_any_element(),
        StepState::Empty => div().w(px(6.0)).h(px(6.0)).rounded(px(3.0)).bg(rgb(MUTED)).into_any_element(),
    };
    div()
        .flex()
        .items_center()
        .gap(px(6.0))
        .child(div().w(px(16.0)).flex().justify_center().child(mark))
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(if step.state.is_settled() { INK_2 } else { INK }))
                .child(step.label.clone()),
        )
        .child(mono(&live::step_meta(step), MUTED))
}

fn sources_view(key: &str, names: &[String]) -> Div {
    let mut row = div().flex().flex_wrap().gap(px(6.0));
    for (i, name) in names.iter().enumerate() {
        if name.starts_with("https://") || name.starts_with("http://") {
            let link = name.clone();
            let host = name.split('/').nth(2).unwrap_or(name);
            row = row.child(plate_s(gpui::ElementId::named_usize(format!("chat-source-{key}"), i), &format!("{} · {host}", i))
                .max_w(px(240.0)).overflow_hidden()
                .text_color(rgb(ICE)).on_click(move |_, _, cx| cx.open_url(&link)));
        } else { row = row.child(chip(name)); }
    }
    row
}

/// An answer, line by line. A line that opens a list item (a number, a dash or
/// a star) is a compact row with a hairline above it, so a shortlist reads as
/// rows, not as one paragraph.
fn text_block(text: &str) -> Div {
    let mut column = div()
        .flex()
        .flex_col()
        .gap(px(4.0))
        .font_family(SANS)
        .text_size(px(14.0))
        .text_color(rgb(INK));
    let mut code = false;
    for line in text.lines() {
        let line = line.trim_end();
        if line.trim_start().starts_with("```") { code = !code; continue; }
        if code {
            column = column.child(div().font_family(CODE).bg(rgb(WELL)).px(px(8.0)).child(line.to_string()));
            continue;
        }
        let line = line.trim();
        if line.is_empty() { column = column.child(div().h(px(5.0))); continue; }
        if line.starts_with("# ") || line.starts_with("## ") || line.starts_with("### ") {
            column = column.child(div().pt(px(6.0)).font_weight(FontWeight::SEMIBOLD)
                .text_size(px(16.0)).child(formatted_line(line.trim_start_matches('#').trim_start())));
            continue;
        }
        column = if is_list_item(line) {
            column.child(
                div()
                    .py(px(6.0))
                    .border_t_1()
                    .border_color(rgba(HAIRLINE))
                    .child(formatted_line(line)),
            )
        } else {
            column.child(formatted_line(line))
        };
    }
    column
}

/// A small set of inline formatting shared by streamed and saved replies.
/// Unclosed markers stay visible while the next streamed fragment arrives.
fn formatted_line(line: &str) -> gpui::StyledText {
    let mut display = String::new();
    let mut highlights = Vec::new();
    let mut rest = line;
    while !rest.is_empty() {
        let marker = if rest.starts_with("**") { Some("**") }
            else if rest.starts_with('`') { Some("`") } else { None };
        if let Some(marker) = marker {
            if let Some(end) = rest[marker.len()..].find(marker) {
                let start = display.len();
                display.push_str(&rest[marker.len()..marker.len() + end]);
                highlights.push((start..display.len(), gpui::HighlightStyle {
                    font_weight: (marker == "**").then_some(FontWeight::SEMIBOLD),
                    background_color: (marker == "`").then_some(rgb(WELL).into()),
                    ..Default::default()
                }));
                rest = &rest[end + marker.len() * 2..];
                continue;
            }
        }
        let ch = rest.chars().next().unwrap();
        display.push(ch);
        rest = &rest[ch.len_utf8()..];
    }
    gpui::StyledText::new(display).with_highlights(highlights)
}

/// A line that opens a list item: "1." or "2)" or a dash or star bullet.
fn is_list_item(line: &str) -> bool {
    let digits = line.chars().take_while(|c| c.is_ascii_digit()).count();
    (digits > 0 && digits <= 2 && matches!(line.chars().nth(digits), Some('.') | Some(')')))
        || line.starts_with("- ")
        || line.starts_with("* ")
}

fn danger_line(text: &str) -> Div {
    well()
        .px(px(14.0))
        .py(px(4.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .text_color(rgb(DANGER))
        .child(text.to_string())
}

// ---- the composer ----

/// The question box, with the agent picker beside it and Send at its end. The
/// picker is one chip that names the agent and steps to the next on each press.
fn composer(app: &Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let busy = chat.sending || chat.in_flight.is_some();
    let label = chat
        .harnesses
        .iter()
        .find(|(id, _)| *id == chat.harness)
        .map(|(_, label)| label.clone())
        .unwrap_or_else(|| "No agent".to_string());
    let mut agents = div().flex().flex_wrap().items_center().gap(px(6.0)).child(mono("Agent", MUTED));
    for (i, (id, name)) in chat.harnesses.iter().enumerate() {
        let selected = id == &chat.harness;
        let id = id.clone();
        agents = agents.child(pill(("chat-agent", i), name, selected).on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
            if !this.live.chat.sending && this.live.chat.in_flight.is_none() { this.live.chat.harness = id.clone(); }
            cx.notify();
        })));
    }
    if chat.harnesses.is_empty() { agents = agents.child(row_desc(&label)); }
    let note = (!chat.local_note.is_empty())
        .then(|| row_desc(&format!("Local agent: {}", chat.local_note)));
    let input = app.input_field(
        Field::ChatAsk,
        "chat-input",
        "Message Kriko…",
        Some("agents"),
        window,
        cx,
    );
    let send = cx.listener(|this, _: &ClickEvent, _w, cx| {
        if this.live.chat.in_flight.is_some() { this.stop_chat_turn(cx); }
        else { this.send_chat_message(cx); }
        cx.notify();
    });
    div()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .child(agents)
        .children(note)
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(6.0))
                .child(div().flex_1().min_w(px(0.0)).child(input))
                .child(key_or_busy(busy, chat.sending).on_click(send)),
        )
        .child(div().flex().justify_between()
            .child(mono("Enter to send · Shift+Enter for a new line", MUTED))
            .child(mono(&format!("{} / 2000", app.chat_input.value.chars().count()),
                if app.chat_input.value.chars().count() > 2000 { DANGER } else { MUTED })))
}

fn key_or_busy(busy: bool, sending: bool) -> gpui::Stateful<Div> {
    let label = if sending { "Sending…" } else if busy { "Stop" } else { "Send" };
    key("chat-send", label)
}
