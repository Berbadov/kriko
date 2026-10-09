//! Compare: the shortlist workbench. Named drafts, four slots, the
//! specifications and the known risks cell by cell with their status icons,
//! a drawing board for your own marks, and follow-up questions your agent
//! answers while you weigh things up.

use std::cell::RefCell;
use std::rc::Rc;

use gpui::{
    canvas, div, point, prelude::*, px, rgb, rgba, size, Bounds, Corners, Div, Edges, FontWeight,
    MouseButton, PaintQuad, Pixels, SharedString, Styled, Window,
};

use crate::app::{Field, Kriko, Tab};
use crate::live::compare::{self as live, Check, Level, Loaded, Note, QState, QuestionRun, MAX_SLOTS};
use crate::marks::{self, mark_tile, phase_beat, Phase};
use crate::screens::{empty_note, mono, plate_s, row_desc, th, trust_icon};
use crate::theme::*;

/// The agent's own mark by the id the engine knows it by; the built-in mark
/// for one without a mark of its own.
fn mark_for(id: &str) -> &'static marks::Mark {
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

/// The engine's own word for a risk's severity, in the chip's look.
fn level_chip(level: Level) -> Div {
    let (glyph, fg, bg): (&[&str], u32, u32) = match level {
        Level::Critical => (&X5, DANGER, DANGER_WASH),
        Level::High => (&BANG5, 0xffb86b, 0xffb86b1f),
        Level::Medium => (&BANG5, INK_2, WELL),
        Level::Low | Level::Unrated => (&QUEUE5, MUTED, WELL),
    };
    div()
        .h(px(24.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .gap(px(7.0))
        .rounded(px(7.0))
        .bg(rgb(bg))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .font_family(MONO)
        .text_size(px(10.0))
        .text_color(rgb(fg))
        .child(led_matrix(glyph, fg, 3.0, 1.0))
        .child(level.word())
}

/// The check a slot holds, once read.
fn check_in<'a>(app: &'a Kriko, id: &Option<String>) -> Option<&'a Check> {
    match id.as_ref().and_then(|id| app.live.compare.checks.get(id)) {
        Some(Loaded::Ready(c)) => Some(c),
        _ => None,
    }
}

/// A tiny bezel icon button (the slot's clear x, the note's remove x).
fn x_button(
    id: impl Into<gpui::ElementId>,
    cx: &mut Context<Kriko>,
    on_click: impl Fn(&mut Kriko, &mut Context<Kriko>) + 'static,
) -> gpui::Stateful<Div> {
    let listener = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| on_click(this, cx));
    div()
        .id(id)
        .w(px(24.0))
        .h(px(24.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(7.0))
        .cursor_pointer()
        .bg(rgba(GLASS_1))
        .border_1()
        .border_color(rgba(HAIRLINE))
        .hover(|s| s.bg(rgba(DANGER_WASH)))
        .child(icon("x", 12.0).text_color(rgb(MUTED)))
        .on_click(listener)
}

/// The fraction of the board's box a window position lands on.
fn board_point(
    bounds: Bounds<Pixels>,
    position: gpui::Point<Pixels>,
) -> (f32, f32) {
    (
        f32::from((position.x - bounds.origin.x) / bounds.size.width).clamp(0.0, 1.0),
        f32::from((position.y - bounds.origin.y) / bounds.size.height).clamp(0.0, 1.0),
    )
}

// ---- the drawing board ----

/// The board: your free marks over the comparison. Strokes and notes are
/// fractions of the board's own box, so they land on the same column
/// whatever width the window is at.
fn board(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let bounds_cell: Rc<RefCell<Option<Bounds<Pixels>>>> = Rc::new(RefCell::new(None));

    let down_cell = bounds_cell.clone();
    let on_down = cx.listener(
        move |this, event: &gpui::MouseDownEvent, _w, cx| {
            if event.button != MouseButton::Left {
                return;
            }
            let bounds = down_cell.borrow().unwrap_or_default();
            if bounds.size.width <= px(0.0) || bounds.size.height <= px(0.0) {
                return;
            }
            let (x, y) = board_point(bounds, event.position);
            if this.live.compare.board_tool == 0 {
                this.live.compare.drawing = true;
                this.live.compare.stroke_current = vec![(x, y)];
            } else {
                this.live.compare.notes.push(Note {
                    x,
                    y,
                    text: String::new(),
                });
                let open = this.live.compare.notes.len() - 1;
                this.live.compare.note_open = Some(open);
                this.compare_note_input.set_value(String::new());
            }
            cx.notify();
        },
    );

    let move_cell = bounds_cell.clone();
    let on_move = cx.listener(move |this, event: &gpui::MouseMoveEvent, _w, cx| {
        if !this.live.compare.drawing || this.live.compare.board_tool != 0 {
            return;
        }
        let bounds = move_cell.borrow().unwrap_or_default();
        if bounds.size.width <= px(0.0) || bounds.size.height <= px(0.0) {
            return;
        }
        let (x, y) = board_point(bounds, event.position);
        let len = this.live.compare.stroke_current.len();
        let moved = len == 0 || {
            let last = this.live.compare.stroke_current[len - 1];
            (last.0 - x).abs() > 0.002 || (last.1 - y).abs() > 0.002
        };
        if moved {
            this.live.compare.stroke_current.push((x, y));
            cx.notify();
        }
    });

    let on_up = cx.listener(|this, _: &gpui::MouseUpEvent, _w, cx| {
        if this.live.compare.drawing {
            this.live.compare.drawing = false;
            if this.live.compare.stroke_current.len() > 1 {
                let stroke = std::mem::take(&mut this.live.compare.stroke_current);
                this.live.compare.strokes.push(stroke);
                this.save_board_soon(cx);
            } else {
                this.live.compare.stroke_current.clear();
            }
            cx.notify();
        }
    });

    let undo = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.compare.strokes.pop();
        this.save_board_soon(cx);
        cx.notify();
    });
    let clear = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.compare.strokes.clear();
        this.live.compare.notes.clear();
        this.live.compare.note_open = None;
        this.save_board_soon(cx);
        cx.notify();
    });
    let close = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.compare.board_open = false;
        cx.notify();
    });

    let pick_tool = |i: usize| {
        cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.compare.board_tool = i;
            cx.notify();
        })
    };
    let tools = div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .flex_wrap()
        .child(div().flex_1().min_w(px(0.0)))
        .child(
            tool_chip("board-pen", "check", "PEN", app.live.compare.board_tool == 0)
                .on_click(pick_tool(0)),
        )
        .child(
            tool_chip("board-note", "plus", "NOTE", app.live.compare.board_tool == 1)
                .on_click(pick_tool(1)),
        )
        .child(plate_s("board-undo", "Undo mark").on_click(undo))
        .child(plate_s("board-clear", "Clear").on_click(clear))
        .child(plate_s("board-close", "Close").on_click(close));

    // The canvas that paints every stroke: fractions land wherever the
    // board is drawn now, never where the pen happened to be.
    let mut strokes: Vec<Vec<(f32, f32)>> = app.live.compare.strokes.clone();
    strokes.push(app.live.compare.stroke_current.clone());
    let surface = canvas(
        move |bounds, _, _| bounds,
        move |bounds, _, window, _| {
            for stroke in &strokes {
                for w in stroke.windows(2) {
                    let (a, b) = (w[0], w[1]);
                    let w = f32::from(bounds.size.width);
                    let h = f32::from(bounds.size.height);
                    let p0 = point(
                        bounds.origin.x + px(a.0 * w),
                        bounds.origin.y + px(a.1 * h),
                    );
                    let p1 = point(
                        bounds.origin.x + px(b.0 * w),
                        bounds.origin.y + px(b.1 * h),
                    );
                    let dx = f32::from(p1.x - p0.x);
                    let dy = f32::from(p1.y - p0.y);
                    let dist = (dx * dx + dy * dy).sqrt();
                    let steps = ((dist / 2.0).ceil() as usize).max(1);
                    for s in 0..=steps {
                        let t = s as f32 / steps as f32;
                        let dot = px(3.0);
                        let pos = point(
                            p0.x + px(dx * t),
                            p0.y + px(dy * t),
                        );
                        window.paint_quad(PaintQuad {
                            bounds: Bounds::new(
                                pos - point(dot / 2.0, dot / 2.0),
                                size(dot, dot),
                            ),
                            corner_radii: Corners::default(),
                            background: hsla(ICE).into(),
                            border_widths: Edges::default(),
                            border_color: hsla(0),
                            border_style: Default::default(),
                        });
                    }
                }
            }
        },
    )
    .absolute()
    .size_full();

    let hint = div().flex().items_center().gap(px(8.0)).child(row_desc(
        if app.live.compare.board_tool == 0 {
            "Drag over the board to mark it: circle the winner, cross out a column."
        } else {
            "Click anywhere on the board to pin a note where it belongs."
        },
    ));

    div()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(tools)
        .child(
            div()
                .id("board-surface")
                .relative()
                .h(px(260.0))
                .rounded(px(16.0))
                .bg(rgb(WELL))
                .border_1()
                .border_color(rgba(BORDER_CONTROL))
                .overflow_hidden()
                .on_mouse_down(MouseButton::Left, on_down)
                .on_mouse_move(on_move)
                .on_mouse_up(MouseButton::Left, on_up)
                .child(surface)
                .children(pin_notes(app, &bounds_cell, window, cx)),
        )
        .child(hint)
}

/// The tool chip: a small well that lights when it is the picked tool.
fn tool_chip(id: &'static str, icon_name: &str, label: &str, picked: bool) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(36.0))
        .px(px(14.0))
        .flex()
        .items_center()
        .gap(px(8.0))
        .rounded(px(10.0))
        .cursor_pointer()
        .font_family(MONO)
        .text_size(px(12.0))
        .when(picked, |s| {
            s.bg(rgb(WELL))
                .border_1()
                .border_color(rgba(BORDER_CONTROL))
                .text_color(rgb(ICE))
        })
        .when(!picked, |s| s.text_color(rgb(MUTED)))
        .child(
            icon(icon_name, 14.0).text_color(rgb(if picked { ICE } else { MUTED })),
        )
        .child(label.to_string())
        .child(led_matrix(
            &CHECK5,
            if picked { ICE } else { LED_DIM },
            3.0,
            1.0,
        ))
}

// ---- the pinned notes ----

fn pin_notes(
    app: &mut Kriko,
    bounds_cell: &Rc<RefCell<Option<Bounds<Pixels>>>>,
    window: &mut Window,
    cx: &mut Context<Kriko>,
) -> Vec<gpui::AnyElement> {
    let notes: Vec<Note> = app.live.compare.notes.clone();
    let mut pinned: Vec<gpui::AnyElement> = Vec::new();
    for (i, note) in notes.into_iter().enumerate() {
        // The position is read from the box the board was painted in, so a
        // note stays pinned to its column through a resize.
        let (nx, ny) = match *bounds_cell.borrow() {
            Some(b) if b.size.width > px(0.0) => (
                note.x * f32::from(b.size.width),
                note.y * f32::from(b.size.height),
            ),
            _ => (16.0, 16.0),
        };
        let open = app.live.compare.note_open == Some(i);
        let open_note = cx.listener(move |this, _: &gpui::ClickEvent, window, cx| {
            if i >= this.live.compare.notes.len() {
                return;
            }
            this.live.compare.note_open = Some(i);
            this.compare_note_input.set_value(this.live.compare.notes[i].text.clone());
            let handle = this.compare_note_input.handle.clone();
            window.focus(&handle);
            cx.notify();
        });
        let remove_note = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
            if this.live.compare.note_open == Some(i) {
                this.live.compare.note_open = None;
            }
            if i < this.live.compare.notes.len() {
                this.live.compare.notes.remove(i);
                this.save_board_soon(cx);
            }
            cx.notify();
        };
        let chip: gpui::AnyElement = if open {
            div()
                .w(px(184.0))
                .p(px(10.0))
                .rounded(px(10.0))
                .bg(rgba(FROST))
                .shadow(vec![shadow(0x02061773, 0.0, 10.0, 24.0, 0.0)])
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(app.input_field(
                    Field::BoardNote,
                    "board-note-input",
                    "type the note...",
                    None,
                    window,
                    cx,
                ))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .justify_between()
                        .child(mono("ENTER TO PIN", DIM))
                        .child(x_button(("note-remove", i), cx, remove_note)),
                )
                .into_any_element()
        } else {
            div()
                .id(("note-chip", i))
                .max_w(px(184.0))
                .p(px(10.0))
                .rounded(px(10.0))
                .bg(rgba(FROST))
                .shadow(vec![shadow(0x02061773, 0.0, 10.0, 24.0, 0.0)])
                .cursor_pointer()
                .on_click(open_note)
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(0x0a0e1a))
                        .child(if note.text.is_empty() {
                            SharedString::from("Empty note")
                        } else {
                            SharedString::from(note.text.clone())
                        }),
                )
                .into_any_element()
        };
        pinned.push(
            div()
                .absolute()
                .left(px(nx))
                .top(px(ny))
                .child(chip)
                .into_any_element(),
        );
    }
    pinned
}

/// ---- the table ----

/// The preferred pin: one click marks a row as yours. Marked rows tint
/// and join what the agent reads off the board.
fn pin_button(
    id: impl Into<gpui::ElementId> + 'static,
    marked: bool,
    on_click: impl Fn(&mut Kriko, &mut Context<Kriko>) + 'static,
    cx: &mut Context<Kriko>,
) -> gpui::Stateful<Div> {
    let listener = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| on_click(this, cx));
    div()
        .id(id)
        .w(px(26.0))
        .h(px(26.0))
        .flex()
        .items_center()
        .justify_center()
        .rounded(px(8.0))
        .cursor_pointer()
        .hover(|s| s.bg(rgba(GLASS_1)))
        .child(led_matrix(
            if marked { &CHECK5 } else { &QUEUE5 },
            if marked { ICE } else { LED_DIM },
            3.0,
            1.0,
        ))
        .on_click(listener)
}

fn preferred_chip() -> Div {
    div()
        .px(px(7.0))
        .h(px(18.0))
        .flex()
        .items_center()
        .rounded(px(6.0))
        .bg(rgba(BRAND_WASH))
        .font_family(MONO)
        .text_size(px(9.0))
        .text_color(rgb(BRAND_BRIGHT))
        .child("PREFERRED")
}

/// The compare table: one column per slot, sections for specs and risks,
/// one section and one detail row open at a time. Every cell is what the
/// saved check and its product say; a column still being read says so.
fn table(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let all: Vec<Option<String>> = app.live.compare.slots.clone();
    // the column window: three products at a time when many are lined
    // up, scrubbed by the slider that sits above the table
    let filled: Vec<String> = all.iter().flatten().cloned().collect();
    let visible = filled.len().min(3);
    let first = if filled.len() > visible {
        (app.live.compare.scroll * (filled.len() - visible) as f32).round() as usize
    } else {
        0
    };
    let slots: Vec<Option<String>> = if filled.len() > visible {
        filled[first..first + visible].iter().cloned().map(Some).collect()
    } else {
        all
    };
    let columns: Vec<Option<&Check>> = slots.iter().map(|s| check_in(app, s)).collect();
    let specs = live::spec_rows(&columns);
    let risks = live::risk_rows(&columns);
    let names: Vec<String> = slots
        .iter()
        .map(|s| match s.as_ref().and_then(|id| app.live.compare.checks.get(id)) {
            Some(Loaded::Ready(c)) => c.name.clone(),
            Some(Loaded::Missing(_)) => "Not found".to_string(),
            Some(Loaded::Loading) => "Reading".to_string(),
            None => "Empty slot".to_string(),
        })
        .collect();
    let col_w = px(190.0);
    let marks_now: Vec<String> = app.marks_now().to_vec();

    // The header: the attribute column, then one per slot.
    let mut head = div()
        .flex()
        .items_center()
        .pb(px(10.0))
        .child(div().flex_1().min_w(px(150.0)).child(th("Attribute")));
    for (slot, name) in slots.iter().zip(&names) {
        head = head.child(
            div().w(col_w).min_w(px(0.0)).child(
                div()
                    .font_family(MONO)
                    .text_size(px(11.0))
                    .text_color(rgb(if slot.is_some() { DIM } else { LED_OFF }))
                    .child(name.to_uppercase()),
            ),
        );
    }

    let mut body = card().flex().flex_col().child(head).child(hairline());
    let section = app.live.compare.section;

    // ---- the specs section ----
    let open_specs = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.compare.section = 0;
        this.live.compare.detail = None;
        cx.notify();
    });
    let open_risks = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.compare.section = 1;
        this.live.compare.detail = None;
        cx.notify();
    });
    let specs_label = format!("Specifications ({})", specs.len());
    let risks_label = format!("Known risks ({})", risks.len());
    body = body.child(
        section_head("cmp-specs", specs_label.as_str(), "layers", section == 0, cx)
            .on_click(open_specs),
    );

    if section == 0 {
        for (ri, row_data) in specs.iter().enumerate() {
            let detail = app.live.compare.detail == Some((0, ri));
            let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.compare.detail = if this.live.compare.detail == Some((0, ri)) {
                    None
                } else {
                    Some((0, ri))
                };
                cx.notify();
            });
            let key = format!("spec:{}", row_data.label);
            let marked = marks_now.contains(&key);
            let pin = {
                let key = key.clone();
                move |this: &mut Kriko, cx: &mut Context<Kriko>| {
                    this.toggle_mark(key.clone(), cx);
                    cx.notify();
                }
            };
            let mut row = div()
                .id(("spec-row", ri))
                .py(px(11.0))
                .flex()
                .items_center()
                .cursor_pointer()
                .when(marked, |s| s.bg(rgba(BRAND_WASH)))
                .hover(|s| s.bg(rgba(GLASS_1)))
                .on_click(toggle)
                .child(
                    div()
                        .flex_1()
                        .min_w(px(150.0))
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .text_color(rgb(if detail || marked { ICE } else { INK }))
                                .child(row_data.label.clone()),
                        )
                        .when(row_data.differs, |d| {
                            d.child(
                                div()
                                    .px(px(7.0))
                                    .h(px(18.0))
                                    .flex()
                                    .items_center()
                                    .rounded(px(6.0))
                                    .bg(rgba(BRAND_WASH))
                                    .font_family(MONO)
                                    .text_size(px(9.0))
                                    .text_color(rgb(BRAND_BRIGHT))
                                    .child("DIFFERS"),
                            )
                        })
                        .when(marked, |d| d.child(preferred_chip())),
                );
            for cell in &row_data.cells {
                let cell_div = match cell {
                    Some(c) => div()
                        .w(col_w)
                        .min_w(px(0.0))
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(
                            div()
                                .min_w(px(0.0))
                                .flex_1()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .text_color(rgb(INK_2))
                                .child(c.value.clone()),
                        )
                        .child(trust_icon((!c.source.is_empty()).then_some(true))),
                    None => div().w(col_w).child(mono("Not stated", DIM)),
                };
                row = row.child(cell_div);
            }
            row = row.child(pin_button(("spec-pin", ri), marked, pin, cx));
            body = body.child(row);
            if detail {
                let mut d = div()
                    .pl(px(8.0))
                    .py(px(10.0))
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(row_desc("Where each value comes from:"));
                for (ci, cell) in row_data.cells.iter().enumerate() {
                    let name = names.get(ci).cloned().unwrap_or_default();
                    let line = match cell {
                        Some(c) if !c.source.is_empty() => format!("{}: read from {}.", name, c.source),
                        Some(_) => format!("{}: the catalog names no page for it.", name),
                        None => format!("{}: no installed catalog states this.", name),
                    };
                    d = d.child(
                        div()
                            .pl(px(14.0))
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .child(match cell {
                                Some(c) => trust_icon((!c.source.is_empty()).then_some(true)),
                                None => led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0),
                            })
                            .child(mono(&line, MUTED)),
                    );
                }
                body = body.child(well().p(px(12.0)).mb(px(6.0)).child(d));
            }
            if ri + 1 < specs.len() {
                body = body.child(hairline());
            }
        }
        if specs.is_empty() {
            body = body.child(row_desc(if columns.iter().any(|c| c.is_some()) {
                "No specifications are recorded for these products."
            } else {
                "Line up a saved check to read its specifications."
            }));
        }
    }

    // ---- the risks section ----
    body = body.child(hairline());
    body = body.child(
        section_head("cmp-risks", risks_label.as_str(), "check", section == 1, cx)
            .on_click(open_risks),
    );

    if section == 1 {
        for (ri, row_data) in risks.iter().enumerate() {
            let detail = app.live.compare.detail == Some((1, ri));
            let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.compare.detail = if this.live.compare.detail == Some((1, ri)) {
                    None
                } else {
                    Some((1, ri))
                };
                cx.notify();
            });
            let key = format!("risk:{}", row_data.title);
            let marked = marks_now.contains(&key);
            let pin = {
                let key = key.clone();
                move |this: &mut Kriko, cx: &mut Context<Kriko>| {
                    this.toggle_mark(key.clone(), cx);
                    cx.notify();
                }
            };
            let mut row = div()
                .id(("risk-row", ri))
                .py(px(11.0))
                .flex()
                .items_center()
                .cursor_pointer()
                .when(marked, |s| s.bg(rgba(BRAND_WASH)))
                .hover(|s| s.bg(rgba(GLASS_1)))
                .on_click(toggle)
                .child(
                    div()
                        .flex_1()
                        .min_w(px(150.0))
                        .pr(px(12.0))
                        .flex()
                        .flex_col()
                        .gap(px(4.0))
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .text_color(rgb(if detail || marked { ICE } else { INK }))
                                .child(row_data.title.clone()),
                        )
                        .when(marked, |d| d.child(div().flex().child(preferred_chip()))),
                );
            for cell in &row_data.cells {
                let cell_div = match cell {
                    Some(c) => div()
                        .w(col_w)
                        .min_w(px(0.0))
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(level_chip(c.level))
                        .child(trust_icon(c.backed())),
                    None => div().w(col_w).child(mono("Not recorded", DIM)),
                };
                row = row.child(cell_div);
            }
            row = row.child(pin_button(("risk-pin", ri), marked, pin, cx));
            body = body.child(row);
            if detail {
                let mut d = div()
                    .pl(px(8.0))
                    .py(px(10.0))
                    .flex()
                    .flex_col()
                    .gap(px(8.0))
                    .child(row_desc("The evidence behind each word:"));
                for (ci, cell) in row_data.cells.iter().enumerate() {
                    let name = names.get(ci).cloned().unwrap_or_default();
                    if let Some(c) = cell {
                        let said = match (c.disputed, c.sources.len()) {
                            (true, n) => format!("disputed · {n} source(s) on record"),
                            (false, 0) => "no source on record".to_string(),
                            (false, n) => format!("backed · {n} source(s) on record: {}", c.sources.join(", ")),
                        };
                        d = d.child(
                            div()
                                .pl(px(14.0))
                                .flex()
                                .flex_col()
                                .gap(px(2.0))
                                .child(
                                    div()
                                        .flex()
                                        .items_center()
                                        .gap(px(8.0))
                                        .child(level_chip(c.level))
                                        .child(mono(&name, MUTED)),
                                )
                                .child(row_desc(&c.body))
                                .child(mono(&said, DIM)),
                        );
                    }
                }
                body = body.child(well().p(px(12.0)).mb(px(6.0)).child(d));
            }
            if ri + 1 < risks.len() {
                body = body.child(hairline());
            }
        }
        if risks.is_empty() {
            body = body.child(row_desc(if columns.iter().any(|c| c.is_some()) {
                "No known risks are recorded for these products."
            } else {
                "Line up a saved check to read its known risks."
            }));
        }
    }

    body
}

// One section header: the icon, the label, and the open state.
fn section_head(
    id: impl Into<gpui::ElementId>,
    label: &str,
    icon_name: &str,
    open: bool,
    _cx: &mut Context<Kriko>,
) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .py(px(12.0))
        .flex()
        .items_center()
        .gap(px(10.0))
        .cursor_pointer()
        .hover(|s| s.bg(rgba(GLASS_1)))
        .child(icon(icon_name, 15.0).text_color(rgb(if open { ICE } else { MUTED })))
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(if open { ICE } else { DIM }))
                .child(label.to_uppercase()),
        )
        .child(div().flex_1())
        .child(icon(
            if open { "chevron-down" } else { "arrow-right" },
            14.0,
        )
        .text_color(rgb(DIM)))
}

// ---- the screen ----

/// The column slider: when more products are lined up than the screen
/// shows, its thumb scrubs through the columns. Drag it or click the
/// track; the table windows to wherever it sits.
fn column_slider(
    app: &mut Kriko,
    filled: usize,
    visible: usize,
    cx: &mut Context<Kriko>,
) -> Div {
    let cell: Rc<RefCell<Option<Bounds<Pixels>>>> = Rc::new(RefCell::new(None));

    let jump_cell = cell.clone();
    let jump = cx.listener(move |this, ev: &gpui::MouseDownEvent, _w, cx| {
        let bounds = jump_cell.borrow().unwrap_or_default();
        if bounds.size.width <= px(0.0) {
            return;
        }
        this.live.compare.dragging = true;
        this.live.compare.scroll = (f32::from(ev.position.x - bounds.origin.x)
            / f32::from(bounds.size.width))
            .clamp(0.0, 1.0);
        cx.notify();
    });
    let drag_cell = cell.clone();
    let drag = cx.listener(move |this, ev: &gpui::MouseMoveEvent, _w, cx| {
        if !this.live.compare.dragging {
            return;
        }
        let bounds = drag_cell.borrow().unwrap_or_default();
        if bounds.size.width <= px(0.0) {
            return;
        }
        this.live.compare.scroll = (f32::from(ev.position.x - bounds.origin.x)
            / f32::from(bounds.size.width))
            .clamp(0.0, 1.0);
        cx.notify();
    });
    let release = cx.listener(|this, _: &gpui::MouseUpEvent, _w, cx| {
        this.live.compare.dragging = false;
        cx.notify();
    });

    let track_w = 220.0;
    let thumb_w = (track_w * visible as f32 / filled as f32)
        .max(24.0)
        .min(track_w);
    let thumb_x = app.live.compare.scroll * (track_w - thumb_w);
    let first = (app.live.compare.scroll * (filled - visible) as f32).round() as usize;

    // the canvas quietly records the track's box, so the next drag knows
    // where the track sits on screen
    let capture = cell;
    let surface = canvas(
        move |bounds, _, _| {
            *capture.borrow_mut() = Some(bounds);
            bounds
        },
        |_, _, _, _| {},
    )
    .absolute()
    .size_full();

    div()
        .flex()
        .items_center()
        .gap(px(12.0))
        .child(mono("PRODUCTS", DIM))
        .child(
            div()
                .id("cmp-slider")
                .relative()
                .w(px(track_w))
                .h(px(12.0))
                .rounded(px(6.0))
                .bg(rgb(WELL))
                .border_1()
                .border_color(rgba(HAIRLINE))
                .cursor_pointer()
                .on_mouse_down(MouseButton::Left, jump)
                .on_mouse_move(drag)
                .on_mouse_up(MouseButton::Left, release)
                .child(
                    div()
                        .absolute()
                        .top(px(1.0))
                        .left(px(1.0 + thumb_x))
                        .w(px(thumb_w - 2.0))
                        .h(px(8.0))
                        .rounded(px(4.0))
                        .bg(rgb(ICE))
                        .opacity(0.8)
                        .shadow(vec![shadow(0xbfe4ff66, 0.0, 0.0, 8.0, 0.0)]),
                )
                .child(surface),
        )
        .child(mono(
            &format!(
                "{}-{} of {}",
                first + 1,
                (first + visible).min(filled),
                filled
            ),
            MUTED,
        ))
}

/// One agent in a row of agent keys: its own mark, lit while it works.
fn agent_key(
    id: impl Into<gpui::ElementId>,
    tile_id: &str,
    agent_id: &str,
    label: &str,
    picked: bool,
    working: bool,
    motion: bool,
) -> gpui::Stateful<Div> {
    div()
        .id(id)
        .h(px(36.0))
        .pl(px(5.0))
        .pr(px(12.0))
        .flex()
        .items_center()
        .gap(px(8.0))
        .rounded(px(10.0))
        .cursor_pointer()
        .when(picked, |s| s.bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL)))
        .when(!picked, |s| s.hover(|h| h.bg(rgba(GLASS_1))))
        .child(mark_tile(
            tile_id,
            mark_for(agent_id),
            if picked && working { Phase::Thinking } else { Phase::Idle },
            26.0,
            motion,
        ))
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(if picked { ICE } else { MUTED }))
                .child(label.to_string()),
        )
}

/// Queue mode: the products queued from the browser extension, one agent
/// researching them in turn, and the researched ones handed to the slots
/// below as a new draft.
fn queue_card(app: &mut Kriko, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let c = &app.live.compare;
    let running = c.queue_running;
    let n = c.queue.len();
    let done_n = c.queue.iter().filter(|q| q.state == QState::Done).count();
    let ready_n = c
        .queue
        .iter()
        .filter(|q| q.state == QState::Done && !q.lookup_id.is_empty())
        .count();
    let left_n = n - done_n;
    let agent_name = c
        .harnesses
        .iter()
        .find(|(id, _)| *id == c.queue_harness)
        .map(|(_, label)| label.clone())
        .unwrap_or_else(|| "The agent".to_string());
    let working_id = c.queue_harness.clone();

    // ---- the agent that researches the queue ----
    let mut agent_row = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (i, (id, label)) in c.harnesses.iter().enumerate() {
        let pick = {
            let id = id.clone();
            cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                if !this.live.compare.queue_running {
                    this.live.compare.queue_harness = id.clone();
                }
                cx.notify();
            })
        };
        agent_row = agent_row.child(
            agent_key(
                ("queue-agent", i),
                &format!("queue-agent-tile-{i}"),
                id,
                label,
                *id == working_id,
                running,
                motion,
            )
            .on_click(pick),
        );
    }

    // ---- the queue itself, in research order ----
    let mut rows = div().flex().flex_col();
    for (qi, item) in c.queue.iter().enumerate() {
        let run = c.queue_run.get(&item.queue_id).cloned().unwrap_or_default();
        let phase = match item.state {
            QState::Researching => run.phase.unwrap_or(Phase::Thinking),
            QState::Done => Phase::Idle,
            QState::Waiting => Phase::Off,
        };
        let queue_id = item.queue_id.clone();
        let remove = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
            this.queue_remove(queue_id.clone(), cx);
            cx.notify();
        };
        let (state, word) = match (item.state, &run.note) {
            (QState::Researching, _) => (TagState::Live, "Researching".to_string()),
            (QState::Done, _) => (
                TagState::Done,
                match run.claims {
                    Some(k) => format!("{k} claims"),
                    None => "Researched".to_string(),
                },
            ),
            (QState::Waiting, Some(note)) if note == "not in your catalogs" => {
                (TagState::Need, "Not in catalogs".to_string())
            }
            (QState::Waiting, Some(_)) => (TagState::Need, "Passed over".to_string()),
            (QState::Waiting, None) => (TagState::Queue, "Queued".to_string()),
        };
        let status: gpui::AnyElement = match item.state {
            QState::Researching => {
                phase_beat(&format!("queue-beat-{qi}"), phase, motion).into_any_element()
            }
            _ => tag(format!("queue-tag-{qi}"), state, &word, motion).into_any_element(),
        };
        let since = live::ago(&item.added_at);
        let sub = match (item.state, &run.note) {
            (QState::Researching, _) => run.line.clone(),
            (QState::Done, _) => format!("from {} · ready to compare", item.origin),
            (QState::Waiting, Some(note)) => format!("from {} · {}", item.origin, note),
            (QState::Waiting, None) => format!("from {} · queued {}", item.origin, since),
        };
        let progress = match item.state {
            QState::Done => 100.0,
            QState::Researching => run.progress,
            QState::Waiting => 0.0,
        };
        rows = rows.child(
            div()
                .py(px(10.0))
                .flex()
                .items_center()
                .gap(px(14.0))
                .child(mono(&format!("{:02}", qi + 1), DIM))
                .child(mark_tile(
                    &format!("queue-row-tile-{qi}"),
                    mark_for(&working_id),
                    phase,
                    34.0,
                    motion,
                ))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(
                            div()
                                .font_family(SANS)
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_size(px(14.0))
                                .text_color(rgb(if item.state == QState::Waiting { INK_2 } else { INK }))
                                .child(item.title()),
                        )
                        .child(mono(&sub, MUTED)),
                )
                .child(div().w(px(150.0)).flex_none().child(meter_slim(progress, 12)))
                .child(div().w(px(132.0)).flex_none().flex().child(status))
                .child(
                    div().w(px(24.0)).flex_none().children(
                        (item.state != QState::Researching)
                            .then(|| x_button(("queue-remove", qi), cx, remove).into_any_element()),
                    ),
                ),
        );
        if qi + 1 < n {
            rows = rows.child(hairline());
        }
    }
    if n == 0 {
        rows = rows.child(div().py(px(14.0)).child(row_desc(if c.queue_loaded {
            "The queue is empty. Queue the products you are weighing up from their listings."
        } else {
            "Reading the queue..."
        })));
    }

    // ---- the keys ----
    let start = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        if this.live.compare.queue_running {
            this.queue_stop();
        } else {
            this.queue_start(cx);
        }
        cx.notify();
    });
    let to_compare = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.queue_to_compare(cx);
        cx.notify();
    });
    let clear_done = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.queue_clear_done(cx);
        cx.notify();
    });
    let auto_on = c.queue_auto;
    let auto_toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
        this.set_queue_auto(!auto_on, cx);
        cx.notify();
    });
    let overall = if n == 0 {
        0.0
    } else {
        c.queue
            .iter()
            .map(|q| match q.state {
                QState::Done => 100.0,
                QState::Researching => c.queue_run.get(&q.queue_id).map(|r| r.progress).unwrap_or(0.0),
                QState::Waiting => 0.0,
            })
            .sum::<f32>()
            / n as f32
    };
    let summary = if !c.queue_loaded {
        "reading".to_string()
    } else if running {
        format!("{agent_name} researching · {done_n} of {n} done")
    } else if n > 0 && left_n == 0 {
        format!("all {n} researched · ready to compare")
    } else if n == 0 {
        "nothing queued".to_string()
    } else {
        format!("{left_n} waiting · {done_n} researched")
    };
    let can_start = running
        || (c.queue.iter().any(|q| q.state == QState::Waiting) && !c.harnesses.is_empty());

    let keys = div()
        .flex()
        .items_center()
        .gap(px(12.0))
        .flex_wrap()
        .when(can_start, |d| {
            d.child(
                key(
                    "queue-start",
                    if running {
                        "Stop queue"
                    } else if done_n > 0 && left_n > 0 {
                        "Resume queue"
                    } else {
                        "Start queue"
                    },
                )
                .on_click(start),
            )
        })
        .when(ready_n >= 2, |d| {
            d.child(plate_s("queue-compare", &format!("Compare {ready_n} below")).on_click(to_compare))
        })
        .when(done_n > 0 && !running, |d| {
            d.child(plate_s("queue-clear", "Clear done").on_click(clear_done))
        })
        .child(div().flex_1().min_w(px(0.0)))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(mono("FILL SLOTS WHEN DONE", DIM))
                .child(switch_anim("queue-auto", auto_on, motion).on_click(auto_toggle)),
        );

    card()
        .flex()
        .flex_col()
        .gap(px(14.0))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(eyebrow("Research queue"))
                .child(div().flex_1())
                .child(mono(&summary, if running { ICE } else { MUTED })),
        )
        .child(row_desc(
            "Products you queue from the browser extension. One agent researches each in turn, sources first, then claims, and the researched ones land in the slots below to compare.",
        ))
        .child(meter_live("queue-overall", overall, 28, running, motion))
        .child(if c.harnesses.is_empty() {
            empty_note("No agent is ready on this machine. Settings shows which ones Kriko can start.")
                .into_any_element()
        } else {
            agent_row.into_any_element()
        })
        .child(
            // how a product gets here: from its listing, through the panel
            well()
                .px(px(14.0))
                .py(px(10.0))
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(icon("extension", 16.0).text_color(rgb(ICE)))
                .child(
                    div().flex_1().min_w(px(0.0)).child(row_desc(
                        "On a listing, open the Kriko panel and press Add to queue. It lands here, in the order you queued it.",
                    )),
                )
                .child(keycap("Alt"))
                .child(keycap("K")),
        )
        .child(well().px(px(14.0)).py(px(4.0)).child(rows))
        .child(keys)
}

fn question_run_detail(run: &QuestionRun) -> Div {
    let mut detail = div().pl(px(24.0)).flex().flex_col().gap(px(5.0));
    if !run.state.is_empty() {
        let stage = if run.state == "succeeded" { "Complete" }
            else if run.state == "failed" { "Failed" }
            else if run.state == "cancelled" { "Cancelled" }
            else { "In progress" };
        detail = detail.child(mono(
            &format!("{} · {:.0}% · {}", stage, (run.progress * 100.0).clamp(0.0, 100.0), run.message),
            MUTED,
        ));
    }
    if !run.saved_checks.is_empty() {
        let sources = run.saved_checks.iter()
            .map(|(name, risks)| format!("{name} ({risks} known risks)"))
            .collect::<Vec<_>>().join(" · ");
        detail = detail.child(mono(&format!("Saved checks behind answer: {sources}"), MUTED));
    } else if run.state == "succeeded" {
        detail = detail.child(mono("Saved check summary was not recorded for this answer", DIM));
    }
    if !run.steps.is_empty() {
        detail = detail.child(mono("STEPS", DIM));
        for step in &run.steps {
            detail = detail.child(mono(&format!("• {step}"), MUTED));
        }
    }
    if !run.model.is_empty() {
        detail = detail.child(mono(&format!("Model: {}", run.model), MUTED));
    } else if run.state == "succeeded" {
        detail = detail.child(mono("Model name not reported by this agent", DIM));
    }
    if run.state == "succeeded" {
        let usage = match run.tokens_used {
            Some(total) => {
                let parts = match (run.tokens_in, run.tokens_out) {
                    (Some(input), Some(output)) => format!(" ({input} in, {output} out)"),
                    _ => String::new(),
                };
                format!("{total} tokens{parts}")
            }
            None => "Token use not reported by this agent".to_string(),
        };
        let brief = run.brief_chars.map(|n| format!(" · {n} brief characters (some risks may be omitted)"))
            .unwrap_or_default();
        let search = if run.no_web_search { " · no new web search" } else { "" };
        detail = detail.child(mono(&format!("{usage}{brief}{search}"), MUTED));
    }
    detail
}

pub fn compare(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;

    // ---- drafts + the board toggle ----
    let board_toggle = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.compare.board_open = !this.live.compare.board_open;
        cx.notify();
    });
    let mut drafts_row = div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .flex_wrap()
        .child(mono("DRAFTS", DIM));
    let open_draft = app.live.compare.draft.clone();
    for (i, draft) in app.live.compare.drafts.iter().enumerate() {
        let id = draft.draft_id.clone();
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.select_draft(&id, cx);
            cx.notify();
        });
        let current = open_draft.as_deref() == Some(draft.draft_id.as_str());
        drafts_row = drafts_row.child(
            div()
                .id(("draft", i))
                .h(px(30.0))
                .px(px(12.0))
                .flex()
                .items_center()
                .rounded(px(8.0))
                .cursor_pointer()
                .font_family(MONO)
                .text_size(px(11.0))
                .when(current, |s| {
                    s.bg(rgb(WELL)).border_1().border_color(rgba(HAIRLINE)).text_color(rgb(ICE))
                })
                .when(!current, |s| {
                    s.text_color(rgb(MUTED)).hover(|h| h.bg(rgba(GLASS_1)).text_color(rgb(INK)))
                })
                .child(draft.name.clone())
                .on_click(pick),
        );
    }
    if !app.live.compare.drafts_loaded {
        drafts_row = drafts_row.child(mono("reading", DIM));
    } else if app.live.compare.drafts.is_empty() {
        drafts_row = drafts_row.child(mono("none saved yet", DIM));
    }
    let new_draft = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.new_draft(cx);
        cx.notify();
    });
    let save_draft = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.save_draft(cx);
        cx.notify();
    });
    let delete_draft = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.delete_draft(cx);
        cx.notify();
    });
    let unsaved = app.draft_unsaved();
    drafts_row = drafts_row
        .child(plate_s("draft-new", "+ New").on_click(new_draft))
        .child(plate_s("draft-save", "Save").on_click(save_draft))
        .when(open_draft.is_some(), |d| {
            d.child(plate_s("draft-delete", "Delete").on_click(delete_draft))
        })
        .when(unsaved, |d| d.child(mono("UNSAVED SLOTS", DIM)))
        .child(div().flex_1().min_w(px(0.0)))
        .child(
            div()
                .id("draft-board")
                .h(px(36.0))
                .px(px(14.0))
                .flex()
                .items_center()
                .gap(px(8.0))
                .rounded(px(10.0))
                .cursor_pointer()
                .font_family(MONO)
                .text_size(px(12.0))
                .when(app.live.compare.board_open, |s| {
                    s.bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL)).text_color(rgb(ICE))
                })
                .when(!app.live.compare.board_open, |s| {
                    s.text_color(rgb(MUTED)).hover(|h| h.bg(rgba(GLASS_1)).text_color(rgb(INK)))
                })
                .child(icon("check", 14.0).text_color(rgb(if app.live.compare.board_open {
                    ICE
                } else {
                    MUTED
                })))
                .child("BOARD")
                .on_click(board_toggle),
        );

    // ---- the slots: at least two, one trailing empty, eight at most ----
    let mut slots: Vec<Option<String>> = app.live.compare.slots.clone();
    while slots.len() < 2 {
        slots.push(None);
    }
    if slots.len() < MAX_SLOTS {
        slots.push(None);
    }
    // how many sources stand behind each product's knowledge, against the
    // best-read product on the board
    let best_read = slots
        .iter()
        .filter_map(|s| check_in(app, s))
        .map(|c| c.sources())
        .max()
        .unwrap_or(1)
        .max(1);
    let mut slot_row = div().flex().items_start().gap(px(12.0)).flex_wrap();
    for (i, slot) in slots.iter().take(MAX_SLOTS).enumerate() {
        let open_picker = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.compare.picker = if this.live.compare.picker == Some(i) { None } else { Some(i) };
            cx.notify();
        });
        let clear_slot = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
            this.clear_slot(i);
            cx.notify();
        };
        let label = ["FIRST", "SECOND", "THIRD", "FOURTH", "FIFTH", "SIXTH", "SEVENTH", "EIGHTH"][i];
        let mut col = well()
            .id(("slot", i))
            .flex_1()
            .min_w(px(190.0))
            .p(px(12.0))
            .flex()
            .flex_col()
            .gap(px(8.0))
            .cursor_pointer()
            .on_click(open_picker)
            .child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(mono(label, DIM))
                    .child(div().flex_1())
                    .children(slot.as_ref().map(|_| x_button(("slot-clear", i), cx, clear_slot).into_any_element())),
            );
        col = match slot.as_ref().map(|id| (id, app.live.compare.checks.get(id))) {
            Some((_, Some(Loaded::Ready(check)))) => {
                let sources = check.sources();
                let rating = sources as f32 / best_read as f32 * 100.0;
                col.child(
                    div()
                        .min_w(px(0.0))
                        .font_family(SANS)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(15.0))
                        .text_color(rgb(INK))
                        .child(check.name.clone()),
                )
                .child(mono(
                    if check.category.is_empty() { "no catalog matched" } else { check.category.as_str() },
                    MUTED,
                ))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(mono("INFO", DIM))
                        .child(meter_slim(rating, 10).flex_1()),
                )
                .child(mono(&format!("{sources} sources · vs the best-read here"), MUTED))
            }
            Some((id, Some(Loaded::Missing(why)))) => col
                .child(mono("NOT FOUND", DIM))
                .child(row_desc(&format!("The saved check {id} could not be read: {why}"))),
            Some((id, _)) => {
                let name = app
                    .live
                    .compare
                    .history
                    .iter()
                    .find(|h| h.lookup_id == *id)
                    .map(|h| h.label.clone())
                    .unwrap_or_else(|| "Reading the saved check".to_string());
                col.child(
                    div()
                        .font_family(SANS)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(15.0))
                        .text_color(rgb(INK_2))
                        .child(name),
                )
                .child(mono("reading...", DIM))
            }
            None => col.child(
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(icon("plus", 14.0).text_color(rgb(DIM)))
                    .child(
                        div()
                            .font_family(SANS)
                            .text_size(px(14.0))
                            .text_color(rgb(DIM))
                            .child(if i < 2 { "choose a check" } else { "add another" }),
                    ),
            ),
        };
        slot_row = slot_row.child(col);
    }

    // ---- the picker: every saved check, one click to assign ----
    let picker_card = app.live.compare.picker.map(|slot_i| {
        let mut list = div().flex().flex_col().flex_none();
        for (ci, item) in app.live.compare.history.iter().enumerate() {
            let taken = slots.contains(&Some(item.lookup_id.clone()));
            let lookup_id = item.lookup_id.clone();
            let assign = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.assign_slot(slot_i, lookup_id.clone(), cx);
                cx.notify();
            });
            list = list.child(
                div()
                    .id(("pick", ci))
                    .py(px(8.0))
                    .px(px(12.0))
                    .flex()
                    .items_center()
                    .gap(px(12.0))
                    .rounded(px(10.0))
                    .cursor_pointer()
                    .when(!taken, |s| s.hover(|h| h.bg(rgba(GLASS_1))))
                    .when(taken, |s| s.opacity(0.35))
                    .on_click(assign)
                    .child(
                        div().flex_1().min_w(px(0.0)).flex().flex_col().child(
                            div()
                                .font_family(SANS)
                                .text_size(px(13.0))
                                .text_color(rgb(if taken { MUTED } else { INK }))
                                .child(item.label.clone()),
                        ),
                    )
                    .child(mono(
                        &if item.category.is_empty() {
                            live::ago(&item.created_at)
                        } else {
                            format!("{} · {}", item.category, live::ago(&item.created_at))
                        },
                        MUTED,
                    )),
            );
        }
        let body: gpui::AnyElement = if !app.live.compare.history_loaded {
            empty_note("Reading your saved checks...").into_any_element()
        } else if app.live.compare.history.is_empty() {
            empty_note("No saved checks yet. Run a check, or use the extension on a listing, and it will be here.")
                .into_any_element()
        } else {
            div()
                .id("picker-scroll")
                .max_h(px(260.0))
                .overflow_y_scroll().occlude()
                .flex()
                .flex_col()
                .child(list)
                .into_any_element()
        };
        card()
            .flex()
            .flex_col()
            .gap(px(4.0))
            .child(eyebrow("Pick a saved check"))
            .child(hairline())
            .child(body)
    });

    // ---- the answer, said from the lined-up data ----
    let ready: Vec<Option<&Check>> = app
        .live
        .compare
        .slots
        .iter()
        .flatten()
        .map(|id| match app.live.compare.checks.get(id) {
            Some(Loaded::Ready(c)) => Some(c),
            _ => None,
        })
        .collect();
    let said = live::answer_lines(&ready);
    let answer_card = (!said.is_empty()).then(|| {
        let mut lines = div().flex().flex_col().gap(px(6.0));
        for line in said {
            lines = lines.child(
                div()
                    .font_family(SANS)
                    .text_size(px(14.0))
                    .line_height(px(21.0))
                    .text_color(rgb(INK_2))
                    .child(line),
            );
        }
        card()
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(eyebrow("What the lined-up data says"))
            .child(lines)
            .child(mono("COUNTED FROM THE COLUMNS BELOW · NOT A RANKING", DIM))
    });

    // ---- the agent: which one answers, and the saved checks it reads ----
    let spec_n = live::spec_rows(&ready).len();
    let risk_n = live::risk_rows(&ready).len();
    let attached = format!(
        "saved checks: {} · {} spec rows · {} known risks",
        ready.iter().flatten().count(),
        spec_n,
        risk_n,
    );
    let waiting_answer = app.live.compare.asking || app.live.compare.questions.iter().any(|q| q.answer.is_none() && !app.live.compare.failed.contains_key(&q.question_id));
    let mut agent_row = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (ai, (id, label)) in app.live.compare.harnesses.iter().enumerate() {
        let pick = {
            let id = id.clone();
            cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.compare.harness = id.clone();
                cx.notify();
            })
        };
        agent_row = agent_row.child(
            agent_key(
                ("cmp-agent", ai),
                &format!("cmp-agent-tile-{ai}"),
                id,
                label,
                *id == app.live.compare.harness,
                waiting_answer,
                motion,
            )
            .on_click(pick),
        );
    }
    // The local model is one of the engine's agent rows now (`/api/prefs`
    // lists it when its server holds a model), so it is picked above like
    // any agent, never drawn twice.

    // ---- follow-up questions ----
    let ask_input = app.input_field(
        Field::CompareAsk,
        "compare-ask",
        "Ask about this shortlist...",
        Some("agents"),
        window,
        cx,
    );
    let ask = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.ask_compare_question(cx);
        cx.notify();
    });
    let mut suggestions = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (i, text) in crate::data::COMPARE_SUGGESTIONS.iter().enumerate() {
        let fill = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.compare_question_input.set_value(text.to_string());
            cx.notify();
        });
        suggestions = suggestions.child(
            div()
                .id(("sugg", i))
                .h(px(30.0))
                .px(px(12.0))
                .flex()
                .items_center()
                .rounded(px(8.0))
                .cursor_pointer()
                .bg(rgb(WELL))
                .border_1()
                .border_color(rgba(HAIRLINE))
                .hover(|s| s.border_color(rgba(BORDER_CONTROL)))
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(INK_2))
                .child(text.to_string())
                .on_click(fill),
        );
    }
    let draft_name = app
        .live
        .compare
        .draft
        .as_ref()
        .and_then(|id| app.live.compare.drafts.iter().find(|d| d.draft_id == *id))
        .map(|d| d.name.clone())
        .unwrap_or_default();
    let mut questions = div().flex().flex_col().gap(px(10.0));
    let saved_questions = app.live.compare.questions.clone();
    for (qi, q) in saved_questions.iter().enumerate() {
        let failure = app.live.compare.failed.get(&q.question_id);
        let run = app.live.compare.question_runs.get(&q.job_id);
        questions = questions.child(
            well()
                .p(px(14.0))
                .flex()
                .flex_col()
                .gap(px(8.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(10.0))
                        .child(icon("agents", 14.0).text_color(rgb(BRAND_BRIGHT)))
                        .child(
                            div()
                                .min_w(px(0.0))
                                .font_family(SANS)
                                .font_weight(FontWeight::SEMIBOLD)
                                .text_size(px(14.0))
                                .text_color(rgb(INK))
                                .child(q.text.clone()),
                        ),
                )
                .child(match (&q.answer, failure) {
                    (Some(a), _) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(div().flex().items_center().gap(px(8.0)).child(tag(
                            format!("compare-answered-{qi}"),
                            TagState::Done,
                            "answered",
                            motion,
                        )))
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .line_height(px(21.0))
                                .text_color(rgb(INK_2))
                                .child(a.clone()),
                        ),
                    (None, Some(why)) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(div().flex().items_center().gap(px(8.0)).child(tag(
                            format!("compare-failed-{qi}"),
                            TagState::Need,
                            "no answer",
                            motion,
                        )))
                        .child(row_desc(why)),
                    (None, None) if run.is_some_and(|r| r.state == "succeeded") => div()
                        .pl(px(24.0))
                        .child(tag(format!("compare-empty-{qi}"), TagState::Need,
                            "no text returned", motion)),
                    (None, None) => div()
                        .pl(px(24.0))
                        .flex()
                        .flex_col()
                        .gap(px(6.0))
                        .child(div().flex().items_center().gap(px(8.0)).child(tag(
                            format!("compare-asking-{qi}"),
                            TagState::Live,
                            "answering",
                            motion,
                        ))),
                })
                .children(run.map(question_run_detail))
                .child(mono(
                    &format!(
                        "kept with {} · asked {}",
                        if draft_name.is_empty() { "this draft" } else { draft_name.as_str() },
                        live::ago(&q.asked_at)
                    ),
                    DIM,
                )),
        );
    }
    for q in &saved_questions {
        if let Some(job) = app.live.run.jobs.iter().find(|job| job.id == q.job_id).cloned() {
            questions = questions.child(crate::screens::logs::job_logs(app, &job, cx));
        }
    }

    let questions_card = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Ask about this comparison"))
        .child(row_desc(
            "Ask from the saved checks in these slots. The local model reads a short, relevant brief without searching the web. Asking saves the slots to this draft first.",
        ))
        .child(if app.live.compare.harnesses.is_empty() {
            let open_local = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                this.tab = Tab::Local;
                cx.notify();
            });
            div().flex().items_center().gap(px(12.0))
                .child(empty_note("No agent or local model is ready."))
                .child(ghost("compare-open-local", "Set up Local LLM").on_click(open_local))
                .into_any_element()
        } else {
            agent_row.into_any_element()
        })
        .child(div().font_family(MONO).text_size(px(11.0)).text_color(rgb(MUTED)).child(attached))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .flex_wrap()
                .child(div().flex_1().min_w(px(260.0)).child(ask_input))
                .child(key("cmp-ask", if app.live.compare.asking { "Asking..." } else { "Ask" }).on_click(ask)),
        )
        .child(suggestions)
        .child(questions);

    // ---- assemble ----
    // The board sits directly under the toggle that opens it, so it is on
    // screen the moment it appears, with the slots above the table below.
    let mut page = div().flex().flex_col().gap(px(20.0)).child(drafts_row);
    if let Some(say) = app.live.compare.say.clone() {
        page = page.child(
            div()
                .font_family(MONO)
                .text_size(px(12.0))
                .text_color(rgb(DANGER))
                .child(say),
        );
    }
    page = page.child(queue_card(app, cx)).children(picker_card);
    if app.live.compare.board_open {
        page = page.child(board(app, window, cx));
    }
    page = page.child(slot_row);
    // the slider appears once the shortlist outgrows the screen
    let filled_n = app.live.compare.slots.iter().flatten().count();
    if filled_n > 3 {
        page = page.child(column_slider(app, filled_n, 3, cx));
    }
    page = page.children(answer_card);
    page = page
        .child(
            div()
                .id("compare-table-scroll")
                .overflow_x_scroll().map(horizontal_wheel)
                .child(table(app, window, cx).min_w(px(860.0))),
        )
        .child(questions_card);
    page
}
