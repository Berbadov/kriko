//! Text and caret share a single shaped line, including mouse hit testing.
use gpui::{canvas, div, fill, font, point, prelude::*, px, rgb, rgba, size, Bounds,
    ContentMask, Context, Div, MouseButton, Stateful, TextRun, Window};
use crate::app::{Field, Kriko};
use crate::theme::*;

pub fn field(app: &Kriko, field: Field, id: &'static str, placeholder: &str,
             icon_name: Option<&str>, window: &mut Window, cx: &mut Context<Kriko>) -> Stateful<Div> {
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
    div().id(id).track_focus(&input.handle).h(px(48.0)).min_w(px(0.0))
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
