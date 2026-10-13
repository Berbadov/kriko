//! Small, state-based next steps used by screens that otherwise leave the
//! reader at an empty or terminal state. Arrival is a single 260 ms motion and
//! follows the same focused-window and Reduce motion switch as the rest of UI.

use gpui::{div, prelude::*, px, AnyElement, SharedString};

use crate::screens::{row_desc, row_title};
use crate::theme::{arrive, callout, eyebrow};

/// Render one next step with its real screen action. The caller owns the
/// action's route or API call, so a callout cannot promise an unavailable fix.
pub fn next_step(
    id: impl Into<SharedString>,
    title: &str,
    detail: &str,
    action: AnyElement,
    motion: bool,
) -> AnyElement {
    let body = callout()
        .child(
            div()
                .flex_1()
                .min_w(px(220.0))
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(eyebrow("Next step"))
                .child(row_title(title))
                .child(row_desc(detail)),
        )
        .child(div().flex_none().child(action));
    arrive(body, id, motion)
}
