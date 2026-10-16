//! Chat: a calm transcript with the reader's own agent, grounded in the
//! knowledge and sources available to this install.

use gpui::{div, prelude::*, px, rgb, rgba, ClickEvent, Context, Div, FontWeight, Styled, Window};

use crate::app::{Field, Kriko};
use crate::data::CHAT_EXAMPLES;
use crate::live::chat::{self as live, Message, Partial, Role, Step, StepState};
use crate::screens::{mono, row_desc};
use crate::theme::*;

/// Reserve enough width for the conversation rail and a readable transcript.
const NARROW_W: f32 = 620.0;
const THREAD_RAIL_W: f32 = 168.0;

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
        list = list.child(row_desc(if chat.loaded {
            "No conversations yet."
        } else {
            "Loading conversations…"
        }));
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
                .px(px(10.0))
                .flex_none()
                .flex()
                .items_center()
                .gap(px(6.0))
                .rounded(px(8.0))
                .cursor_pointer()
                .font_family(SANS)
                .text_size(px(13.0))
                .text_color(rgb(if picked { INK } else { INK_2 }))
                .when(compact, |d| d.w(px(190.0)))
                .when(!compact, |d| d.w_full())
                .when(picked, |d| {
                    d.bg(rgba(GLASS_1)).border_1().border_color(rgba(HAIRLINE))
                })
                .when(!picked, |d| d.hover(|h| h.bg(rgba(GLASS_1))))
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
                            .font_family(SANS)
                            .text_size(px(11.0))
                            .text_color(rgb(ICE))
                            .child("Working"),
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
                .text_color(rgb(MUTED))
                .child("Conversations"),
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

fn conversation(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let title = chat
        .thread
        .as_ref()
        .and_then(|id| chat.threads.iter().find(|t| t.thread_id == *id))
        .map(|t| t.name())
        .unwrap_or_else(|| "New conversation".to_string());
    let running_here = chat
        .in_flight
        .as_ref()
        .is_some_and(|f| chat.thread.as_deref() == Some(f.thread_id.as_str()));
    let status = if chat.sending {
        Some("Sending question".to_string())
    } else if running_here {
        let partial = chat.partial.as_ref();
        Some(turn_status(partial, &chat.job_message))
    } else if chat.failed.is_some() {
        Some("Could not finish".to_string())
    } else {
        None
    };

    let mut header = div()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(8.0))
        .pb(px(8.0))
        .border_b_1()
        .border_color(rgba(HAIRLINE))
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
                        .text_color(rgb(INK))
                        .overflow_hidden()
                        .whitespace_nowrap()
                        .text_ellipsis()
                        .child(title),
                )
                .children(status.map(|value| status_label(&value))),
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
        .gap(px(10.0))
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
    let chars = app
        .live
        .chat
        .messages
        .iter()
        .map(|m| m.text.len())
        .sum::<usize>()
        + app.live.chat.partial.as_ref().map_or(0, |p| p.answer.len());
    let chat = &mut app.live.chat;
    if chars != chat.rendered_chars {
        if chat.rendered_chars == 0
            || (chat.scroll.offset().y + chat.scroll.max_offset().height).abs() < px(60.0)
        {
            chat.scroll.scroll_to_bottom();
        }
        chat.rendered_chars = chars;
    }

    let chat = &app.live.chat;
    let mut transcript = div().flex().flex_col().gap(px(16.0));
    if chat.messages.is_empty() && chat.in_flight.is_none() {
        transcript = transcript.child(examples(cx));
    }
    for message in chat.messages.iter() {
        transcript = transcript.child(match message.role {
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
        transcript = transcript.child(pending_block(&partial, &chat.job_message, chat));
    }
    if let Some(why) = chat.failed.as_ref() {
        let retry = cx.listener(|this, _: &ClickEvent, _w, cx| this.retry_chat_turn(cx));
        transcript = transcript.child(
            div()
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(status_label("The answer could not be completed"))
                .child(danger_line(why))
                .child(text_action("chat-retry", "Retry last message").on_click(retry)),
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

/// An empty thread offers a few useful starting questions without filling the
/// transcript with decorative cards.
fn examples(cx: &mut Context<Kriko>) -> Div {
    let mut column = div()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(
            div()
                .font_family(DISPLAY)
                .font_weight(FontWeight::MEDIUM)
                .text_size(px(21.0))
                .text_color(rgb(INK))
                .child("What would you like to know?"),
        )
        .child(row_desc(
            "Ask about products, search the web, or explore saved research.",
        ));
    for (i, text) in CHAT_EXAMPLES.iter().enumerate() {
        let fill = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.chat_input.set_value(text.to_string());
            cx.notify();
        });
        column = column.child(
            div()
                .id(("chat-example", i))
                .w_full()
                .px(px(10.0))
                .py(px(8.0))
                .rounded(px(8.0))
                .cursor_pointer()
                .bg(rgba(GLASS_1))
                .font_family(SANS)
                .text_size(px(13.0))
                .text_color(rgb(INK_2))
                .hover(|s| s.bg(rgba(GLASS_2)))
                .child(text.to_string())
                .on_click(fill),
        );
    }
    column
}

fn reader_line(message: &Message) -> Div {
    div().flex().justify_end().child(
        div()
            .px(px(13.0))
            .py(px(9.0))
            .max_w(px(560.0))
            .rounded(px(10.0))
            .bg(rgba(BRAND_WASH))
            .font_family(SANS)
            .text_size(px(14.0))
            .text_color(rgb(INK))
            .child(message.text.clone()),
    )
}

fn agent_block(message: &Message, expanded: bool, cx: &mut Context<Kriko>) -> Div {
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
                gpui::ElementId::named_usize(format!("chat-details-{id}"), 0),
                if expanded {
                    "Hide research"
                } else {
                    "Research details"
                },
            )
            .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                if !this.live.chat.details.remove(&id) {
                    this.live.chat.details.insert(id.clone());
                }
                cx.notify();
            })),
        );
    }

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
                .child(speaker("Kriko"))
                .child(actions),
        )
        .child(text_block(&message.text));
    if expanded {
        body = body.child(steps_view(&message.steps));
    }
    if !message.sources.is_empty() {
        body = body.child(sources_view(&message.message_id, &message.sources));
    }
    body
}

/// A running turn shows the engine's current phase, its own step labels, and
/// any answer text already received. Nothing estimates how far it has left.
fn pending_block(partial: &Partial, job_message: &str, chat: &live::State) -> Div {
    let who = if partial.agent.is_empty() {
        selected_agent(chat)
    } else {
        partial.agent.clone()
    };
    let mut body = div().flex().flex_col().gap(px(8.0)).child(
        div()
            .flex()
            .items_center()
            .justify_between()
            .gap(px(8.0))
            .child(speaker(&who))
            .child(status_label(&turn_status(Some(partial), job_message))),
    );
    if !partial.steps.is_empty() {
        body = body.child(steps_view(&partial.steps));
    }
    if !partial.answer.is_empty() {
        body = body.child(text_block(&partial.answer));
    }
    if !partial.sources.is_empty() {
        body = body.child(sources_view("pending", &partial.sources));
    }
    body
}

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
        "" => "Preparing the answer".to_string(),
        "queued" => "Waiting to start".to_string(),
        "running" => "Working".to_string(),
        message => message.to_string(),
    }
}

fn steps_view(steps: &[Step]) -> Div {
    let mut rows = div().flex().flex_col().gap(px(6.0));
    for step in steps {
        let mark: gpui::AnyElement = match step.state {
            StepState::Running => div()
                .w(px(7.0))
                .h(px(7.0))
                .rounded(px(4.0))
                .bg(rgb(ICE))
                .into_any_element(),
            StepState::Done => icon("check", 12.0).text_color(rgb(ICE)).into_any_element(),
            StepState::Error => icon("x", 12.0).text_color(rgb(DANGER)).into_any_element(),
            StepState::Empty => div()
                .w(px(6.0))
                .h(px(6.0))
                .rounded(px(3.0))
                .bg(rgb(MUTED))
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
                        .text_color(rgb(INK_2))
                        .child(step.label.clone()),
                )
                .child(mono(&live::step_meta(step), MUTED)),
        );
    }
    rows
}

fn sources_view(key: &str, names: &[String]) -> Div {
    let mut links = div().flex().flex_wrap().items_center().gap(px(4.0));
    for (i, name) in names.iter().enumerate() {
        if name.starts_with("https://") || name.starts_with("http://") {
            let link = name.clone();
            let host = name.split('/').nth(2).unwrap_or(name);
            let host = host.strip_prefix("www.").unwrap_or(host);
            links = links.child(
                text_action(
                    gpui::ElementId::named_usize(format!("chat-source-{key}"), i),
                    &format!("{}. {host}", i + 1),
                )
                .max_w(px(240.0))
                .overflow_hidden()
                .whitespace_nowrap()
                .text_ellipsis()
                .text_color(rgb(ICE))
                .on_click(move |_, _, cx| cx.open_url(&link)),
            );
        } else {
            links = links.child(source_tag(key, name, i));
        }
    }
    div()
        .flex()
        .flex_col()
        .gap(px(3.0))
        .pt(px(2.0))
        .child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::MEDIUM)
                .text_size(px(12.0))
                .text_color(rgb(MUTED))
                .child(format!("Sources · {}", names.len())),
        )
        .child(links)
}

fn source_tag(key: &str, name: &str, index: usize) -> gpui::Stateful<Div> {
    let readable = match name {
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
    };
    div()
        .id(gpui::ElementId::named_usize(
            format!("chat-source-name-{key}"),
            index,
        ))
        .h(px(26.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .rounded(px(6.0))
        .bg(rgba(GLASS_1))
        .font_family(SANS)
        .text_size(px(12.0))
        .text_color(rgb(INK_2))
        .child(format!("{}. {readable}", index + 1))
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
        .text_color(rgb(INK))
        .child(name.to_string())
}

fn status_label(value: &str) -> Div {
    div()
        .px(px(8.0))
        .py(px(3.0))
        .max_w(px(280.0))
        .overflow_hidden()
        .whitespace_nowrap()
        .text_ellipsis()
        .rounded(px(6.0))
        .bg(rgba(GLASS_1))
        .font_family(SANS)
        .text_size(px(11.0))
        .text_color(rgb(ICE))
        .child(value.to_string())
}

/// A small set of inline formatting shared by streamed and saved replies.
/// Unclosed markers stay visible while the next streamed fragment arrives.
fn text_block(text: &str) -> Div {
    let mut column = div()
        .flex()
        .flex_col()
        .gap(px(4.0))
        .font_family(SANS)
        .text_size(px(14.0))
        .line_height(px(21.0))
        .text_color(rgb(INK));
    let mut code = false;
    for line in text.lines() {
        let line = line.trim_end();
        if line.trim_start().starts_with("```") {
            code = !code;
            continue;
        }
        if code {
            column = column.child(
                div()
                    .font_family(CODE)
                    .bg(rgba(GLASS_1))
                    .px(px(8.0))
                    .child(line.to_string()),
            );
            continue;
        }
        let line = line.trim();
        if line.is_empty() {
            column = column.child(div().h(px(4.0)));
            continue;
        }
        if line.starts_with("# ") || line.starts_with("## ") || line.starts_with("### ") {
            column = column.child(
                div()
                    .pt(px(5.0))
                    .font_weight(FontWeight::SEMIBOLD)
                    .text_size(px(16.0))
                    .child(formatted_line(line.trim_start_matches('#').trim_start())),
            );
            continue;
        }
        column = column.child(if is_list_item(line) {
            div()
                .pl(px(10.0))
                .border_l_1()
                .border_color(rgba(HAIRLINE))
                .child(formatted_line(line))
        } else {
            div().child(formatted_line(line))
        });
    }
    column
}

fn formatted_line(line: &str) -> gpui::StyledText {
    let mut display = String::new();
    let mut highlights = Vec::new();
    let mut rest = line;
    while !rest.is_empty() {
        let marker = if rest.starts_with("**") {
            Some("**")
        } else if rest.starts_with('`') {
            Some("`")
        } else {
            None
        };
        if let Some(marker) = marker {
            if let Some(end) = rest[marker.len()..].find(marker) {
                let start = display.len();
                display.push_str(&rest[marker.len()..marker.len() + end]);
                highlights.push((
                    start..display.len(),
                    gpui::HighlightStyle {
                        font_weight: (marker == "**").then_some(FontWeight::SEMIBOLD),
                        background_color: (marker == "`").then_some(rgba(GLASS_1).into()),
                        ..Default::default()
                    },
                ));
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

fn is_list_item(line: &str) -> bool {
    let digits = line.chars().take_while(|c| c.is_ascii_digit()).count();
    (digits > 0 && digits <= 2 && matches!(line.chars().nth(digits), Some('.') | Some(')')))
        || line.starts_with("- ")
        || line.starts_with("* ")
}

fn danger_line(text: &str) -> Div {
    div()
        .font_family(SANS)
        .text_size(px(12.0))
        .text_color(rgb(DANGER))
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
        .text_color(rgb(MUTED))
        .hover(|d| d.bg(rgba(GLASS_1)).text_color(rgb(INK)))
        .child(label.to_string())
}

// ---- the composer ----

fn composer(app: &Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let chat = &app.live.chat;
    let busy = chat.sending || chat.in_flight.is_some();
    let mut agents = div().flex().flex_wrap().items_center().gap(px(5.0)).child(
        div()
            .mr(px(3.0))
            .font_family(SANS)
            .text_size(px(12.0))
            .text_color(rgb(MUTED))
            .child("Reply with"),
    );
    for (i, (id, name)) in chat.harnesses.iter().enumerate() {
        let selected = id == &chat.harness;
        let id = id.clone();
        agents = agents.child(
            div()
                .id(("chat-agent", i))
                .h(px(30.0))
                .px(px(10.0))
                .flex_none()
                .flex()
                .items_center()
                .rounded(px(7.0))
                .cursor_pointer()
                .font_family(SANS)
                .text_size(px(12.0))
                .text_color(rgb(if selected { ICE } else { MUTED }))
                .when(selected, |d| {
                    d.bg(rgba(GLASS_1))
                        .border_1()
                        .border_color(rgba(BORDER_CONTROL))
                })
                .when(!selected, |d| {
                    d.hover(|s| s.bg(rgba(GLASS_1)).text_color(rgb(INK)))
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
    if chat.harnesses.is_empty() {
        agents = agents.child(row_desc("No agent is ready"));
    }

    let note = (!chat.local_note.is_empty())
        .then(|| row_desc(&format!("Local agent: {}", chat.local_note)));
    let input = app.input_field(
        Field::ChatAsk,
        "chat-input",
        "Message Kriko…",
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
            .h(px(42.0))
            .px(px(14.0))
            .flex()
            .items_center()
            .rounded(px(8.0))
            .bg(rgba(GLASS_1))
            .font_family(SANS)
            .text_size(px(13.0))
            .text_color(rgb(MUTED))
            .child("Sending…")
    } else {
        let label = if busy { "Stop" } else { "Send" };
        div()
            .id("chat-send")
            .h(px(42.0))
            .px(px(16.0))
            .flex_none()
            .flex()
            .items_center()
            .justify_center()
            .rounded(px(8.0))
            .cursor_pointer()
            .font_family(SANS)
            .font_weight(FontWeight::MEDIUM)
            .text_size(px(13.0))
            .text_color(rgb(if busy { 0xffd2cf } else { 0xffffff }))
            .bg(rgb(if busy { 0x532b31 } else { BRAND }))
            .hover(|d| d.opacity(0.9))
            .child(label)
            .on_click(send)
    };

    div()
        .flex()
        .flex_col()
        .gap(px(6.0))
        .pt(px(8.0))
        .border_t_1()
        .border_color(rgba(HAIRLINE))
        .child(agents)
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
                .justify_between()
                .gap(px(8.0))
                .child(row_desc("Enter to send · Shift+Enter for a new line"))
                .child(row_desc(&format!(
                    "{} / 2000",
                    app.chat_input.value.chars().count()
                ))),
        )
}
