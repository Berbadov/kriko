//! The first-run setup: the flow a reader walks once, before the app.
//!
//! Four steps over the engine's own answers: welcome, the agent that runs
//! checks, the catalogs it reads, and the browser extension. Every choice is
//! written through the same methods the app's screens use, so finishing here
//! leaves the app in exactly the state those screens would have left it in.
//! The shell renders this in place of the tabs while `app.onboarding` is
//! `Some` and the settings have answered; the floating titlebar paints over
//! the top, so the page keeps 56 px of room for it.

use gpui::{
    div, prelude::*, px, svg, ClickEvent, Context, Div, FontWeight, SharedString, Stateful, Styled,
    Window,
};

use crate::app::{Kriko, Tab, ONBOARD_STEPS};
use crate::live::knowledge::{AppUpdate, ExtStatus, PackRow};
use crate::live::run::{Harness, RunState, Verify};
use crate::screens::run::option_chip;
use crate::screens::{empty_note, mono, row_desc, row_title};
use crate::theme::*;

const STEP_TITLES: [&str; ONBOARD_STEPS] = [
    "Set up Kriko",
    "Choose your agent",
    "Install a catalog",
    "Check pages as you browse",
];

const STEP_LEADS: [&str; ONBOARD_STEPS] = [
    "Kriko reads product listings against knowledge on this computer. Three short choices and you are in.",
    "Pick the agent Kriko asks when a check needs research. Change it later on Agents.",
    "Catalogs are the knowledge Kriko checks against. Switch on the ones you want; they work offline, with no key.",
    "The extension shows what Kriko knows beside the page you are reading. Set it up now, or later from Browser extension.",
];

const STEP_NAMES: [&str; ONBOARD_STEPS] = ["Welcome", "Agent", "Knowledge", "Extension"];

pub fn onboarding(
    app: &mut Kriko,
    window: &mut Window,
    cx: &mut Context<Kriko>,
) -> impl gpui::IntoElement {
    let step = app
        .onboarding
        .as_ref()
        .map(|o| o.step)
        .unwrap_or(0)
        .min(ONBOARD_STEPS - 1);
    let motion = app.motion;
    let chosen_agent = app.onboarding.as_ref().and_then(|o| o.agent.clone());

    // The page is centred in the window at one column; the card's own inner
    // width decides whether the agent rows sit two abreast or stack.
    let viewport_w = f32::from(window.viewport_size().width);
    let page_w = (viewport_w - 64.0).clamp(0.0, 860.0);
    let card_inner_w = (page_w - 40.0).max(0.0);

    let body = match step {
        0 => welcome(motion),
        1 => agent_step(
            &app.live.run.harnesses,
            &app.live.run.preferred,
            chosen_agent.as_deref(),
            &app.live.run.agent_note,
            app.live.run.verifying,
            app.live.run.verify.as_ref(),
            card_inner_w,
            motion,
            window,
            cx,
        ),
        2 => knowledge_step(
            &app.live.knowledge.packs,
            app.live.knowledge.packs_loaded,
            app.live.knowledge.app_update.as_ref(),
            motion,
            cx,
        ),
        _ => extension_step(
            app.live.knowledge.ext.as_ref(),
            app.live.knowledge.ext_checking,
            app.live.knowledge.ext_error.as_deref(),
            motion,
            cx,
        ),
    };

    // The top row: Back on the left from the second step, Skip on the right.
    let back = if step > 0 {
        let back = cx.listener(|this, _: &ClickEvent, _w, cx| this.onboarding_back(cx));
        small_action("ob-back", "arrow-left", "Back")
            .on_click(back)
            .into_any_element()
    } else {
        div().into_any_element()
    };
    let skip = cx.listener(|this, _: &ClickEvent, _w, cx| this.finish_onboarding(cx));

    // The dots say where the reader is and are also a way to jump back.
    let mut dots = div().flex().items_center().gap(px(SPACE_S));
    for i in 0..ONBOARD_STEPS {
        let goto = cx.listener(move |this, _: &ClickEvent, _w, cx| this.onboarding_goto(i, cx));
        let current = i == step;
        dots = dots.child(
            div()
                .id(("ob-dot", i))
                .size(px(if current { 9.0 } else { 7.0 }))
                .rounded_full()
                .cursor_pointer()
                .bg(if current {
                    paint(ICE)
                } else {
                    paint_a(HAIRLINE)
                })
                .hover(|d| d.bg(paint(ICE)))
                .on_click(goto),
        );
    }

    let next = cx.listener(|this, _: &ClickEvent, _w, cx| {
        let last = this
            .onboarding
            .as_ref()
            .is_some_and(|o| o.step + 1 >= ONBOARD_STEPS);
        if last {
            this.finish_onboarding(cx);
        } else {
            this.onboarding_next(cx);
        }
    });
    let primary = if step + 1 >= ONBOARD_STEPS {
        key("ob-finish", "Open Kriko")
    } else {
        key("ob-next", "Continue")
    };
    let primary = primary.on_click(next);

    let footer = div()
        .mt(px(SPACE_2XL))
        .pt(px(SPACE_L))
        .border_t_1()
        .border_color(paint_a(HAIRLINE))
        .flex()
        .flex_wrap()
        .items_center()
        .justify_between()
        .gap(px(16.0))
        .child(
            div().flex().items_center().gap(px(12.0)).child(dots).child(
                div()
                    .font_family(MONO)
                    .text_size(px(12.0))
                    .text_color(paint(DIM))
                    .child(STEP_NAMES[step].to_uppercase()),
            ),
        )
        .child(primary);

    div()
        .id("onboarding-page")
        .flex_1()
        .min_h(px(0.0))
        .w_full()
        .overflow_y_scroll()
        .overflow_x_hidden()
        .flex()
        .flex_col()
        .items_center()
        .px(px(32.0))
        .pt(px(SPACE_2XL))
        .pb(px(SPACE_2XL))
        .child(
            div()
                .w_full()
                .max_w(px(860.0))
                .flex()
                .flex_col()
                .child(
                    div()
                        .flex()
                        .items_center()
                        .justify_between()
                        .gap(px(12.0))
                        .child(back)
                        .child(
                            ghost("ob-skip", "Skip setup")
                                .h(px(40.0))
                                .px(px(SPACE_L))
                                .text_size(px(13.0))
                                .on_click(skip),
                        ),
                )
                .child({
                    let mut heading = div().mt(px(SPACE_XL)).flex().flex_col();
                    if step == 0 {
                        heading = heading.child(div().mb(px(SPACE_XL)).child(brand_mark()));
                    }
                    heading.child(
                        div()
                            .flex()
                            .flex_col()
                            .gap(px(SPACE_M))
                            .child(
                                div()
                                    .font_family(DISPLAY)
                                    .font_weight(FontWeight::SEMIBOLD)
                                    .text_size(px(36.0))
                                    .line_height(px(42.0))
                                    .text_color(paint(INK))
                                    .child(STEP_TITLES[step].to_string()),
                            )
                            .child(
                                div()
                                    .max_w(px(660.0))
                                    .font_family(SANS)
                                    .text_size(px(15.0))
                                    .line_height(px(23.0))
                                    .text_color(paint(MUTED))
                                    .child(STEP_LEADS[step].to_string()),
                            ),
                    )
                })
                // One arrival per step change: the id carries the step, so a
                // new step remounts and plays once; a notify does not.
                .child(
                    div()
                        .mt(px(SPACE_XL))
                        .child(arrive(body, format!("ob-step-{step}"), motion)),
                )
                .child(footer),
        )
}

// ---- step 0: welcome ----

/// The brand mark on its own: the white cut on the brand blue, so it reads in
/// both themes without a second file.
fn brand_mark() -> Div {
    div()
        .size(px(52.0))
        .flex_none()
        .rounded(px(14.0))
        .bg(paint(BRAND))
        .flex()
        .items_center()
        .justify_center()
        .shadow(vec![shadow(0x102b9c80, 0.0, 6.0, 18.0, 0.0)])
        .child(
            svg()
                .path(SharedString::from("kriko-mark-white.svg"))
                .size(px(30.0))
                .text_color(fixed(0xffffff)),
        )
}

fn welcome(motion: bool) -> Div {
    let promises = [
        (
            "database",
            "Your knowledge stays local",
            "Catalogs, checks and history stay on this computer.",
        ),
        (
            "agents",
            "An agent you already trust",
            "Checks go to a coding agent installed here, or to a local model.",
        ),
        (
            "extension",
            "Read beside the listing",
            "The extension shows what Kriko knows on the page you are reading.",
        ),
    ];
    let mut list = div().flex().flex_col();
    for (i, (icon_name, title, desc)) in promises.iter().enumerate() {
        if i > 0 {
            list = list.child(hairline());
        }
        list = list.child(promise(i, icon_name, title, desc, motion));
    }

    card()
        .flex()
        .flex_col()
        .px(px(SPACE_L))
        .py(px(SPACE_S))
        .child(
            div()
                .pt(px(12.0))
                .pb(px(4.0))
                .child(card_head("spark", "What you get", motion)),
        )
        .child(list)
}

fn promise(index: usize, icon_name: &str, title: &str, desc: &str, motion: bool) -> Div {
    div()
        .flex()
        .items_start()
        .gap(px(12.0))
        .py(px(12.0))
        .child(icon_alive(icon_name, 14.0, "ob-promise", index, motion))
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(SPACE_XS))
                .child(row_title(title))
                .child(row_desc(desc)),
        )
}

// ---- step 1: the agent ----

fn agent_step(
    harnesses: &[Harness],
    preferred: &str,
    chosen_agent: Option<&str>,
    agent_note: &str,
    verifying: bool,
    verify: Option<&Verify>,
    inner_w: f32,
    motion: bool,
    window: &mut Window,
    cx: &mut Context<Kriko>,
) -> Div {
    let refresh = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_agents(cx));
    let test = cx.listener(|this, _: &ClickEvent, _w, cx| this.verify_agents(cx));
    let controls = div()
        .flex()
        .flex_wrap()
        .gap(px(8.0))
        .child(small_action("ob-agents-refresh", "refresh", "Refresh").on_click(refresh))
        .child(small_action("ob-agents-test", "check-circle", "Test").on_click(test));

    let mut page = card()
        .flex()
        .flex_col()
        .gap(px(SPACE_L))
        .px(px(SPACE_L))
        .py(px(SPACE_L))
        .child(card_head_row(
            "agents",
            "Agents on this machine",
            Some(controls.into_any_element()),
            motion,
        ));

    let mut rows: Vec<Stateful<Div>> = Vec::new();
    for (i, h) in harnesses.iter().enumerate() {
        let selectable = matches!(h.state, RunState::Ready);
        let picked = preferred == h.id || chosen_agent == Some(h.id.as_str());
        let desc = match &h.state {
            RunState::Ready => "detected on this machine".to_string(),
            RunState::Unusable(reason) if !reason.is_empty() => reason.clone(),
            RunState::Unusable(_) => "found, but not usable yet".to_string(),
            RunState::Missing { hint, .. } if !hint.is_empty() => hint.clone(),
            RunState::Missing { .. } => "not installed on this machine".to_string(),
        };
        let glyph = well()
            .size(px(40.0))
            .flex_none()
            .flex()
            .items_center()
            .justify_center()
            .font_family(MONO)
            .font_weight(FontWeight::SEMIBOLD)
            .text_size(px(12.0))
            .text_color(paint(if picked { ICE } else { MUTED }))
            .child(glyph_initials(&h.label));
        let mut row = div()
            .id(("ob-agent", i))
            .flex()
            .items_start()
            .gap(px(12.0))
            .p(px(SPACE_M))
            .rounded(px(10.0))
            .border_1()
            .border_color(paint_a(HAIRLINE))
            .when(picked, |d| {
                d.bg(paint_a(BRAND_WASH)).border_color(paint_a(0x86a3ff48))
            })
            .when(!picked && selectable, |d| {
                d.bg(paint_a(GLASS_1)).hover(|s| {
                    s.bg(paint_a(GLASS_2))
                        .border_color(paint_a(BORDER_CONTROL))
                        .relative()
                        .top(px(-1.0))
                })
            })
            .child(glyph)
            .child(
                div()
                    .flex_1()
                    .min_w(px(0.0))
                    .flex()
                    .flex_col()
                    .gap(px(SPACE_XS))
                    .child(row_title(&h.label))
                    .child(row_desc(&desc)),
            )
            .when(picked, |d| {
                d.child(tag(
                    format!("ob-agent-chosen-{i}"),
                    TagState::Done,
                    "Chosen",
                    motion,
                ))
            });
        // Only an agent that can actually run a check is a choice. The others
        // stay visible, with the engine's reason under the name, so the reader
        // can see what is missing instead of wondering why the row is dead.
        if selectable {
            let id = h.id.clone();
            let model = h.llm.clone();
            row =
                row.cursor_pointer()
                    .on_click(cx.listener(move |this, _: &ClickEvent, _w, cx| {
                        this.prefer_agent(id.clone(), cx);
                        if let Some(onboarding) = this.onboarding.as_mut() {
                            onboarding.agent = Some(id.clone());
                            onboarding.model = model.clone();
                        }
                        cx.notify();
                    }));
        }
        rows.push(row);
    }

    if rows.is_empty() {
        page = page.child(empty_note(
            "No agent found yet. Refresh, or set one up on Agents.",
        ));
    } else {
        page = page.child(grid(inner_w, 340.0, rows));
    }

    // The model for the picked agent. The engine holds the same value, so a
    // click is felt at once and a refusal falls back to what it holds.
    let picked_h = harnesses
        .iter()
        .find(|h| h.id == preferred)
        .or_else(|| chosen_agent.and_then(|id| harnesses.iter().find(|h| h.id == id)))
        .or_else(|| {
            harnesses
                .iter()
                .find(|h| matches!(h.state, RunState::Ready))
        });

    let mut model = div().flex().flex_col().gap(px(SPACE_M));
    match picked_h {
        Some(h) => {
            model = model.child(mono(&format!("Model · {}", h.label), MUTED));
            if h.llm_selectable {
                let mut chips = well().p(px(8.0)).flex().flex_wrap().gap(px(SPACE_S));

                let default_id = h.id.clone();
                let default = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                    this.pick_agent_model(default_id.clone(), String::new(), cx);
                    if let Some(onboarding) = this.onboarding.as_mut() {
                        onboarding.model.clear();
                    }
                    cx.notify();
                });
                chips = chips.child(
                    option_chip("ob-model-default", "Default", h.llm.is_empty()).on_click(default),
                );

                let mut names: Vec<String> = Vec::new();
                for name in &h.llms {
                    if !names.contains(name) {
                        names.push(name.clone());
                    }
                }
                // A chosen model the provider no longer lists still stays
                // picked, so a refresh never silently moves a run.
                if !h.llm.is_empty() && !names.contains(&h.llm) {
                    names.insert(0, h.llm.clone());
                }
                for (i, name) in names.iter().enumerate() {
                    let picked_model = h.llm == name.as_str();
                    let id = h.id.clone();
                    let choice = name.clone();
                    let pick = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                        this.pick_agent_model(id.clone(), choice.clone(), cx);
                        if let Some(onboarding) = this.onboarding.as_mut() {
                            onboarding.model = choice.clone();
                        }
                        cx.notify();
                    });
                    chips = chips
                        .child(option_chip(("ob-model", i), name, picked_model).on_click(pick));
                }
                model = model.child(chips);
                if h.llms_pending {
                    model = model.child(
                        div()
                            .flex()
                            .items_center()
                            .gap(px(8.0))
                            .child(spinner("ob-models-spin", 12.0, motion))
                            .child(mono("Asking the provider for its models…", DIM)),
                    );
                }
            } else {
                model = model.child(row_desc(
                    "This CLI has no model switch; it runs its set-up model.",
                ));
            }
        }
        None => {
            model = model.child(mono("Model", MUTED));
            model = model.child(row_desc(
                "Pick a ready agent above to choose its model.",
            ));
        }
    }
    if !agent_note.is_empty() {
        model = model.child(mono(agent_note, DIM));
    }
    page = page.child(model);

    // The test's answer, at the bottom of the card: the same strip on success
    // and on failure, with the engine's transcript one quiet click away.
    if verifying {
        page = page.child(
            div()
                .flex()
                .items_center()
                .gap(px(SPACE_M))
                .child(spinner("ob-verify-spin", 14.0, motion))
                .child(mono("Testing the agent…", MUTED)),
        );
    }
    if let Some(v) = verify {
        let label = picked_h.map(|h| h.label.as_str()).unwrap_or("Agent");
        let line = if v.ok {
            format!("{label} replied in {} ms · ok", v.ms)
        } else {
            format!("{label} did not reply · {} ms", v.ms)
        };
        let mut strip = well()
            .px(px(SPACE_L))
            .py(px(12.0))
            .flex()
            .flex_col()
            .gap(px(8.0))
            .child(
                div()
                    .flex()
                    .flex_wrap()
                    .items_center()
                    .gap(px(SPACE_M))
                    .child(if v.ok {
                        tag("ob-verify-ok", TagState::Done, "Agent replied", motion)
                    } else {
                        tag(
                            "ob-verify-block",
                            TagState::Block,
                            "Agent did not reply",
                            motion,
                        )
                    })
                    .child(mono(&line, if v.ok { MUTED } else { DANGER })),
            );
        if !v.ok && !v.detail.is_empty() {
            strip = strip.child(row_desc(&v.detail));
        }
        if !v.log.is_empty() {
            let show_log = window.use_keyed_state("ob-show-verify-log", cx, |_, _| false);
            let log_open = *show_log.read(cx);
            let toggle = cx.listener(move |_this, _: &ClickEvent, _w, cx| {
                show_log.update(cx, |open, cx| {
                    *open = !*open;
                    cx.notify();
                });
            });
            strip = strip.child(
                small_action(
                    "ob-verify-log-toggle",
                    if log_open {
                        "chevron-down"
                    } else {
                        "chevron-right"
                    },
                    if log_open {
                        "Hide the full check"
                    } else {
                        "Show the full check"
                    },
                )
                .on_click(toggle),
            );
            if log_open {
                strip = strip.child(
                    well()
                        .id("ob-verify-log")
                        .max_h(px(220.0))
                        .overflow_y_scroll()
                        .p(px(12.0))
                        .font_family(CODE)
                        .text_size(px(12.0))
                        .line_height(px(17.0))
                        .text_color(paint(INK_2))
                        .whitespace_normal()
                        .child(v.log.clone()),
                );
            }
        }
        page = page.child(strip);
    }

    page
}

// ---- step 2: the catalogs ----

fn knowledge_step(
    packs: &[PackRow],
    loaded: bool,
    update: Option<&AppUpdate>,
    motion: bool,
    cx: &mut Context<Kriko>,
) -> Div {
    let install = cx.listener(|this, _: &ClickEvent, _w, cx| this.install_pack_file(cx));
    let refresh = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_packs(cx));
    let controls = div()
        .flex()
        .flex_wrap()
        .gap(px(8.0))
        .child(
            small_action("ob-packs-install", "download", "Install from a file").on_click(install),
        )
        .child(small_action("ob-packs-refresh", "refresh", "Refresh").on_click(refresh));

    let mut page = card()
        .flex()
        .flex_col()
        .gap(px(SPACE_M))
        .px(px(SPACE_L))
        .py(px(SPACE_L))
        .child(card_head_row(
            "layers",
            "Catalogs",
            Some(controls.into_any_element()),
            motion,
        ));

    if packs.is_empty() {
        let install = cx.listener(|this, _: &ClickEvent, _w, cx| this.install_pack_file(cx));
        page = page.child(
            div()
                .flex()
                .flex_col()
                .items_center()
                .gap(px(12.0))
                .py(px(24.0))
                .child(
                    well()
                        .size(px(48.0))
                        .flex()
                        .items_center()
                        .justify_center()
                        .child(icon("download", 20.0).text_color(paint(MUTED))),
                )
                .child(row_title(if loaded {
                    "No catalogs yet"
                } else {
                    "Reading your catalogs"
                }))
                .child(
                    row_desc(if loaded {
                        "Install one in Overview, or load a .kpack file."
                    } else {
                        "The engine has not sent the catalog list yet."
                    })
                    .max_w(px(460.0))
                    .text_align(gpui::TextAlign::Center),
                )
                .child(key("ob-packs-empty-install", "Install from a file").on_click(install)),
        );
    } else {
        for (i, pack) in packs.iter().enumerate() {
            if i > 0 {
                page = page.child(hairline());
            }
            let id = pack.id.clone();
            let want = !pack.enabled;
            let toggle = cx.listener(move |this, _: &ClickEvent, _w, cx| {
                this.set_pack_enabled(id.clone(), want, cx);
            });

            let mut line = Vec::new();
            if !pack.version.is_empty() {
                line.push(format!("v{}", pack.version));
            }
            line.push(format!("{} products", pack.subjects));
            line.push(format!("{} claims", pack.claims));
            if !pack.enabled {
                line.push("off".to_string());
            }

            page = page.child(
                div()
                    .flex()
                    .items_center()
                    .justify_between()
                    .gap(px(16.0))
                    .py(px(SPACE_M))
                    .child(
                        div()
                            .flex_1()
                            .min_w(px(0.0))
                            .flex()
                            .flex_col()
                            .gap(px(4.0))
                            .child(row_title(&pack.name))
                            .child(row_desc(&line.join(" · "))),
                    )
                    .child(switch_anim(("ob-pack-sw", i), pack.enabled, motion).on_click(toggle)),
            );
        }
        let on = packs.iter().filter(|p| p.enabled).count();
        page = page.child(
            div()
                .pt(px(SPACE_XS))
                .child(mono(&format!("{} catalogs · {} on", packs.len(), on), DIM)),
        );
    }

    if let Some(update) = update {
        if update.newer && !update.version.is_empty() {
            page = page.child(hairline()).child(mono(
                &format!("Kriko {} is available.", update.version),
                MUTED,
            ));
        }
    }

    page
}

// ---- step 3: the extension ----

fn extension_step(
    ext: Option<&ExtStatus>,
    checking: bool,
    error: Option<&str>,
    motion: bool,
    cx: &mut Context<Kriko>,
) -> Div {
    let refresh = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_extension(cx));
    let mut page = card()
        .flex()
        .flex_col()
        .gap(px(16.0))
        .px(px(SPACE_L))
        .py(px(SPACE_L))
        .child(card_head_row(
            "extension",
            "Browser extension",
            Some(
                small_action("ob-ext-refresh", "refresh", "Refresh")
                    .on_click(refresh)
                    .into_any_element(),
            ),
            motion,
        ));

    match ext {
        None => {
            if checking {
                page = page.child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(SPACE_M))
                        .child(spinner("ob-ext-spin", 14.0, motion))
                        .child(mono("Reading the extension status…", MUTED)),
                );
            } else {
                let check = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_extension(cx));
                page = page
                    .child(empty_note(error.unwrap_or(
                        "The engine has not sent the extension status yet.",
                    )))
                    .child(small_action("ob-ext-check", "refresh", "Check again").on_click(check));
            }
        }
        Some(e) => {
            let (state, word) = if e.connected {
                (TagState::Live, "Connected")
            } else if e.available {
                (TagState::Queue, "Not connected")
            } else {
                (TagState::Block, "Unavailable")
            };
            page = page.child(
                div()
                    .flex()
                    .flex_wrap()
                    .items_center()
                    .gap(px(8.0))
                    .child(tag("ob-ext-state", state, word, motion))
                    .when(e.connected, |d| {
                        d.child(tag("ob-ext-done", TagState::Done, "Done", motion))
                    }),
            );

            let lead = if e.connected {
                "The extension is connected. Pages you open are read beside the listing."
            } else if e.available {
                "The extension is ready but has not reached Kriko. Set it up once, then read beside any listing."
            } else {
                "This build has no browser extension. Checks still work from Run and Chat."
            };
            page = page.child(row_desc(lead));

            if !e.version.is_empty() || e.port > 0 || !e.browsers.is_empty() || e.hits > 0 {
                let mut details = div().flex().flex_wrap().gap(px(SPACE_S));
                if !e.version.is_empty() {
                    details = details.child(chip(&format!("version {}", e.version)));
                }
                if e.port > 0 {
                    details = details.child(chip(&format!("port {}", e.port)));
                }
                if !e.browsers.is_empty() {
                    details = details.child(chip(&format!(
                        "{} browser{}",
                        e.browsers.len(),
                        if e.browsers.len() == 1 { "" } else { "s" }
                    )));
                }
                if e.hits > 0 {
                    details = details.child(chip(&format!("{} pages", e.hits)));
                }
                page = page.child(details);
            }

            if e.connected {
                page = page.child(row_desc("Nothing else to set up."));
            } else if e.available {
                let setup = cx.listener(|this, _: &ClickEvent, _w, cx| {
                    this.tab = Tab::Extension;
                    this.on_open_tab(cx);
                    this.finish_onboarding(cx);
                });
                page = page
                    .child(key("ob-ext-setup", "Set up the extension").on_click(setup))
                    .child(row_desc("Opens Browser extension, where the steps are."));
                if e.ever_connected {
                    page = page.child(mono("Seen before. Open a page to check in again.", DIM));
                }
            } else {
                page = page.child(
                    div()
                        .flex()
                        .items_center()
                        .gap(px(12.0))
                        .child(
                            well()
                                .p(px(SPACE_M))
                                .flex()
                                .child(icon("globe", 18.0).text_color(paint(MUTED))),
                        )
                        .child(row_desc(
                            "You can keep checking products in Kriko without it.",
                        )),
                );
            }
        }
    }

    page
}

// ---- small builders ----

/// A ghost-sized action with its glyph before the word. `ghost` appends its
/// own label, so the word here is a child of the caller's choosing.
fn small_action(id: impl Into<gpui::ElementId>, icon_name: &str, label: &str) -> Stateful<Div> {
    ghost(id, "")
        .h(px(40.0))
        .px(px(SPACE_L))
        .gap(px(SPACE_S))
        .child(icon(icon_name, 13.0).text_color(paint(MUTED)))
        .child(div().text_size(px(13.0)).child(label.to_string()))
}

/// The letters on an agent's well: one per word, or the first two letters of
/// a one-word name. Nothing is invented for a name with no letters.
fn glyph_initials(label: &str) -> String {
    let words: Vec<&str> = label.split_whitespace().collect();
    let mut out = String::new();
    if words.len() >= 2 {
        for word in words.iter().take(2) {
            if let Some(c) = word.chars().next() {
                out.extend(c.to_uppercase());
            }
        }
    } else {
        out = label
            .chars()
            .filter(|c| !c.is_whitespace())
            .take(2)
            .collect::<String>()
            .to_uppercase();
    }
    if out.is_empty() {
        "?".into()
    } else {
        out
    }
}
