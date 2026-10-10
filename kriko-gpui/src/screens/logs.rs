//! A persistent log control shared by durable tasks.
use gpui::{div, prelude::*, px, rgb, Context, Div, ScrollHandle};
use crate::app::Kriko;
use crate::live::history::{now_secs, parse_utc};
use crate::live::run::{kind_word, Job};
use crate::screens::{empty_note, mono, plate_s, row_desc};
use crate::theme::*;

#[derive(Default)]
pub struct View {
    pub open: bool,
    pub level: usize,
    pub scroll: ScrollHandle,
    pub lines: usize,
}

pub fn job_logs(app: &mut Kriko, job: &Job, cx: &mut Context<Kriko>) -> Div {
    let id = job.id.clone();
    let events = job.log_events();
    let view = app.log_views.entry(id.clone()).or_default();
    let open = view.open;
    let level = view.level;
    let scroll = view.scroll.clone();
    if open && events.len() != view.lines {
        if view.lines == 0 || (scroll.offset().y + scroll.max_offset().height).abs() < px(12.0) {
            scroll.scroll_to_bottom();
        }
        view.lines = events.len();
    }
    let toggle_id = id.clone();
    let toggle = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
        let view = this.log_views.entry(toggle_id.clone()).or_default();
        view.open = !view.open; cx.notify();
    });
    let elapsed = parse_utc(&job.created_at).map(|start| {
        (parse_utc(&job.finished_at).unwrap_or_else(now_secs) - start).max(0)
    });
    let result = div().flex().flex_col().gap(px(10.0))
        .child(div().flex().flex_wrap().items_center().gap(px(10.0))
            .child(tag(format!("task-state-{id}"), if !job.done && job.state == "running" { TagState::Live }
                else if matches!(job.state.as_str(), "failed" | "interrupted") { TagState::Block }
                else if job.done { TagState::Done } else { TagState::Queue }, &job.state, !app.reduce_motion))
            .child(plate_s(gpui::ElementId::named_usize(format!("task-logs-{id}"), 0), if open { "Hide logs" } else { "Show logs" }).on_click(toggle)))
        .child(row_desc(&format!("{} · {} · {} · {} · {}",
            kind_word(&job.kind), if job.harness.is_empty() { job.backend.as_str() } else { job.harness.as_str() },
            if job.model.is_empty() { "Model not reported" } else { &job.model },
            job.message, elapsed.map(|n| format!("{n} s")).unwrap_or_else(|| "Time unavailable".into()))));
    let kinds = ["", "search", "source", "finding", "problem"];
    let labels = ["All", "Search", "Sources", "Findings", "Problems"];
    let selected = level.min(4);
    let lines: Vec<_> = events.iter().filter(|line| selected == 0 || line.kind == kinds[selected]).collect();
    let copied = lines.iter().map(|line| line.text.as_str()).collect::<Vec<_>>().join("\n");
    let copy = cx.listener(move |_this, _: &gpui::ClickEvent, _w, cx| cx.write_to_clipboard(gpui::ClipboardItem::new_string(copied.clone())));
    let mut controls = div().flex().flex_wrap().gap(px(8.0));
    for (i, label) in labels.iter().enumerate() {
        let pick_id = id.clone();
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.log_views.entry(pick_id.clone()).or_default().level = i; cx.notify();
        });
        controls = controls.child(plate_s(gpui::ElementId::named_usize(format!("log-filter-{id}"), i), label)
            .when(selected == i, |b| b.border_color(rgb(ICE))).on_click(pick));
    }
    let controls = controls.child(plate_s(gpui::ElementId::named_usize(format!("log-copy-{id}"), 0), "Copy log").on_click(copy));
    let mut body = div().id(gpui::ElementId::named_usize(format!("log-scroll-{id}"), 0)).track_scroll(&scroll).overflow_y_scroll().occlude().on_scroll_wheel(|_, _, cx| cx.stop_propagation())
        .h(px(280.0)).flex_none().min_h(px(40.0)).p(px(12.0)).bg(rgb(WELL)).flex().flex_col().gap(px(5.0));
    if lines.is_empty() { body = body.child(empty_note(if job.done { "No log entries for this filter." } else { "Waiting for log entries." })); }
    for line in lines { body = body.child(mono(&line.text, INK_2).font_family(CODE).flex_none()); }
    result.child(reveal(div().flex().flex_col().gap(px(10.0)).child(controls).child(body), format!("log-disclosure-{id}"), open, 350.0, !app.reduce_motion))
}
