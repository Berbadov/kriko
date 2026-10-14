//! How a progress bar moves between the reports the engine makes.
//!
//! The engine reports progress at a few fixed points. A research run says
//! 10%, then 20%, then nothing at all while the agent searches and reads (one
//! call that can take minutes), then 85% when the findings are checked. The
//! bar used to draw that raw value, so it sat still for minutes and then
//! leaped. `Smoothed` is the bar's own view of the job: it eases toward each
//! report, creeps within a stage while no report comes, never goes backwards,
//! and glides to full when the job succeeds.
//!
//! Time is seconds on a monotonic clock, passed in, so the rules are tested
//! on a fake clock. A frame with no motion (Reduce motion, or a window that
//! is not in front) is not advanced at all: the screens draw the report.

/// Seconds for a jump to close about 95% of its gap: a jump is read in about
/// a second, not in one frame.
const EASE_TAU: f64 = 0.33;
/// Seconds for a silent stage to close about 63% of its creep.
const CREEP_TAU: f64 = 90.0;
/// Seconds for a finished job to close most of its gap to full: about 0.3 s
/// from a bar at 90%.
const DONE_TAU: f64 = 0.08;
/// How far past the last report a silent stage may creep, when the stage's
/// own end is not known to the screen. The engine does not say where a stage
/// ends, so the creep is bounded by a fixed span past the report.
const CREEP_SPAN: f32 = 0.2;
/// The creep never reaches this: a running job is never drawn as finished.
const CREEP_CAP: f32 = 0.98;
/// A frame gap longer than this (the window was away) is not eased through
/// second by second: the bar is brought to the report at once.
const AWAY_AFTER: f64 = 5.0;
/// Within this of full, a finished bar is drawn as full.
const SETTLED: f32 = 0.995;

/// The bar's eased value for one job.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Smoothed {
    shown: f32,
    last: Option<f64>,
}

impl Smoothed {
    /// A bar that starts at the value the engine has reported.
    pub fn at(reported: f32) -> Self {
        Self { shown: clamp01(reported), last: None }
    }

    /// The value the bar draws.
    pub fn shown(&self) -> f32 {
        self.shown
    }

    /// Whether the bar has reached full and can stop being followed.
    pub fn settled(&self) -> bool {
        self.shown >= SETTLED
    }

    /// Moves the bar one frame toward the job and returns the value to draw.
    ///
    /// `reported` is the engine's value, `ceiling` the most this stage may
    /// creep to (see `unknown_ceiling`), `now` seconds on a monotonic clock,
    /// `done` whether the job succeeded. The value never goes down.
    pub fn advance(&mut self, reported: f32, ceiling: f32, now: f64, done: bool) -> f32 {
        let reported = clamp01(reported);
        let ceiling = clamp01(ceiling).max(reported);
        // A clock reading that is not a number counts as no time passing.
        let now = if now.is_finite() { now } else { self.last.unwrap_or(0.0) };
        let dt = self.last.map_or(0.0, |t| (now - t).max(0.0));
        self.last = Some(now);

        if done {
            // the glide to full: a fraction of a second, then exactly full
            let k = 1.0 - (-dt / DONE_TAU).exp();
            self.shown += (1.0 - self.shown) * k as f32;
            if self.shown >= SETTLED {
                self.shown = 1.0;
            }
            return self.shown;
        }
        if dt > AWAY_AFTER {
            // back from the background: nobody watched the gap, so bring the
            // bar to the report at once rather than easing through it
            self.shown = self.shown.max(reported);
            return self.shown;
        }
        // ease toward the report that has arrived
        if reported > self.shown {
            let k = 1.0 - (-dt / EASE_TAU).exp();
            self.shown += (reported - self.shown) * k as f32;
        }
        // creep through the silence, slowing as the ceiling nears
        if self.shown < ceiling {
            let k = 1.0 - (-dt / CREEP_TAU).exp();
            self.shown += (ceiling - self.shown) * k as f32;
        }
        self.shown = self.shown.min(1.0);
        self.shown
    }
}

/// The most a stage may creep to when the screen does not know where the
/// next stage starts: a fixed span past the last report, short of full.
pub fn unknown_ceiling(reported: f32) -> f32 {
    let reported = clamp01(reported);
    (reported + CREEP_SPAN).min(CREEP_CAP).max(reported)
}

fn clamp01(v: f32) -> f32 {
    if v.is_nan() { 0.0 } else { v.clamp(0.0, 1.0) }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A research run as the engine reports it: planning, the agent's whole
    /// search and read as one silent stage, the findings check, then done.
    /// `(seconds, reported, done)`.
    fn research_reports() -> Vec<(f64, f32, bool)> {
        vec![
            (0.0, 0.1, false),
            (0.5, 0.2, false),
            (50.0, 0.85, false),
            (51.5, 1.0, true),
        ]
    }

    /// Frames every `step` seconds to `until`, each drawing what `bar` makes
    /// of the latest report it has seen. `(seconds, shown)`.
    fn replay(
        reports: &[(f64, f32, bool)],
        until: f64,
        step: f64,
        mut bar: impl FnMut(f32, f64, bool) -> f32,
    ) -> Vec<(f64, f32)> {
        let mut out = Vec::new();
        let mut t = 0.0;
        while t <= until + 1e-9 {
            let (reported, done) = reports
                .iter()
                .filter(|(at, _, _)| *at <= t + 1e-9)
                .last()
                .map(|(_, r, d)| (*r, *d))
                .unwrap_or((0.0, false));
            out.push((t, bar(reported, t, done)));
            t += step;
        }
        out
    }

    /// The bar as the app draws it: one `Smoothed` followed through the run.
    fn followed() -> impl FnMut(f32, f64, bool) -> f32 {
        let mut bar = Smoothed::at(0.0);
        move |reported, now, done| bar.advance(reported, unknown_ceiling(reported), now, done)
    }

    /// Longest stretch, in seconds, over which the drawn value does not move.
    fn longest_frozen(series: &[(f64, f32)]) -> f64 {
        let mut longest = 0.0_f64;
        let mut since = series.first().map_or(0.0, |s| s.0);
        for pair in series.windows(2) {
            if (pair[1].1 - pair[0].1).abs() > 1e-4 {
                since = pair[1].0;
            }
            longest = longest.max(pair[1].0 - since);
        }
        longest
    }

    #[test]
    fn the_bar_never_goes_backwards() {
        let series = replay(&research_reports(), 60.0, 0.25, followed());
        assert!(series.windows(2).all(|p| p[1].1 + 1e-6 >= p[0].1), "{series:?}");
    }

    #[test]
    fn the_bar_never_runs_past_its_ceiling_while_the_job_runs() {
        let series = replay(&research_reports(), 49.0, 0.25, followed());
        // while the agent is silent, the report is 0.2 and the creep stops short of 0.4
        assert!(series.iter().all(|(_, shown)| *shown <= 0.4 + 1e-6), "{series:?}");
    }

    #[test]
    fn a_jump_is_eased_not_leapt() {
        // the 0.85 report lands at t = 50; the bar should have closed 95% of
        // the gap from where it was by about a second later, not at once
        let series = replay(&research_reports(), 53.0, 0.05, followed());
        let before = series.iter().find(|(t, _)| *t >= 49.95).map(|s| s.1).unwrap();
        let target = 0.85;
        let closed_at = series
            .iter()
            .find(|(t, shown)| *t >= 50.0 && (target - shown) <= 0.05 * (target - before))
            .map(|s| s.0 - 50.0)
            .expect("the bar reaches 95% of the jump");
        assert!((0.5..=1.5).contains(&closed_at), "closed 95% after {closed_at} s");
    }

    #[test]
    fn a_silent_stage_keeps_creeping_but_stays_under_the_ceiling() {
        // 30 s of silence after the 0.2 report: the bar must keep changing
        let reports = [(0.0, 0.2, false)];
        let series = replay(&reports, 30.0, 0.25, followed());
        let first = series.first().unwrap().1;
        let last = series.last().unwrap().1;
        assert!(last > first + 0.02, "{first} -> {last}");
        assert!(series.iter().all(|(_, shown)| *shown < unknown_ceiling(0.2) + 1e-6));
    }

    #[test]
    fn the_bar_never_sits_frozen_for_seconds_while_a_run_is_going() {
        // the stall: the research run's silent agent stage is 50 s long
        let series = replay(&research_reports(), 49.0, 0.25, followed());
        let frozen = longest_frozen(&series);
        assert!(frozen < 2.0, "frozen for {frozen} s");
    }

    #[test]
    fn a_finished_job_glides_to_full_in_under_half_a_second() {
        let reports = [(0.0, 0.9, false), (1.0, 1.0, true)];
        let series = replay(&reports, 1.5, 0.05, followed());
        let full = series.iter().find(|(_, shown)| *shown == 1.0).expect("reaches full");
        assert!(full.0 - 1.0 <= 0.5, "reached full at {} s", full.0);
    }

    #[test]
    fn a_huge_gap_between_frames_does_not_overshoot() {
        let mut bar = Smoothed::at(0.2);
        bar.advance(0.2, unknown_ceiling(0.2), 0.0, false);
        let after_away = bar.advance(0.3, unknown_ceiling(0.3), 3600.0, false);
        assert!(after_away.is_finite());
        assert!(after_away <= unknown_ceiling(0.3) + 1e-6, "{after_away}");
        assert!(after_away >= 0.2, "{after_away}");
    }

    #[test]
    fn nan_and_repeated_clock_readings_are_harmless() {
        let mut bar = Smoothed::at(0.5);
        let a = bar.advance(f32::NAN, 0.7, 1.0, false);
        let b = bar.advance(0.5, 0.7, 1.0, false);
        let c = bar.advance(0.5, 0.7, f64::NAN, false);
        assert!([a, b, c].iter().all(|v| v.is_finite() && (0.0..=1.0).contains(v)));
    }
}
