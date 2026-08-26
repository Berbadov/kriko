// Kriko dashboard. Plain ES modules, no build step, no dependencies.
//
// The one idea worth knowing before reading this file: **the form is generated
// from pack data.** Nothing here knows what a car is or what a drill is. It
// asks the store which attributes actually identify a subject in the selected
// pack, and builds inputs for those. Adding a category changes what this page
// asks for without changing a line of it.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const api = async (path, options) => {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
};

const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ── tabs ──────────────────────────────────────────────────────────────
$$(".tab").forEach((tab) => tab.addEventListener("click", () => {
  $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
  $$("section").forEach((s) => s.classList.toggle("active", s.id === tab.dataset.tab));
  if (tab.dataset.tab === "packs") renderPacks();
  if (tab.dataset.tab === "browse") renderSubjects();
}));

// ── ask ───────────────────────────────────────────────────────────────
let packs = [];

async function boot() {
  packs = await api("/api/packs");
  const enabled = packs.filter((p) => p.enabled);
  $("#pack").innerHTML = enabled.map(
    (p) => `<option value="${esc(p.pack_id)}">${esc(p.name)}</option>`).join("");
  if (!enabled.length) {
    $("#result").innerHTML =
      `<p class="empty">No packs installed. Build one with
       <code>kriko build packs/drill</code> and install it with
       <code>kriko install dist/drill.kpack</code>.</p>`;
    return;
  }
  await onPackChange();
}

async function onPackChange() {
  const packId = $("#pack").value;
  const kinds = await api("/api/kinds");
  const mine = kinds.filter((k) => k.pack_id === packId);
  $("#kind").innerHTML = mine.map(
    (k) => `<option value="${esc(k.kind)}">${esc(k.kind)} (${k.n})</option>`).join("");

  const keys = await api(`/api/identity-keys/${encodeURIComponent(packId)}`);
  $("#identity-fields").innerHTML = keys.map((k) => `
    <div class="field">
      <label for="id-${esc(k.key)}">${esc(k.key)}</label>
      <input id="id-${esc(k.key)}" data-identity="${esc(k.key)}">
    </div>`).join("");

  const vocab = await api(`/api/packs/${encodeURIComponent(packId)}/vocabulary`);
  const contextKeys = vocab.context_key || [];
  $("#context-fields").innerHTML = contextKeys.map((t) => `
    <div class="field">
      <label for="ctx-${esc(t.term_id)}">${esc(t.term_id)}${
        t.unit ? ` <span class="meta">(${esc(t.unit)})</span>` : ""}</label>
      <input id="ctx-${esc(t.term_id)}" data-context="${esc(t.term_id)}">
    </div>`).join("");
}

const collect = (attr) => Object.fromEntries(
  $$(`[data-${attr}]`)
    .filter((el) => el.value.trim())
    .map((el) => {
      const raw = el.value.trim();
      const num = Number(raw);
      return [el.dataset[attr], raw !== "" && !Number.isNaN(num) ? num : raw];
    }));

async function ask() {
  const body = {
    kind: $("#kind").value || "product",
    identity: collect("identity"),
    context: collect("context"),
    limit: 12,
  };
  $("#result").innerHTML = `<p class="empty">…</p>`;
  const data = await api("/api/lookup", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  renderResult(data);
}

function renderResult(data) {
  const head = `
    <p class="meta" style="margin-top:18px">
      match <strong>${esc(data.method)}</strong> ·
      ${esc(data.coverage)} ·
      ${data.subjects.length} subject(s)
      ${data.flags.map((f) => `<span class="flag">· ${esc(f)}</span>`).join("")}
    </p>`;

  if (!data.claims.length) {
    $("#result").innerHTML = head +
      `<p class="empty">Nothing known about this one yet.</p>`;
    return;
  }

  $("#result").innerHTML = head + data.claims.map((c) => `
    <article class="card">
      <h3>
        <span class="sev ${esc(c.severity)}">${esc(c.severity)}</span>
        ${esc(c.title)}
        ${c.disputed ? '<span class="badge disputed">disputed</span>' : ""}
      </h3>
      <p class="meta">
        ${esc(c.subject)} · ${esc(c.domain)} ·
        relevance ${c.relevance} · <span class="badge">${esc(c.pack_id)}</span>
      </p>
      ${c.body ? `<p>${esc(c.body)}</p>` : ""}
      ${c.advice ? `<p class="meta"><strong>Check:</strong> ${esc(c.advice)}</p>` : ""}
      <details>
        <summary>Why this is here, and where it came from</summary>
        <ul class="why">${c.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>
        ${c.sources.map((s) => `
          <blockquote class="${esc(s.stance)}">
            ${esc(s.quote)}<br>
            <span class="meta">${s.stance === "refutes" ? "contradicts · " : ""}
              ${esc(s.tier)} · <a href="${esc(s.url)}" target="_blank"
              rel="noreferrer noopener">${esc(s.domain || s.url)}</a></span>
          </blockquote>`).join("")}
      </details>
    </article>`).join("");
}

// ── browse ────────────────────────────────────────────────────────────
async function renderSubjects() {
  const q = $("#search").value.trim();
  const rows = await api(`/api/subjects?limit=60&q=${encodeURIComponent(q)}`);
  $("#subject-detail").innerHTML = "";
  if (!rows.length) {
    $("#subjects").innerHTML = `<p class="empty">Nothing matches.</p>`;
    return;
  }
  $("#subjects").innerHTML = `
    <table>
      <thead><tr><th>Subject</th><th>Kind</th><th>Pack</th>
        <th class="num">Claims</th></tr></thead>
      <tbody>${rows.map((r) => `
        <tr data-subject="${esc(r.subject_id)}" style="cursor:pointer">
          <td>${esc(r.label)}</td><td class="meta">${esc(r.kind)}</td>
          <td class="meta">${esc(r.pack_id)}</td>
          <td class="num">${r.claims}</td>
        </tr>`).join("")}</tbody>
    </table>`;
  $$("[data-subject]").forEach((tr) => tr.addEventListener(
    "click", () => showSubject(tr.dataset.subject)));
}

async function showSubject(id) {
  const s = await api(`/api/subjects/${encodeURIComponent(id)}`);
  const brief = await api(`/api/subjects/${encodeURIComponent(id)}/brief`);
  $("#subject-detail").innerHTML = `
    <article class="card">
      <h3>${esc(s.label)}</h3>
      <p class="meta">${esc(s.kind)} · ${esc(s.pack_id)}</p>
      <table>
        <tbody>${s.attributes.map((a) => `
          <tr><td class="meta">${esc(a.key)}${a.is_identity ? " *" : ""}</td>
              <td>${esc(a.value_text)}${a.unit ? " " + esc(a.unit) : ""}
              ${a.valid_from ? `<span class="meta"> (${esc(a.valid_from)}–${
                esc(a.valid_to || "")})</span>` : ""}</td></tr>`).join("")}
        </tbody>
      </table>
      ${s.relations.length ? `<p class="meta" style="margin-top:10px">
        Built from: ${s.relations.map((r) => esc(r.object_label || r.object_id)).join(", ")}
      </p>` : `<p class="meta" style="margin-top:10px">No components — claims attach
        directly to this subject.</p>`}
      <details ${s.claims.length ? "" : "open"}>
        <summary>Research brief (${brief.queries.length} searches) — paste into a
          coding agent; the subscription does the work</summary>
        <pre><code>${esc(brief.brief)}</code></pre>
      </details>
    </article>`;
}

// ── packs ─────────────────────────────────────────────────────────────
async function renderPacks() {
  packs = await api("/api/packs");
  if (!packs.length) {
    $("#pack-list").innerHTML = `<p class="empty">No packs installed.</p>`;
    return;
  }
  $("#pack-list").innerHTML = packs.map((p) => `
    <article class="card">
      <h3>${esc(p.name)} <span class="badge">${esc(p.version)}</span></h3>
      <p class="meta">
        ${esc(p.pack_id)} · ${p.subjects} subjects · ${p.claims} claims ·
        ${p.evidence} evidence · digest ${esc(p.digest)}
        ${p.license ? ` · ${esc(p.license)}` : ""}
      </p>
      <div class="row" style="margin-top:8px">
        <button data-toggle="${esc(p.pack_id)}" data-enabled="${p.enabled}">
          ${p.enabled ? "Disable" : "Enable"}
        </button>
        <button class="danger ghost" data-remove="${esc(p.pack_id)}">Uninstall</button>
        <span class="meta">${p.enabled ? "" : "disabled — rows kept, hidden from every read"}</span>
      </div>
    </article>`).join("");

  $$("[data-toggle]").forEach((b) => b.addEventListener("click", async () => {
    const on = b.dataset.enabled !== "true";
    await api(`/api/packs/${encodeURIComponent(b.dataset.toggle)}/enabled?enabled=${on}`,
      { method: "POST" });
    renderPacks();
  }));
  $$("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Uninstall ${b.dataset.remove}? Every other pack is untouched.`)) return;
    await api(`/api/packs/${encodeURIComponent(b.dataset.remove)}`, { method: "DELETE" });
    renderPacks();
  }));
}

// ── wiring ────────────────────────────────────────────────────────────
$("#pack").addEventListener("change", onPackChange);
$("#go").addEventListener("click", ask);
$("#clear").addEventListener("click", () => {
  $$("[data-identity], [data-context]").forEach((el) => (el.value = ""));
  $("#result").innerHTML = "";
});
$("#search").addEventListener("input", () => {
  clearTimeout(window.__t);
  window.__t = setTimeout(renderSubjects, 180);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && $("#ask").classList.contains("active")) ask();
});

boot().catch((err) => {
  $("#result").innerHTML = `<p class="empty">${esc(err.message)}</p>`;
});
