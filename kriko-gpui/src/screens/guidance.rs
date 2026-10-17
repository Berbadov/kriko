//! Small, state-based next steps used by screens that otherwise leave the
//! reader at an empty or terminal state. Arrival is a single 260 ms motion and
//! follows the same focused-window and Reduce motion switch as the rest of UI.

use gpui::{div, prelude::*, px, AnyElement, SharedString};

use crate::screens::row_title;
use crate::textfx::words_reveal;
use crate::theme::{arrive, callout, enter, eyebrow, icon_alive};

/// Render one next step with its real screen action. The caller owns the
/// action's route or API call, so a callout cannot promise an unavailable fix.
pub fn next_step(
    id: impl Into<SharedString>,
    title: &str,
    detail: &str,
    action: AnyElement,
    motion: bool,
) -> AnyElement {
    let key: SharedString = id.into();
    let body = callout()
        .child(
            div()
                .flex_1()
                .min_w(px(220.0))
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(8.0))
                        .child(icon_alive("spark", 12.0, key.as_str(), 0, motion))
                        .child(eyebrow("Next step")),
                )
                .child(row_title(title))
                .child(words_reveal(detail, key.as_str(), motion)),
        )
        .child(div().flex_none().child(action));
    enter(arrive(body, key.clone(), motion), key.as_str(), 0, motion)
}
