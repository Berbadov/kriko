"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const fmt = $ => '$' + Number($).toFixed(4);
// "1m 42s" style elapsed for the run status line — ticks on every 1s poll,
// which is itself the liveness signal: a frozen counter means a frozen hub.
const fmtElapsed = s => {
  if (s == null) return '…';
  const m = Math.floor(s / 60);
  return m ? m + 'm ' + Math.floor(s % 60) + 's' : Math.floor(s) + 's';
};

let state = null, logState = null;
let selPart = '', selDoc = '', selTable = 'documents';
let running = false, prevRunning = false, polling = false;
let covLoaded = false;
const TABS = ['models', 'review', 'overview', 'parts', 'sources', 'run', 'ledger',
  'coverage'];
let curTab = 'models';

function showTab(p) {
  curTab = p;
  TABS.forEach(t => {
    $('#p-' + t).classList.toggle('on', t === p);
    document.querySelector('#nav button[data-p="' + t + '"]')
      .classList.toggle('on', t === p);
  });
  if (p === 'coverage' && !covLoaded) loadCoverage(false);
  if (p === 'coverage') { loadMatrix(); loadDoctor(); }
  if (p === 'review') loadReview();
  if (p === 'sources') loadSourceDomains();
  if (p === 'models') {
    loadModels(); loadActivity(); loadDemand(); loadHarnesses();
    loadRuns(); loadAgentRuns();
  }
}
document.querySelectorAll('#nav button')
  .forEach(b => b.onclick = () => { location.hash = b.dataset.p; });

// The tab lives in the URL: a refresh (or a link you paste to yourself) comes
// back to the pane you were watching instead of resetting to Models.
function tabFromHash() {
  const want = location.hash.replace(/^#/, '');
  showTab(TABS.includes(want) ? want : 'models');
}
addEventListener('hashchange', tabFromHash);

function kpi(label, val, accent) {
  return '<div class="kpi"><b style="color:' + (accent || '') + '">'
    + esc(val) + '</b><span>' + esc(label) + '</span></div>';
}
function rows(heads, data) {
  return '<table><tr>' + heads.map(h => '<th>' + esc(h) + '</th>').join('')
    + '</tr>' + data.map(r => '<tr>' + r.map(c => '<td>' + c + '</td>')
      .join('') + '</tr>').join('') + '</table>';
}
const sev = s => '<span class="tag sev-' + esc(s) + '">' + esc(s) + '</span>';

function renderState() {
  const c = state.counts, s = state.spend, p = state.pending;
  const cat = state.catalog;
  $('#kpis').innerHTML =
    kpi('documents', c.documents) + kpi('evidence', c.evidence) +
    kpi('clusters', c.clusters) + kpi('verdicts', c.verdicts) +
    // These two are file counts, not row counts — say so. A dashboard that
    // reads "4 variants" for a catalog holding 27 variant rows is lying in
    // the one place a person looks for scale.
    kpi('parts', cat.parts) + kpi('variant files', cat.variants) +
    kpi('fitment files', cat.fitment) + kpi('claims', cat.claims) +
    kpi('total spend', fmt(s.total_usd), '#ff8a3d') +
    kpi('import verdicts', s.verdicts_import + ' ($0)', '#6fce8e') +
    kpi('LLM verdicts', s.verdicts_llm) +
    kpi('cost to finish', fmt(p.extract_usd + p.verdict_usd), '#ff8a3d');
  $('#t-spend').innerHTML = rows(['stage', 'model', 'calls', 'tokens_in',
    'tokens_out', 'usd'], s.rows.map(r => [r.stage, r.model, r.calls,
      r.tokens_in, r.tokens_out, fmt(r.usd)]));
  $('#t-pending').innerHTML = rows(['pending extraction', 'pending verdicts',
    'import-ready', 'LLM', 'extract $', 'verdict $'], [[
      p.extract_chunks + ' chunks', p.verdict_pending + ' clusters',
      p.import_ready, p.llm, fmt(p.extract_usd), fmt(p.verdict_usd)]]);
  $('#t-runs').innerHTML = rows(['started_at', 'stage', 'model', 'calls',
    'usd'], state.runs.map(r => [r.started_at.slice(0, 19), r.stage,
      r.model || '-', r.calls, fmt(r.usd)]));

  const sel = $('#part-sel');
  const parts = state.parts.map(x => x.part_id + ' (' + x.claims + ')');
  if (parts.join() !== sel.dataset.items) {
    sel.dataset.items = parts.join();
    sel.innerHTML = parts.length
      ? parts.map(v => '<option>' + esc(v) + '</option>').join('')
      : '<option>no parts in catalog yet</option>';
  }
  if (!sel.value) sel.selectedIndex = 0;
  const cur = sel.value && sel.value.split(' ')[0];
  if (cur !== selPart) { selPart = cur; if (cur) loadPart(cur); }

  const dsel = $('#doc-sel');
  const dopt = state.documents.map(d => '#' + d.id + ' ' + d.source_type
    + ' ' + d.url);
  if (dopt.join() !== dsel.dataset.items) {
    dsel.dataset.items = dopt.join();
    dsel.innerHTML = dopt.length
      ? dopt.map(v => '<option>' + esc(v.slice(0, 90))
          + '</option>').join('')
      : '<option>no documents yet</option>';
  }
  const dcur = dsel.value && Number(dsel.value.split(' ')[0].slice(1));
  if (dcur && dcur !== selDoc) { selDoc = dcur; loadDoc(dcur); }

  if (state.last_remediation)
    $('#meta').textContent = 'last remediation ' + state.last_remediation.ts
      + ' · ' + fmt(state.last_remediation.usd);

  renderRail();
}

// The header rail is the instrument cluster: the five numbers worth a glance
// from across the desk, plus a lamp that says whether anything is alive. It
// reads the same /api/state poll everything else does — no extra request.
function renderRail() {
  const c = state.counts, s = state.spend, cat = state.catalog;
  $('#hdr-docs').textContent = c.documents;
  $('#hdr-ev').textContent = c.evidence;
  $('#hdr-claims').textContent = cat.claims;
  $('#hdr-import').textContent = s.verdicts_import;
  $('#hdr-spend').textContent = fmt(s.total_usd);
}

function setLamp(isRunning, label) {
  const el = $('#hdr-lamp');
  el.classList.toggle('on', !!isRunning);
  el.textContent = isRunning ? (label || 'running') : 'idle';
}

async function loadPart(id) {
  const r = await fetch('/api/part/' + id);
  if (!r.ok) {
    $('#part-detail').innerHTML = '<div class="err">' + esc(await r.text())
      + '</div>';
    return;
  }
  const d = await r.json();
  $('#part-detail').innerHTML =
    '<div class="muted">' + esc(d.title || '') + ' · ' + esc(d.part_type)
    + '</div><div class="muted">variants: '
    + esc((d.variants || []).join(', ') || 'none') + '</div>'
    + rows(['title', 'severity', 'domain'],
      (d.claims || []).map(c => [c.title, sev(c.severity), c.domain]));
}
async function loadDoc(id) {
  const r = await fetch('/api/doc/' + id);
  if (!r.ok) {
    $('#doc-detail').innerHTML = '<div class="err">' + esc(await r.text())
      + '</div>';
    return;
  }
  const d = await r.json();
  $('#doc-detail').innerHTML = '<div class="muted">' + esc(d.url) + ' ['
    + esc(d.source_type) + '] target=' + esc(d.target_hint) + '</div><pre>'
    + esc(d.raw_text.slice(0, 20000)) + '</pre>';
}
async function loadTable(t) {
  const q = await fetch('/api/table/' + t);
  const d = await q.json();
  $('#table-preview').textContent = d.head + '\n' + d.body;
  $('#table-meta').textContent = (d.count ?? '?') + ' rows (first 50)';
}
async function loadCoverage(force) {
  try {
    const q = await fetch('/api/coverage' + (force ? '?refresh=1' : ''));
    const d = await q.json();
    covLoaded = true;
    $('#t-findings').innerHTML = rows(['kind', 'axis', 'subject', 'part',
      'message'], d.findings.map(f => [f.kind, f.axis || '', f.subject,
        f.part_id || '', f.message]));
    $('#cov-meta').textContent = 'built ' + new Date(d.ts * 1000).toLocaleTimeString();
  } catch (e) {
    $('#t-findings').innerHTML = '<div class="err">coverage report failed: '
      + esc(String(e)) + '</div>';
  }
}

// ── Phase 4: review queue, coverage heatmap, sources, run history ───────────

// Claim inspector — what the deterministic gate says about each claim.
//
// This used to be a promotion queue whose approve button rewrote `status` in
// the part YAML. That is a human inside the data path, which CLAUDE.md's
// automation principle rules out (G5), and it does not scale past the first
// thousand claims. What is left is the half that scales: the gate's verdict
// with its reasons, and an agree/disagree signal that tunes the RULE.
let revFilter = { group: null, model_key: null };

function gateBox(g) {
  if (!g) return '';
  if (g.ok) {
    const warned = (g.warnings || []).length ? ' has-warn' : '';
    return '<div class="gate gate-ok' + warned + '">gate: keep'
      + (warned ? ', with a caveat' : '')
      + (g.warnings || []).map(w => '<div class="gwarn">⚠ ' + esc(w)
        + '</div>').join('') + '</div>';
  }
  return '<div class="gate gate-drop">gate: would drop'
    + (g.rejections || []).map(r => '<div class="gdrop">✕ ' + esc(r)
      + '</div>').join('') + '</div>';
}

function reviewCard(c) {
  const srcs = (c.sources || []).map(s =>
    '<div class="rsrc"><a href="' + esc(s.url) + '" target="_blank"'
    + ' rel="noreferrer">' + esc(s.domain) + '</a> — '
    + esc((s.quote || '').slice(0, 240)) + '</div>').join('');
  return '<div class="rclaim">'
    + '<div class="rclaim-h">' + sev(c.severity)
    + '<span class="pill">' + esc(c.part_id) + '</span>'
    + (c.domain ? '<span class="pill">' + esc(c.domain) + '</span>' : '')
    + '<span class="pill">conf ' + esc(c.confidence ?? '-') + '</span>'
    + '<span class="act-t">'
    + '<button class="run go" data-act="agree" data-id="'
    + esc(c.claim_id) + '">agree</button> '
    + '<button class="run" data-act="disagree" data-id="'
    + esc(c.claim_id) + '">disagree</button>'
    + '</span></div>'
    + '<div class="act-l"><b>' + esc(c.title) + '</b></div>'
    + (c.title_tr && c.title_tr !== c.title
      ? '<div class="muted">' + esc(c.title_tr) + '</div>' : '')
    + gateBox(c.gate)
    + (srcs ? '<div class="rsrcs">' + srcs + '</div>'
      : '<div class="muted">no quoted sources</div>')
    + '</div>';
}

function renderReviewFilters(total) {
  const f = revFilter;
  const bits = [];
  if (f.group || f.model_key) {
    bits.push(chip('clear filter ✕', (f.group || '')
      + (f.model_key ? (f.group ? ' · ' : '') + f.model_key : ''), false));
  } else {
    bits.push(chip('all claims', total + ' claims', true));
  }
  $('#review-filters').innerHTML = bits.join('');
  [...$('#review-filters').children].forEach(b => {
    b.onclick = () => { revFilter = { group: null, model_key: null }; loadReview(); };
  });
}

async function loadReview() {
  const q = new URLSearchParams();
  if (revFilter.group) q.set('group', revFilter.group);
  if (revFilter.model_key) q.set('model_key', revFilter.model_key);
  try {
    const d = await fetch('/api/review?' + q).then(r => r.json());
    renderReviewFilters(d.total);
    $('#review-meta').textContent = d.total + ' unsettled · the gate would drop '
      + d.would_drop
      + (d.total > d.claims.length ? ' (showing ' + d.claims.length + ')' : '');
    $('#review-list').innerHTML = d.claims.length
      ? d.claims.map(reviewCard).join('')
      : '<p class="muted">Nothing unsettled here.</p>';
  } catch (e) {
    $('#review-list').innerHTML = '<div class="err">claim inspector failed: '
      + esc(String(e)) + '</div>';
  }
}

$('#review-list').addEventListener('click', async e => {
  const b = e.target.closest('button[data-act]');
  if (!b) return;
  const card = b.closest('.rclaim');
  [...card.querySelectorAll('button[data-act]')].forEach(x => x.disabled = true);
  const r = await fetch('/api/review/' + encodeURIComponent(b.dataset.id), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: b.dataset.act })
  });
  const t = await r.json().catch(() => ({}));
  if (!r.ok) {
    [...card.querySelectorAll('button[data-act]')].forEach(x => x.disabled = false);
    $('#review-meta').innerHTML = '<span class="err">'
      + esc(t.detail || 'signal failed') + '</span>';
    return;
  }
  // The card stays: nothing changed in the catalog, and pretending otherwise
  // by removing it would be the old promotion-queue illusion.
  card.classList.add('signalled');
  card.querySelector('.act-t').innerHTML =
    '<span class="muted">recorded: ' + esc(b.dataset.act) + '</span>';
});
$('#b-review-refresh').onclick = () => loadReview();

// Catalog doctor — identity damage across every car, and the $0 repair.
async function loadDoctor() {
  try {
    const d = await fetch('/api/doctor').then(r => r.json());
    $('#doc-meta').textContent = d.fixable + ' fixable · '
      + d.needs_research + ' need research';
    $('#t-doctor').innerHTML = d.findings.length
      ? rows(['kind', 'model', 'fix', 'what'],
          d.findings.map(f => [esc(f.kind), esc(f.model_key),
            f.fixable ? 'auto' : '<b>research</b>', esc(f.message)]))
      : '<tr><td class="muted">catalog identity is clean</td></tr>';
  } catch (e) {
    $('#t-doctor').innerHTML = '<tr><td class="err">doctor failed: '
      + esc(String(e)) + '</td></tr>';
  }
}
$('#b-doctor').onclick = () => loadDoctor();
$('#b-doctor-fix').onclick = async () => {
  $('#doc-meta').textContent = 'repairing…';
  await fetch('/api/doctor/repair', { method: 'POST' });
  loadDoctor();
};

// Agent results — what onboarding passes achieved (logs/agent_runs.jsonl,
// written by the MCP finish_model tool). Survives the session; the output
// pane does not.
async function loadAgentRuns() {
  try {
    const d = await fetch('/api/agent-runs').then(r => r.json());
    $('#t-agentruns').innerHTML = d.runs.length
      ? rows(['when', 'model', 'variants', 'draft', 'researched', 'open parts'],
          d.runs.map(r => [
            (r.ts || '').replace('T', ' ').slice(0, 19),
            esc(r.model_key || '-'),
            r.variants ?? '-',
            r.variants_draft ?? '-',
            (r.rollup || {}).has_claims ?? '-',
            esc((r.open_parts || []).join(', ') || '—')]))
      : '';
    $('#agentruns-meta').textContent = d.runs.length
      ? d.runs.length + ' recorded' : 'no agent pass has reported yet';
  } catch (e) { /* optional chrome */ }
}

// Coverage heatmap — row per model, column per subsystem display group.
// Density shading is sqrt-scaled so sparse cells stay visible next to dense
// ones; a click drills the review queue to exactly those claims.
async function loadMatrix() {
  try {
    const d = await fetch('/api/coverage-matrix').then(r => r.json());
    const max = d.max || 1;
    const head = '<tr><th>model</th>'
      + d.groups.map(g => '<th>' + esc(g) + '</th>').join('')
      + '<th>total</th></tr>';
    const body = d.models.map(m => '<tr><td>' + esc(m.model_key) + '</td>'
      + d.groups.map(g => {
        const n = m.cells[g] || 0;
        // sqrt so sparse cells stay visible next to dense ones; floored so a
        // single claim is not indistinguishable from none, capped so the
        // figure never disappears into its own shading.
        const a = n ? Math.min(0.55, 0.10 + Math.sqrt(n / max) * 0.5).toFixed(2) : 0;
        return '<td class="hm" data-m="' + esc(m.model_key)
          + '" data-g="' + esc(g) + '" style="background:rgba(255,138,61,'
          + a + ')">' + (n || '') + '</td>';
      }).join('')
      + '<td class="hm">' + m.total + '</td></tr>').join('');
    $('#t-matrix').innerHTML = head + body;
    $('#matrix-meta').textContent = d.models.length + ' models · '
      + d.groups.length + ' groups';
  } catch (e) {
    $('#t-matrix').innerHTML = '<tr><td class="err">matrix failed: '
      + esc(String(e)) + '</td></tr>';
  }
}

$('#t-matrix').addEventListener('click', e => {
  const td = e.target.closest('td.hm');
  if (!td || !td.dataset.g) return;
  revFilter = { group: td.dataset.g, model_key: td.dataset.m };
  showTab('review');
});

// Source browser — every source_domain in the catalog, tiered via
// knowledge/sources/tiers.py (the same resolution verdicts use).
let srcSortDir = -1;
function tierBadge(t) {
  return '<span class="tier tier-' + esc(t) + '">' + esc(t) + '</span>';
}

async function loadSourceDomains() {
  try {
    const d = await fetch('/api/sources').then(r => r.json());
    const list = d.sources.slice().sort((a, b) =>
      srcSortDir * (a.contribution_count - b.contribution_count));
    $('#t-sources').innerHTML = '<tr><th>domain</th><th>tier</th>'
      + '<th>trust</th><th class="sortable" id="th-src-count">claims ↕</th></tr>'
      + list.map(s => '<tr><td>' + esc(s.domain) + '</td><td>'
        + tierBadge(s.tier) + '</td><td>' + s.trust.toFixed(2) + '</td>'
        + '<td>' + s.contribution_count + '</td></tr>').join('');
    $('#src-meta').textContent = list.length + ' domains';
    $('#th-src-count').onclick = () => {
      srcSortDir = -srcSortDir; loadSourceDomains();
    };
  } catch (e) {
    $('#t-sources').innerHTML = '<tr><td class="err">sources failed: '
      + esc(String(e)) + '</td></tr>';
  }
}

// Run history — persisted agent/CLI runs (knowledge/hub/runs.jsonl).
async function loadRuns() {
  try {
    const d = await fetch('/api/runs').then(r => r.json());
    $('#t-runhist').innerHTML = d.runs.length
      ? rows(['when', 'task', 'model', 'exit', 'dur', 'command'],
          d.runs.map(r => [
            (r.ts || '').replace('T', ' ').slice(0, 19),
            r.task || '-',
            r.make && r.model ? r.make + ' ' + r.model : '-',
            r.exit_code ?? '-',
            r.duration_s != null ? r.duration_s + 's' : '-',
            (r.argv || []).join(' ').slice(0, 90)]))
      : '';
    $('#runhist-meta').textContent = d.runs.length
      ? d.runs.length + ' recent' : 'no runs recorded yet';
  } catch (e) { /* history is optional chrome — never break the tab */ }
}

// ── Models tab ───────────────────────────────────────────────────────────────
//
// The agent writes through MCP, so the ledger — not the harness's stdout — is
// the authoritative record of what it is doing. The activity feed reads that,
// which is why it works the same whichever harness is driving.

let selModel = null;

const STATE_LABEL = {
  missing: 'missing', zero_claim: 'empty', has_claims: 'researched',
};

function pill(st, n) {
  if (!n) return '';
  return '<span class="pill p-' + st + '">' + n + ' ' + STATE_LABEL[st]
    + '</span>';
}

async function loadModels() {
  const d = await fetch('/api/models').then(r => r.json());
  const html = d.models.map(m => {
    const r = m.rollup;
    const draft = m.variants_draft
      ? '<span class="pill p-draft">' + m.variants_draft + ' draft</span>' : '';
    return '<tr class="clickable" data-key="' + esc(m.model_key) + '">'
      + '<td><b>' + esc(m.make) + '</b> ' + esc(m.model) + '</td>'
      + '<td>' + m.variants + ' variants ' + draft + '</td>'
      + '<td>' + pill('has_claims', r.has_claims) + pill('zero_claim', r.zero_claim)
      + pill('missing', r.missing) + '</td></tr>';
  }).join('');
  $('#t-models').innerHTML = '<tbody>' + html + '</tbody>';
  $('#t-models').querySelectorAll('tr[data-key]').forEach(tr => {
    tr.onclick = () => loadModel(tr.dataset.key);
  });
  if (selModel) highlightModel();
}

function highlightModel() {
  $('#t-models').querySelectorAll('tr[data-key]').forEach(tr => {
    tr.classList.toggle('sel', tr.dataset.key === selModel);
  });
}

async function loadModel(key) {
  selModel = key;
  highlightModel();
  const r = await fetch('/api/model/' + encodeURIComponent(key));
  if (!r.ok) {
    $('#model-detail').innerHTML = '<div class="err">no such model</div>';
    return;
  }
  const d = await r.json();
  $('#md-title').textContent = 'Model detail — ' + d.model_key;

  const scaffold = d.has_variants
    ? '<span class="pill p-has_claims">scaffold ok</span>'
    : '<span class="pill p-missing">no scaffold — agent must research the '
      + 'trim lineup first</span>';

  const parts = d.parts.length ? rows(['part', 'type', 'state', 'claims'],
    d.parts.map(p => [p.part_id, p.part_type || '—',
      '<span class="pill p-' + p.state + '">' + STATE_LABEL[p.state] + '</span>',
      p.claims])) : '<p class="muted">No parts referenced yet.</p>';

  const drafts = d.drafts.length ? rows(['draft variant', 'missing figures'],
    d.drafts.map(x => [x.id, x.missing.join(', ') || '—']))
    : '<p class="muted">No draft rows — every figure is sourced.</p>';

  $('#model-detail').innerHTML = '<p>' + scaffold + ' · ' + d.variants
    + ' variants, ' + d.variants_draft + ' draft</p>'
    + '<h3>Parts</h3>' + parts
    + '<h3>Draft rows <span class="muted">(unsourced figures — never guessed)'
    + '</span></h3>' + drafts;
}

function actIcon(e) {
  if (e.kind === 'document') return '<span class="act-doc">doc</span>';
  const g = e.grounded ? '<span class="ok" title="quote verified against the '
    + 'source">✓ grounded</span>'
    : '<span class="warn" title="no verified quote">no quote</span>';
  return '<span class="act-ev">evidence</span> ' + g;
}

async function loadActivity() {
  const d = await fetch('/api/activity?limit=40').then(r => r.json());
  if (!d.events.length) {
    $('#activity').innerHTML = '<p class="muted">Nothing written yet.</p>';
    return;
  }
  $('#activity').innerHTML = d.events.map(e =>
    '<div class="act' + (e.by_agent ? ' by-agent' : '') + '">'
    + '<div class="act-h">' + actIcon(e)
    + (e.by_agent ? '<span class="pill p-agent">agent</span>' : '')
    + '<span class="act-t">' + esc((e.at || '').replace('T', ' ').slice(0, 19))
    + '</span></div>'
    + '<div class="act-l">' + esc(e.label) + '</div>'
    + '<div class="muted">' + esc(e.detail || '')
    + (e.target ? ' → ' + esc(e.target) : '') + '</div></div>').join('');
  $('#act-meta').textContent = d.events.length + ' recent';
}

// ── Top-down picker: make → model → generation ───────────────────────────────
//
// Options come from the demand queue (cars real buyers hit that we don't
// cover), never a hand-maintained list. Generations can't come from traffic —
// listings give a year, not a generation number — so an agent researches the
// lineup first, and that same step resolves scraped names like
// "VW CC 1.4 TSI" to a real model slug.

let demand = { makes: [] };
let pickMake = null, pickModel = null, pickGen = null;

function chip(label, sub, on, cls) {
  return '<button class="chip' + (on ? ' on' : '') + (cls ? ' ' + cls : '')
    + '">' + esc(label)
    + (sub ? '<span class="chip-sub">' + esc(sub) + '</span>' : '') + '</button>';
}

async function loadDemand() {
  demand = await fetch('/api/demand').then(r => r.json());
  renderMakes();
}

function renderMakes() {
  const el = $('#pick-make');
  if (!demand.makes.length) {
    el.innerHTML = '<span class="muted">No demand data yet — run some '
      + 'analyses, or use a catalogued model below.</span>';
    return;
  }
  el.innerHTML = demand.makes.map(m =>
    chip(m.make, m.hits + ' hits', m.slug === pickMake)).join('');
  [...el.children].forEach((b, i) => {
    b.onclick = () => selectMake(demand.makes[i]);
  });
}

function selectMake(m) {
  pickMake = m.slug;
  pickModel = pickGen = null;
  renderMakes();
  $('#step-model').hidden = false;
  $('#step-gen').hidden = true;
  $('#step-go').hidden = true;
  const el = $('#pick-model');
  el.innerHTML = m.models.map(x =>
    chip(x.model, x.hits + ' hits · ' + x.reason.replace('_', ' '),
      x.slug === pickModel,
      x.reason === 'not_onboarded' ? 'want' : '')).join('');
  [...el.children].forEach((b, i) => {
    b.onclick = () => selectModel(m.models[i]);
  });
}

async function selectModel(x) {
  pickModel = x.slug;
  pickGen = null;
  $('#step-gen').hidden = false;
  $('#step-go').hidden = false;   // task step: 'find generations' is valid now
  renderTasks();
  refreshPreview();
  [...$('#pick-model').children].forEach(b =>
    b.classList.toggle('on', b.textContent.startsWith(x.model)));
  await renderGenerations();
}

async function renderGenerations() {
  const el = $('#pick-gen');
  el.innerHTML = '<span class="muted">checking…</span>';
  const d = await fetch('/api/generations/' + encodeURIComponent(pickMake)
    + '/' + encodeURIComponent(pickModel)).then(r => r.json());

  if (!d.researched) {
    el.innerHTML = '<span class="muted">Not researched yet — an agent has to '
      + 'find this car’s generations first.</span>'
      + '<button class="run" id="b-find-gens">Find generations →</button>';
    $('#b-find-gens').onclick = () => {
      pickTask = 'generations';
      renderTasks();
      refreshPreview().then(runAgent);
    };
    return;
  }
  // The lineup may be filed under a canonical slug the scrape got wrong.
  pickModel = d.model;
  el.innerHTML = d.generations.map(g =>
    chip(g.name, g.year_from + '–' + (g.year_to || ''),
      g.generation === pickGen)).join('');
  [...el.children].forEach((b, i) => {
    b.onclick = () => selectGen(d.generations[i]);
  });
}

function selectGen(g) {
  pickGen = g.generation;
  [...$('#pick-gen').children].forEach((b, i) =>
    b.classList.toggle('on', i === g.generation - 1));
  pickTask = 'onboard';
  renderTasks();
  refreshPreview();
}

// ── Task, harness, model, and the command preview ────────────────────────────
//
// The preview is fetched from /api/agent-preview, which builds argv with the
// same function the run endpoints use — so what's shown here is literally the
// command that will execute, not a JS reconstruction of it.

const TASKS = [
  { id: 'generations', label: 'Find generations',
    sub: 'research the lineup, submit it, stop' },
  { id: 'onboard', label: 'Onboard',
    sub: 'scaffold + research every part' },
];
let pickTask = 'onboard';
let harnesses = [];

function renderTasks() {
  const el = $('#pick-task');
  el.innerHTML = TASKS.map(t =>
    chip(t.label, t.sub, t.id === pickTask)).join('');
  [...el.children].forEach((b, i) => {
    b.onclick = () => { pickTask = TASKS[i].id; renderTasks(); refreshPreview(); };
  });
  $('#step-run').hidden = false;
}

async function loadHarnesses() {
  const d = await fetch('/api/harnesses').then(r => r.json());
  harnesses = d.harnesses;
  const sel = $('#ob-harness');
  sel.innerHTML = harnesses.map(h =>
    '<option value="' + esc(h.name) + '"' + (h.available ? '' : ' disabled')
    + '>' + esc(h.name) + (h.available ? '' : ' (not installed)')
    + '</option>').join('');
  const first = harnesses.find(h => h.available);
  if (first && !sel.value) sel.value = first.name;
  renderLlmModels();
}

function renderLlmModels() {
  const h = harnesses.find(x => x.name === $('#ob-harness').value);
  const free = (h && h.models) || [];
  const paid = (h && h.paid_models) || [];
  const opts = m => '<option value="' + esc(m) + '">' + esc(m) + '</option>';

  // Paid models are grouped and labelled, never mixed into the flat-rate list:
  // they bill per token, which is the one thing this whole path avoids.
  $('#ob-llm').innerHTML = '<option value="">default model</option>'
    + (free.length
      ? '<optgroup label="flat rate (subscription)">'
        + free.map(opts).join('') + '</optgroup>' : '')
    + (paid.length
      ? '<optgroup label="⚠ pay-per-token (API key — costs money)">'
        + paid.map(opts).join('') + '</optgroup>' : '');
}

function selectedModelIsPaid() {
  const h = harnesses.find(x => x.name === $('#ob-harness').value);
  return !!(h && (h.paid_models || []).includes($('#ob-llm').value));
}

function agentBody() {
  return {
    task: pickTask,
    make: pickMake,
    model: pickModel,
    generation: pickTask === 'onboard' ? pickGen : null,
    harness: $('#ob-harness').value,
    llm_model: $('#ob-llm').value,
  };
}

async function refreshPreview() {
  const el = $('#cmd-preview');
  if (!pickMake || !pickModel) { el.textContent = ''; return; }
  const r = await fetch('/api/agent-preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(agentBody()),
  });
  const d = await r.json();
  if (!r.ok) {
    el.innerHTML = '<span class="err">' + esc(d.detail) + '</span>';
    return;
  }
  const paid = selectedModelIsPaid();
  el.innerHTML = '$ ' + esc(d.display)
    + (paid ? '\n<span class="warn">⚠ this model bills per token — the agent '
      + 'path is $0 only on the flat-rate plane</span>' : '');
  el.classList.toggle('paid', paid);
  $('#b-agent-run').textContent =
    (pickTask === 'generations' ? 'Find generations' : 'Onboard') + ' →';
}

async function runAgent() {
  const body = agentBody();
  const url = body.task === 'generations'
    ? '/api/research-generations' : '/api/onboard';
  $('#onboard-state').textContent = 'starting…';
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) {
    $('#onboard-state').innerHTML = '<span class="err">' + esc(d.detail)
      + '</span>';
    return;
  }
  $('#onboard-state').textContent = 'running ' + body.harness + '…';
  if (d.model_key) loadModel(d.model_key);
}

async function poll() {
  polling = true;
  try {
    const [s, l] = await Promise.all([
      fetch('/api/state').then(r => r.json()),
      fetch('/api/log').then(r => r.json()),
    ]);
    state = s;
    logState = l;
    running = l.running;
    renderState();

    const logEl = $('#log');
    const nearBottom = logEl.scrollTop + logEl.clientHeight
      >= logEl.scrollHeight - 40;
    logEl.textContent = l.buf;
    if (nearBottom) logEl.scrollTop = logEl.scrollHeight;
    $('#run-state').textContent = running ? 'running · ' + fmtElapsed(l.elapsed)
      : 'exit ' + (l.exit ?? '-') + ' · ' + (l.cmd || '');
    $('#run-state').classList.toggle('err', !running && l.exit);
    document.title = running ? '● kriko-hub — running' : 'kriko-hub';
    // The lamp names WHAT is alive, not just that something is: an agent run
    // and a pipeline stage look identical in a spinner and nothing alike in
    // consequence (one is $0 research, the other can be spending).
    setLamp(running, running
      ? (l.cmd || '').includes('knowledge.ledger.run')
        ? 'pipeline ' + fmtElapsed(l.elapsed)
        : 'agent ' + fmtElapsed(l.elapsed)
      : '');
    setRunButtons(!running);

    // The agent's own output pane mirrors the shared run log — one run slot.
    const obLog = $('#ob-log');
    const obBottom = obLog.scrollTop + obLog.clientHeight
      >= obLog.scrollHeight - 40;
    // A running agent can legitimately produce nothing for the first minute
    // (LLM thinking, MCP calls). Say so instead of showing a dead blank pane.
    obLog.textContent = running && !l.buf.trim()
      ? '· agent working — waiting for first output…'
      : l.buf;
    if (obBottom) obLog.scrollTop = obLog.scrollHeight;
    $('#ob-run-state').textContent = running
      ? '● running · ' + fmtElapsed(l.elapsed)
      : (l.cmd ? 'exit ' + (l.exit ?? '-') + ' · ' + l.cmd : '');
    $('#ob-run-state').classList.toggle('live', running);

    // Real-time view of what the agent is writing. Cheap queries, so they
    // ride the poll while the Models tab is showing.
    if (curTab === 'models') {
      await Promise.all([loadActivity(), loadModels()]);
      if (selModel) loadModel(selModel);
    }

    if (prevRunning && !running) {  // a run just finished: refresh tables
      loadTable(selTable);
      if (covLoaded) loadCoverage(false);
      if (curTab === 'models') {
        $('#onboard-state').textContent =
          l.exit ? 'agent exited ' + l.exit : 'agent finished';
        loadDemand();
        // a generations run just landed a lineup: show the buttons
        if (pickMake && pickModel) renderGenerations();
      }
    }
    prevRunning = running;
  } catch (e) {
    state = null;
    setRunButtons(false);
    setLamp(false, '');
    $('#meta').textContent = 'ledger unavailable — is the hub server running?';
  } finally {
    polling = false;
    schedulePoll();
  }
}

function setRunButtons(en) {
  ['b-extract', 'b-verdict', 'b-resolve', 'b-cluster', 'b-import',
    'b-remediate', 'b-export'].forEach(id => $('#' + id).disabled = !en);
}
async function doRun(argv) {
  const r = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ argv })
  });
  if (!r.ok) $('#run-state').textContent = (await r.json()).detail;
}

function schedulePoll() {
  const delay = document.hidden ? 3000 : (running ? 1000 : 5000);
  setTimeout(poll, delay);
}
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && !polling) poll();
});

$('#b-extract').onclick = () => doRun(['extract', '--max-usd',
  (Number($('#cap').value) || 0).toFixed(2)]);
$('#b-verdict').onclick = () => doRun(['verdict', '--max-usd',
  (Number($('#cap').value) || 0).toFixed(2)]);
$('#b-resolve').onclick = () => doRun(['resolve']);
$('#b-cluster').onclick = () => doRun(['cluster']);
$('#b-import').onclick = () => doRun(['verdict', '--import-only']);
$('#b-remediate').onclick = () => doRun(['remediate']);
$('#b-export').onclick = () => doRun(['export']);
$('#b-cov').onclick = () => loadCoverage(true);
$('#b-agent-run').onclick = runAgent;
$('#ob-harness').addEventListener('change', () => {
  renderLlmModels(); refreshPreview();
});
$('#ob-llm').addEventListener('change', refreshPreview);
$('#b-onboard-stop').onclick = async () => {
  await fetch('/api/stop', { method: 'POST' });
};

$('#b-stop').onclick = async () => { await fetch('/api/stop', { method: 'POST' }); };
$('#table-sel').addEventListener('change', e => loadTable(e.target.value));

poll();
// First paint honours the URL's tab (and loads that pane's data): showTab only
// fired on a nav click before, so the make picker stayed empty until the user
// re-clicked the tab they were already on.
tabFromHash();
