//! Run: one check, from question to stored claims. The subject banner holds
//! the job the engine is running (or ran last) and the phase stepper driven
//! from it; the lane is that job's agent; the feed is the engine's own feed
//! for it. No verdicts anywhere: when the run ends, the claims are stored.
//!
//! Everything here is read from `live::run`; while that has not arrived, or
//! the engine has no job, a quiet note stands in.

use gpui::{
    div, linear_color_stop, linear_gradient, prelude::*, px, rgb, rgba,
    Context, Div, FontWeight, Stateful, Styled, Window,
};

use crate::app::{Field, Kriko, Tab};
use crate::api::{self, Value};
use crate::live::run::{ago, mark_for, Job, Stage};
use crate::marks::{mark_tile, phase_beat};
use crate::screens::{empty_note, guidance, mono, plate_s, row_desc, row_title};
use crate::theme::*;

/// The run's phases, in order, as the LEDs name them.
const PHASES: [&str; 4] = ["QUEUED", "READING", "GROUNDING", "STORED"];

/// A small choice chip: one answer to a question, one agent to pick. The
/// chosen one runs in the brand blue.
pub fn option_chip(id: impl Into<gpui::ElementId>, text: &str, chosen: bool) -> Stateful<Div> {
    chip_skin(chip_base(id), chosen).child(text.to_string())
}

/// A chip for a label that may be longer than the room it is given (words
/// from the engine): the text wraps inside the chip and the chip grows to
/// fit, instead of running out past its border.
pub fn option_chip_wrapping(id: impl Into<gpui::ElementId>, text: &str, chosen: bool) -> Stateful<Div> {
    chip_skin(chip_base(id), chosen)
        .h_auto()
        .min_h(px(30.0))
        .py(px(7.0))
        .child(
            div()
                .flex_1()
                .min_w(px(0.0))
                .whitespace_normal()
                .child(text.to_string()),
        )
}

fn chip_base(id: impl Into<gpui::ElementId>) -> Stateful<Div> {
    div()
        .id(id)
        .h(px(30.0))
        .flex_none()
        .px(px(12.0))
        .flex()
        .items_center()
        .rounded(px(8.0))
        .font_family(MONO)
        .text_size(px(12.0))
        .cursor_pointer()
        .active(|s| s.opacity(0.75))
}

fn chip_skin(base: Stateful<Div>, chosen: bool) -> Stateful<Div> {
    if chosen {
        base.text_color(rgb(0xffffff))
            .border_1()
            .border_color(rgba(0xffffff40))
            .bg(rgb(BRAND))
            .hover(|s| s.bg(rgb(BRAND_HOVER)))
    } else {
        base.text_color(rgb(INK_2))
            .border_1()
            .border_color(rgba(BORDER_CONTROL))
            .bg(rgba(GLASS_1))
            .hover(|s| s.bg(rgba(GLASS_2)))
    }
}

pub fn run(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    let motion = app.motion;
    let mut page = div().flex().flex_col().gap(px(24.0));

    let job = app.live.run.current().cloned();
    match (&job, app.live.run.jobs_loaded) {
        (Some(job), _) => {
            page = page.child(subject_card(app, job, motion, cx));
            if let Some(next) = terminal_next_step(app, job, motion, cx) {
                page = page.child(next);
            }
            if job.kind == "quick_look" && job.done {
                if let Some(evidence) = quick_look_result_card(&job.result, &job.product, &job.state) {
                    page = page.child(evidence);
                }
            }
            if let Some(answer) = answer_card(job) {
                page = page.child(answer);
            }
            if job.kind == "quick_look" && job.done {
                page = page.child(follow_up_card(app, job.id.clone(), window, cx));
            }
            if job.attention.is_some() {
                page = page.child(questions_card(app, job, motion, cx));
            }
        }
        (None, loaded) => {
            let empty = if loaded {
                empty_note("No check has run yet. Start one below.").into_any_element()
            } else {
                let retry = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                    this.refresh_jobs(cx);
                    this.refresh_agents(cx);
                    cx.notify();
                });
                guidance::next_step(
                    "run-job-list-waiting",
                    "Waiting for the engine",
                    "The job list has not arrived yet. Check again to retry while the product search stays below.",
                    ghost("run-jobs-retry", "Check again").on_click(retry).into_any_element(),
                    motion,
                )
            };
            page = page.child(
                card()
                    .flex()
                    .flex_col()
                    .gap(px(12.0))
                    .child(eyebrow("Run"))
                    .child(empty),
            );
        }
    }
    page = page.child(start_card(app, window, cx));
    if let Some(job) = &job {
        page = page.child(lane_card(app, job, motion));
        page = page.child(card().child(crate::screens::logs::job_logs(app, job, cx)));
    }
    page
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RunNext {
    Retry,
    Activity,
}

fn next_for_job(done: bool, stage: Stage, needs_answers: bool) -> Option<RunNext> {
    if !done || needs_answers {
        return None;
    }
    match stage {
        Stage::Failed | Stage::Cancelled => Some(RunNext::Retry),
        Stage::Stored => Some(RunNext::Activity),
        Stage::Queued | Stage::Reading | Stage::Grounding => None,
    }
}

fn terminal_next_step(
    app: &Kriko,
    job: &Job,
    motion: bool,
    cx: &mut Context<Kriko>,
) -> Option<gpui::AnyElement> {
    let next = next_for_job(job.done, job.stage(), job.attention.is_some())?;
    let id = format!("run-next-{}-{}", job.id, match next { RunNext::Retry => "retry", RunNext::Activity => "activity" });
    let job_id = job.id.clone();
    let retrying = next == RunNext::Retry
        && (crate::live::run::retry_pending(&app.live.run.retry_pending, &job.id, std::time::Instant::now())
            || app.live.run.jobs.iter().any(|j| j.retry_of == job.id && !j.done));
    let (title, detail, label) = match next {
        RunNext::Retry => (
            "Run this request again",
            "This attempt remains below with its message and log. Retrying creates a new run with the same request.",
            "Retry run",
        ),
        RunNext::Activity => (
            "Review the finished work",
            "The run has ended. Activity keeps its job updates, and the run details remain below.",
            "Open Activity",
        ),
    };
    let action = match next {
        RunNext::Retry => key("run-retry", if retrying { "Retry submitted…" } else { label })
            .opacity(if retrying { 0.55 } else { 1.0 })
            .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                let now = std::time::Instant::now();
                if crate::live::run::retry_pending(&this.live.run.retry_pending, &job_id, now) {
                    return;
                }
                if this.live.run.jobs.iter().any(|j| j.retry_of == job_id && !j.done) {
                    return;
                }
                this.live.run.retry_pending.insert(job_id.clone(), now);
                cx.notify();
                let path = format!("/api/jobs/{}/retry", api::seg(&job_id));
                let retry_parent = job_id.clone();
                this.fetch(cx, move || api::post(&path, serde_json::json!({})), move |this, reply, cx| {
                    this.note(&reply);
                    let mut submitted = false;
                    if let Ok(v) = reply {
                        let id = api::s(&v, "job_id");
                        if !id.is_empty() {
                            this.live.run.pinned = Some(id);
                            this.live.run.detail = None;
                            submitted = true;
                        }
                    }
                    if !submitted {
                        this.live.run.retry_pending.remove(&retry_parent);
                    }
                    this.refresh_jobs(cx);
                })
            }))
            .into_any_element(),
        RunNext::Activity => ghost("run-open-activity", label)
            .on_click(cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
                this.tab = Tab::Activity;
                this.on_open_tab(cx);
                cx.notify();
            }))
            .into_any_element(),
    };
    Some(guidance::next_step(&id, title, detail, action, motion))
}

fn attention_detail(done: bool) -> &'static str {
    if done {
        "This run has finished with its own answers. Choose yours, then run it again to carry them into a new attempt."
    } else {
        "This run keeps going with its own answers. Choose yours now; when it finishes, run it again to carry them into a new attempt."
    }
}

/// A finished agent run must show its answer, even when the engine returned
/// no answer text. The job feed is a record of work, not the answer itself.
fn answer_card(job: &Job) -> Option<Div> {
    if job.state != "succeeded"
        || !matches!(job.kind.as_str(), "research" | "agenda_run" | "compare_ask")
    {
        return None;
    }
    let answer = job.answer.trim();
    let reason = job.no_answer_why.trim();
    let mut result = card().flex().flex_col().gap(px(10.0)).child(eyebrow("Agent answer"));
    if answer.is_empty() {
        result = result.child(row_title("The agent returned no answer"));
        result = result.child(row_desc(if reason.is_empty() {
            "The run finished without answer text. Check its log and stored findings below."
        } else {
            reason
        }));
    } else {
        result = result.child(row_desc(answer));
    }
    Some(result)
}

/// Render the saved result separately from the narrated job log. This accepts
/// every quick-look backend so a persisted result is still readable in
/// history after the active run has gone away.
pub(crate) fn quick_look_result_card(result: &Value, product: &str, state: &str) -> Option<Div> {
    if result.is_null() {
        return None;
    }
    let model = api::s(result, "model");
    let risks = api::arr(result, "risks");
    let specs = api::arr(result, "specs");
    let dropped = api::n(result, "dropped").unwrap_or(0.0) as usize;
    let coverage = result.get("coverage")
        .or_else(|| result.get("telemetry").and_then(|value| value.get("coverage")))
        .filter(|value| value.is_object());
    let listing = result.get("listing").filter(|value| value.is_object());
    let mut card = card().flex().flex_col().gap(px(10.0))
        .child(eyebrow("Quick Look · saved evidence"));
    let saved_product = api::s(result, "product");
    let label = if !saved_product.is_empty() { saved_product }
        else if !product.is_empty() { product.to_string() }
        else { String::new() };
    if !label.is_empty() {
        card = card.child(row_title(&label));
    }
    let tokens = api::n(result, "tokens_used")
        .map(|n| format!("{} tokens", n as u64))
        .unwrap_or_else(|| "token use not reported".into());
    card = card.child(row_desc(&format!("{} · {tokens} · {} sourced risk(s) · {} sourced product fact(s) · {} unsupported item(s) omitted",
        if model.is_empty() { "Model not reported" } else { &model }, risks.len(), specs.len(), dropped)));
    let diagnostic = result.get("diagnostic").unwrap_or(&Value::Null);
    let diagnostic_message = api::s(diagnostic, "message");
    if risks.is_empty() {
        let message = quick_look_empty_message(result, state);
        if !message.is_empty() {
            card = card.child(row_desc(&message));
        }
    } else if !diagnostic_message.is_empty() {
        card = card.child(row_desc(&diagnostic_message));
    }
    if let Some(coverage) = coverage {
        let count = |key: &str| api::n(coverage, key)
            .map(|value| format!("{value:.0}"))
            .unwrap_or_else(|| "not reported".into());
        card = card.child(mono(&format!(
            "READ {} · PRODUCT MATCHES {} · CHECKED {} · PUBLISHERS {} · CITED {}",
            count("pages_read"), count("pages_relevant"),
            count("pages_extracted"), count("publishers_read"), count("sources_cited")), MUTED));
        let coverage_status = api::s(coverage, "status");
        let status = match coverage_status.as_str() {
            "supported_findings" => "Evidence checks kept one or more findings",
            "partial" => "Some research or evidence stages were incomplete",
            "no_matching_product_evidence" => "No read page established a match to this exact product",
            "evidence_rejected" => "Candidate findings did not pass the evidence checks",
            "no_supported_findings" => "No sourced risks were kept from the pages read",
            _ if risks.is_empty() => "No sourced risks were kept in the saved result",
            _ => "Evidence coverage recorded",
        };
        if !risks.is_empty() {
            card = card.child(row_desc(status));
        }
        card = card.child(mono(&format!("Pages checked: {} · candidates rejected: {}",
            count("pages_extracted"), count("rejected_candidates")), DIM));
    } else if risks.is_empty() && diagnostic_message.is_empty() {
        card = card.child(row_desc("No sourced risks were kept in the saved result. Coverage details were not reported."));
    }

    let evidence_pages = api::arr(result, "evidence_pages");
    if !evidence_pages.is_empty() {
        card = card.child(hairline()).child(eyebrow("Pages checked"));
        for (page_index, page) in evidence_pages.iter().enumerate() {
            let url = api::s(page, "url");
            let domain = api::s(page, "domain");
            let excerpt = ["excerpt", "quote", "text", "content"]
                .iter()
                .map(|key| api::s(page, key))
                .find(|text| !text.trim().is_empty())
                .unwrap_or_default();
            if !excerpt.is_empty() {
                card = card.child(row_desc(&short_text(&excerpt, 320)));
            }
            if !url.is_empty() {
                card = card.child(source_link(
                    gpui::ElementId::named_usize("quicklook-page-source", page_index),
                    if domain.is_empty() { "Page" } else { &domain },
                    &url,
                ));
            }
        }
    }

    if let Some(listing) = listing {
        let description = api::s(listing, "description");
        let listing_url = api::s(listing, "url");
        let facts = listing.get("facts").unwrap_or(&Value::Null);
        if !description.is_empty() || !listing_url.is_empty() || !facts.is_null() {
            card = card.child(hairline()).child(eyebrow("Product listing"));
            if !description.is_empty() {
                card = card.child(row_desc(&description));
            }
            if !listing_url.is_empty() {
                card = card.child(source_link("quicklook-listing-source", "Listing", &listing_url));
            }
            for (fact_index, (name, value, quote, url)) in quick_look_listing_facts(facts).into_iter().enumerate() {
                card = card.child(row_title(&format!("{name} · {value}")));
                if !quote.is_empty() {
                    card = card.child(row_desc(&format!("“{quote}”")));
                }
                if !url.is_empty() {
                    card = card.child(source_link(
                        gpui::ElementId::named_usize("quicklook-listing-fact-source", fact_index),
                        "Listing fact",
                        &url,
                    ));
                }
            }
        }
    }
    let assumed = api::s(result, "assumed");
    if !assumed.is_empty() {
        card = card.child(mono(&format!("Variant assumption · {assumed}"), MUTED));
    }
    if let Some(identity) = result.get("identity").filter(|value| value.is_object()) {
        let name = api::s(identity, "canonical_name");
        let variant = api::s(identity, "variant");
        let identifiers = api::arr(identity, "identifiers").iter()
            .filter_map(Value::as_str).collect::<Vec<_>>().join(", ");
        let unknowns = api::arr(identity, "unknowns").iter()
            .filter_map(Value::as_str).collect::<Vec<_>>().join(", ");
        let resolved = identity.get("resolved").and_then(Value::as_bool).unwrap_or(false);
        let identity_line = format!("Identity · {} · {} · {}",
            if name.is_empty() { "product name not reported" } else { &name },
            if variant.is_empty() { "exact variant unresolved" } else { &variant },
            if resolved { "resolved" } else { "unresolved" });
        card = card.child(mono(&identity_line, INK_2));
        if !identifiers.is_empty() {
            card = card.child(mono(&format!("Identifiers · {identifiers}"), MUTED));
        }
        if !unknowns.is_empty() {
            card = card.child(mono(&format!("Still unknown · {unknowns}"), DIM));
        }
    }
    if let Some(pack_identity) = result.get("pack_identity") {
        for fact in quick_look_facts(pack_identity) {
            card = card.child(mono(&format!("Catalog identity · {fact}"), MUTED));
        }
    }
    let runtime = result.get("runtime")
        .filter(|runtime| {
            !api::s(runtime, "requested_device").is_empty()
                || !matches!(api::s(runtime, "device").as_str(), "" | "unknown")
        })
        .or_else(|| result.get("telemetry").and_then(|telemetry| telemetry.get("runtime")))
        .filter(|runtime| runtime.is_object());
    if let Some(runtime) = runtime {
        let requested = api::s(runtime, "requested_device");
        let actual = api::s(runtime, "device");
        let actual = if actual.is_empty() || actual == "unknown" { String::new() } else { actual };
        let device = match (requested.is_empty(), actual.is_empty()) {
            (false, false) => format!("Device · requested {requested}, runtime reported {actual}"),
            (false, true) => format!("Device · requested {requested}, actual use not reported"),
            (true, false) => format!("Device reported · {actual}"),
            (true, true) => String::new(),
        };
        if !device.is_empty() {
            card = card.child(mono(&device, MUTED));
        }
    }

    let verification = result.get("verification").unwrap_or(&Value::Null);
    if verification.is_object() {
        let error = api::s(verification, "error");
        let unsupported = api::arr(verification, "unsupported");
        card = if !error.is_empty() {
            card.child(mono(&format!("Self-check unavailable: {error}"), DANGER))
        } else if unsupported.is_empty() {
            card.child(mono("Self-check: no unsupported risks reported", MUTED))
        } else {
            card.child(mono(&format!("Self-check flagged {} risk(s):", unsupported.len()), DANGER))
        };
        for item in unsupported {
            card = card.child(row_desc(&format!("{} — {}", api::s(item, "title"), api::s(item, "reason"))));
        }
        let note = api::s(verification, "note");
        if !note.is_empty() {
            card = card.child(row_desc(&note));
        }
    } else if let Some(check) = result.get("telemetry").and_then(|telemetry| telemetry.get("self_verify")) {
        card = card.child(row_desc("Model self-check opinions; source quotes remain the evidence gate."));
        if let Some(verdicts) = check.get("verdicts").and_then(Value::as_array) {
            for verdict in verdicts {
                let index = api::n(verdict, "index").unwrap_or(0.0) as usize;
                let title = risks.get(index).map(|risk| api::s(risk, "title")).unwrap_or_default();
                let supported = verdict.get("supported").and_then(Value::as_bool).unwrap_or(false);
                card = card.child(row_desc(&format!("{} · {} · {}", title,
                    if supported { "supported" } else { "flagged" }, api::s(verdict, "reason"))));
            }
        } else {
            card = card.child(row_desc(&format!("Self-check unavailable: {} {}", api::s(check, "status"), api::s(check, "message"))));
        }
    } else {
        card = card.child(mono("Self-check verdict not recorded for this run", DIM));
    }

    if !risks.is_empty() {
        card = card.child(hairline()).child(eyebrow("Sourced risks"));
        for (risk_index, risk) in risks.iter().enumerate() {
            let title = api::s(risk, "title");
            let severity = api::s(risk, "severity");
            card = card.child(row_title(&if severity.is_empty() { title.clone() }
                else { format!("{title} · {severity}") }));
            let body = api::s(risk, "body");
            if !body.is_empty() {
                card = card.child(row_desc(&body));
            }
            let advice = api::s(risk, "advice");
            if !advice.is_empty() {
                card = card.child(mono(&format!("Worth checking · {advice}"), MUTED));
            }
            for (source_index, source) in api::arr(risk, "sources").iter().enumerate() {
                let domain = api::s(source, "domain");
                let url = api::s(source, "url");
                let quote = api::s(source, "quote");
                if !quote.is_empty() {
                    card = card.child(row_desc(&format!("“{quote}”")));
                }
                if !url.is_empty() {
                    card = card.child(source_link(
                        gpui::ElementId::named_usize(format!("quicklook-risk-source-{risk_index}"), source_index),
                        if domain.is_empty() { "Source" } else { &domain },
                        &url,
                    ));
                }
            }
        }
    }
    if !specs.is_empty() {
        card = card.child(hairline()).child(eyebrow("Sourced product facts"));
        for (spec_index, spec) in specs.iter().enumerate() {
            let name = api::s(spec, "name");
            let value = api::s(spec, "value");
            card = card.child(row_title(&format!("{name} · {value}")));
            let quote = api::s(spec, "quote");
            if !quote.is_empty() {
                card = card.child(row_desc(&format!("“{quote}”")));
            }
            let url = api::s(spec, "url");
            if !url.is_empty() {
                let domain = {
                    let domain = api::s(spec, "domain");
                    if domain.is_empty() { "Source".to_string() } else { domain }
                };
                card = card.child(source_link(
                    gpui::ElementId::named_usize("quicklook-spec-source", spec_index),
                    &domain,
                    &url,
                ));
            }
        }
    }
    Some(card)
}

/// Normalize both the result's list of `{name,value}` rows and the older
/// pack-identity map into short, visible product facts.
fn quick_look_facts(value: &Value) -> Vec<String> {
    match value {
        Value::Array(items) => items.iter().filter_map(|item| {
            let name = api::s(item, "name");
            let value = api::s(item, "value");
            if name.is_empty() || value.is_empty() { None } else { Some(format!("{name} · {value}")) }
        }).collect(),
        Value::Object(items) => items.iter().map(|(name, value)| {
            let value = value.as_str().map(str::to_string).unwrap_or_else(|| value.to_string());
            format!("{name} · {value}")
        }).collect(),
        _ => Vec::new(),
    }
}

fn quick_look_listing_facts(value: &Value) -> Vec<(String, String, String, String)> {
    match value {
        Value::Array(items) => items.iter().filter_map(|item| {
            let name = api::s(item, "name");
            let value = api::s(item, "value");
            if name.is_empty() || value.is_empty() {
                None
            } else {
                Some((name, value, api::s(item, "quote"), api::s(item, "url")))
            }
        }).collect(),
        Value::Object(items) => items.iter().map(|(name, value)| {
            let value = value.as_str().map(str::to_string).unwrap_or_else(|| value.to_string());
            (name.clone(), value, String::new(), String::new())
        }).collect(),
        _ => Vec::new(),
    }
}

fn source_link(id: impl Into<gpui::ElementId>, label: &str, url: &str) -> Stateful<Div> {
    let full_label = format!("{label} · {url}");
    let label = if full_label.chars().count() > 92 {
        format!("{}…", full_label.chars().take(91).collect::<String>())
    } else {
        full_label
    };
    let link = url.to_string();
    div()
        .id(id)
        .cursor_pointer()
        .child(mono(&label, ICE))
        .on_click(move |_, _, cx| cx.open_url(&link))
}

fn short_text(text: &str, limit: usize) -> String {
    let flat = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= limit {
        return flat;
    }
    format!("{}…", flat.chars().take(limit.saturating_sub(1)).collect::<String>())
}

fn quick_look_empty_message(result: &Value, state: &str) -> String {
    if !api::arr(result, "risks").is_empty() {
        return String::new();
    }
    let diagnostic = result.get("diagnostic").unwrap_or(&Value::Null);
    let message = api::s(diagnostic, "message");
    let coverage = result.get("coverage")
        .or_else(|| result.get("telemetry").and_then(|value| value.get("coverage")))
        .unwrap_or(&Value::Null);
    let summary = if !message.is_empty() {
        message
    } else {
        match api::s(coverage, "status").as_str() {
            "no_matching_product_evidence" => "No read page established a match to this exact product.".into(),
            "evidence_rejected" => "Candidate risks did not pass the evidence checks on the pages read.".into(),
            "no_supported_findings" => "No sourced risks were kept from the pages read.".into(),
            "partial" => "Some research stages were incomplete, and no sourced risks were kept.".into(),
            _ => "No sourced risks were kept in the saved result.".into(),
        }
    };
    let caveat = if state == "succeeded" {
        "This describes the saved coverage result; it does not prove the product has no problems."
    } else {
        "This result is incomplete and does not establish whether the product has problems."
    };
    format!("{summary} {caveat}")
}

#[cfg(test)]
mod quick_look_result_tests {
    use super::quick_look_empty_message;
    use crate::api::Value;

    #[test]
    fn an_empty_success_describes_coverage_without_claiming_the_product_is_clear() {
        let result: Value = serde_json::json!({
            "risks": [],
            "diagnostic": {"code": "no_issues_found", "message": "No known issues were found in the pages read."},
            "coverage": {"status": "no_supported_findings", "pages_read": 4}
        });
        let message = quick_look_empty_message(&result, "succeeded");
        assert!(message.contains("No known issues were found in the pages read."));
        assert!(message.contains("does not prove the product has no problems."));
    }

    #[test]
    fn an_unmatched_product_is_reported_as_a_coverage_gap() {
        let result: Value = serde_json::json!({
            "risks": [],
            "coverage": {"status": "no_matching_product_evidence"}
        });
        let message = quick_look_empty_message(&result, "succeeded");
        assert!(message.contains("No read page established a match to this exact product."));
        assert!(message.contains("does not prove the product has no problems."));
    }
}

/// #112: a web-searched follow-up, with the product context and source pages
/// kept beside the answer.
fn follow_up_card(
    app: &mut Kriko,
    job_id: String,
    window: &mut Window,
    cx: &mut Context<Kriko>,
) -> Div {
    let ask = app.input_field(Field::QuickAsk, "quick-ask-input", "Ask about this quick look", Some("search"), window, cx);
    let go = cx.listener({
        let job_id = job_id.clone();
        move |this, _: &gpui::ClickEvent, _w, cx| {
            let question = this.quick_ask_input.value.trim().to_string();
            if !question.is_empty() {
                this.start_quick_ask(cx);
                this.quick_ask_input.value.clear();
            }
            let _ = &job_id;
            cx.notify();
        }
    });
    let mut c = card().flex().flex_col().gap(px(10.0)).child(eyebrow("Ask a follow-up"))
        .child(row_desc("Follow-ups search the web using this product's saved listing details and Quick Look evidence."));
    for (ask_index, a) in app.live.run.quick_asks.iter().enumerate() {
        c = c.child(row_title(&a.question));
        if a.done {
            c = c.child(row_desc(if a.answer.is_empty() { "No answer." } else { &a.answer }));
            if !a.sources.is_empty() {
                c = c.child(mono("Sources read", DIM));
                for (source_index, (domain, url)) in a.sources.iter().enumerate() {
                    c = c.child(source_link(
                        gpui::ElementId::named_usize(
                            format!("quick-followup-source-{ask_index}"),
                            source_index,
                        ),
                        if domain.is_empty() { "Source" } else { domain },
                        url,
                    ));
                }
            } else {
                c = c.child(row_desc(if a.message.is_empty() {
                    "No source pages were reported for this answer."
                } else {
                    &a.message
                }));
            }
        } else {
            c = c.child(row_desc("Searching and answering…"));
        }
    }
    if app.live.run.quick_asks_loading && app.live.run.quick_asks.is_empty() {
        c = c.child(row_desc("Loading saved follow-ups…"));
    }
    if let Some(note) = app.live.run.quick_ask_note.clone() {
        c = c.child(row_desc(&note));
    }
    c.child(
        div().flex().items_center().gap(px(8.0))
            .child(ask)
            .child(key("quick-ask-go", if app.live.run.quick_asking { "Asking" } else { "Ask" }).on_click(go)),
    )
}

fn subject_card(app: &Kriko, job: &Job, motion: bool, cx: &mut Context<Kriko>) -> Div {
    let stage = job.stage();
    let terminal = matches!(stage, Stage::Stored | Stage::Failed | Stage::Cancelled);
    let at = stage.index();

    // ---- the stepper: QUEUED - READING - GROUNDING - STORED ----
    let mut stepper = div().flex().items_center().gap(px(8.0));
    for (i, name) in PHASES.iter().enumerate() {
        let ended_badly = matches!(stage, Stage::Failed | Stage::Cancelled) && i == 3;
        let name = if ended_badly {
            if stage == Stage::Failed { "FAILED" } else { "CANCELLED" }
        } else {
            name
        };
        let done = if terminal {
            stage == Stage::Stored && i <= 3
        } else {
            at > i
        };
        let live = !terminal && at == i;
        let lit = live || ended_badly;
        let mut seg = well()
            .h(px(36.0))
            .flex()
            .items_center()
            .px(px(14.0))
            .gap(px(10.0))
            .when(live, |s| {
                s.bg(linear_gradient(
                    180.0,
                    linear_color_stop(hsla(BRAND_HOVER), 0.0),
                    linear_color_stop(hsla(BRAND_LOW), 1.0),
                ))
                .border_color(rgba(0xffffff40))
                .shadow(vec![shadow(0x0f2a9c99, 0.0, 2.0, 8.0, 0.0)])
            });
        let glyph = if live {
            led_ripple(&format!("run-phase-{i}"), motion)
        } else if ended_badly {
            led_matrix(&BANG5, 0xffb86b, 3.0, 1.0)
        } else if done {
            led_matrix(&CHECK5, INK_2, 3.0, 1.0)
        } else {
            led_matrix(&QUEUE5, LED_DIM, 3.0, 1.0)
        };
        seg = seg.child(glyph).child(
            div()
                .font_family(MONO)
                .text_size(px(11.0))
                .text_color(rgb(if live {
                    0xffffff
                } else if lit {
                    0xffb86b
                } else if done {
                    INK_2
                } else {
                    MUTED
                }))
                .child(name),
        );
        stepper = stepper.child(seg);
    }
    stepper = stepper.child(div().flex_1());
    if !job.done {
        let id = job.id.clone();
        let stop = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.stop_job(id.clone(), cx);
            cx.notify();
        });
        stepper = stepper.child(plate_s("run-stop", "Stop").on_click(stop));
    }

    let when = if job.done {
        format!("finished {}", ago(&job.finished_at))
    } else {
        format!("started {}", ago(&job.created_at))
    };
    let heading = if job.done { "Last run · finished" } else { "Running now" };
    let mut meta = vec![when];
    if !job.harness.is_empty() {
        meta.push(format!("with {}", job.harness));
    }
    if !job.model.is_empty() {
        meta.push(format!("model {}", job.model));
    }
    let duration = job.duration_word();
    if !duration.is_empty() {
        meta.push(duration);
    }
    if !job.done {
        meta.push(format!("{}%", (job.progress * 100.0).round() as i64));
    }

    card()
        .flex()
        .flex_col()
        .gap(px(8.0))
        .child(eyebrow(heading))
        .child(
            div()
                .font_family(SANS)
                .font_weight(FontWeight::BOLD)
                .text_size(px(20.0))
                .text_color(rgb(INK))
                .child(app.live.run.task(job)),
        )
        .child(mono(&meta.join(" · "), DIM))
        .when(!job.message.is_empty(), |c| c.child(row_desc(&job.message)))
        .child(div().mt(px(8.0)).child(stepper))
}

/// The questions a run put to the reader, with their options; answering is
/// a new run that carries them.
fn questions_card(app: &Kriko, job: &Job, motion: bool, cx: &mut Context<Kriko>) -> gpui::AnyElement {
    let Some(att) = &job.attention else { return div().into_any_element() };
    let mut c = card().flex().flex_col().gap(px(12.0));
    c = c
        .child(
            div().flex().items_center().justify_between().gap(px(12.0))
                .child(eyebrow("Needs you"))
                .child(tag(format!("run-needs-user-{}", job.id), TagState::Need, "Choose answers", motion)),
        )
        .child(row_desc(&att.say))
        .child(row_desc(attention_detail(job.done)));
    for (qi, q) in att.questions.iter().enumerate() {
        let chosen = app
            .live
            .run
            .answers
            .get(&q.id)
            .cloned()
            .unwrap_or_else(|| q.default.clone());
        let mut options = div().flex().flex_wrap().gap(px(8.0));
        for (oi, opt) in q.options.iter().enumerate() {
            let (qid, o) = (q.id.clone(), opt.clone());
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.pick_answer(qid.clone(), o.clone());
                cx.notify();
            });
            options = options.child(
                option_chip(("run-opt", qi * 16 + oi), opt, *opt == chosen).on_click(pick),
            );
        }
        c = c.child(
            div()
                .flex()
                .flex_col()
                .gap(px(6.0))
                .child(row_title(&q.ask))
                .when(!q.because.is_empty(), |d| d.child(row_desc(&q.because)))
                .child(options),
        );
    }
    if job.done {
        let id = job.id.clone();
        let go = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.answer_job(id.clone(), cx);
            cx.notify();
        });
        c = c.child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(key("run-answer", "Run again with answers").on_click(go))
                .child(row_desc("A new run that carries these answers.")),
        );
    } else {
    }
    arrive(c, format!("run-questions-{}", job.id), motion)
}

fn route_button(
    cx: &mut Context<Kriko>,
    id: &'static str,
    label: &str,
    destination: Tab,
) -> gpui::AnyElement {
    key(id, label)
        .on_click(cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
            this.tab = destination;
            this.on_open_tab(cx);
            match destination {
                Tab::Run => {
                    this.refresh_jobs(cx);
                    this.refresh_agents(cx);
                }
                Tab::Agents => this.refresh_agents(cx),
                Tab::Browse => this.refresh_subjects(cx),
                _ => {}
            }
            cx.notify();
        }))
        .into_any_element()
}

fn quick_look_available(agents_ready: bool, extension_available: bool) -> bool {
    agents_ready && extension_available
}

fn pending_agent_choice_labels(llms_pending: bool, efforts_pending: bool) -> Vec<&'static str> {
    let mut labels = Vec::new();
    if llms_pending {
        labels.push("Checking available models…");
    }
    if efforts_pending {
        labels.push("Checking effort choices…");
    }
    labels
}

/// Start a check: look a subject up, pick it, pick the agent, go.
fn start_card(app: &mut Kriko, window: &mut Window, cx: &mut Context<Kriko>) -> Div {
    // With nothing run yet, starting one is the only thing this screen is
    // for: the form is simply there, with no "New" to find first.
    // The same test the Run card uses for "No check has run yet".
    let first = app.live.run.current().is_none();
    let open = app.live.run.start.open || first;
    let toggle = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        let s = &mut this.live.run.start;
        s.open = !s.open;
        cx.notify();
    });
    let mut c = card().flex().flex_col().gap(px(12.0)).child(
        div()
            .flex()
            .items_center()
            .child(eyebrow("Start a check"))
            .child(div().flex_1())
            .when(!first, |d| d.child(plate_s("run-start-toggle", if open { "Close" } else { "New" }).on_click(toggle))),
    );
    if !open {
        return c;
    }

    if app.live.history.packs.is_none() {
        let check = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.refresh_history(cx);
            this.refresh_agents(cx);
            this.refresh_extension(cx);
            cx.notify();
        });
        let primary = ghost("run-catalog-check", "Check again")
            .on_click(check)
            .into_any_element();
        let can_quick_look = quick_look_available(
            app.live.run.harnesses.iter().any(|h| matches!(h.state, crate::live::run::RunState::Ready)),
            app.live.knowledge.ext.as_ref().is_some_and(|e| e.available),
        );
        let actions = if can_quick_look {
            div().flex().items_center().gap(px(8.0))
                .child(primary)
                .child(route_button(cx, "run-quick-look-pending-catalog", "Quick Look a product", Tab::Extension))
                .into_any_element()
        } else {
            primary
        };
        return c.child(guidance::next_step(
            "run-catalogs-waiting",
            "Catalog details have not loaded",
            "Kriko has not confirmed which catalogs are available. Check again to retry; if an agent and extension are ready, Quick Look can start from a product listing meanwhile.",
            actions,
            app.motion,
        ));
    }
    if let Some(packs) = app.live.history.packs.as_ref() {
        if !packs.iter().any(|pack| pack.enabled) {
            let (title, detail) = if packs.is_empty() {
                ("Install a catalog", "Install a catalog in Overview to search known products. Once an agent and browser extension are available, Quick Look can also start from a listing without a catalog.")
            } else {
                ("Switch on a catalog", "Every installed catalog is off. Switch one on in Overview to search known products. Once an agent and browser extension are available, Quick Look can also start from a listing.")
            };
            let primary = route_button(cx, "run-open-overview", "Open Overview", Tab::Overview);
            let can_quick_look = quick_look_available(
                app.live.run.harnesses.iter().any(|h| matches!(h.state, crate::live::run::RunState::Ready)),
                app.live.knowledge.ext.as_ref().is_some_and(|e| e.available),
            );
            let actions = if can_quick_look {
                div().flex().items_center().gap(px(8.0))
                    .child(primary)
                    .child(route_button(cx, "run-quick-look-listing", "Quick Look a product", Tab::Extension))
                    .into_any_element()
            } else {
                primary
            };
            return c.child(guidance::next_step(
                if packs.is_empty() { "run-no-catalog" } else { "run-catalogs-off" },
                title,
                detail,
                actions,
                app.motion,
            ));
        }
    }

    let search = app.input_field(Field::RunSearch, "run-search", "Find a product...", Some("search"), window, cx);
    let go = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
        this.search_subjects(cx);
        cx.notify();
    });
    c = c.child(
        div()
            .flex()
            .items_center()
            .gap(px(8.0))
            .child(search)
            .child(key("run-search-go", if app.live.run.start.searching { "Looking" } else if app.live.run.start.note.is_empty() { "Search" } else { "Try again" }).on_click(go)),
    );

    let start = &app.live.run.start;
    if let Some(hit) = &start.picked {
        c = c.child(
            well()
                .p(px(12.0))
                .flex()
                .flex_col()
                .gap(px(2.0))
                .child(row_title(&hit.label))
                .child(mono(&hit.pack_id, DIM)),
        );
        // the agent: the preferred one unless the reader picks another
        let chosen = app.live.run.start_harness();
        let mut agents = div().flex().flex_wrap().gap(px(8.0));
        for (i, h) in app.live.run.harnesses.iter().enumerate() {
            if !matches!(h.state, crate::live::run::RunState::Ready) {
                continue;
            }
            let id = h.id.clone();
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.run.start.harness = id.clone();
                cx.notify();
            });
            agents = agents.child(option_chip(("run-agent", i), &h.label, h.id == chosen).on_click(pick));
        }
        let begin = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.start_check(cx);
            cx.notify();
        });
        let back = cx.listener(|this, _: &gpui::ClickEvent, _w, cx| {
            this.live.run.start.picked = None;
            cx.notify();
        });
        let ready = app.live.run.harnesses.iter().any(|h| matches!(h.state, crate::live::run::RunState::Ready));
        c = c.child(mono("RUN WITH", DIM));
        if ready {
            c = c.child(agents);
            if let Some(agent) = app.live.run.harnesses.iter().find(|h| h.id == chosen) {
                for label in pending_agent_choice_labels(agent.llms_pending, agent.efforts_pending) {
                    c = c.child(row_desc(label));
                }
            }
        } else if app.live.run.prefs_loaded {
            c = c.child(guidance::next_step(
                "run-no-ready-agent",
                "Set up an agent",
                "No agent is ready to run this check. Connect or install one in Agents, then come back.",
                route_button(cx, "run-open-agents", "Open Agents", Tab::Agents),
                app.motion,
            ));
        } else {
            c = c.child(empty_note("Checking which agents can run a check."));
        }
        c = c.child(
            div().flex().items_center().gap(px(8.0))
                .when(ready, |d| d.child(key("run-begin", "Start").on_click(begin)))
                .child(ghost("run-back", "Back").on_click(back)),
        );
    } else if start.searched && start.hits.is_empty() && start.note.is_empty() {
        c = c.child(empty_note("Nothing in the installed catalogs matches that."))
            .child(guidance::next_step(
                "run-search-no-match",
                "Browse catalog products",
                "See which products are available in the catalogs installed here.",
                route_button(cx, "run-browse-products", "Open Browse", Tab::Browse),
                app.motion,
            ));
    } else {
        for (i, hit) in start.hits.iter().enumerate() {
            let h = hit.clone();
            let pick = cx.listener(move |this, _: &gpui::ClickEvent, _w, cx| {
                this.live.run.start.picked = Some(h.clone());
                cx.notify();
            });
            c = c.child(
                well()
                    .id(("run-hit", i))
                    .p(px(12.0))
                    .flex()
                    .flex_col()
                    .gap(px(2.0))
                    .cursor_pointer()
                    .hover(|s| s.bg(rgba(GLASS_1)))
                    .on_click(pick)
                    .child(row_title(&hit.label))
                    .child(mono(
                        &format!("{} · {} claims", hit.identity, hit.claims),
                        DIM,
                    )),
            );
        }
    }
    if !start.note.is_empty() {
        c = c.child(row_desc(&start.note));
    }
    c
}

/// The agent doing the job: its mark, what it is doing, how far.
fn lane_card(app: &Kriko, job: &Job, motion: bool) -> Div {
    let agent = if job.harness.is_empty() { "agent" } else { job.harness.as_str() };
    let label = app
        .live
        .run
        .harnesses
        .iter()
        .find(|h| h.id == job.harness)
        .map(|h| h.label.clone())
        .unwrap_or_else(|| if job.harness.is_empty() { "Agent".to_string() } else { job.harness.clone() });
    let phase = job.lane_phase();
    let progress = if job.stage() == Stage::Stored { 100.0 } else { job.progress * 100.0 };
    card()
        .flex()
        .flex_col()
        .gap(px(12.0))
        .child(eyebrow("Agent"))
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(14.0))
                .child(mark_tile("run-lane-tile", mark_for(agent), phase, 48.0, motion))
                .child(
                    div()
                        .flex_1()
                        .min_w(px(0.0))
                        .flex()
                        .flex_col()
                        .gap(px(2.0))
                        .child(
                            div()
                                .flex()
                                .items_center()
                                .justify_between()
                                .gap(px(12.0))
                                .child(row_title(&label))
                                .child(phase_beat("run-lane-beat", phase, motion)),
                        )
                        .child(mono(&app.live.run.task(job), MUTED)),
                ),
        )
        .child(
            div()
                .flex()
                .items_center()
                .gap(px(12.0))
                .child(meter_live("run-lane-meter", progress, 28, !job.done, motion).flex_1())
                .child(if job.done {
                    led_matrix(&CHECK5, INK_2, 3.0, 1.0)
                } else {
                    led_ripple("run-lane", motion)
                }),
        )
}

#[cfg(test)]
mod guidance_tests {
    use super::{attention_detail, next_for_job, pending_agent_choice_labels, quick_look_available, RunNext};
    use crate::live::run::Stage;

    #[test]
    fn active_jobs_and_question_runs_keep_their_own_next_action() {
        assert_eq!(next_for_job(false, Stage::Reading, false), None);
        assert_eq!(next_for_job(true, Stage::Stored, true), None);
        assert!(attention_detail(false).contains("when it finishes"));
        assert!(attention_detail(true).contains("run it again"));
    }

    #[test]
    fn failed_or_stopped_runs_can_be_retried_and_completed_runs_lead_to_activity() {
        assert_eq!(next_for_job(true, Stage::Failed, false), Some(RunNext::Retry));
        assert_eq!(next_for_job(true, Stage::Cancelled, false), Some(RunNext::Retry));
        assert_eq!(next_for_job(true, Stage::Stored, false), Some(RunNext::Activity));
    }

    #[test]
    fn quick_look_is_offered_only_when_an_agent_and_extension_are_available() {
        assert!(quick_look_available(true, true));
        assert!(!quick_look_available(false, true));
        assert!(!quick_look_available(true, false));
    }

    #[test]
    fn run_picker_only_shows_model_and_effort_messages_while_they_are_pending() {
        assert_eq!(pending_agent_choice_labels(false, false), Vec::<&str>::new());
        assert_eq!(pending_agent_choice_labels(true, false), vec!["Checking available models…"]);
        assert_eq!(pending_agent_choice_labels(false, true), vec!["Checking effort choices…"]);
        assert_eq!(pending_agent_choice_labels(true, true), vec![
            "Checking available models…", "Checking effort choices…"
        ]);
    }
}
