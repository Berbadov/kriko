"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const fmt = $ => '$' + Number($).toFixed(4);

let state = null, logState = null;
let selPart = '', selDoc = '', selTable = 'documents';
let running = false, prevRunning = false, polling = false;
let covLoaded = false;
const TABS = ['overview', 'parts', 'sources', 'run', 'ledger', 'coverage'];

function showTab(p) {
  TABS.forEach(t => {
    $('#p-' + t).classList.toggle('on', t === p);
    document.querySelector('#nav button[data-p="' + t + '"]')
      .classList.toggle('on', t === p);
  });
  if (p === 'coverage' && !covLoaded) loadCoverage(false);
}
document.querySelectorAll('#nav button')
  .forEach(b => b.onclick = () => showTab(b.dataset.p));

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
    kpi('parts', cat.parts) + kpi('variants', cat.variants) +
    kpi('fitment', cat.fitment) + kpi('claims', cat.claims) +
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
    $('#meta').textContent = 'last remediation: ' + state.last_remediation.ts
      + ' · ' + fmt(state.last_remediation.usd);
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
    $('#run-state').textContent = running ? 'running…'
      : 'exit ' + (l.exit ?? '-') + ' · ' + (l.cmd || '');
    $('#run-state').classList.toggle('err', !running && l.exit);
    document.title = running ? '● kriko-hub — running' : 'kriko-hub';
    setRunButtons(!running);

    if (prevRunning && !running) {  // a run just finished: refresh tables
      loadTable(selTable);
      if (covLoaded) loadCoverage(false);
    }
    prevRunning = running;
  } catch (e) {
    state = null;
    setRunButtons(false);
    $('#meta').textContent = 'ledger unavailable — is the hub server running?';
  } finally {
    polling = false;
    schedulePoll();
  }
}

function setRunButtons(en) {
  ['b-extract', 'b-verdict', 'b-resolve', 'b-cluster', 'b-import',
    'b-remediate', 'b-export'].forEach(id => $(id).disabled = !en);
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
$('#b-stop').onclick = async () => { await fetch('/api/stop', { method: 'POST' }); };
$('#table-sel').addEventListener('change', e => loadTable(e.target.value));

poll();
