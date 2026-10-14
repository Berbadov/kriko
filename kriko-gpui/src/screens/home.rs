//! Home: what you were doing, what you saved, and the shape of the knowledge.
//! Recent work and drafts side by side, then the graphs. The next-step card
//! routes an empty or returning Home to a real action from current engine facts.
//! Everything comes from the engine: `/api/history`, `/api/compare-drafts`,
//! `/api/status` and `/api/packs`.

use gpui::{
    div, prelude::*, px, rgb, rgba, relative, ClickEvent, Context, Div, FontWeight, Stateful,
    Styled, Window,
};

use crate::app::{Kriko, Tab};
use crate::live::history::{ago, month_buckets, now_secs, Item};
use crate::screens::history::clip;
use crate::screens::{empty_note, mono, plate_s};
use crate::screens::guidance;
use crate::theme::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum HomeStep {
    InstallCatalog,
    EnableCatalog,
    ConnectAgent,
    FirstCheck,
    ConnectExtension,
    AnotherCheck,
}

impl HomeStep {
    fn id(self) -> &'static str {
        match self {
            Self::InstallCatalog => "home-install-catalog",
            Self::EnableCatalog => "home-enable-catalog",
            Self::ConnectAgent => "home-connect-agent",
            Self::FirstCheck => "home-first-check",
            Self::ConnectExtension => "home-connect-extension",
            Self::AnotherCheck => "home-another-check",
        }
    }

    fn title(self) -> &'static str {
        match self {
            Self::InstallCatalog => "Install a catalog",
            Self::EnableCatalog => "Switch on a catalog",
            Self::ConnectAgent => "Set up an agent",
            Self::FirstCheck => "Start your first check",
            Self::ConnectExtension => "Use Kriko on listing pages",
            Self::AnotherCheck => "Check another product",
        }
    }

    fn detail(self) -> &'static str {
        match self {
            Self::InstallCatalog => "Choose a catalog in Overview to search its known products. Once an agent and browser extension are available, Quick Look can also start from a listing without a catalog.",
            Self::EnableCatalog => "All installed catalogs are off. Switch one on in Overview to search known products. Once an agent and browser extension are available, Quick Look can also start from a listing.",
            Self::ConnectAgent => "No agent can run a check yet. Agents shows what is available and what needs setup.",
            Self::FirstCheck => "Search a product title in Run, or open a product URL in your browser and use Quick Look on the listing. Then choose an available agent.",
            Self::ConnectExtension => "Set up the browser extension to check pages as you read them. You can also run checks here.",
            Self::AnotherCheck => "Search another product title in Run, or open its URL in your browser and use Quick Look from the listing.",
        }
    }

    fn button(self) -> &'static str {
        match self {
            Self::InstallCatalog | Self::EnableCatalog => "Open Overview",
            Self::ConnectAgent => "Open Agents",
            Self::FirstCheck | Self::AnotherCheck => "Start a check",
            Self::ConnectExtension => "Set up extension",
        }
    }

    fn destination(self) -> Tab {
        match self {
            Self::InstallCatalog | Self::EnableCatalog => Tab::Overview,
            Self::ConnectAgent => Tab::Agents,
            Self::FirstCheck | Self::AnotherCheck => Tab::Run,
            Self::ConnectExtension => Tab::Extension,
        }
    }
}

/// The top action on Home follows facts that have actually arrived from the
/// engine. Unknown slices stay quiet while they load or if a request failed.
fn next_home_step(
    catalogs: Option<(usize, usize)>,
    agents_ready: Option<bool>,
    has_checks: Option<bool>,
    extension: Option<(bool, bool)>,
) -> Option<HomeStep> {
    let (all, enabled) = catalogs?;
    if all == 0 {
        return Some(HomeStep::InstallCatalog);
    }
    if enabled == 0 {
        return Some(HomeStep::EnableCatalog);
    }
    if !agents_ready? {
        return Some(HomeStep::ConnectAgent);
    }
    if !has_checks? {
        return Some(HomeStep::FirstCheck);
    }
    let (extension_available, extension_seen) = extension?;
    if extension_available && !extension_seen {
        return Some(HomeStep::ConnectExtension);
    }
    Some(HomeStep::AnotherCheck)
}

fn quick_look_available(step: HomeStep, agents_ready: Option<bool>, extension_available: bool) -> bool {
    matches!(step, HomeStep::InstallCatalog | HomeStep::EnableCatalog)
        && agents_ready == Some(true)
        && extension_available
}

fn next_step_card(app: &Kriko, cx: &mut Context<Kriko>) -> Option<gpui::AnyElement> {
    let h = &app.live.history;
    let catalogs = h.packs.as_ref().map(|packs| {
        (packs.len(), packs.iter().filter(|pack| pack.enabled).count())
    });
    let agents_ready = app.live.run.prefs_loaded.then(|| {
        app.live.run.harnesses.iter().any(|h| matches!(h.state, crate::live::run::RunState::Ready))
    });
    let has_checks = h.loaded.then(|| !h.items.is_empty());
    let extension = if has_checks == Some(true) {
        app.live.knowledge.ext.as_ref().map(|e| (e.available, e.ever_connected))
    } else {
        None
    };
    let step = next_home_step(catalogs, agents_ready, has_checks, extension);
    let Some(step) = step else {
        let refresh = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.refresh_history(cx);
            this.refresh_agents(cx);
            this.refresh_extension(cx);
            cx.notify();
        });
        return Some(guidance::next_step(
            "home-setup-loading",
            "Checking your setup",
            "Some setup details are still loading or a request failed. Check again to retry catalogs, agents, and recent checks.",
            ghost("home-setup-refresh", "Check again").on_click(refresh).into_any_element(),
            app.motion,
        ));
    };
    let destination = step.destination();
    let action = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.tab = destination;
        this.on_open_tab(cx);
        match destination {
            Tab::Run => {
                this.refresh_jobs(cx);
                this.refresh_agents(cx);
            }
            Tab::Agents => this.refresh_agents(cx),
            _ => {}
        }
        cx.notify();
    });
    let primary = key("home-next-step", step.button()).on_click(action).into_any_element();
    let extension_available = app.live.knowledge.ext.as_ref().is_some_and(|e| e.available);
    let controls = if quick_look_available(step, agents_ready, extension_available) {
        let quick_look = cx.listener(|this, _: &ClickEvent, _w, cx| {
            this.tab = Tab::Extension;
            this.on_open_tab(cx);
            cx.notify();
        });
        div().flex().items_center().gap(px(8.0))
            .child(primary)
            .child(ghost("home-quick-look", "Quick Look a product").on_click(quick_look))
            .into_any_element()
    } else {
        primary
    };
    Some(guidance::next_step(
        step.id(),
        step.title(),
        step.detail(),
        controls,
        app.motion,
    ))
}

/// One recent check: what it was about, which catalog, when. Info, no verdict.
fn recent_row(cx: &mut Context<Kriko>, ri: usize, check: &Item, now: i64) -> Stateful<Div> {
    let open_history = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::History;
        this.page = 0;
        cx.notify();
    });
    div()
        .id(("home-recent", ri))
        .py(px(10.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .gap(px(16.0))
        .ml(px(-8.0))
        .mr(px(-8.0))
        .rounded(px(10.0))
        .cursor_pointer()
        .hover(|s| s.bg(rgba(GLASS_1)))
        .on_click(open_history)
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
                        .text_size(px(15.0))
                        .text_color(rgb(INK))
                        .child(check.label.clone()),
                )
                .child(mono(&clip(&check.pack_line(), 48), MUTED)),
        )
        .child(
            div()
                .w(px(110.0))
                .flex()
                .items_center()
                .justify_end()
                .child(mono(&ago(check.ts, now), DIM)),
        )
}

/// A saved comparison draft, openable straight into Compare. `subjects` are
/// the products' names, read from the history by lookup id.
fn draft_row(cx: &mut Context<Kriko>, i: usize, name: &str, subjects: &str) -> Stateful<Div> {
    // Compare loads its own drafts; Home only takes you there.
    let open_draft = cx.listener(move |this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::Compare;
        cx.notify();
    });
    div()
        .id(("home-draft", i))
        .py(px(10.0))
        .px(px(8.0))
        .flex()
        .items_center()
        .gap(px(16.0))
        .ml(px(-8.0))
        .mr(px(-8.0))
        .rounded(px(10.0))
        .cursor_pointer()
        .hover(|s| s.bg(rgba(GLASS_1)))
        .on_click(open_draft)
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .flex()
                .flex_col()
                .gap(px(4.0))
                .child(
                    div()
                        .font_family(SANS)
                        .font_weight(FontWeight::SEMIBOLD)
                        .text_size(px(15.0))
                        .text_color(rgb(INK))
                        .child(name.to_string()),
                )
                .child(
                    div()
                        .font_family(SANS)
                        .text_size(px(13.0))
                        .text_color(rgb(MUTED))
                        .child(subjects.to_string()),
                ),
        )
        .child(icon("compare", 16.0).text_color(rgb(DIM)))
}

/// The activity graph: one column per month, the bar as tall as the count.
fn checks_graph(months: &[(String, u32)]) -> Div {
    let max = months.iter().map(|(_, v)| *v).max().unwrap_or(1).max(1) as f32;
    let mut cols = div().flex().items_end().gap(px(10.0));
    for (label, value) in months {
        let height = 10.0 + 110.0 * (*value as f32) / max;
        cols = cols.child(
            div()
                .flex_1()
                .flex()
                .flex_col()
                .items_center()
                .gap(px(8.0))
                .child(
                    div()
                        .w_full()
                        .max_w(px(28.0))
                        .flex()
                        .flex_col()
                        .justify_end()
                        .h(px(120.0))
                        .child(
                            div()
                                .w_full()
                                .h(px(if *value == 0 { 3.0 } else { height }))
                                .rounded(px(3.0))
                                .bg(rgb(ICE))
                                .opacity(if *value == 0 {
                                    0.15
                                } else {
                                    0.55 + 0.45 * (*value as f32) / max
                                })
                                .shadow(vec![shadow(0xbfe4ff40, 0.0, 0.0, 8.0, 0.0)]),
                        ),
                )
                .child(
                    div()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(DIM))
                        .child(label.clone()),
                ),
        );
    }
    cols
}

/// Horizontal bars, longest on top: a label, a bar as long as its share of
/// the biggest value, and the figures at the right.
fn bar_rows(rows: &[(String, f32, String)]) -> Div {
    let max = rows.iter().map(|r| r.1).fold(0.0f32, f32::max).max(1.0);
    let mut graph = div().flex().flex_col().gap(px(10.0));
    for (label, value, figure) in rows {
        graph = graph.child(
            div()
                .flex()
                .items_center()
                .gap(px(10.0))
                .child(
                    div()
                        .w(px(130.0))
                        .font_family(MONO)
                        .text_size(px(11.0))
                        .text_color(rgb(MUTED))
                        .child(label.clone()),
                )
                .child(
                    div()
                        .flex_1()
                        .h(px(10.0))
                        .rounded(px(2.0))
                        .bg(rgb(WELL))
                        .border_1()
                        .border_color(rgba(HAIRLINE))
                        .child(
                            div()
                                .h_full()
                                .w(relative(value / max))
                                .rounded(px(2.0))
                                .bg(rgb(ICE))
                                .opacity(0.8),
                        ),
                )
                .child(
                    div()
                        .w(px(70.0))
                        .flex()
                        .justify_end()
                        .font_family(MONO)
                        .text_size(px(10.0))
                        .text_color(rgb(DIM))
                        .child(figure.clone()),
                ),
        );
    }
    graph
}

/// The launch notice: a newer Kriko is published. The app opens on Home, so
/// this is where the reader sees it without going to About. Windows offers an
/// explicit install action; other platforms link to the release downloads.
fn update_card(app: &Kriko, _cx: &mut Context<Kriko>) -> Option<Div> {
    let k = &app.live.knowledge;
    let offer = k.app_update.as_ref().filter(|u| u.newer)?;
    let busy = k.app_update_busy;
    #[cfg(windows)]
    let line = if busy {
        "Installing the update. Kriko will close and reopen.".to_string()
    } else {
        format!("Version {} is available. Installing keeps your catalogs and history.", offer.version)
    };
    #[cfg(not(windows))]
    let line = if busy {
        "Preparing the update information.".to_string()
    } else {
        format!("Version {} is available. Download it from Releases and follow the manual install steps.", offer.version)
    };
    let mut row = div()
        .flex()
        .items_center()
        .justify_between()
        .gap(px(24.0))
        .child(mono(&line, INK_2).min_w(px(0.0)));
    #[cfg(windows)]
    let action = if !busy {
        Some(
            key("home-app-update-install", "Install and restart")
                .on_click(_cx.listener(|this, _: &ClickEvent, _w, cx| this.install_app_update(cx)))
                .into_any_element(),
        )
    } else {
        None
    };
    #[cfg(not(windows))]
    let action = if !busy {
        let releases_url = if app.live.health.releases_url.is_empty() {
            "https://github.com/Berbadov/kriko/releases".to_string()
        } else {
            app.live.health.releases_url.clone()
        };
        Some(
            key("home-app-update-releases", "Open release downloads")
                .on_click(move |_, _, cx| cx.open_url(&releases_url))
                .into_any_element(),
        )
    } else {
        None
    };
    if let Some(action) = action {
        row = row.child(action);
    }
    let mut notice = card().flex().flex_col().gap(px(10.0)).child(eyebrow("Updates")).child(row);
    if let Some(note) = &k.app_update_note {
        notice = notice.child(mono(note, DIM));
    }
    Some(notice)
}

pub fn home(app: &mut Kriko, _window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let open_history = cx.listener(|this, _: &ClickEvent, _w, cx| {
        this.tab = Tab::History;
        this.page = 0;
        cx.notify();
    });
    let now = now_secs();
    let h = &app.live.history;

    // ---- recent work: the four newest checks ----
    let mut recent = card().flex().flex_col();
    recent = recent.child(div().mb(px(SPACE_TITLE)).child(eyebrow("Recent work")));
    if !h.loaded {
        recent = recent.child(empty_note("Reading your history from the engine."));
    } else if h.items.is_empty() {
        recent = recent.child(empty_note("No checks yet. The next one you run shows up here."));
    } else {
        let shown = h.items.len().min(4);
        for (ri, check) in h.items.iter().take(shown).enumerate() {
            recent = recent
                .child(recent_row(cx, ri, check, now))
                .when(ri + 1 < shown, |d| d.child(hairline()));
        }
        recent = recent.child(
            div()
                .mt(px(12.0))
                .flex()
                .items_center()
                .justify_end()
                .child(plate_s("home-all", "All history").on_click(open_history)),
        );
    }

    // ---- drafts: the saved comparisons ----
    let mut drafts = card().flex().flex_col();
    drafts = drafts.child(div().mb(px(SPACE_TITLE)).child(eyebrow("Drafts")));
    if !h.drafts_loaded {
        let retry = cx.listener(|this, _: &ClickEvent, _w, cx| this.refresh_history(cx));
        drafts = drafts
            .child(empty_note("Drafts have not loaded yet. Check again if the request failed."))
            .child(ghost("home-refresh-drafts", "Check again").on_click(retry));
    } else if h.drafts.is_empty() {
        let (destination, label, said) = if h.items.is_empty() {
            (Tab::Run, "Start a check", "Run checks first, then line them up in Compare.")
        } else {
            (Tab::Compare, "Open Compare", "Choose saved checks in Compare to create a comparison.")
        };
        let go = cx.listener(move |this, _: &ClickEvent, _w, cx| {
            this.tab = destination;
            if destination == Tab::Compare {
                this.refresh_compare(cx);
            } else {
                this.refresh_jobs(cx);
                this.refresh_agents(cx);
            }
            cx.notify();
        });
        drafts = drafts
            .child(empty_note(&format!("No saved comparisons yet. {said}")))
            .child(div().mt(px(10.0)).child(ghost("home-empty-drafts", label).on_click(go)));
    } else {
        let n = h.drafts.len();
        let rows: Vec<(String, String)> = h
            .drafts
            .iter()
            .map(|d| {
                let names: Vec<&str> =
                    d.lookup_ids.iter().filter_map(|id| h.label_of(id)).collect();
                let line = if names.is_empty() {
                    format!("{} products", d.lookup_ids.len())
                } else {
                    names.join(" · ")
                };
                (d.name.clone(), line)
            })
            .collect();
        for (i, (name, line)) in rows.iter().enumerate() {
            drafts = drafts
                .child(draft_row(cx, i, name, line))
                .when(i + 1 < n, |d| d.child(hairline()));
        }
    }

    // ---- the graphs ----
    let checks_body: gpui::AnyElement = if h.loaded && !h.items.is_empty() {
        let months = month_buckets(h.items.iter().filter_map(|i| i.ts), now, 6);
        checks_graph(&months).into_any_element()
    } else if h.loaded {
        empty_note("No checks to count yet.").into_any_element()
    } else {
        empty_note("Check counts have not loaded yet. Use Check again in the next step above.").into_any_element()
    };
    let checks_card = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Checks per month"))
        .child(checks_body);

    let claims_body: gpui::AnyElement = match &h.counts {
        Some(c) => bar_rows(&[
            ("subjects".to_string(), c.subjects as f32, c.subjects.to_string()),
            ("claims".to_string(), c.claims as f32, c.claims.to_string()),
            ("sources behind them".to_string(), c.evidence as f32, c.evidence.to_string()),
        ])
        .into_any_element(),
        None => empty_note("Evidence counts have not loaded yet. Use Check again in the next step above.").into_any_element(),
    };
    let claims_card = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Evidence in the store"))
        .child(claims_body);

    let packs_body: gpui::AnyElement = match &h.packs {
        Some(packs) => {
            let mut live: Vec<_> = packs.iter().filter(|p| p.enabled).collect();
            live.sort_by(|a, b| b.claims.cmp(&a.claims));
            if live.is_empty() {
                // Either nothing is installed (every fresh install) or it is
                // all switched off; both are fixed on the Knowledge screen,
                // so the note is the way there.
                let go = cx.listener(|this, _: &ClickEvent, _w, cx| {
                    this.tab = Tab::Overview;
                    this.on_open_tab(cx);
                    cx.notify();
                });
                let say = if packs.is_empty() {
                    "No catalog installed yet. Open Overview to install one."
                } else {
                    "Every catalog is switched off. Open Overview to switch one on."
                };
                div().id("home-no-catalog").cursor_pointer().on_click(go)
                    .child(empty_note(say)).into_any_element()
            } else {
                let rows: Vec<(String, f32, String)> = live
                    .iter()
                    .take(4)
                    .map(|p| {
                        (
                            clip(&p.name, 20),
                            p.claims as f32,
                            format!("{} claims", p.claims),
                        )
                    })
                    .collect();
                bar_rows(&rows).into_any_element()
            }
        }
        None => empty_note("Catalog details have not loaded yet. Use Check again in the next step above.").into_any_element(),
    };
    let packs_card = card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Claims per catalog"))
        .child(packs_body);

    // Recent work and drafts side by side from 300 px each; the three graphs
    // side by side from 240 px each. Each row shares one height.
    let mut column = div().flex().flex_col().gap(px(SPACE_SECTION));
    if let Some(notice) = update_card(app, cx) {
        column = column.child(notice);
    }
    if let Some(next) = next_step_card(app, cx) {
        column = column.child(next);
    }
    column
        .child(grid(app.content_w, 300.0, vec![recent, drafts]))
        .child(grid(app.content_w, 240.0, vec![checks_card, claims_card, packs_card]))
}

#[cfg(test)]
mod guidance_tests {
    use super::{next_home_step, quick_look_available, HomeStep};

    #[test]
    fn home_waits_for_live_facts_before_recommending_a_route() {
        assert_eq!(next_home_step(None, Some(true), Some(false), None), None);
        assert_eq!(next_home_step(Some((1, 1)), None, Some(false), None), None);
    }

    #[test]
    fn first_time_path_leads_from_catalog_to_agent_to_check() {
        assert_eq!(next_home_step(Some((0, 0)), None, None, None), Some(HomeStep::InstallCatalog));
        assert_eq!(next_home_step(Some((2, 0)), None, None, None), Some(HomeStep::EnableCatalog));
        assert_eq!(next_home_step(Some((2, 1)), Some(false), None, None), Some(HomeStep::ConnectAgent));
        assert_eq!(next_home_step(Some((2, 1)), Some(true), Some(false), None), Some(HomeStep::FirstCheck));
    }

    #[test]
    fn returning_reader_gets_extension_then_another_check() {
        let ready = (Some((1, 1)), Some(true), Some(true));
        assert_eq!(next_home_step(ready.0, ready.1, ready.2, Some((true, false))), Some(HomeStep::ConnectExtension));
        assert_eq!(next_home_step(ready.0, ready.1, ready.2, Some((true, true))), Some(HomeStep::AnotherCheck));
        assert_eq!(next_home_step(ready.0, ready.1, ready.2, Some((false, false))), Some(HomeStep::AnotherCheck));
    }

    #[test]
    fn quick_look_stays_available_without_catalogs_when_its_requirements_are_known() {
        assert!(quick_look_available(HomeStep::InstallCatalog, Some(true), true));
        assert!(quick_look_available(HomeStep::EnableCatalog, Some(true), true));
        assert!(!quick_look_available(HomeStep::InstallCatalog, Some(false), true));
        assert!(!quick_look_available(HomeStep::InstallCatalog, Some(true), false));
        assert!(!quick_look_available(HomeStep::FirstCheck, Some(true), true));
    }
}
