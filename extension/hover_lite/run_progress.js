/* RunProgress: what a running look-up is doing, from what the engine has said.
 *
 * The bar this replaces was the job's own share of its work, drawn as a
 * percentage-shaped fill with a moving sheen. An agent job jumps from a tenth
 * to done, so the fill read as a stall and the sheen as a lie. The reader
 * asked for the opposite (#262): real stages, with the true count of pages
 * read out of pages attempted, and nothing invented.
 *
 * So this reads only what the job already carries and says nothing it does
 * not know:
 *   - the stage is the furthest step its own log has reached (a search, a
 *     page read, a source being checked), never a guess from elapsed time;
 *   - the counts are lines the run wrote: a page it read, a page it could not,
 *     a source it is on. Until the run finishes they are what has happened so
 *     far, which is exactly what "4 of 6 pages read" should mean mid-run;
 *   - a finished run's own coverage block, when it sent one, replaces the
 *     counts, because the run itself tallied those.
 * A run whose log says nothing this module recognises shows its own message
 * and no stage bar, rather than a bar that pretends.
 *
 * Pure: no DOM, no clock, no chrome.*. The panel owns drawing and the clock.
 * Words are English panel chrome; nothing here names a site, a category or a
 * product. What the run's own log said is reduced to the few shapes the engine
 * writes (a search, a host it read, a source it checked) and never passed
 * through whole: a URL becomes its hostname, a line is clipped, and only the
 * last few survive. That is what the panel's work terminal draws; the full log
 * still opens in the app.
 */
(function () {
  const STAGES = [
    { key: "page", label: "Reading the page" },
    { key: "search", label: "Searching" },
    { key: "read", label: "Reading sources" },
    { key: "check", label: "Checking quotes" },
  ];

  /* Why the reader is waiting, in plain words. A wait with no reason is the
   * thing this replaces: every one of these is a state the panel already
   * knows it is in, so none of it is guessed from elapsed time. */
  const WAIT_REASONS = {
    app_not_running: "Kriko isn't running, so the page can't be read yet.",
    no_adapter: "No installed catalog reads this site.",
    not_a_listing: "This page isn't a product listing.",
    scrape_failed: "The page couldn't be read.",
    checking_packs: "Checking which catalogs read this page.",
    reading_page: "Reading this page.",
    looking_up: "Looking it up in the catalogs.",
    saved_answer: "Using the answer this page already had.",
    starting: "Starting the search.",
    queued: "Waiting for a free slot in Kriko.",
    blocked: "Waiting for another run to finish.",
    starting_agent: "Starting your agent.",
    starting_research: "Starting the research run.",
    page: "Reading this page.",
    search: "Searching for sources.",
    read: "Reading the pages it found.",
    check: "Checking what each source says.",
    working: "Kriko is working.",
    done: "Done.",
    stopped: "Stopped.",
  };

  function waitReason(key) {
    return WAIT_REASONS[key] || WAIT_REASONS.working;
  }

  // The terminal is a glance, not a log view: the last five lines the run
  // wrote, each clipped to one comfortable line.
  const WORK_LINES_MAX = 5;
  const WORK_LINE_CHARS = 72;

  /* The hostname and nothing else. A path or a query string can name a
   * product, a search the reader typed, or a session token; the panel only
   * needs to say which site was read. */
  function hostOf(value) {
    // Parsed by hand, not through `URL`: this file runs inside a page and in
    // the tests' bare vm context, and neither is guaranteed the web API.
    const text = String(value || "").trim()
      .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")   // scheme
      .replace(/^[^/?#]*@/, "");                  // userinfo
    const host = text.split(/[/?#]/)[0].replace(/:\d+$/, "").toLowerCase();
    return host && (host.includes(".") || host === "localhost") ? host : "";
  }

  function clipped(text) {
    const one = String(text || "").replace(/\s+/g, " ").trim();
    return one.length > WORK_LINE_CHARS
      ? `${one.slice(0, WORK_LINE_CHARS - 1)}\u2026` : one;
  }

  // A query is the engine's own words, but a query can carry an address a
  // reader pasted; its host is the most the panel needs, and the only part
  // safe to put on a page the reader may be sharing.
  function queryText(value) {
    return String(value || "")
      .replace(/[a-z][a-z0-9+.-]*:\/\/\S+/gi, (url) => hostOf(url) || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  /* The actual activity lines in a run's log, oldest first. Only the shapes
   * the engine writes are read, so an unrecognised line (a page title, an
   * agent's aside) cannot carry a URL or a product name to the screen. */
  function workLines(text) {
    const out = [];
    const add = (line) => {
      const one = clipped(line);
      if (!one || out[out.length - 1] === one) return;
      out.push(one);
    };
    for (const raw of String(text || "").split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      let hit;
      if ((hit = /^search language:.*?\bqueries:\s*(.+)$/i.exec(line))) {
        for (const query of hit[1].split(";")) if (query.trim()) add(`Search: ${queryText(query)}`);
        continue;
      }
      if ((hit = /^searching:\s*(.+)$/i.exec(line))) {
        for (const query of hit[1].split(";")) if (query.trim()) add(`Search: ${queryText(query)}`);
        continue;
      }
      if ((hit = /^searched\s+["\u201c'](.+?)["\u201d']\s*$/i.exec(line))) {
        add(`Search: ${queryText(hit[1])}`);
        continue;
      }
      if ((hit = /^could not read:\s*(\S+)/i.exec(line))) {
        const host = hostOf(hit[1]);
        if (host) add(`Couldn't read: ${host}`);
        continue;
      }
      if ((hit = /^read:\s*(\S+)/i.exec(line)) || (hit = /^fetched\s+(\S+)/i.exec(line))) {
        const host = hostOf(hit[1]);
        if (host) add(`Read: ${host}`);
        continue;
      }
      if (/^read through the page reader\b/i.test(line)) {
        const url = /[a-z][a-z0-9+.-]*:\/\/\S+/i.exec(line);
        const host = url ? hostOf(url[0]) : "";
        add(host ? `Read: ${host}` : "Read the page");
        continue;
      }
      if ((hit = /^found\s+(\d+)\s+page/i.exec(line))) {
        const pages = number(hit[1]);
        add(`Found ${pages} ${pages === 1 ? "page" : "pages"}`);
        continue;
      }
      if ((hit = /^extracting source\s+(\d+)\/(\d+)(?::\s*(\S+))?/i.exec(line))) {
        const host = hit[3] ? hostOf(hit[3]) : "";
        add(`Source ${number(hit[1])} of ${number(hit[2])}${host ? `: ${host}` : ""}`);
        continue;
      }
      if (/^(?:evidence check|self-check)\b/i.test(line)) add("Evidence check");
    }
    return out.slice(-WORK_LINES_MAX);
  }

  /* The shapes of the lines a run writes. They are the engine's own wording
   * (the local agent's `_say`, the CLI harness's tool narration), kept to the
   * start of the line so a page title that happens to contain "read" cannot
   * move a stage. */
  const LINE = {
    searches: /^(?:searched\b|search:)/i,
    searching: /^searching:\s*(.*)$/i,
    planned: /^search language:/i,
    readOk: /^(?:read: |fetched |read through the page reader\b)/i,
    readFail: /^could not read: /i,
    found: /^found (\d+) page\(s\)/i,
    extracting: /^extracting source (\d+)\/(\d+)/i,
    checked: /^(?:evidence check|self-check)\b/i,
  };

  const FINISHED = ["succeeded", "cancelled", "failed", "interrupted"];

  function number(value) {
    const n = Number(value);
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
  }

  /* Tally the log: how far the run got, and what it did on the way. */
  function readLog(text) {
    const seen = { reached: 0, searches: 0, read: 0, failed: 0, source: 0, of: 0 };
    for (const raw of String(text || "").split("\n")) {
      const line = raw.trim();
      if (!line) continue;
      let hit;
      if (LINE.searches.test(line)) {
        seen.searches += 1;
        seen.reached = Math.max(seen.reached, 1);
      } else if ((hit = LINE.searching.exec(line))) {
        // One line may carry several queries, split by the engine's own "; ".
        seen.searches += Math.max(1, hit[1].split(";").filter((q) => q.trim()).length);
        seen.reached = Math.max(seen.reached, 1);
      } else if (LINE.planned.test(line)) {
        seen.reached = Math.max(seen.reached, 1);
      } else if (LINE.readOk.test(line)) {
        seen.read += 1;
        seen.reached = Math.max(seen.reached, 2);
      } else if (LINE.readFail.test(line)) {
        seen.failed += 1;
        seen.reached = Math.max(seen.reached, 2);
      } else if (LINE.found.test(line)) {
        seen.reached = Math.max(seen.reached, 2);
      } else if ((hit = LINE.extracting.exec(line))) {
        seen.source = number(hit[1]);
        seen.of = number(hit[2]);
        seen.reached = 3;
      } else if (LINE.checked.test(line)) {
        seen.reached = 3;
      }
    }
    return seen;
  }

  /* "4 of 6 pages read": only claims an "of" when a page was attempted and
   * not read, because "6 of 6" is just "6". Empty when nothing was tried. */
  function pagesText(read, attempted) {
    if (!attempted) return "";
    const noun = (n) => (n === 1 ? "page" : "pages");
    if (read === attempted) return `${read} ${noun(read)} read`;
    return `${read} of ${attempted} pages read`;
  }

  function describeRun(job) {
    const row = job && typeof job === "object" ? job : {};
    const state = String(row.state || "");
    const finished = Boolean(row.done) || FINISHED.includes(state);
    const seen = readLog(row.log);
    const coverage = row.result && typeof row.result.coverage === "object" && row.result.coverage
      ? row.result.coverage : null;

    let read = seen.read;
    let failed = seen.failed;
    if (finished && coverage && coverage.pages_read !== undefined) {
      read = number(coverage.pages_read);
      failed = number(coverage.pages_unreadable) + number(coverage.pages_timed_out);
    }
    const attempted = read + failed;

    // A quick look always has a story to tell; anything else only when its
    // own log has said something this module can place.
    const staged = row.kind === "quick_look" || seen.reached > 0;
    const succeeded = finished && state === "succeeded";
    const reached = succeeded ? STAGES.length : seen.reached;

    const stages = staged ? STAGES.map((stage, i) => ({
      key: stage.key,
      label: stage.label,
      // A run that ended early marks the step it was on as where it stopped.
      state: i < reached ? "done" : (i === reached ? (finished ? "stopped" : "now") : "todo"),
    })) : null;

    const now = staged && !succeeded ? STAGES[Math.min(seen.reached, STAGES.length - 1)] : null;
    let detail = "";
    if (now && !finished) {
      if (now.key === "search" && seen.searches) {
        detail = `${seen.searches} search${seen.searches === 1 ? "" : "es"} run`;
      } else if (now.key === "check" && seen.source && seen.of) {
        detail = `source ${seen.source} of ${seen.of}`;
      }
    }
    const pages = pagesText(read, attempted);

    // What to say the run is doing. A finished run says how it ended; a run
    // with no stages says its own message; otherwise the stage it is in.
    let headline;
    if (succeeded) headline = "Done";
    else if (finished) headline = state === "cancelled" ? "Stopped" : "Stopped early";
    else if (now) headline = now.label;
    else headline = String(row.message || state || "Working").split(/(?<=[.!?])\s/)[0].slice(0, 60);

    // Why this run is being waited on, from its own state and log: the stage
    // it reached, the queue it is in, or the fact that it has said nothing
    // this module can place. The panel shows these words as the terminal's
    // header, so a wait never goes unexplained.
    let reason;
    if (finished) reason = waitReason(succeeded ? "done" : "stopped");
    else if (state === "queued") reason = waitReason("queued");
    else if (state === "blocked") reason = waitReason("blocked");
    else if (now) reason = waitReason(now.key);
    else reason = waitReason("working");
    const terminal = {
      reason,
      stage: now ? now.label : "",
      lines: workLines(row.log),
    };

    const step = staged && !finished ? Math.min(seen.reached, STAGES.length - 1) + 1 : 0;
    const spoken = [headline, detail, pages].filter(Boolean).join(", ");
    return {
      staged,
      finished,
      stages,
      step,
      total: STAGES.length,
      headline,
      detail,
      pages,
      // The lines the run actually wrote, reduced to a host a line, plus why
      // the reader is waiting. The panel draws it only while a run is live.
      terminal,
      counts: { read, failed, attempted, searches: seen.searches },
      // For a screen reader, in one phrase: where the run is and what it has done.
      spoken: staged && !finished ? `Step ${step} of ${STAGES.length}: ${spoken}` : spoken,
    };
  }

  /* What a finished look-up covered, in one sentence the card can lead with:
   * pages read of pages tried, then how many were about this product, were
   * checked, and are cited. Zeroes are said ("0 cited"), because a run that
   * cited nothing is the finding; a figure the run never reported is left out
   * rather than shown as 0. */
  function coverageSummary(coverage) {
    const c = coverage && typeof coverage === "object" ? coverage : null;
    if (!c) return { pages: "", rest: [] };
    const read = number(c.pages_read);
    const attempted = read + number(c.pages_unreadable) + number(c.pages_timed_out);
    const rest = [];
    const add = (value, text) => { if (value !== undefined && value !== null) rest.push(text(number(value))); };
    add(c.pages_relevant, (n) => `${n} about this product`);
    add(c.pages_extracted, (n) => `${n} checked`);
    add(c.sources_cited, (n) => `${n} cited`);
    return { pages: pagesText(read, attempted || read) || "0 pages read", rest };
  }

  window.__KrikoRunProgress = {
    STAGES, WAIT_REASONS, describeRun, coverageSummary, readLog, pagesText,
    workLines, waitReason, hostOf,
  };
})();
