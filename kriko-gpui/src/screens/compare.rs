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

use crate::app::{CompareNote, Field, Kriko, QueueState};
use crate::data::{self, CompareSubject, RiskCell, SpecCell};
use crate::screens::{mono, plate_s, row_desc, severity_chip, th, trust_icon};
use crate::marks::{mark_tile, phase_beat, Phase};
use crate::theme::*;

/// The subject data for a check, or None when nothing is known about it.
fn subject_for(check: usize) -> Option<&'static CompareSubject> {
    data::COMPARE_SUBJECTS.iter().find(|s| s.check == check)
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
            if this.compare_board_tool == 0 {
                this.compare_drawing = true;
                this.compare_stroke_current = vec![(x, y)];
            } else {
                this.compare_notes.push(CompareNote {
                    x,
                    y,
                    text: String::new(),
                });
                let open = this.compare_notes.len() - 1;
                this.compare_note_open = Some(open);
                this.compare_note_input.value.clear();
            }
            cx.notify();
        },
    );

    let move_cell = bounds_cell.clone();
    let on_move = cx.listener(move |this, event: &gpui::MouseMoveEvent, _w, cx| {
        if !this.compare_drawing || this.compare_board_tool != 0 {
            return;
        }
        let bounds = move_cell.borrow().unwrap_or_default();
        if bounds.size.width <= px(0.0) || bounds.size.height <= px(0.0) {
            return;
        }
        let (x, y) = board_point(bounds, event.position);
        let len = this.compare_stroke_current.len();
        let moved = len == 0 || {
            let last = this.compare_stroke_current[len - 1];
            (last.0 - x).abs() > 0.002 || (last.1 - y).abs() > 0.002
        };
        if moved {
            this.compare_stroke_current.push((x, y));
            cx.notify();
        }
    });

    let on_up = cx.listener(|this, _: &gpui::MouseUpEvent, _w, cx| {
        if this.compare_drawing {
            this.compare_drawing = false;
            if this.compare_stroke_current.len() > 1 {
                let stroke = std::mem::take(&mut this.compare_stroke_current);
                this.compare_strokes.push(stroke);
            } else {
                this.compare_stroke_current.clear();
            }
            cx.notify();
        }
    });

    let undo = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.compare_strokes.pop();
        cx.notify();
    });
    let clear = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.compare_strokes.clear();
        this.compare_notes.clear();
        this.compare_note_open = None;
        cx.notify();
    });
    let close = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.compare_board_open = false;
        cx.notify();
    });

    let pick_tool = |i: usize| {
        cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.compare_board_tool = i;
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
            tool_chip("board-pen", "check", "PEN", app.compare_board_tool == 0)
                .on_click(pick_tool(0)),
        )
        .child(
            tool_chip("board-note", "plus", "NOTE", app.compare_board_tool == 1)
                .on_click(pick_tool(1)),
        )
        .child(plate_s("board-undo", "Undo mark").on_click(undo))
        .child(plate_s("board-clear", "Clear").on_click(clear))
        .child(plate_s("board-close", "Close").on_click(close));

    // The canvas that paints every stroke: fractions land wherever the
    // board is drawn now, never where the pen happened to be.
    let mut strokes: Vec<Vec<(f32, f32)>> = app.compare_strokes.clone();
    strokes.push(app.compare_stroke_current.clone());
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
        if app.compare_board_tool == 0 {
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
    let notes: Vec<CompareNote> = app.compare_notes.clone();
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
        let open = app.compare_note_open == Some(i);
        let open_note = cx.listener(move |this, _: &gpui::ClickEvent, window, cx| {
            if i >= this.compare_notes.len() {
                return;
            }
            this.compare_note_open = Some(i);
            this.compare_note_input.value = this.compare_notes[i].text.clone();
            let handle = this.compare_note_input.handle.clone();
            window.focus(&handle);
            cx.notify();
        });
        let remove_note = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
            if this.compare_note_open == Some(i) {
                this.compare_note_open = None;
            }
            if i < this.compare_notes.len() {
                this.compare_notes.remove(i);
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

// ---- the table ----

/// Every spec label any chosen subject carries, first-seen order.
fn spec_rows(
    subjects: &[Option<&'static CompareSubject>],
) -> Vec<(&'static str, Vec<Option<SpecCell>>)> {
    let mut labels: Vec<&'static str> = Vec::new();
    for subject in subjects.iter().flatten() {
        for (label, _) in subject.specs {
            if !labels.contains(label) {
                labels.push(label);
            }
        }
    }
    labels
        .into_iter()
        .map(|label| {
            let cells = subjects
                .iter()
                .map(|subject| {
                    subject
                        .and_then(|s| s.specs.iter().find(|(l, _)| *l == label))
                        .map(|(_, cells)| cells[0])
                })
                .collect();
            (label, cells)
        })
        .collect()
}

/// Every risk title any chosen subject carries, first-seen order.
fn risk_rows(
    subjects: &[Option<&'static CompareSubject>],
) -> Vec<(&'static str, Vec<Option<RiskCell>>)> {
    let mut labels: Vec<&'static str> = Vec::new();
    for subject in subjects.iter().flatten() {
        for (label, _) in subject.risks {
            if !labels.contains(label) {
                labels.push(label);
            }
        }
    }
    labels
        .into_iter()
        .map(|label| {
            let cells = subjects
                .iter()
                .map(|subject| {
                    subject
                        .and_then(|s| s.risks.iter().find(|(l, _)| *l == label))
                        .map(|(_, cells)| cells[0])
                })
                .collect();
            (label, cells)
        })
        .collect()
}

/// The grounded claims each subject carries, aligned by position: row i
/// holds every subject's i-th claim with the source it was read from.
fn claim_rows(
    subjects: &[Option<&'static CompareSubject>],
) -> Vec<Vec<Option<(&'static str, &'static str)>>> {
    let max = subjects
        .iter()
        .flatten()
        .map(|s| data::evidence_for(&data::CHECKS[s.check]).claims.len())
        .max()
        .unwrap_or(0);
    (0..max)
        .map(|i| {
            subjects
                .iter()
                .map(|subject| {
                    subject.and_then(|s| {
                        data::evidence_for(&data::CHECKS[s.check])
                            .claims
                            .get(i)
                            .copied()
                    })
                })
                .collect()
        })
        .collect()
}

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

/// The compare table: one column per slot, sections for specs and risks,
/// one section and one detail row open at a time.
fn table(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let slots: Vec<Option<usize>> = app.compare_slots.clone();
    // the column window: three products at a time when many are lined
    // up, scrubbed by the slider that sits above the table
    let filled: Vec<usize> = slots.iter().flatten().copied().collect();
    let visible = filled.len().min(3);
    let first = if filled.len() > visible {
        (app.compare_scroll * (filled.len() - visible) as f32).round() as usize
    } else {
        0
    };
    let slots: Vec<Option<usize>> = if filled.len() > visible {
        filled[first..first + visible]
            .iter()
            .map(|c| Some(*c))
            .collect()
    } else {
        slots
    };
    let subjects: Vec<Option<&'static CompareSubject>> =
        slots.iter().map(|s| (*s).and_then(subject_for)).collect();
    let specs = spec_rows(&subjects);
    let risks = risk_rows(&subjects);
    let col_w = px(190.0);

    // The header: the attribute column, then one per slot.
    let mut head = div()
        .flex()
        .items_center()
        .pb(px(10.0))
        .child(div().flex_1().min_w(px(150.0)).child(th("Attribute")));
    for slot in &slots {
        let label = slot
            .map(|c| data::CHECKS[c].name.to_uppercase())
            .unwrap_or_else(|| "EMPTY SLOT".to_string());
        head = head.child(
            div().w(col_w).min_w(px(0.0)).child(
                div()
                    .font_family(MONO)
                    .text_size(px(11.0))
                    .text_color(rgb(if slot.is_some() { DIM } else { LED_OFF }))
                    .child(label),
            ),
        );
    }

    let mut body = card().flex().flex_col().child(head).child(hairline());
    let section = app.compare_section;

    // ---- the specs section ----
    let open_specs = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.compare_section = 0;
        this.compare_detail = None;
        cx.notify();
    });
    let open_risks = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.compare_section = 1;
        this.compare_detail = None;
        cx.notify();
    });
    let specs_label = format!("Specifications ({})", specs.len());
    let risks_label = format!("Known risks ({})", risks.len());
    body = body.child(
        section_head(
            "cmp-specs",
            specs_label.as_str(),
            "layers",
            section == 0,
            cx,
        )
        .on_click(open_specs),
    );

    if section == 0 {
        for (ri, (label, cells)) in specs.iter().enumerate() {
            let differs = {
                let vals: Vec<&str> = cells.iter().filter_map(|c| c.map(|c| c.value)).collect();
                vals.len() > 1 && vals.windows(2).any(|w| w[0] != w[1])
            };
            let detail = app.compare_detail == Some((0, ri));
            let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.compare_detail = if this.compare_detail == Some((0, ri)) {
                    None
                } else {
                    Some((0, ri))
                };
                cx.notify();
            });
            let marked = app.compare_marks.contains(&(0, ri));
            let pin = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
                if this.compare_marks.contains(&(0, ri)) {
                    this.compare_marks.retain(|m| *m != (0, ri));
                } else {
                    this.compare_marks.push((0, ri));
                }
                cx.notify();
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
                                .child(label.to_string()),
                        )
                        .when(differs, |d| {
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
                        .when(marked, |d| {
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
                                    .child("PREFERRED"),
                            )
                        }),
                );
            for cell in cells {
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
                                .child(c.value.to_string()),
                        )
                        .child(trust_icon(c.backed)),
                    None => div().w(col_w).child(mono("Not recorded", DIM)),
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
                for (ci, cell) in cells.iter().enumerate() {
                    let name = slots
                        .get(ci)
                        .and_then(|s| *s)
                        .map(|c| data::CHECKS[c].name)
                        .unwrap_or("Empty slot");
                    let line = match cell {
                        Some(c) => format!("{}: {} source(s) on record.", name, c.sources),
                        None => format!("{}: no installed catalog holds this attribute.", name),
                    };
                    d = d.child(
                        div()
                            .pl(px(14.0))
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .child(match cell {
                                Some(c) => trust_icon(c.backed),
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
            body = body.child(row_desc("No specifications recorded for this shortlist."));
        }
    }

    // ---- the risks section ----
    body = body.child(hairline());
    body = body.child(
        section_head(
            "cmp-risks",
            risks_label.as_str(),
            "check",
            section == 1,
            cx,
        )
        .on_click(open_risks),
    );

    if section == 1 {
        for (ri, (label, cells)) in risks.iter().enumerate() {
            let detail = app.compare_detail == Some((1, ri));
            let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.compare_detail = if this.compare_detail == Some((1, ri)) {
                    None
                } else {
                    Some((1, ri))
                };
                cx.notify();
            });
            let any = cells.iter().any(|c| c.is_some());
            let mut row = div()
                .id(("risk-row", ri))
                .py(px(11.0))
                .flex()
                .items_center()
                .cursor_pointer()
                .hover(|s| s.bg(rgba(GLASS_1)))
                .on_click(toggle)
                .child(
                    div()
                        .flex_1()
                        .min_w(px(150.0))
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(14.0))
                                .text_color(rgb(if detail { ICE } else { INK }))
                                .child(label.to_string()),
                        ),
                );
            for cell in cells {
                let cell_div = match cell {
                    Some(c) => div().w(col_w).min_w(px(0.0)).flex().items_center().child(
                        match c.severity {
                            Some(sev) => severity_chip(sev),
                            None => mono("None", DIM),
                        },
                    ),
                    None => div().w(col_w).child(mono("Not recorded", DIM)),
                };
                row = row.child(cell_div);
            }
            body = body.child(row);
            if detail {
                let mut d = div()
                    .pl(px(8.0))
                    .py(px(10.0))
                    .flex()
                    .flex_col()
                    .gap(px(6.0))
                    .child(row_desc("The evidence behind each word:"));
                for (ci, cell) in cells.iter().enumerate() {
                    let name = slots
                        .get(ci)
                        .and_then(|s| *s)
                        .map(|c| data::CHECKS[c].name)
                        .unwrap_or("Empty slot");
                    if let Some(c) = cell {
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
                                        .child(match c.severity {
                                            Some(sev) => {
                                                severity_chip(sev).into_any_element()
                                            }
                                            None => led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0),
                                        })
                                        .child(mono(name, MUTED)),
                                )
                                .child(row_desc(c.body))
                                .child(mono(
                                    &format!("{} source(s) on record.", c.sources),
                                    DIM,
                                )),
                        );
                    }
                }
                if !any {
                    d = d.child(row_desc("Nothing recorded against any of them."));
                }
                body = body.child(well().p(px(12.0)).mb(px(6.0)).child(d));
            }
            if ri + 1 < risks.len() {
                body = body.child(hairline());
            }
        }
        if risks.is_empty() {
            body = body.child(row_desc("No known risks recorded for this shortlist."));
        }
    }

    // ---- the knowledge section: the claims each product is grounded on ----
    let claims = claim_rows(&subjects);
    let claims_label = format!("Knowledge ({})", claims.len());
    let open_knowledge = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.compare_section = 2;
        this.compare_detail = None;
        cx.notify();
    });
    body = body.child(hairline());
    body = body.child(
        section_head(
            "cmp-knowledge",
            claims_label.as_str(),
            "database",
            section == 2,
            cx,
        )
        .on_click(open_knowledge),
    );

    if section == 2 {
        // clicking a claim marks it as preferred — the knowledge you care
        // about joins what the agent reads off the board
        for (ri, cells) in claims.iter().enumerate() {
            let marked = app.compare_marks.contains(&(2, ri));
            let mark = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                if this.compare_marks.contains(&(2, ri)) {
                    this.compare_marks.retain(|m| *m != (2, ri));
                } else {
                    this.compare_marks.push((2, ri));
                }
                cx.notify();
            });
            let mut row = div()
                .id(("knowledge-row", ri))
                .py(px(11.0))
                .flex()
                .items_center()
                .cursor_pointer()
                .when(marked, |s| s.bg(rgba(BRAND_WASH)))
                .hover(|s| s.bg(rgba(GLASS_1)))
                .on_click(mark)
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
                                .text_color(rgb(if marked { ICE } else { INK }))
                                .child(format!("Grounded claim {}", ri + 1)),
                        )
                        .when(marked, |d| {
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
                                    .child("PREFERRED"),
                            )
                        }),
                );
            for cell in cells {
                let cell_div = match cell {
                    Some((claim, source)) => div()
                        .w(col_w)
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(
                            div()
                                .font_family(SANS)
                                .text_size(px(13.0))
                                .text_color(rgb(INK_2))
                                .child(claim.to_string()),
                        )
                        .child(mono(source, DIM)),
                    None => div().w(col_w).child(mono("No claim grounded", DIM)),
                };
                row = row.child(cell_div);
            }
            body = body.child(row);
            if ri + 1 < claims.len() {
                body = body.child(hairline());
            }
        }
        if claims.is_empty() {
            body = body.child(row_desc("No claims grounded for this shortlist."));
        }
    }

    body
}

/// One section header: the icon, the label, and the open state.
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
        this.compare_dragging = true;
        this.compare_scroll = (f32::from(ev.position.x - bounds.origin.x)
            / f32::from(bounds.size.width))
            .clamp(0.0, 1.0);
        cx.notify();
    });
    let drag_cell = cell.clone();
    let drag = cx.listener(move |this, ev: &gpui::MouseMoveEvent, _w, cx| {
        if !this.compare_dragging {
            return;
        }
        let bounds = drag_cell.borrow().unwrap_or_default();
        if bounds.size.width <= px(0.0) {
            return;
        }
        this.compare_scroll = (f32::from(ev.position.x - bounds.origin.x)
            / f32::from(bounds.size.width))
            .clamp(0.0, 1.0);
        cx.notify();
    });
    let release = cx.listener(|this, _: &gpui::MouseUpEvent, _w, cx| {
        this.compare_dragging = false;
        cx.notify();
    });

    let track_w = 220.0;
    let thumb_w = (track_w * visible as f32 / filled as f32)
        .max(24.0)
        .min(track_w);
    let thumb_x = app.compare_scroll * (track_w - thumb_w);
    let first = (app.compare_scroll * (filled - visible) as f32).round() as usize;

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

/// What the queue's agent is doing at `progress` percent through a product:
/// reading its pages, then weighing them, then writing the claims.
fn queue_phase(progress: f32) -> Phase {
    if progress < 40.0 {
        Phase::Reading
    } else if progress < 75.0 {
        Phase::Thinking
    } else {
        Phase::Writing
    }
}

/// Queue mode: a few products lined up, one agent researching them in turn,
/// and the researched ones handed to the slots below as a new draft.
fn queue_card(app: &mut Kriko, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;
    let running = app.queue_running;
    let done_n = app.queue.iter().filter(|q| q.state == QueueState::Done).count();
    let left_n = app.queue.len() - done_n;

    // ---- the agent that researches the queue ----
    let mut agent_row = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (i, agent) in data::AGENTS.iter().enumerate() {
        let usable = app.agent_allowed.get(i).copied().unwrap_or(agent.allowed)
            && matches!(agent.state, TagState::Live | TagState::Done);
        if !usable {
            continue;
        }
        let picked = app.queue_agent == i;
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            if !this.queue_running {
                this.queue_agent = i;
            }
            cx.notify();
        });
        agent_row = agent_row.child(
            div()
                .id(("queue-agent", i))
                .h(px(36.0))
                .pl(px(5.0))
                .pr(px(12.0))
                .flex()
                .items_center()
                .gap(px(8.0))
                .rounded(px(10.0))
                .cursor_pointer()
                .when(picked, |s| {
                    s.bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL))
                })
                .when(!picked, |s| s.hover(|h| h.bg(rgba(GLASS_1))))
                .child(mark_tile(
                    &format!("queue-agent-tile-{i}"),
                    agent.mark,
                    if picked && running { Phase::Thinking } else { Phase::Idle },
                    26.0,
                    motion,
                ))
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(11.0))
                        .text_color(rgb(if picked { ICE } else { MUTED }))
                        .child(agent.name.to_string()),
                )
                .on_click(pick),
        );
    }

    // ---- the queue itself, in research order ----
    let mut rows = div().flex().flex_col();
    let agent = &data::AGENTS[app.queue_agent];
    let n = app.queue.len();
    for (qi, item) in app.queue.iter().enumerate() {
        let check = &data::CHECKS[item.check];
        let phase = match item.state {
            QueueState::Researching => queue_phase(item.progress),
            QueueState::Done => Phase::Idle,
            QueueState::Waiting => Phase::Off,
        };
        let remove = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
            if qi < this.queue.len() && this.queue[qi].state != QueueState::Researching {
                this.queue.remove(qi);
            }
            cx.notify();
        };
        let (state, word) = match item.state {
            QueueState::Waiting => (TagState::Queue, "Queued".to_string()),
            QueueState::Researching => (TagState::Live, "Researching".to_string()),
            QueueState::Done => (TagState::Done, format!("{} claims", item.claims)),
        };
        let status: gpui::AnyElement = match item.state {
            QueueState::Researching => phase_beat(&format!("queue-beat-{qi}"), phase, motion)
                .into_any_element(),
            _ => tag(format!("queue-tag-{qi}"), state, &word, motion).into_any_element(),
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
                    agent.mark,
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
                                .text_color(rgb(if item.state == QueueState::Waiting {
                                    INK_2
                                } else {
                                    INK
                                }))
                                .child(check.name.to_string()),
                        )
                        .child(mono(
                            &match item.state {
                                QueueState::Researching => match phase {
                                    Phase::Reading => format!("reading sources for {}", check.pack),
                                    Phase::Thinking => "weighing what the sources agree on".to_string(),
                                    _ => "writing claims to the store".to_string(),
                                },
                                QueueState::Done => format!("from {} · ready to compare", item.origin),
                                QueueState::Waiting => format!("from {} · waiting its turn", item.origin),
                            },
                            MUTED,
                        )),
                )
                .child(
                    div()
                        .w(px(150.0))
                        .flex_none()
                        .child(meter_slim(item.progress, 12)),
                )
                .child(div().w(px(132.0)).flex_none().flex().child(status))
                .child(
                    div()
                        .w(px(24.0))
                        .flex_none()
                        .children((item.state != QueueState::Researching).then(|| {
                            x_button(("queue-remove", qi), cx, remove).into_any_element()
                        })),
                ),
        );
        if qi + 1 < n {
            rows = rows.child(hairline());
        }
    }
    if n == 0 {
        rows = rows.child(
            div()
                .py(px(14.0))
                .child(row_desc("The queue is empty. Queue the products you are weighing up from their listings.")),
        );
    }

    // ---- the keys ----
    let start = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        if this.queue_running {
            this.queue_running = false;
            for q in this.queue.iter_mut() {
                if q.state == QueueState::Researching {
                    q.state = QueueState::Waiting;
                    q.progress = 0.0;
                }
            }
            cx.notify();
        } else {
            this.queue_start(cx);
        }
    });
    let to_compare = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.queue_to_compare();
        cx.notify();
    });
    let clear_done = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.queue.retain(|q| q.state != QueueState::Done);
        cx.notify();
    });
    let auto_toggle = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.queue_auto = !this.queue_auto;
        cx.notify();
    });
    let overall = if n == 0 {
        0.0
    } else {
        app.queue.iter().map(|q| q.progress).sum::<f32>() / n as f32
    };
    let summary = if running {
        format!("{} researching · {done_n} of {n} done", agent.name)
    } else if n > 0 && left_n == 0 {
        format!("all {n} researched · ready to compare")
    } else {
        format!("{left_n} waiting · {done_n} researched")
    };

    let keys = div()
        .flex()
        .items_center()
        .gap(px(12.0))
        .flex_wrap()
        .child(
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
        .when(done_n >= 2, |d| {
            d.child(plate_s("queue-compare", &format!("Compare {done_n} below")).on_click(to_compare))
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
                .child(switch_anim("queue-auto", app.queue_auto, motion).on_click(auto_toggle)),
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
        .child(agent_row)
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
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .child(row_desc("On a listing, open the Kriko panel and press Add to queue. It lands here, in the order you queued it.")),
                )
                .child(keycap("Alt"))
                .child(keycap("K")),
        )
        .child(well().px(px(14.0)).py(px(4.0)).child(rows))
        .child(keys)
}

pub fn compare(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = !app.reduce_motion;

    // ---- drafts + the board toggle ----
    let board_toggle = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.compare_board_open = !this.compare_board_open;
        cx.notify();
    });
    let mut drafts_row = div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .flex_wrap()
        .child(mono("DRAFTS", DIM));
    for (i, draft) in app.compare_drafts.iter().enumerate() {
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.compare_draft = i;
            this.compare_slots = this.compare_drafts[i].slots.clone();
            this.compare_detail = None;
            cx.notify();
        });
        let current = app.compare_draft == i;
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
                    s.bg(rgb(WELL))
                        .border_1()
                        .border_color(rgba(HAIRLINE))
                        .text_color(rgb(ICE))
                })
                .when(!current, |s| {
                    s.text_color(rgb(MUTED))
                        .hover(|h| h.bg(rgba(GLASS_1)).text_color(rgb(INK)))
                })
                .child(draft.name.clone())
                .on_click(pick),
        );
    }
    let new_draft = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        let n = this.compare_drafts.len() + 1;
        this.compare_drafts.push(crate::app::CompareDraftDef {
            name: format!("New draft {n}"),
            slots: this.compare_slots.clone(),
        });
        this.compare_draft = this.compare_drafts.len() - 1;
        cx.notify();
    });
    let save_draft = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        let d = this.compare_draft;
        if d < this.compare_drafts.len() {
            this.compare_drafts[d].slots = this.compare_slots.clone();
        }
        cx.notify();
    });
    let delete_draft = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        if this.compare_drafts.len() > 1 {
            this.compare_drafts.remove(this.compare_draft);
            this.compare_draft = 0;
            this.compare_slots = this.compare_drafts[0].slots.clone();
        }
        cx.notify();
    });
    drafts_row = drafts_row
        .child(plate_s("draft-new", "+ New").on_click(new_draft))
        .child(plate_s("draft-save", "Save").on_click(save_draft))
        .child(plate_s("draft-delete", "Delete").on_click(delete_draft))
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
                .when(app.compare_board_open, |s| {
                    s.bg(rgb(WELL))
                        .border_1()
                        .border_color(rgba(BORDER_CONTROL))
                        .text_color(rgb(ICE))
                })
                .when(!app.compare_board_open, |s| {
                    s.text_color(rgb(MUTED))
                        .hover(|h| h.bg(rgba(GLASS_1)).text_color(rgb(INK)))
                })
                .child(
                    icon("check", 14.0).text_color(rgb(if app.compare_board_open {
                        ICE
                    } else {
                        MUTED
                    })),
                )
                .child("BOARD")
                .on_click(board_toggle),
        );

    // ---- the slots: at least two, one trailing empty, eight at most ----
    let mut slots: Vec<Option<usize>> = app.compare_slots.clone();
    while slots.len() < 2 {
        slots.push(None);
    }
    if slots.len() < 8 {
        slots.push(None);
    }
    // how many resources stand behind each product's knowledge, against
    // the best-read product on the board
    let sources_of = |subject: Option<&'static CompareSubject>| -> u32 {
        subject
            .map(|s| {
                let specs: u32 = s
                    .specs
                    .iter()
                    .flat_map(|(_, cells)| cells.iter())
                    .map(|c| c.sources as u32)
                    .sum();
                let risks: u32 = s
                    .risks
                    .iter()
                    .flat_map(|(_, cells)| cells.iter())
                    .map(|c| c.sources as u32)
                    .sum();
                let claims = data::evidence_for(&data::CHECKS[s.check]).claims.len() as u32;
                specs + risks + claims
            })
            .unwrap_or(0)
    };
    let best_read = slots
        .iter()
        .filter_map(|s| (*s).and_then(subject_for))
        .map(|s| sources_of(Some(s)))
        .max()
        .unwrap_or(1)
        .max(1);
    let mut slot_row = div().flex().items_start().gap(px(12.0)).flex_wrap();
    for (i, slot) in slots.iter().take(8).enumerate() {
        let open_picker = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.compare_picker = if this.compare_picker == Some(i) {
                None
            } else {
                Some(i)
            };
            cx.notify();
        });
        let clear_slot = move |this: &mut Kriko, cx: &mut Context<Kriko>| {
            while this.compare_slots.len() <= i {
                this.compare_slots.push(None);
            }
            this.compare_slots[i] = None;
            this.compare_detail = None;
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
                    .children(slot.map(|_| {
                        x_button(("slot-clear", i), cx, clear_slot).into_any_element()
                    })),
            );
        col = match slot {
            Some(c) => {
                let check = &data::CHECKS[*c];
                let sources = sources_of(subject_for(*c));
                let rating = sources as f32 / best_read as f32 * 100.0;
                col.child(
                        div()
                            .min_w(px(0.0))
                            .font_family(SANS)
                            .font_weight(FontWeight::SEMIBOLD)
                            .text_size(px(15.0))
                            .text_color(rgb(INK))
                            .child(check.name.to_string()),
                    )
                    .child(mono(check.pack, MUTED))
                    .child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .child(mono("INFO", DIM))
                            .child(meter_slim(rating, 10).flex_1()),
                    )
                    .child(mono(
                        &format!("{sources} sources · vs the best-read here"),
                        MUTED,
                    ))
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
    let picker_card = app.compare_picker.map(|slot_i| {
        let mut list = div().flex().flex_col().flex_none();
        for (ci, check) in data::CHECKS.iter().enumerate() {
            let taken = slots.contains(&Some(ci));
            let assign = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                while this.compare_slots.len() <= slot_i {
                    this.compare_slots.push(None);
                }
                this.compare_slots[slot_i] = Some(ci);
                this.compare_picker = None;
                this.compare_detail = None;
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
                        div()
                            .flex_1()
                            .min_w(px(0.0))
                            .flex()
                            .flex_col()
                            .child(
                                div()
                                    .font_family(SANS)
                                    .text_size(px(13.0))
                                    .text_color(rgb(if taken { MUTED } else { INK }))
                                    .child(check.name.to_string()),
                            ),
                    )
                    .child(mono(check.pack, MUTED)),
            );
        }
        card()
            .flex()
            .flex_col()
            .gap(px(4.0))
            .child(eyebrow("Pick a saved check"))
            .child(hairline())
            .child(
                div()
                    .id("picker-scroll")
                    .max_h(px(260.0))
                    .overflow_y_scroll()
                    .flex()
                    .flex_col()
                    .child(list),
            )
    });

    // ---- the agent: which one answers, and everything it sees ----
    let picks: Vec<usize> = app.compare_slots.iter().flatten().copied().collect();
    let board_subjects: Vec<Option<&'static CompareSubject>> =
        picks.iter().map(|&c| subject_for(c)).collect();
    let spec_n = spec_rows(&board_subjects).len();
    let risk_n = risk_rows(&board_subjects).len();
    let claim_n = claim_rows(&board_subjects).len();
    let notes_n = app
        .compare_notes
        .iter()
        .filter(|n| !n.text.trim().is_empty())
        .count();
    let marks_n = app.compare_marks.len();
    let strokes_n = app.compare_strokes.len();
    let notes_chars: usize = app.compare_notes.iter().map(|n| n.text.len()).sum();
    let tokens = picks.len() * 18
        + spec_n * 16
        + risk_n * 18
        + claim_n * 28
        + marks_n * 6
        + strokes_n * 8
        + notes_chars / 4;
    let attached = format!(
        "attached: {} subjects · {} spec rows · {} risks · {} claims · {} notes · {} marks · {} strokes — ≈{:.1}k tokens",
        picks.len(),
        spec_n,
        risk_n,
        claim_n,
        notes_n,
        marks_n,
        strokes_n,
        tokens as f32 / 1000.0
    );
    let answerers: Vec<usize> = data::AGENTS
        .iter()
        .enumerate()
        .filter(|(_, a)| a.can_answer)
        .map(|(i, _)| i)
        .collect();
    let mut agent_row = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for &ai in &answerers {
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.compare_agent = ai;
            cx.notify();
        });
        let agent = &data::AGENTS[ai];
        let picked = app.compare_agent == ai;
        agent_row = agent_row.child(
            div()
                .id(("cmp-agent", ai))
                .h(px(34.0))
                .px(px(10.0))
                .flex()
                .items_center()
                .gap(px(8.0))
                .rounded(px(10.0))
                .cursor_pointer()
                .when(picked, |s| {
                    s.bg(rgb(WELL))
                        .border_1()
                        .border_color(rgba(BORDER_CONTROL))
                })
                .child(mark_tile(
                    &format!("cmp-agent-tile-{ai}"),
                    agent.mark,
                    if app.compare_questions.iter().any(|q| q.agent == ai && q.answer.is_none()) {
                        Phase::Thinking
                    } else {
                        Phase::Idle
                    },
                    26.0,
                    motion,
                ))
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(11.0))
                        .text_color(rgb(if picked { ICE } else { MUTED }))
                        .child(agent.name.to_string()),
                )
                .on_click(pick),
        );
    }

    // ---- follow-up questions ----
    let ask_input = app.input_field(
        Field::CompareAsk,
        "compare-ask",
        "Ask your agent about this shortlist...",
        Some("agents"),
        window,
        cx,
    );
    let ask = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.ask_compare_question(cx);
    });
    let mut suggestions = div().flex().items_center().gap(px(8.0)).flex_wrap();
    for (i, text) in data::COMPARE_SUGGESTIONS.iter().enumerate() {
        let fill = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.compare_question_input.value = text.to_string();
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
    let draft_name = app.compare_drafts[app.compare_draft].name.clone();
    let mut questions = div().flex().flex_col().gap(px(10.0));
    for (qi, q) in app.compare_questions.iter().enumerate() {
        let agent = &data::AGENTS[q.agent];
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
                .child(match &q.answer {
                    Some(a) => div().pl(px(24.0)).flex().flex_col().gap(px(6.0)).child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .child(tag(
                                format!("compare-answered-{qi}"),
                                TagState::Done,
                                &format!("{} answered", agent.name),
                                motion,
                            )),
                    ).child(
                        div()
                            .font_family(SANS)
                            .text_size(px(14.0))
                            .line_height(px(21.0))
                            .text_color(rgb(INK_2))
                            .child(a.clone()),
                    ),
                    None => div()
                        .pl(px(24.0))
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(tag(
                            format!("compare-asking-{qi}"),
                            TagState::Live,
                            &format!("asking {}", agent.name),
                            motion,
                        )),
                })
                .child(mono(&format!("kept with {}", draft_name), DIM)),
        );
    }

    let questions_card = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Ask your agent"))
        .child(row_desc(
            "A question about this shortlist. The agent reads the whole board: the columns, your marks, your notes.",
        ))
        .child(agent_row)
        .child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(MUTED))
                .child(attached),
        )
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .flex_wrap()
                .child(div().flex_1().min_w(px(260.0)).child(ask_input))
                .child(key("cmp-ask", "Ask").on_click(ask)),
        )
        .child(suggestions)
        .child(questions);

    // ---- assemble ----
    // The board sits directly under the toggle that opens it, so it is on
    // screen the moment it appears, with the slots above the table below.
    let mut page = div()
        .flex()
        .flex_col()
        .gap(px(20.0))
        .child(drafts_row)
        .child(queue_card(app, cx))
        .children(picker_card);
    if app.compare_board_open {
        page = page.child(board(app, window, cx));
    }
    page = page.child(slot_row);
    // the slider appears once the shortlist outgrows the screen
    let filled_n = app.compare_slots.iter().flatten().count();
    if filled_n > 3 {
        page = page.child(column_slider(app, filled_n, 3, cx));
    }
    page = page
        .child(
            div()
                .id("compare-table-scroll")
                .overflow_x_scroll()
                .child(table(app, window, cx).min_w(px(860.0))),
        )
        .child(questions_card);
    page
}
