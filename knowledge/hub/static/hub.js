"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const fmt = $ => '$' + Number($).toFixed(4);

let state = null, logState = null;
let selPart = '', selDoc = '', selTable = 'documents';
let running = false;
const TABS = ['overview', 'parts', 'sources', 'run', 'ledger', 'coverage'];

function showTab(p) {
  TABS.forEach(t => {
    $('#p-' + t).classList.toggle('on', t === p);
    document.querySelector('#nav button[data-p="' + t + '"]')
      .classList.toggle('on', t === p);
  });
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

function renderState() {
  const c = state.counts, s = state.spend, p = state.pending;
  $('#kpis').innerHTML =
    kpi('documents', c.documents) + kpi('evidence', c.evidence) +
    kpi('clusters', c.clusters) + kpi('verdicts', c.verdicts) +
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
    sel.innerHTML = parts.map(v => '<option>' + esc(v) + '</option>').join('');
  }
  if (!sel.value) sel.selectedIndex = 0;
  const cur = sel.value && sel.value.split(' ')[0];
  if (cur !== selPart) { selPart = cur; if (cur) loadPart(cur); }

  const dsel = $('#doc-sel');
  const dopt = state.documents.map(d => '#' + d.id + ' ' + d.source_type
    + ' ' + d.url);
  if (dopt.join() !== dsel.dataset.items) {
    dsel.dataset.items = dopt.join();
    dsel.innerHTML = dopt.map(v => '<option>' + esc(v.slice(0, 90))
      + '</option>').join('');
  }
  const dcur = dsel.value && Number(dsel.value.split(' ')[0].slice(1));
  if (dcur && dcur !== selDoc) { selDoc = dcur; loadDoc(dcur); }

  $('#t-findings').innerHTML = rows(['kind', 'subject', 'part', 'message'],
    state.findings.map(f => [f.kind, f.subject, f.part_id || '', f.message]));

  if (state.last_remediation)
    $('#meta').textContent = 'last remediation: ' + state.last_remediation.ts
      + ' · ' + fmt(state.last_remediation.usd);

  if ($('#table-sel').value !== selTable) {
    selTable = $('#table-sel').value || 'documents';
    loadTable(selTable);
  }
}

async function loadPart(id) {
  const r = await fetch('/api/part/' + id);
  const d = await r.json();
  $('#part-detail').innerHTML =
    '<div class="muted">' + esc(d.title || '') + ' · ' + esc(d.part_type)
    + '</div><div class="muted">variants: ' + esc((d.variants || []).join(', '))
    + '</div>' + rows(['title', 'severity', 'domain'],
      (d.claims || []).map(c => [c.title, c.severity, c.domain]));
}
async function loadDoc(id) {
  const r = await fetch('/api/doc/' + id);
  const d = await r.json();
  $('#doc-detail').innerHTML = '<div class="muted">' + esc(d.url) + ' ['
    + esc(d.source_type) + '] target=' + esc(d.target_hint) + '</div><pre>'
    + esc(d.raw_text.slice(0, 20000)) + '</pre>';
}
async function loadTable(t) {
  const q = await fetch('/api/table/' + t);
  const d = await q.json();
  $('#table-preview').textContent = d.head + '\n' + d.body;
}

async function poll() {
  try {
    state = await (await fetch('/api/state')).json();
    renderState();
  } catch (e) {
    $('#meta').textContent = 'ledger unavailable';
  }
  try {
    logState = await (await fetch('/api/log')).json();
    $('#log').textContent = logState.buf;
    running = logState.running;
    $('#run-state').textContent = running ? 'running…'
      : 'exit ' + (logState.exit ?? '-') + ' · ' + (logState.cmd || '');
    setRunButtons(!running);
    if (!running) loadTable(selTable);
  } catch (e) { /* log not ready */ }
}

function setRunButtons(en) {
  ['b-extract', 'b-import', 'b-pass', 'b-remediate', 'b-export']
    .forEach(id => $(id).disabled = !en);
}
async function doRun(argv) {
  const r = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ argv })
  });
  if (!r.ok) $('#run-state').textContent = (await r.json()).detail;
}

$('#b-extract').onclick = () => doRun(['extract', '--max-usd',
  (Number($('#cap').value) || 0).toFixed(2)]);
$('#b-import').onclick = () => doRun(['verdict', '--import-only']);
$('#b-pass').onclick = () => doRun(['pass']);
$('#b-remediate').onclick = () => doRun(['remediate']);
$('#b-export').onclick = () => doRun(['export']);
$('#b-stop').onclick = async () => { await fetch('/api/stop', { method: 'POST' }); };
$('#table-sel').addEventListener('change', e => loadTable(e.target.value));

setInterval(poll, 1000);
poll();
