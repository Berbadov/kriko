//! What a running job is doing, said for a reader: the action it is on now,
//! the step it has reached, the time it has taken, and the last few things it
//! did. Pure, so the words and the clock are tested without a window; the
//! screens draw them in `screens/action_trail.rs`.
//!
//! The words come from the feed the engine already keeps (`FeedLine`, kinds
//! `search`, `source`, `finding`, `problem`, `note`), so nothing here knows
//! a product, a site or a category.

use super::run::{clip, epoch, now_epoch, FeedLine, Job, Stage};

/// The longest a detail is shown before it is cut with an ellipsis.
pub const ACTION_CHARS: usize = 70;

/// The step names the stepper shows, in order.
const STEPS: [&str; 4] = ["Queued", "Reading", "Grounding", "Stored"];

/// The state of one line of the trail.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Dot {
    Done,
    Running,
    Failed,
}

/// One action, as a verb and what it is about.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Action {
    pub verb: String,
    pub detail: String,
    pub dot: Dot,
}

impl Action {
    /// The line a reader sees: "Reading · example.com/page".
    pub fn text(&self) -> String {
        if self.detail.is_empty() {
            self.verb.clone()
        } else {
            format!("{} · {}", self.verb, self.detail)
        }
    }
}

/// What one feed line did, as `(verb, detail)`. A line that says nothing the
/// reader can use falls back to the job's own message, so the line still
/// says what the job is doing.
pub fn describe_action(line: &FeedLine, message: &str) -> (String, String) {
    match line.kind.as_str() {
        "search" => ("Searching the web".into(), tidy(&search_query(&line.text))),
        "source" => match urls_in(&line.text).first() {
            Some(url) => {
                let more = urls_in(&line.text).len().saturating_sub(1);
                let mut detail = stub(url);
                if more > 0 {
                    detail = format!("{detail} and {more} more");
                }
                ("Reading".into(), detail)
            }
            None => ("Reading a page".into(), String::new()),
        },
        "finding" => (
            "Checking a finding".into(),
            clip(&quoted(&line.text).unwrap_or_else(|| tidy(&line.text)), ACTION_CHARS),
        ),
        "problem" => ("Hit a problem".into(), tidy(&line.text)),
        _ => {
            let said = if message.trim().is_empty() { line.text.as_str() } else { message };
            (tidy(said), String::new())
        }
    }
}

/// The action a job is on now: its last feed line, or, before the first line,
/// what the job is waiting for.
pub fn current(job: &Job) -> Action {
    match job.feed.last() {
        Some(line) => {
            let (verb, detail) = describe_action(line, &job.message);
            let dot = if line.kind == "problem" {
                Dot::Failed
            } else if job.done {
                Dot::Done
            } else {
                Dot::Running
            };
            Action { verb, detail, dot }
        }
        None => Action {
            verb: if job.message.trim().is_empty() {
                "Waiting to start".into()
            } else {
                tidy(&job.message)
            },
            detail: String::new(),
            dot: if job.done { Dot::Done } else { Dot::Running },
        },
    }
}

/// The three actions before the one on now, oldest first: what the job has
/// just done. Each is done, or failed.
pub fn trail(job: &Job) -> Vec<Action> {
    let before = job.feed.len().saturating_sub(1);
    let start = before.saturating_sub(3);
    job.feed[start..before]
        .iter()
        .map(|line| {
            let (verb, detail) = describe_action(line, &job.message);
            let dot = if line.kind == "problem" { Dot::Failed } else { Dot::Done };
            Action { verb, detail, dot }
        })
        .collect()
}

/// Where the job stands, as the stepper names it: "Step 2 of 4 · Reading".
/// A stopped run says so instead of a step.
pub fn step_word(job: &Job) -> String {
    match job.stage() {
        Stage::Failed => "Failed".into(),
        Stage::Cancelled => "Cancelled".into(),
        stage => {
            let index = stage.index();
            format!("Step {} of {} · {}", index + 1, STEPS.len(), STEPS[index])
        }
    }
}

/// Seconds the job has run: to its end once it is done, to `now` while it runs.
pub fn elapsed_secs(job: &Job, now: i64) -> Option<i64> {
    let start = epoch(&job.created_at)?;
    let end = if job.done { epoch(&job.finished_at).unwrap_or(now) } else { now };
    Some((end - start).max(0))
}

/// Seconds the job has run, read from the clock the app itself reads.
pub fn elapsed_now(job: &Job) -> Option<i64> {
    elapsed_secs(job, now_epoch())
}

/// `m:ss` for a run under an hour, `h:mm:ss` beyond that.
pub fn clock(secs: i64) -> String {
    let s = secs.max(0);
    if s >= 3600 {
        format!("{}:{:02}:{:02}", s / 3600, (s % 3600) / 60, s % 60)
    } else {
        format!("{}:{:02}", s / 60, s % 60)
    }
}

/// The search words out of a feed line: `searched "brake fluid"`, `query: …`.
fn search_query(text: &str) -> String {
    let t = text.trim();
    let rest = strip_ci(t, "query:")
        .or_else(|| strip_ci(t, "searched:"))
        .or_else(|| strip_ci(t, "searched"))
        .unwrap_or(t);
    rest.trim()
        .trim_matches(|c: char| c == '"' || c == '“' || c == '”' || c.is_whitespace())
        .to_string()
}

fn strip_ci<'a>(text: &'a str, head: &str) -> Option<&'a str> {
    let cut = head.len();
    if text.len() >= cut && text.is_char_boundary(cut) && text[..cut].eq_ignore_ascii_case(head) {
        Some(&text[cut..])
    } else {
        None
    }
}

/// The title a finding was kept under: the text between curly quotes.
fn quoted(text: &str) -> Option<String> {
    let start = text.find('“')? + '“'.len_utf8();
    let end = text[start..].find('”')? + start;
    let title = text[start..end].trim();
    (!title.is_empty()).then(|| title.to_string())
}

/// Web addresses in a line, without the punctuation that trails them.
fn urls_in(text: &str) -> Vec<String> {
    text.split_whitespace()
        .map(|token| token.trim_end_matches([',', ';', ')', '”', '"', '.']))
        .filter(|token| token.starts_with("http://") || token.starts_with("https://"))
        .map(str::to_string)
        .collect()
}

/// A web address as the reader needs it: the host and the first path part.
/// "https://www.example.com/a/b?c=d" becomes "example.com/a".
fn stub(url: &str) -> String {
    let rest = url.split_once("://").map_or(url, |(_, rest)| rest);
    let (host, path) = match rest.find(['/', '?', '#']) {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, ""),
    };
    let host = host.strip_prefix("www.").unwrap_or(host);
    let first = path
        .trim_start_matches('/')
        .split(['/', '?', '#'])
        .next()
        .unwrap_or("");
    if first.is_empty() {
        host.to_string()
    } else {
        format!("{host}/{first}")
    }
}

/// A line with its web addresses cut to host and path, and clipped.
fn tidy(text: &str) -> String {
    let words: Vec<String> = text
        .split_whitespace()
        .map(|token| {
            if token.starts_with("http://") || token.starts_with("https://") {
                stub(token.trim_end_matches([',', ';', ')', '”', '"', '.']))
            } else {
                token.to_string()
            }
        })
        .collect();
    clip(&words.join(" "), ACTION_CHARS)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::live::run::job_from;
    use serde_json::{json, Value};

    fn line(kind: &str, text: &str) -> FeedLine {
        FeedLine { kind: kind.into(), text: text.into() }
    }

    fn running(feed: Value, message: &str) -> Job {
        job_from(&json!({
            "job_id": "j", "kind": "research", "state": "running", "progress": 0.2,
            "done": false, "message": message, "feed": feed,
            "created_at": "2026-10-14T10:00:00",
            "params": {"harness": "claude-code"}
        }))
    }

    #[test]
    fn a_search_line_says_what_was_searched() {
        let (verb, detail) = describe_action(
            &line("search", "searched \"brake fluid leak 2.0 TDI\""), "");
        assert_eq!(verb, "Searching the web");
        assert_eq!(detail, "brake fluid leak 2.0 TDI");
        let (_, detail) = describe_action(&line("search", "query: brake fluid"), "");
        assert_eq!(detail, "brake fluid");
    }

    #[test]
    fn a_source_line_names_the_host_and_the_page_not_the_whole_url() {
        let (verb, detail) = describe_action(
            &line("source", "fetched https://www.example.com/page/2024?ref=abc"), "");
        assert_eq!(verb, "Reading");
        assert_eq!(detail, "example.com/page");
        let (_, detail) = describe_action(
            &line("source", "read through the page reader https://a.test/x, https://b.test/y"), "");
        assert_eq!(detail, "a.test/x and 1 more");
    }

    #[test]
    fn a_finding_line_is_a_check_and_names_the_finding() {
        let (verb, detail) = describe_action(
            &line("finding", "kept “Worn pads squeal” as claim_12"), "");
        assert_eq!(verb, "Checking a finding");
        assert_eq!(detail, "Worn pads squeal");
    }

    #[test]
    fn a_line_with_no_words_falls_back_to_the_jobs_message() {
        let (verb, detail) = describe_action(&line("note", "started"), "checking 3 findings against their pages");
        assert_eq!(verb, "checking 3 findings against their pages");
        assert!(detail.is_empty());
    }

    #[test]
    fn a_long_address_is_cut_and_a_long_detail_is_clipped() {
        let long = format!("searched \"{}\"", "word ".repeat(40));
        let (_, detail) = describe_action(&line("search", &long), "");
        assert!(detail.chars().count() <= ACTION_CHARS + 1, "{}", detail.chars().count());
        assert!(detail.ends_with('…'));
    }

    #[test]
    fn the_trail_is_the_three_actions_before_the_one_on_now() {
        let job = running(json!([
            {"kind": "search", "text": "searched \"a\""},
            {"kind": "source", "text": "fetched https://x.test/1"},
            {"kind": "problem", "text": "refused https://x.test/2"},
            {"kind": "source", "text": "fetched https://x.test/3"}
        ]), "");
        let items = trail(&job);
        assert_eq!(items.len(), 3);
        assert_eq!(items[0].dot, Dot::Done);
        assert_eq!(items[1].dot, Dot::Done);
        assert_eq!(items[2].dot, Dot::Failed);
        assert_eq!(current(&job).text(), "Reading · x.test/3");
        assert_eq!(current(&job).dot, Dot::Running);
    }

    #[test]
    fn the_trail_holds_at_most_three_and_none_for_a_first_action() {
        let feed: Vec<Value> = (0..6).map(|i| json!({"kind": "source", "text": format!("fetched https://x.test/{i}")})).collect();
        let job = running(json!(feed), "");
        let items = trail(&job);
        assert_eq!(items.len(), 3);
        assert_eq!(items[0].detail, "x.test/2");
        assert!(trail(&running(json!([{"kind": "search", "text": "searched \"a\""}]), "")).is_empty());
    }

    #[test]
    fn a_queued_job_says_what_it_waits_for_and_has_no_trail() {
        let job = running(json!([]), "planning a search");
        assert!(trail(&job).is_empty());
        assert_eq!(current(&job).text(), "planning a search");
    }

    #[test]
    fn the_step_follows_the_stage() {
        assert_eq!(step_word(&running(json!([{"kind": "source", "text": "x"}]), "")), "Step 2 of 4 · Reading");
        assert_eq!(
            step_word(&running(json!([{"kind": "finding", "text": "kept x"}]), "")),
            "Step 3 of 4 · Grounding"
        );
        let stopped = job_from(&json!({"job_id": "j", "kind": "research", "state": "cancelled", "done": true}));
        assert_eq!(step_word(&stopped), "Cancelled");
    }

    #[test]
    fn the_clock_reads_minutes_then_hours() {
        assert_eq!(clock(0), "0:00");
        assert_eq!(clock(7), "0:07");
        assert_eq!(clock(83), "1:23");
        assert_eq!(clock(3725), "1:02:05");
    }

    #[test]
    fn elapsed_time_runs_to_now_while_running_and_to_the_end_once_done() {
        let job = running(json!([]), "");
        let start = epoch("2026-10-14T10:00:00").unwrap();
        assert_eq!(elapsed_secs(&job, start + 83), Some(83));
        let done = job_from(&json!({
            "job_id": "j", "kind": "research", "state": "succeeded", "done": true,
            "created_at": "2026-10-14T10:00:00", "finished_at": "2026-10-14T10:01:00"
        }));
        assert_eq!(elapsed_secs(&done, start + 900), Some(60));
    }
}
