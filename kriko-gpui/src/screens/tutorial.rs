//! The first-run tutorial: five steps over a scrim, offered once.
//!
//! A first install starts with no catalogs, no agent and no extension, and the
//! sidebar names none of that. The tour walks the reader to each place in the
//! order the app needs them: a catalog, an agent, the extension, then the
//! first check. Each step's Go button opens that screen behind the scrim, so
//! the words and the place stay together.
//!
//! Offered once: `~/.kriko/tutorial-seen` (beside `extension-port`, the same
//! per-user file pattern) says the reader has seen it, and is written when the
//! tour is finished or skipped. A verification launch never gets it on its
//! own — every page of `KRIKO_VERIFY` must stay exactly the page asked for —
//! but `KRIKO_VERIFY=tutorial` shows it for a screenshot, and Settings shows
//! it again on demand.

use std::path::Path;

use gpui::{div, prelude::*, px, ClickEvent, Context, FontWeight, Styled};

use crate::app::{Kriko, Tab};
use crate::screens::row_desc;
use crate::theme::*;

struct Step {
    icon: &'static str,
    title: &'static str,
    body: &'static str,
    /// The screen this step points at; the Go button opens it behind the scrim.
    dest: Option<Tab>,
    /// What that Go button says; `None` on the steps without one.
    go: Option<&'static str>,
    /// What the primary key says.
    key: &'static str,
}

const STEPS: &[Step] = &[
    Step {
        icon: "check",
        title: "Welcome to Kriko",
        body: "Kriko puts known product problems, their sources, and useful \
checks beside the listing you are reading. Catalogs and history stay on this \
computer. Online research sends your question and context to the providers \
you choose.",
        dest: None,
        go: None,
        key: "Begin",
    },
    Step {
        icon: "overview",
        title: "Install a catalog",
        body: "A catalog is one product category as data. Overview lists the \
ones this release publishes; install them there and keep them current. An \
installed catalog works offline, with no key.",
        dest: Some(Tab::Overview),
        go: Some("Open Overview"),
        key: "Next",
    },
    Step {
        icon: "agents",
        title: "Set up an agent",
        body: "Online research asks an agent to search and read. Agents shows \
what this machine has — a coding agent, a local model, or a paid API with \
your key — and what each still needs.",
        dest: Some(Tab::Agents),
        go: Some("Open Agents"),
        key: "Next",
    },
    Step {
        icon: "extension",
        title: "Read beside a listing",
        body: "The browser extension reads the page you are on and shows \
Kriko's findings beside it. Browser extension stages it and steps you \
through loading it.",
        dest: Some(Tab::Extension),
        go: Some("Set up extension"),
        key: "Next",
    },
    Step {
        icon: "run",
        title: "Start your first check",
        body: "Search a product title in Run, or use Quick Look from a listing. \
Kriko asks your agent, quote-checks the sources, and files what holds.",
        dest: Some(Tab::Run),
        go: None,
        key: "Start a check",
    },
];

/// The last step's screen, which its key opens as it closes the tour.
pub fn last_dest() -> Tab {
    STEPS.last().and_then(|s| s.dest).unwrap_or(Tab::Run)
}

/// The tour's length; the open step lives on `Kriko` as an index into it.
pub const STEPS_LEN: usize = STEPS.len();

// ---- seen once ----

fn state_path() -> Option<std::path::PathBuf> {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(|home| std::path::PathBuf::from(home).join(".kriko").join("tutorial-seen"))
}

fn mark_seen_at(path: &Path) -> std::io::Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, b"1")
}

/// The reader has finished or skipped the tour; a failure to write leaves
/// it offered again, which is the side to err on.
pub fn mark_seen() {
    if let Some(path) = state_path() {
        let _ = mark_seen_at(&path);
    }
}

/// A verification launch: every `KRIKO_VERIFY` page must stay the page asked
/// for, so the tour is never offered on its own there.
fn review() -> bool {
    std::env::var("KRIKO_VERIFY").is_ok_and(|page| !page.trim().is_empty())
}

/// Whether this launch should offer the tour: a normal launch whose flag file
/// is not there. A machine whose home cannot be found is left alone, because
/// the tour could not be marked seen and would return every launch.
pub fn due_for_tour() -> bool {
    !review() && state_path().is_some_and(|path| !path.is_file())
}

// ---- the overlay ----

/// The tour over everything: a scrim that blocks the app behind it, and one
/// card at a time. Painted last in `render`, so it sits over the dock and the
/// titlebar too; `occlude` keeps the app under the scrim out of reach.
pub fn overlay(app: &mut Kriko, cx: &mut Context<Kriko>) -> gpui::AnyElement {
    let step = app.tutorial.unwrap_or(0).min(STEPS.len() - 1);
    let page = &STEPS[step];
    let last = step + 1 == STEPS.len();

    let skip = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.close_tour(cx);
    });
    let go = page
        .dest
        .filter(|_| !last)
        .zip(page.go)
        .map(|(dest, label)| {
            ghost("tutorial-go", label).on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.tab = dest;
                this.on_open_tab(cx);
                cx.notify();
            }))
        });
    // The last step's key is the tour's own exit: it opens the screen the
    // words point at, and the tour is done.
    let next = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        if last {
            this.tab = last_dest();
            this.on_open_tab(cx);
            this.close_tour(cx);
        } else {
            this.advance_tour(cx);
        }
    });

    let mut dots = div().flex().items_center().gap(px(SPACE_S));
    for i in 0..STEPS.len() {
        dots = dots.child(
            div()
                .w(px(6.0))
                .h(px(6.0))
                .rounded(px(3.0))
                .bg(paint(if i == step { BRAND_BRIGHT } else { DIM })),
        );
    }

    let card = div()
        .id("tutorial-card")
        .flex()
        .flex_col()
        // Keep the centered overlay card at its measured content height. The
        // default flex shrink squeezed the body to one line-height even when
        // its text wrapped, which let the footer paint over the last lines.
        .flex_none()
        .gap(px(SPACE_M))
        .max_w(px(520.0))
        .w_full()
        .bg(paint(SURFACE_1))
        .border_1()
        .border_color(paint_a(HAIRLINE))
        .rounded(px(16.0))
        .p(px(24.0))
        .shadow(card_shadow())
        .child(enter(
            div()
                .flex()
                .flex_none()
                .w_full()
                .items_center()
                .gap(px(SPACE_M))
                .child(icon_alive(page.icon, 16.0, "tutorial-step", step, app.motion))
                .child(eyebrow(&format!("First run — {} of {}", step + 1, STEPS.len()))),
            "tutorial-0",
            0,
            app.motion,
        ))
        .child(enter(
            div()
                .flex_none()
                .w_full()
                .font_family(DISPLAY)
                .font_weight(FontWeight::SEMIBOLD)
                .text_size(px(24.0))
                .line_height(px(28.0))
                .text_color(paint(INK))
                .child(page.title),
            "tutorial-1",
            1,
            app.motion,
        ))
        .child(enter(
            row_desc(page.body).flex_none().w_full(),
            "tutorial-2",
            2,
            app.motion,
        ))
        .child(enter(
            div()
                .flex_none()
                .w_full()
                .mt(px(SPACE_S))
                .flex()
                .items_center()
                .gap(px(SPACE_M))
                .child(dots)
                .child(div().flex_1())
                .child(ghost("tutorial-skip", "Skip tour").on_click(skip))
                .children(go)
                .child(key("tutorial-next", page.key).on_click(next)),
            "tutorial-3",
            3,
            app.motion,
        ));

    div()
        .id("tutorial-scrim")
        .absolute()
        .size_full()
        .flex()
        .items_center()
        .justify_center()
        .p(px(SPACE_XL))
        .bg(fixed_a(0x05070fd9))
        .occlude()
        .child(card)
        .into_any_element()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scratch(name: &str) -> std::path::PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!("kriko-tutorial-test-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        path
    }

    #[test]
    fn seen_is_a_file_and_comes_back() {
        let root = scratch("seen");
        let flag = root.join("deep").join("tutorial-seen");
        assert!(!flag.is_file(), "a fresh machine has no flag");
        mark_seen_at(&flag).expect("the flag writes, parent folders made");
        assert_eq!(std::fs::read_to_string(&flag).unwrap(), "1");
        assert!(flag.is_file(), "and it stays: the tour is not re-offered");
        std::fs::remove_dir_all(&root).ok();
    }

    #[test]
    fn the_tour_walks_every_place_in_order() {
        // Every step says something and names a real screen where it can.
        let titles: std::collections::HashSet<_> = STEPS.iter().map(|s| s.title).collect();
        assert_eq!(titles.len(), STEPS.len(), "each step is its own screen");
        for step in STEPS {
            assert!(!step.body.is_empty());
            assert!(!step.key.is_empty());
            assert!(
                step.dest.is_some() || step.go.is_none(),
                "a Go button needs a place to go"
            );
        }
        // The order the app needs them in, ending on the screen it is for.
        let dests: Vec<&str> = STEPS.iter().filter_map(|s| s.dest.map(|d| d.key())).collect();
        assert_eq!(
            dests,
            ["overview", "agents", "extension", "run"],
            "catalog, agent, extension, then the first check"
        );
        assert!(matches!(last_dest(), Tab::Run), "the last step starts the reader off");
    }
}
