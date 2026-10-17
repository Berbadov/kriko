//! Text and caret share a single shaped line, including mouse hit testing.
use gpui::{canvas, div, fill, font, point, prelude::*, px, rgb, rgba, size, Bounds,
    ContentMask, Context, Div, MouseButton, Stateful, TextRun, Window};
use crate::app::{Field, Kriko};
use crate::theme::*;

pub fn field(app: &Kriko, field: Field, id: &'static str, placeholder: &str,
             icon_name: Option<&str>, window: &mut Window, cx: &mut Context<Kriko>) -> Stateful<Div> {
    if field == Field::ChatAsk { return chat_field(app, id, placeholder, window, cx); }
    let input = app.input(field);
    let focused = input.handle.is_focused(window);
    let empty = input.value.is_empty();
    let display = if empty { placeholder.to_string() } else { input.value.clone() };
    let cursor = if empty { 0 } else { input.position() };
    let selection = input.selection();
    let old_scroll = input.scroll_x;
    let entity = cx.entity();
    let text = canvas(move |bounds, window, _cx| {
        let run = TextRun { len: display.len(), font: font(SANS),
            color: rgb(if empty { DIM } else { INK }).into(),
            background_color: None, underline: None, strikethrough: None };
        let line = window.text_system().shape_line(display.into(), px(16.0), &[run], None);
        let caret = line.x_for_index(cursor);
        let visible = (bounds.size.width - px(3.0)).max(px(0.0));
        let scroll = if empty { px(0.0) } else {
            old_scroll.max(caret - visible).min(caret).max(px(0.0))
        };
        (line, scroll)
    }, move |bounds, (line, scroll), window, cx| {
        let origin = point(bounds.left() - scroll, bounds.top());
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            if focused && !selection.is_empty() {
                window.paint_quad(fill(Bounds::from_corners(
                    point(origin.x + line.x_for_index(selection.start), bounds.top()),
                    point(origin.x + line.x_for_index(selection.end), bounds.bottom())), rgba(0xbfe4ff40)));
            }
            let _ = line.paint(origin, px(22.0), window, cx);
            if focused {
                window.paint_quad(fill(Bounds::new(
                    point(origin.x + line.x_for_index(cursor), bounds.top()), size(px(1.5), px(22.0))), rgb(INK)));
            }
        });
        entity.update(cx, |app, _| {
            let input = app.input_mut(field);
            input.layout = Some(line);
            input.bounds = Some(bounds);
            input.scroll_x = scroll;
        });
    }).w_full().h(px(22.0));
    div().id(id).track_focus(&input.handle).h(px(48.0)).min_h(px(48.0)).max_h(px(48.0)).min_w(px(0.0))
        .flex().flex_1().items_center().gap(px(12.0)).px(px(16.0))
        .rounded(px(12.0)).bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL))
        .when(focused, |d| d.border_color(rgb(ICE)))
        .on_key_down(cx.listener(move |app, event, _w, cx| Kriko::handle_key(app, field, event, cx)))
        .on_mouse_down(MouseButton::Left, cx.listener(move |app, event: &gpui::MouseDownEvent, window, cx| {
            let input = app.input_mut(field);
            window.focus(&input.handle);
            if let (Some(line), Some(bounds)) = (&input.layout, input.bounds) {
                let at = if input.value.is_empty() { 0 } else {
                    line.closest_index_for_x(event.position.x - bounds.left() + input.scroll_x)
                };
                input.move_cursor(at, event.modifiers.shift);
            }
            input.selecting = true;
            cx.notify();
        }))
        .on_mouse_move(cx.listener(move |app, event: &gpui::MouseMoveEvent, _w, cx| {
            let input = app.input_mut(field);
            if input.selecting {
                if let (Some(line), Some(bounds)) = (&input.layout, input.bounds) {
                    let at = line.closest_index_for_x(event.position.x - bounds.left() + input.scroll_x);
                    input.move_cursor(at, true);
                    cx.notify();
                }
            }
        }))
        .on_mouse_up(MouseButton::Left, cx.listener(move |app, _, _w, _cx| app.input_mut(field).selecting = false))
        .on_mouse_up_out(MouseButton::Left, cx.listener(move |app, _, _w, _cx| app.input_mut(field).selecting = false))
        .children(icon_name.map(|n| icon(n, 18.0).flex_none().text_color(rgb(if empty { DIM } else { MUTED }))))
        .child(div().flex_1().min_w(px(0.0)).overflow_hidden().child(text))
}

pub(crate) fn wrapped_hit(input: &crate::app::InputState, position: gpui::Point<gpui::Pixels>) -> usize {
    let Some(bounds) = input.bounds else { return input.position() };
    let y = (position.y - bounds.top() + input.scroll_y).max(px(0.0));
    for (offset, line, top) in &input.wrapped {
        if y < *top + line.size(px(22.0)).height {
            let local = line.closest_index_for_position(point(position.x - bounds.left(), y - *top), px(22.0));
            return (*offset + local.unwrap_or_else(|index| index)).min(input.value.len());
        }
    }
    input.value.len()
}

pub(crate) fn move_chat_line(input: &mut crate::app::InputState, down: bool, extend: bool) {
    let Some(bounds) = input.bounds else { return };
    let cursor = input.position();
    let position = input.wrapped.iter().find_map(|(offset, line, top)| {
        if cursor < *offset || cursor > *offset + line.len() { return None; }
        line.position_for_index(cursor - *offset, px(22.0))
            .map(|p| point(bounds.left() + p.x, bounds.top() + *top + p.y - input.scroll_y))
    });
    if let Some(position) = position {
        let at = wrapped_hit(input, position + point(px(0.0), px(if down { 22.0 } else { -22.0 })));
        input.move_cursor(at, extend);
    }
}

/// The chat composer wraps long prompts and keeps the caret in its three-line viewport.
fn chat_field(app: &Kriko, id: &'static str, placeholder: &str, window: &mut Window,
              cx: &mut Context<Kriko>) -> Stateful<Div> {
    let input = &app.chat_input;
    let focused = input.handle.is_focused(window);
    let empty = input.value.is_empty();
    let display = if empty { placeholder.to_string() } else { input.value.clone() };
    let cursor = if empty { 0 } else { input.position() };
    let selection = input.selection();
    let old_scroll = input.scroll_y;
    let entity = cx.entity();
    let text = canvas(move |bounds, window, _cx| {
        let run = TextRun { len: display.len(), font: font(SANS),
            color: rgb(if empty { DIM } else { INK }).into(),
            background_color: None, underline: None, strikethrough: None };
        let shaped = window.text_system().shape_text(display.into(), px(15.0), &[run],
            Some(bounds.size.width.max(px(20.0))), None).unwrap_or_default();
        let mut lines = Vec::new();
        let mut offset = 0;
        let mut top = px(0.0);
        let mut caret = point(px(0.0), px(0.0));
        for line in shaped {
            if cursor >= offset && cursor <= offset + line.len() {
                if let Some(position) = line.position_for_index(cursor - offset, px(22.0)) {
                    caret = point(position.x, top + position.y);
                }
            }
            let height = line.size(px(22.0)).height;
            offset += line.len() + 1;
            lines.push((offset - line.len() - 1, line, top));
            top += height;
        }
        let scroll = if empty { px(0.0) } else {
            old_scroll.max(caret.y + px(22.0) - bounds.size.height).min(caret.y).max(px(0.0))
        };
        (lines, caret, scroll)
    }, move |bounds, (lines, caret, scroll), window, cx| {
        window.with_content_mask(Some(ContentMask { bounds }), |window| {
            for (offset, line, top) in &lines {
                let origin = point(bounds.left(), bounds.top() + *top - scroll);
                if focused && !selection.is_empty() {
                    for (at, ch) in line.text.char_indices() {
                        if !selection.contains(&(*offset + at)) { continue; }
                        if let Some(start) = line.position_for_index(at, px(22.0)) {
                            let end = line.position_for_index(at + ch.len_utf8(), px(22.0)).unwrap_or(start + point(px(8.0), px(0.0)));
                            let width = if end.y == start.y { (end.x - start.x).max(px(2.0)) } else { bounds.size.width - start.x };
                            window.paint_quad(fill(Bounds::new(origin + start, size(width, px(22.0))), rgba(0xbfe4ff40)));
                        }
                    }
                }
                let _ = line.paint(origin, px(22.0), gpui::TextAlign::Left, None, window, cx);
            }
            if focused {
                window.paint_quad(fill(Bounds::new(point(bounds.left() + caret.x, bounds.top() + caret.y - scroll),
                    size(px(1.5), px(22.0))), rgb(INK)));
            }
        });
        entity.update(cx, |app, _| {
            app.chat_input.wrapped = lines;
            app.chat_input.bounds = Some(bounds);
            app.chat_input.scroll_y = scroll;
        });
    }).w_full().h(px(66.0));
    div().id(id).track_focus(&input.handle).min_w(px(0.0)).flex_1().p(px(12.0))
        .rounded(px(12.0)).bg(rgb(WELL)).border_1().border_color(rgba(BORDER_CONTROL))
        .when(focused, |d| d.border_color(rgb(ICE)))
        .on_key_down(cx.listener(move |app, event, _w, cx| Kriko::handle_key(app, Field::ChatAsk, event, cx)))
        .on_mouse_down(MouseButton::Left, cx.listener(|app, event: &gpui::MouseDownEvent, window, cx| {
            window.focus(&app.chat_input.handle);
            let at = wrapped_hit(&app.chat_input, event.position);
            app.chat_input.move_cursor(at, event.modifiers.shift);
            app.chat_input.selecting = true;
            cx.notify();
        }))
        .on_mouse_move(cx.listener(|app, event: &gpui::MouseMoveEvent, _w, cx| {
            if app.chat_input.selecting {
                let at = wrapped_hit(&app.chat_input, event.position);
                app.chat_input.move_cursor(at, true);
                cx.notify();
            }
        }))
        .on_mouse_up(MouseButton::Left, cx.listener(|app, _, _w, _cx| app.chat_input.selecting = false))
        .on_mouse_up_out(MouseButton::Left, cx.listener(|app, _, _w, _cx| app.chat_input.selecting = false))
        .child(text)
}
