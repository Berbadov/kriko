//! Settings: where a preference lives, and the fact that it lives anywhere.
//! Five cards in two columns: General, Runs, Shortcuts | Keys, Danger zone — the
//! shape of the reference screen. The app's own preferences are saved in the
//! engine's settings; the keys are the engine's own key file.

use gpui::{div, prelude::*, px, rgb, Context, Div, Stateful, Styled, Window};

use crate::app::{Field, Kriko};
use crate::live::knowledge::RUNS_MAX;
use crate::screens::{empty_note, mono, plate_s, row_desc, row_title, segmented};
use crate::theme::*;

/// One row of a card: title + description left, a control right.
fn row(title: &str, desc: &str, control: gpui::AnyElement) -> Div {
    div()
        .py(px(14.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(title))
                .child(row_desc(desc)),
        )
        .child(control)
}

/// A shortcut row: label left, keycaps right.
fn shortcut_row(label: &str, note: Option<&str>, keys: &[&str]) -> Div {
    let mut caps = div().flex().items_center().gap(px(6.0));
    for (i, k) in keys.iter().enumerate() {
        if i > 0 {
            caps = caps.child(
                div()
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(rgb(DIM))
                    .child("+"),
            );
        }
        caps = caps.child(keycap(k));
    }
    div()
        .py(px(14.0))
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(
            div()
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(label))
                .when(note.is_some(), |d| d.children(note.map(row_desc))),
        )
        .child(caps)
}

pub fn settings(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Stateful<Div> {
    let motion = !app.reduce_motion;
    let key_input = app.input_field(Field::KeyValue, "key-value", "Paste the key, then Save", None, window, cx);
    let k = &app.live.knowledge;

    // ---- general ----
    let login = switch_anim("sw-launch", k.launch_at_login, motion).on_click(cx.listener(
        |this, _: &gpui::ClickEvent, _w, cx| {
            let on = !this.live.knowledge.launch_at_login;
            this.set_launch_at_login(on, cx);
        },
    ));
    let reduce = switch_anim("sw-motion", app.reduce_motion, motion).on_click(cx.listener(
        |this, _: &gpui::ClickEvent, _w, cx| {
            let on = !this.reduce_motion;
            this.set_reduce_motion(on, cx);
        },
    ));
    let store = if app.live.health.store.is_empty() {
        "the engine has not said".to_string()
    } else {
        app.live.health.store.clone()
    };
    let general = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("General")))
        .child(hairline())
        .child(row(
            "Launch at login",
            "Start Kriko when you sign in to Windows",
            login.into_any_element(),
        ))
        .child(hairline())
        .child(row("Reduce motion", "Turns off loops and flicker", reduce.into_any_element()))
        .child(hairline())
        .child(
            div()
                .py(px(14.0))
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(row_title("Data location"))
                .child(row_desc("Everything stays on this machine"))
                .child(mono(&store, MUTED)),
        );

    // ---- runs ----
    // How many agent runs the engine may have going at once (#133). The
    // engine reads it at every start, so a change needs no restart.
    let runs_picker = segmented(
        "runs-at-once",
        &[("1", ONE5), ("2", TWO5), ("3", THREE5), ("4", FOUR5)],
        app.run_concurrency.clamp(1, RUNS_MAX) - 1,
        app.run_concurrency_prev.min(RUNS_MAX - 1),
        motion,
        cx,
        |this, i, cx| {
            this.set_run_concurrency(i + 1, cx);
            cx.notify();
        },
    );
    let runs_note = if app.run_concurrency <= 1 {
        "One at a time; the rest wait their turn in Activity.".to_string()
    } else {
        format!(
            "Up to {} together. Each one spends on its own agent or key.",
            app.run_concurrency
        )
    };
    let runs = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("Runs")))
        .child(hairline())
        .child(row(
            "Agent runs at once",
            "Research, authoring and checks that may go together. Two on the same pack always take turns.",
            runs_picker.into_any_element(),
        ))
        .child(div().pb(px(8.0)).child(row_desc(&runs_note)));

    // ---- keys ----
    let mut keys = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("Keys")))
        .child(hairline());
    if !k.keys_loaded {
        keys = keys.child(div().pt(px(12.0)).child(empty_note("Waiting for Kriko's engine.")));
    }
    for (i, p) in k.keys.iter().enumerate() {
        let picked = k.key_provider.as_deref() == Some(p.id.as_str());
        let (pid, rid) = (p.id.clone(), p.id.clone());
        let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.live.knowledge.key_provider = Some(pid.clone());
            cx.notify();
        });
        let remove = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.remove_key(rid.clone(), cx);
        });
        let state = if p.present {
            let from = if p.source.is_empty() { String::new() } else { format!(" from {}", p.source) };
            format!("set, ends {}{}", p.hint, from)
        } else {
            "not set".to_string()
        };
        keys = keys
            .child(row(
                &p.label,
                &state,
                div()
                    .flex()
                    .items_center()
                    .gap(px(8.0))
                    .child(ghost(("key-pick", i), if picked { "Typing" } else { "Set" }).on_click(pick))
                    .when(p.present, |d| d.child(ghost(("key-remove", i), "Remove").on_click(remove)))
                    .into_any_element(),
            ))
            .child(hairline());
    }
    if let Some(target) = k.key_provider.as_ref().and_then(|id| k.keys.iter().find(|p| &p.id == id)) {
        let id = target.id.clone();
        let save = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            let value = this.key_value.value.trim().to_string();
            this.key_value.value.clear();
            this.save_key(id.clone(), value, cx);
            cx.notify();
        });
        keys = keys.child(
            div()
                .pt(px(12.0))
                .flex()
                .flex_col()
                .gap(px(10.0))
                .child(row_desc(&format!(
                    "A key for {}. It goes to the engine's own key file and nowhere else.",
                    target.label
                )))
                .child(
                    div()
                        .flex()
                        .gap(px(12.0))
                        .child(div().flex_1().min_w(px(0.0)).child(key_input))
                        .child(plate_s("key-save", "Save").on_click(save)),
                ),
        );
    } else if k.keys_loaded {
        keys = keys.child(div().pt(px(12.0)).child(row_desc("Pick Set on a provider to type its key.")));
    }
    if !k.keys_path.is_empty() {
        keys = keys.child(div().pt(px(8.0)).child(mono(&k.keys_path, DIM)));
    }

    // ---- shortcuts ----
    let shortcuts = card()
        .flex()
        .flex_col()
        .child(div().mb(px(4.0)).child(eyebrow("Shortcuts")))
        .child(hairline())
        .child(shortcut_row("New check", Some("Anywhere in Kriko"), &["ctrl", "N"]))
        .child(hairline())
        .child(shortcut_row("Search knowledge", None, &["ctrl", "K"]))
        .child(hairline())
        .child(shortcut_row("Jump to Browse", None, &["ctrl", "B"]));

    // ---- danger zone ----
    let confirm = k.erase_confirm;
    let busy = k.erase_busy;
    let label = if busy {
        "Removing"
    } else if confirm {
        "Really remove every pack?"
    } else {
        "Remove all packs"
    };
    let erase = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        if this.live.knowledge.erase_busy {
            return;
        }
        if !this.live.knowledge.erase_confirm {
            this.live.knowledge.erase_confirm = true;
        } else {
            this.erase_packs(cx);
        }
        cx.notify();
    });
    let cancel = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.live.knowledge.erase_confirm = false;
        cx.notify();
    });
    let danger_zone = card()
        .flex()
        .flex_col()
        .child(
            div().mb(px(4.0)).child(
                div()
                    .font_family(MONO)
                    .text_size(px(11.0))
                    .text_color(rgb(DANGER))
                    .child("DANGER ZONE"),
            ),
        )
        .child(hairline())
        .child(row(
            "Remove every pack",
            if confirm {
                "This removes every installed pack and every pack draft, with their claims and evidence. Your history is kept. Packs come back only when you install them again."
            } else {
                "Removes all packs and drafts. Keeps your history."
            },
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .when(confirm && !busy, |d| d.child(ghost("erase-cancel", "Cancel").on_click(cancel)))
                .child(danger("erase", label).on_click(erase))
                .into_any_element(),
        ))
        .when_some(k.settings_notice.clone(), |c, n| c.child(div().pt(px(8.0)).child(mono(&n, MUTED))));

    div()
        .id("settings-scroll")
        .overflow_x_scroll()
        .child(
            div()
                .flex()
                .gap(px(24.0))
                .items_start()
                .min_w(px(920.0))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(24.0))
                        .child(general)
                        .child(runs)
                        .child(shortcuts),
                )
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(24.0))
                        .child(keys)
                        .child(danger_zone),
                ),
        )
}
