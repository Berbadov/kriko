//! Agents: the coding agents on this machine that can reach Kriko.
//! The table on the left with last-seen and run counts, the detail card
//! for the picked agent on the right: state, latency, tools, reconnect.

use gpui::{div, prelude::*, px, rgb, rgba, Context, Div, FontWeight, Stateful, Styled, Window};

use crate::app::Kriko;
use crate::data;
use crate::screens::{mono, row_desc, row_title, th};
use crate::theme::*;

pub fn agents(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Stateful<Div> {
    let motion = !app.reduce_motion;
    let selected = app.agent_selected.min(data::AGENTS.len() - 1);

    let mut table = card().flex().flex_col();
    table = table
        .child(
            div()
                .flex()
                .items_center()
                .pb(px(10.0))
                .child(div().flex_1().min_w(px(160.0)).child(th("Agent")))
                .child(div().w(px(120.0)).child(th("State")))
                .child(div().w(px(96.0)).child(th("Latency")))
                .child(div().w(px(104.0)).child(th("Last seen")))
                .child(div().w(px(72.0)).child(th("Runs")))
                .child(div().w(px(90.0)).child(th("Allowed"))),
        )
        .child(hairline());

    for (i, agent) in data::AGENTS.iter().enumerate() {
        let is_selected = i == selected;
        let click = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.agent_selected = i;
            cx.notify();
        });
        let allowed = app.agent_allowed.get(i).copied().unwrap_or(agent.allowed);
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            if i < this.agent_allowed.len() {
                this.agent_allowed[i] = !this.agent_allowed[i];
            }
            cx.notify();
        });
        let row = div()
            .id(("agent-row", i))
            .flex()
            .items_center()
            .py(px(12.0))
            .cursor_pointer()
            .hover(|s| s.bg(rgba(GLASS_1)))
            .when(is_selected, |s| {
                s.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE))
            })
            .on_click(click)
            .child(
                div()
                    .flex_1()
                    .min_w(px(160.0))
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .child(agent_tile(letter_rows(agent.monogram), None))
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .gap(px(2.0))
                            .child(
                                div()
                                    .font_family(SANS)
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .text_size(px(15.0))
                                    .text_color(rgb(if is_selected { ICE } else { INK }))
                                    .child(agent.name.to_string()),
                            )
                            .child(mono(agent.kind, MUTED)),
                    ),
            )
            .child(div().w(px(120.0)).flex().child(tag(agent.state, agent.state_label, motion)))
            .child(div().w(px(96.0)).child(mono(agent.latency, INK_2)))
            .child(div().w(px(104.0)).child(mono(agent.last_seen, INK_2)))
            .child(div().w(px(72.0)).child(mono(&agent.runs.to_string(), INK_2)))
            .child(
                div()
                    .w(px(90.0))
                    .flex()
                    .child(switch_anim(("agent-sw", i), allowed, motion).on_click(toggle)),
            );
        table = table.child(row);
        if i + 1 < data::AGENTS.len() {
            table = table.child(hairline());
        }
    }

    // ---- detail card ----
    let agent = &data::AGENTS[selected];
    let allowed = app
        .agent_allowed
        .get(selected)
        .copied()
        .unwrap_or(agent.allowed);
    let tools = app.agent_tools.get(selected).copied().unwrap_or([
        agent.can_read,
        agent.can_run,
        agent.can_answer,
    ]);

    let allowed_toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
        if selected < this.agent_allowed.len() {
            this.agent_allowed[selected] = !this.agent_allowed[selected];
        }
        cx.notify();
    });
    let reconnect = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
        // A reconnect re-reads the MCP handshake; the run stays untouched.
        this.dock_feed.push(crate::app::DockFeedEntry::now(
            format!("{}: reconnected", data::AGENTS[selected].name),
            TagState::Done,
        ));
        cx.notify();
    });

    let mut tool_rows = div().flex().flex_col();
    for (ti, (label, desc)) in [
        ("Read pages", "Read pages Kriko stores, for grounding"),
        ("Take part in Run", "Join a check as one of the working agents"),
        ("Answer questions", "Answer follow-up questions from Compare"),
    ]
    .into_iter()
    .enumerate()
    {
        let on = tools[ti];
        let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            if let Some(t) = this.agent_tools.get_mut(selected) {
                t[ti] = !t[ti];
            }
            cx.notify();
        });
        tool_rows = tool_rows
            .child(
                div()
                    .py(px(11.0))
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap(px(16.0))
                    .child(
                        div()
                            .flex()
                            .flex_col()
                            .gap(px(2.0))
                            .child(row_title(label))
                            .child(row_desc(desc)),
                    )
                    .child(switch_anim(("agent-tool", ti), on, motion).on_click(toggle)),
            )
            .child(hairline());
    }

    let detail = card()
        .flex()
        .flex_col()
        .gap(px(10.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(agent_tile(letter_rows(agent.monogram), None))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title(agent.name))
                        .child(mono(agent.kind, MUTED)),
                ),
        )
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(tag(agent.state, agent.state_label, motion))
                .child(chip(&format!("mcp :{}", agent.port))),
        )
        .child(hairline())
        .child(row_desc(agent.detail))
        .child(hairline())
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(16.0))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(mono("LATENCY", DIM))
                        .child(mono(agent.latency, INK_2)),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(mono("LAST SEEN", DIM))
                        .child(mono(agent.last_seen, INK_2)),
                )
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(mono("RUNS", DIM))
                        .child(mono(&agent.runs.to_string(), INK_2)),
                ),
        )
        .child(
            div()
                .flex()
                .items_center()
                .justify_between()
                .gap(px(16.0))
                .child(
                    div()
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(row_title("Allowed in Run"))
                        .child(row_desc("When off, this agent is skipped in every check.")),
                )
                .child(
                    switch_anim("agent-detail-sw", allowed, motion).on_click(allowed_toggle),
                ),
        )
        .child(hairline())
        .child(div().pb(px(2.0)).child(eyebrow("Tools")))
        .child(tool_rows)
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(ghost("agent-reconnect", "Reconnect").on_click(reconnect))
                .child(row_desc("Re-reads the MCP handshake for this agent.")),
        );

    div()
        .id("agents-row-scroll")
        .overflow_x_scroll()
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .items_start()
                .min_w(px(980.0))
                .child(div().flex_1().min_w(px(0.0)).child(table))
                .child(div().w(px(320.0)).flex_none().child(detail)),
        )
}
