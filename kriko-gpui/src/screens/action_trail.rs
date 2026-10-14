//! What a running agent is doing right now, in words (`live::action` says the
//! words). The line on now fades in each time it changes, a finished action's
//! dot settles, and the step chip slides with the segmented thumb's ease. All
//! of it is still under Reduce motion, and a window that is not in front
//! draws the same words without moving.

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::time::Duration;

use gpui::{
    div, prelude::*, px, rgb, Animation, AnimationExt, AnyElement, Div, ElementId, FontWeight,
    SharedString, Styled,
};

use crate::live::action::{self, Action, Dot};
use crate::live::run::Job;
use crate::screens::mono;
use crate::theme::*;

/// The failed dot and text, the same warm tone the stepper uses for a stop.
const WARN: u32 = 0xffb86b;

/// A key for an element that must replay its animation when its state
/// changes: the same words in the same place keep one key.
fn key_of(text: &str, salt: u64) -> u64 {
    let mut hasher = DefaultHasher::new();
    text.hash(&mut hasher);
    salt.hash(&mut hasher);
    hasher.finish()
}

/// Fades and settles a line in when its key changes. Under motion, the
/// wrapper's id carries the key, so a new line remounts and replays.
fn fade_in(el: Div, id: &str, key: u64, motion: bool) -> AnyElement {
    if !motion {
        return el.into_any_element();
    }
    el.with_animation(
        ElementId::NamedInteger(SharedString::from(format!("{id}-line")), key),
        Animation::new(Duration::from_millis(320)),
        |el, t| el.relative().top(px(6.0 * (1.0 - t))).opacity(t),
    )
    .into_any_element()
}

/// One action's state dot. A finished one settles from a larger ring: the
/// dot's id carries its state, so the move to done replays the settle.
fn dot(id: &str, text: &str, state: Dot, motion: bool) -> AnyElement {
    let color = match state {
        Dot::Done => INK_2,
        Dot::Running => ICE,
        Dot::Failed => WARN,
    };
    let core = div().size(px(6.0)).rounded_full().bg(rgb(color));
    let holder = div()
        .size(px(12.0))
        .flex_none()
        .flex()
        .items_center()
        .justify_center();
    if motion && state == Dot::Done {
        holder
            .child(core.with_animation(
                ElementId::NamedInteger(
                    SharedString::from(format!("{id}-settle")),
                    key_of(text, state as u64),
                ),
                Animation::new(Duration::from_millis(300)),
                |el, t| el.size(px(6.0 + 4.0 * (1.0 - t))),
            ))
            .into_any_element()
    } else {
        holder.child(core).into_any_element()
    }
}

fn line_colour(state: Dot) -> u32 {
    match state {
        Dot::Done => INK_2,
        Dot::Running => INK,
        Dot::Failed => WARN,
    }
}

/// The whole block for a job's card: the action on now, the step and the
/// elapsed time, then the last three actions with their dots.
pub fn action_trail(job: &Job, motion: bool) -> Div {
    let current = action::current(job);
    let text = current.text();
    let line = div()
        .flex_1()
        .min_w(px(0.0))
        .font_family(SANS)
        .font_weight(FontWeight::SEMIBOLD)
        .text_size(px(15.0))
        .text_color(rgb(line_colour(current.dot)))
        .truncate()
        .child(text.clone());
    let line = fade_in(line, &format!("trail-{}", job.id), key_of(&text, job.feed.len() as u64), motion);
    let headline = div()
        .flex()
        .items_center()
        .gap(px(10.0))
        .min_w(px(0.0))
        .child(dot(&format!("trail-{}-now", job.id), &text, current.dot, motion))
        .child(line);

    let step = action::step_word(job);
    let chip = mono(&step, if job.done { MUTED } else { ICE });
    let chip = if motion && !job.done {
        // the chip slides in with the stage it names, as the segmented thumb does
        chip.with_animation(
            ElementId::NamedInteger(
                SharedString::from(format!("trail-{}-step", job.id)),
                job.stage().index() as u64,
            ),
            Animation::new(Duration::from_millis(260)),
            |el, t| el.relative().left(px(-10.0 * (1.0 - ease_mech(t)))),
        )
        .into_any_element()
    } else {
        chip.into_any_element()
    };
    let clock = action::elapsed_now(job).map(action::clock).unwrap_or_default();
    let meta = div()
        .flex()
        .items_center()
        .gap(px(10.0))
        .child(chip)
        .child(div().flex_1())
        .child(mono(&clock, INK_2));

    let mut trail = div().flex().flex_col().gap(px(5.0));
    for (i, item) in action::trail(job).iter().enumerate() {
        trail = trail.child(trail_row(&job.id, i, item, motion));
    }

    div()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(headline)
        .child(meta)
        .child(trail)
}

fn trail_row(job_id: &str, i: usize, item: &Action, motion: bool) -> Div {
    let id = format!("trail-{job_id}-{i}");
    let text = item.text();
    div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .min_w(px(0.0))
        .child(dot(&id, &text, item.dot, motion))
        .child(
            div()
                .min_w(px(0.0))
                .flex_1()
                .font_family(SANS)
                .text_size(px(12.0))
                .text_color(rgb(line_colour(item.dot)))
                .truncate()
                .child(text),
        )
}

/// One line for the places with no room for the whole block (a dock lane,
/// an agent's tile): the action on now and the elapsed time.
pub fn compact_line(job: &Job, motion: bool) -> Div {
    let current = action::current(job);
    let text = current.text();
    let line = div()
        .min_w(px(0.0))
        .flex_1()
        .font_family(SANS)
        .text_size(px(12.0))
        .text_color(rgb(line_colour(current.dot)))
        .truncate()
        .child(text.clone());
    let line = fade_in(line, &format!("compact-{}", job.id), key_of(&text, job.feed.len() as u64), motion);
    let clock = action::elapsed_now(job).map(action::clock).unwrap_or_default();
    div()
        .flex()
        .items_center()
        .gap(px(8.0))
        .min_w(px(0.0))
        .child(line)
        .child(mono(&clock, MUTED))
}
