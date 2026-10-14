//! Chat: a conversation with the agent you already have, over what the app
//! has generated. The agent is told the names of the records it may read and
//! reads each one only when it asks; the steps are drawn as it reads them, and
//! the answer names the sources it used.
//!
//! A thread list sits beside the conversation (above it when the window is
//! narrow); the composer at the bottom picks the agent and sends the question.

use gpui::{div, prelude::*, px, rgb, rgba, ClickEvent, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data::CHAT_EXAMPLES;
use crate::live::chat::{self as live, Message, Partial, Role, Step, StepState};
use crate::screens::local::pill;
use crate::screens::{empty_note, mono, plate_s, row_desc};
use crate::theme::*;

/// Below this content width the thread list stacks above the conversation.
const NARROW_W: f32 = 760.0;

pub fn chat(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let narrow = app.content_w > 0.0 && app.content_w < NARROW_W;
    let threads = thread_list(app, cx);
    let conversation = conversation(app, motion, window, cx);
    let body = if narrow {
        div().flex().flex_col().gap(px(14.0)).child(threads).child(conversation)
    } else {
        div()
            .flex()
            .items_start()
            .gap(px(14.0))
            .child(threads.w(px(240.0)).flex_none())
            .child(conversation.flex_1().min_w(px(0.0)))
    };
    div().flex().flex_col().gap(px(14.0)).child(body)
}

// ---- the thread list ----

fn thread_list(app: &Kriko, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let new_one = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.new_chat_thread(cx);
        cx.notify();
    });
    let mut list = div().flex().flex_col().gap(px(4.0));
    if chat.threads.is_empty() {
        list = list.child(empty_note(if chat.loaded {
            "No conversations yet. Start one with New."
        } else {
            "Reading your conversations..."
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
                .py(px(9.0))
                .rounded(px(10.0))
                .cursor_pointer()
                .font_family(SANS)
                .text_size(px(13.0))
                .text_color(rgb(if picked { INK } else { INK_2 }))
                .when(picked, |d| d.bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL)))
                .when(!picked, |d| d.hover(|h| h.bg(rgba(GLASS_1))))
                .child(thread.name())
                .on_click(open),
        );
    }
    card()
        .p(px(14.0))
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .child(eyebrow("Conversations"))
                .child(plate_s("chat-new", "New").on_click(new_one)),
        )
        .child(list)
}

// ---- the conversation ----

fn conversation(app: &mut Kriko, motion: bool, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let title = chat
        .thread
        .as_ref()
        .and_then(|id| chat.threads.iter().find(|t| t.thread_id == *id))
        .map(|t| t.name())
        .unwrap_or_else(|| "Ask your agent".to_string());
    let open = chat.thread.is_some();
    let say = chat.say.clone();
    let mut head = div().flex().items_center().justify_between().gap(px(12.0)).child(
        div()
            .min_w(px(0.0))
            .font_family(DISPLAY)
            .font_weight(FontWeight::SEMIBOLD)
            .text_size(px(18.0))
            .text_color(rgb(INK))
            .child(title),
    );
    if open {
        let delete = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.delete_chat_thread(cx);
            cx.notify();
        });
        head = head.child(plate_s("chat-delete", "Delete").on_click(delete));
    }
    let messages = messages_view(app, motion, cx);
    let composer = composer(app, window, cx);
    let mut column = card()
        .p(px(16.0))
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(head)
        .child(messages);
    if let Some(text) = say {
        column = column.child(danger_line(&text));
    }
    column.child(composer)
}

fn messages_view(app: &Kriko, motion: bool, cx: &mut Context<Kriko>) -> gpui::Stateful<Div> {
    let chat = &app.live.chat;
    let mut column = div().flex().flex_col().gap(px(12.0));
    if chat.messages.is_empty() && chat.in_flight.is_none() {
        column = column.child(intro(app, cx));
    }
    for message in chat.messages.iter() {
        column = column.child(match message.role {
            Role::Reader => reader_line(message),
            Role::Agent => agent_block(message),
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
    }
    div()
        .id("chat-messages")
        .min_h(px(220.0))
        .max_h(px(520.0))
        .overflow_y_scroll()
        .occlude()
        .on_scroll_wheel(|_, _, cx| cx.stop_propagation())
        .child(column)
}

/// What an empty conversation says: how to ask, three generic examples, and
/// the names of what the agent may read. Names only, never a record.
fn intro(app: &Kriko, cx: &mut Context<Kriko>) -> Div {
    let mut examples = div().flex().flex_col().gap(px(8.0));
    for (i, text) in CHAT_EXAMPLES.iter().enumerate() {
        let fill = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.chat_input.set_value(text.to_string());
            cx.notify();
        });
        examples = examples.child(
            div()
                .id(("chat-example", i))
                .px(px(12.0))
                .py(px(9.0))
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
    let mut reads = div().flex().flex_col().gap(px(6.0));
    for source in &app.live.chat.sources {
        reads = reads.child(
            div()
                .flex()
                .items_baseline()
                .gap(px(10.0))
                .child(mono(&source.name, INK_2).flex_none())
                .child(row_desc(&source.description)),
        );
    }
    div()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(row_desc(
            "Ask in your own words. The agent plans what to look up, reads only that, and answers with the sources it used.",
        ))
        .child(examples)
        .child(eyebrow("It can read"))
        .child(reads)
}

fn reader_line(message: &Message) -> Div {
    div().flex().justify_end().child(
        well()
            .px(px(14.0))
            .py(px(10.0))
            .max_w(px(560.0))
            .font_family(SANS)
            .text_size(px(14.0))
            .text_color(rgb(INK))
            .child(message.text.clone()),
    )
}

fn agent_block(message: &Message) -> Div {
    let mut body = div().flex().flex_col().gap(px(10.0)).child(eyebrow("Agent"));
    body = body.child(text_block(&message.text));
    if !message.steps.is_empty() {
        body = body.child(steps_view(&format!("chat-done-{}", message.message_id), &message.steps, false));
    }
    if !message.sources.is_empty() {
        body = body.child(sources_view(&message.sources));
    }
    card().p(px(16.0)).child(body)
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
        .gap(px(10.0))
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
        .gap(px(10.0))
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

fn sources_view(names: &[String]) -> Div {
    let mut row = div().flex().flex_wrap().gap(px(6.0));
    for name in names {
        row = row.child(chip(name));
    }
    row
}

/// An answer, line by line, so a shortlist keeps its breaks.
fn text_block(text: &str) -> Div {
    let mut column = div()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .font_family(SANS)
        .text_size(px(14.0))
        .text_color(rgb(INK));
    for line in text.lines() {
        column = if line.trim().is_empty() {
            column.child(div().h(px(6.0)))
        } else {
            column.child(line.to_string())
        };
    }
    column
}

fn danger_line(text: &str) -> Div {
    well()
        .px(px(14.0))
        .py(px(10.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .text_color(rgb(DANGER))
        .child(text.to_string())
}

// ---- the composer ----

fn composer(app: &Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let busy = chat.sending || chat.in_flight.is_some();
    let mut agents = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (i, (id, label)) in chat.harnesses.iter().enumerate() {
        let picked = *id == chat.harness;
        let pick = {
            let id = id.clone();
            cx.listener(move |this, _: &ClickEvent, _w, cx| {
                // The agent is fixed for a turn in flight: changing it mid-answer
                // would make the steps and the answer disagree about who gave them.
                if this.live.chat.in_flight.is_none() {
                    this.live.chat.harness = id.clone();
                }
                cx.notify();
            })
        };
        agents = agents.child(pill(("chat-agent", i), label, picked).on_click(pick));
    }
    let input = app.input_field(
        Field::ChatAsk,
        "chat-input",
        "Ask about what this app holds...",
        Some("agents"),
        window,
        cx,
    );
    let send = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.send_chat_message(cx);
        cx.notify();
    });
    div()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(agents)
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(div().flex_1().min_w(px(0.0)).child(input))
                .child(key_or_busy(busy).on_click(send)),
        )
}

fn key_or_busy(busy: bool) -> gpui::Stateful<Div> {
    let label = if busy { "Working" } else { "Send" };
    key("chat-send", label)
}
