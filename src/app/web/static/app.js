const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const esc = (value) =>
    String(value ?? "").replace(
        /[&<>\"]/g,
        (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
    );

async function api(path, options) {
    const response = await fetch(path, options);
    if (!response.ok)
        throw new Error(`${response.status}: ${await response.text()}`);
    return response.json();
}

function showError(target, error) {
    $(target).innerHTML =
        `<p class="state error">Could not load this view: ${esc(error.message)}</p>`;
}

let packs = [];
async function prepareAsk() {
    packs = await api("/api/packs");
    const enabled = packs.filter((pack) => pack.enabled);
    $("#pack").innerHTML = enabled
        .map(
            (pack) =>
                `<option value="${esc(pack.pack_id)}">${esc(pack.name)}</option>`,
        )
        .join("");
    if (enabled.length) await changeAskPack();
    else
        $("#result").innerHTML =
            `<p class="state empty">No packs installed.</p>`;
}
async function changeAskPack() {
    const packId = $("#pack").value;
    const [kinds, keys, vocabulary] = await Promise.all([
        api("/api/kinds"),
        api(`/api/identity-keys/${encodeURIComponent(packId)}`),
        api(`/api/packs/${encodeURIComponent(packId)}/vocabulary`),
    ]);
    $("#kind").innerHTML = kinds
        .filter((kind) => kind.pack_id === packId)
        .map(
            (kind) =>
                `<option value="${esc(kind.kind)}">${esc(kind.kind)}</option>`,
        )
        .join("");
    $("#identity-fields").innerHTML = keys
        .map(
            (key) =>
                `<div class="field"><label>${esc(key.key)}</label><input data-identity="${esc(key.key)}"></div>`,
        )
        .join("");
    $("#context-fields").innerHTML = (vocabulary.context_key || [])
        .map(
            (term) =>
                `<div class="field"><label>${esc(term.term_id)} <span class="meta">${esc(term.unit)}</span></label><input data-context="${esc(term.term_id)}"></div>`,
        )
        .join("");
}
const collectFields = (kind) =>
    Object.fromEntries(
        $$(`[data-${kind}]`)
            .filter((field) => field.value.trim())
            .map((field) => [
                field.dataset[kind],
                Number.isNaN(Number(field.value))
                    ? field.value.trim()
                    : Number(field.value),
            ]),
    );
async function ask() {
    $("#result").innerHTML = `<p class="state loading">Looking up…</p>`;
    try {
        const data = await api("/api/lookup", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
                kind: $("#kind").value,
                identity: collectFields("identity"),
                context: collectFields("context"),
            }),
        });
        $("#result").innerHTML = data.claims.length
            ? data.claims
                  .map(
                      (claim) =>
                          `<article class="card"><h3>${esc(claim.title)}</h3><p>${esc(claim.body)}</p><p class="meta">${esc(claim.subject)} · ${esc(claim.pack_id)}</p></article>`,
                  )
                  .join("")
            : `<p class="state ${data.method === "no_match" ? "no-match" : "empty"}">${data.method === "no_match" ? "No matching subject." : "No claims found."}</p>`;
    } catch (error) {
        showError("#result", error);
    }
}

async function renderDashboard() {
    try {
        const [status, activity] = await Promise.all([
            api("/api/status"),
            api("/api/activity"),
        ]);
        $("#status").innerHTML = [
            ["Packs", status.packs],
            ["Enabled", status.enabled_packs],
            ["Subjects", status.counts.subjects],
            ["Claims", status.counts.claims],
            ["Analyses", activity.items.length],
        ]
            .map(
                ([label, value]) =>
                    `<div class="stat"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`,
            )
            .join("");
        if (!activity.items.length) {
            $("#activity").innerHTML =
                `<p class="state empty">No analysis activity yet.</p>`;
            return;
        }
        $("#activity").innerHTML =
            `<table><thead><tr><th>When</th><th>URL</th><th>Method</th><th>Coverage</th><th>Claims</th></tr></thead><tbody>${activity.items.map((item) => `<tr><td class="meta">${esc(item.timestamp || item.created_at || "—")}</td><td>${esc(item.url || "—")}</td><td>${esc(item.method || "—")}</td><td>${esc(item.coverage || "—")}</td><td class="num">${Array.isArray(item.claim_titles) ? item.claim_titles.length : "—"}</td></tr>`).join("")}</tbody></table>`;
    } catch (error) {
        showError("#activity", error);
    }
}

function renderAnalysis(data) {
    const coverage = data.coverage || "UNKNOWN";
    let state = data.claims?.length
        ? "results"
        : coverage === "NOT_MATCHED"
          ? "no-match"
          : "empty";
    const message = {
        "no-match": "No installed pack matched this listing.",
        empty: "A subject matched, but there are no claims to show.",
        results: "Known risks for this listing.",
    }[state];
    $("#raw-result").innerHTML =
        `<div class="state ${state}"><strong>${esc(message)}</strong><span> ${esc(coverage)} · ${esc(data.method || "—")}</span></div>` +
        (data.claims || [])
            .map(
                (claim) =>
                    `<article class="card"><h3><span class="sev ${esc(claim.severity)}">${esc(claim.severity)}</span> ${esc(claim.title)}</h3><p>${esc(claim.body)}</p><p class="meta">${esc(claim.subject)} · ${esc(claim.pack_id)} · relevance ${esc(claim.relevance)}</p></article>`,
            )
            .join("");
}

async function analyzeRaw() {
    const result = $("#raw-result");
    let fields;
    try {
        fields = JSON.parse($("#raw-fields").value || "{}");
    } catch (error) {
        result.innerHTML = `<p class="state error">Fields must be a JSON object: ${esc(error.message)}</p>`;
        return;
    }
    if (!$("#raw-url").value.trim()) {
        result.innerHTML = `<p class="state error">URL is required.</p>`;
        return;
    }
    result.innerHTML = `<p class="state loading">Analyzing…</p>`;
    try {
        const data = await api("/api/analyze", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({
                url: $("#raw-url").value.trim(),
                title: $("#raw-title").value,
                description: $("#raw-description").value,
                fields,
            }),
        });
        renderAnalysis(data);
        renderDashboard();
    } catch (error) {
        const unknown = error.message.startsWith("404:");
        result.innerHTML = unknown
            ? `<p class="state unknown">No adapter is installed for this listing.</p>`
            : `<p class="state error">Analysis failed: ${esc(error.message)}</p>`;
    }
}

async function renderCoverage() {
    const target = $("#coverage-list");
    try {
        const installed = await api("/api/packs");
        if (!installed.length) {
            target.innerHTML = `<p class="state empty">No packs installed.</p>`;
            return;
        }
        const sections = await Promise.all(
            installed.map(async (pack) => {
                const gaps = await api(
                    `/api/packs/${encodeURIComponent(pack.pack_id)}/gaps`,
                );
                return `<article class="card"><h3>${esc(pack.name)} <span class="badge">${gaps.length} gap(s)</span></h3>${gaps.length ? `<ul>${gaps.map((gap) => `<li>${esc(gap.label)} <span class="meta">(${esc(gap.kind)})</span></li>`).join("")}</ul>` : `<p class="state empty">No coverage gaps reported.</p>`}</article>`;
            }),
        );
        target.innerHTML = sections.join("");
    } catch (error) {
        showError("#coverage-list", error);
    }
}

const SIGNAL_NOTE = {
    refuted: "a source in the pack contradicts this claim",
    thin: "only one independent source supports this",
    weak: "the best supporting source is a low-trust tier",
};

function healthRow(claim) {
    const refuted = claim.refuted_by > 0;
    const stale = claim.oldest_retrieved_at || "unknown";
    const note = refuted
        ? SIGNAL_NOTE.refuted
        : claim.independent_sources <= 1
          ? SIGNAL_NOTE.thin
          : claim.best_trust < 0.5
            ? SIGNAL_NOTE.weak
            : "";
    return `<tr class="${refuted ? "concern" : ""}">
        <td>${esc(claim.title)}<div class="meta">${esc(claim.subject_label)} · ${esc(claim.pack_id)}</div>${note ? `<div class="meta">${esc(note)}</div>` : ""}</td>
        <td class="num signal">${refuted ? `<span class="badge">${claim.refuted_by} refuting</span>` : "—"}</td>
        <td class="num signal">${claim.independent_sources}</td>
        <td class="signal">${esc(claim.best_tier)} <span class="meta">${claim.best_trust.toFixed(2)}</span></td>
        <td class="signal ${claim.oldest_retrieved_at ? "" : "stale"}">${esc(stale)}</td>
        <td><button data-tree="${esc(claim.subject_id)}" data-claim="${esc(claim.claim_id)}">Evidence</button></td>
    </tr>`;
}

function tieNote(claims) {
    if (!claims.length) return "";
    const top = JSON.stringify(claims[0].concern);
    const tied = claims.filter((c) => JSON.stringify(c.concern) === top).length;
    if (tied < 2) return "";
    return `${tied} of the claims shown tie on every signal but best-source
        trust — today only that one column differentiates the top of this
        list. This list is not the whole ranking, just the worst ${claims.length}.`;
}

async function renderHealth() {
    const target = $("#health-list");
    const note = $("#health-tie-note");
    try {
        const { claims } = await api("/api/health/weakest?limit=40");
        if (note) note.textContent = tieNote(claims);
        if (!claims.length) {
            target.innerHTML = `<p class="state empty">No sourced claims installed yet.</p>`;
            return;
        }
        target.innerHTML = `<table><thead><tr>
                <th>Claim</th><th>Contradicted</th><th>Independent sources</th>
                <th>Best source</th><th>Last retrieved</th><th></th>
            </tr></thead><tbody>${claims.map(healthRow).join("")}</tbody></table>
            <div id="health-tree"></div>`;
        $$("[data-tree]", target).forEach((button) =>
            button.addEventListener("click", () =>
                renderHealthTree(button.dataset.tree, button.dataset.claim),
            ),
        );
    } catch (error) {
        showError("#health-list", error);
    }
}

function evidenceHtml(evidence) {
    return evidence.length
        ? evidence
              .map(
                  (row) =>
                      `<blockquote class="${row.stance === "refutes" ? "refutes" : ""}">${esc(row.quote)}<footer class="meta">${esc(row.domain)} · ${esc(row.tier)} · ${esc(row.stance)}${row.independent ? "" : " · not independent"} · retrieved ${esc(row.retrieved_at || "unknown")}</footer></blockquote>`,
              )
              .join("")
        : `<p class="state empty">No sources — this claim rests on an interval or a rule, not a citation.</p>`;
}

function claimDetails({ health, evidence }, { open = false, asked = false } = {}) {
    return `<details${open ? " open" : ""} class="${asked ? "asked" : ""}"><summary>${esc(health.title)} <span class="meta">${health.independent_sources} source(s) · ${esc(health.best_tier)}</span></summary>${evidenceHtml(evidence)}</details>`;
}

async function renderHealthTree(subjectId, claimId) {
    const target = $("#health-tree");
    try {
        const tree = await api(
            `/api/health/subject/${encodeURIComponent(subjectId)}`,
        );
        const asked = claimId
            ? tree.claims.find((node) => node.health.claim_id === claimId)
            : undefined;
        const rest = tree.claims.filter((node) => node !== asked);
        const askedHtml = asked
            ? `<p class="meta"><span class="badge">Asked about</span> ${esc(asked.health.title)}</p>${claimDetails(asked, { open: true, asked: true })}`
            : "";
        const restHtml = rest.length
            ? `<p class="meta">Rest of ${esc(tree.label || subjectId)} <span class="badge">${rest.length} more claim(s)</span></p>${rest.map((node) => claimDetails(node)).join("")}`
            : "";
        target.innerHTML = `<article class="card"><h3>${esc(tree.label || subjectId)} <span class="badge">${tree.claims.length} claim(s)</span></h3>${askedHtml}${restHtml}</article>`;
        if (asked) $(".asked", target)?.scrollIntoView({ block: "nearest" });
    } catch (error) {
        showError("#health-tree", error);
    }
}

async function renderRevisions(packId) {
    const target = $(`[data-revisions="${CSS.escape(packId)}"]`);
    try {
        const [revisions, events] = await Promise.all([
            api(`/api/packs/${encodeURIComponent(packId)}/revisions`),
            api(`/api/packs/${encodeURIComponent(packId)}/events`),
        ]);
        target.innerHTML = `<details open><summary>Revision history (${revisions.length})</summary>${revisions.length ? `<table><thead><tr><th>Revision</th><th>Installed</th><th>State</th><th></th></tr></thead><tbody>${revisions.map((r) => `<tr><td>${esc(r.version)} <span class="meta">${esc(r.content_digest.slice(0, 12))}</span></td><td class="meta">${esc(r.installed_at)}</td><td>${r.active ? "active" : "retained"}</td><td>${r.active ? "" : `<button data-activate="${esc(packId)}" data-revision="${esc(r.revision_id)}">Activate</button>`}</td></tr>`).join("")}</tbody></table>` : `<p class="state empty">No retained revisions.</p>`}<p class="meta">${events.length} lifecycle event(s)</p>${events
            .slice(-5)
            .reverse()
            .map(
                (e) =>
                    `<div class="event"><strong>${esc(e.action)}</strong> · ${esc(e.created_at)} <span class="meta">${esc(e.revision_id)}</span></div>`,
            )
            .join("")}</details>`;
        $$("[data-activate]").forEach((button) =>
            button.addEventListener("click", async () => {
                await api(
                    `/api/packs/${encodeURIComponent(button.dataset.activate)}/activate?revision=${encodeURIComponent(button.dataset.revision)}`,
                    { method: "POST" },
                );
                renderPacks();
            }),
        );
    } catch (error) {
        target.innerHTML = `<p class="state error">Lifecycle data unavailable: ${esc(error.message)}</p>`;
    }
}

async function installPack() {
    const result = $("#pack-install-result");
    const file = $("#pack-file").files[0];
    if (!file) {
        result.innerHTML = `<p class="state error">Choose a .kpack file first.</p>`;
        return;
    }
    result.innerHTML = `<p class="state loading">Installing ${esc(file.name)}…</p>`;
    try {
        const data = await api("/api/packs/install", {
            method: "POST",
            headers: { "X-Filename": file.name },
            body: file,
        });
        result.innerHTML = `<p class="state results">Installed ${esc(data.pack.name)} <span class="meta">${esc(data.pack.version)} · ${esc(data.revision.revision_id)}</span></p>`;
        $("#pack-file").value = "";
        await renderPacks();
        renderDashboard();
        prepareAsk();
    } catch (error) {
        result.innerHTML = `<p class="state error">Install failed: ${esc(error.message)}</p>`;
    }
}

async function renderPacks() {
    try {
        const rows = await api("/api/packs");
        $("#pack-list").innerHTML = rows.length
            ? rows
                  .map(
                      (pack) =>
                          `<article class="card"><h3>${esc(pack.name)} <span class="badge">${esc(pack.version)}</span></h3><p class="meta">${esc(pack.pack_id)} · ${pack.subjects} subjects · ${pack.claims} claims · ${pack.evidence} evidence · digest ${esc(pack.digest)}</p><div class="row"><button data-toggle="${esc(pack.pack_id)}" data-enabled="${pack.enabled}">${pack.enabled ? "Disable" : "Enable"}</button><button class="ghost danger" data-revisions="load-${esc(pack.pack_id)}">Lifecycle</button><span class="meta">${pack.enabled ? "" : "disabled"}</span></div><div data-revisions="${esc(pack.pack_id)}"></div></article>`,
                  )
                  .join("")
            : `<p class="state empty">No packs installed.</p>`;
        $$("[data-toggle]").forEach((button) =>
            button.addEventListener("click", async () => {
                await api(
                    `/api/packs/${encodeURIComponent(button.dataset.toggle)}/enabled?enabled=${button.dataset.enabled !== "true"}`,
                    { method: "POST" },
                );
                renderPacks();
            }),
        );

        $$('[data-revisions^="load-"]').forEach((button) =>
            button.addEventListener("click", () =>
                renderRevisions(button.dataset.revisions.slice(5)),
            ),
        );
    } catch (error) {
        showError("#pack-list", error);
    }
}

async function renderSubjects() {
    try {
        const rows = await api(
            `/api/subjects?limit=60&q=${encodeURIComponent($("#search").value.trim())}`,
        );
        $("#subjects").innerHTML = rows.length
            ? `<table><thead><tr><th>Subject</th><th>Kind</th><th>Pack</th><th>Claims</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(r.label)}</td><td>${esc(r.kind)}</td><td>${esc(r.pack_id)}</td><td class="num">${r.claims}</td></tr>`).join("")}</tbody></table>`
            : `<p class="state empty">No matching subjects.</p>`;
    } catch (error) {
        showError("#subjects", error);
    }
}

$$(".tab").forEach((tab) =>
    tab.addEventListener("click", () => {
        $$(".tab").forEach((item) =>
            item.classList.toggle("active", item === tab),
        );
        $$("section").forEach((section) =>
            section.classList.toggle("active", section.id === tab.dataset.tab),
        );
        if (tab.dataset.tab === "dashboard") renderDashboard();
        if (tab.dataset.tab === "ask") prepareAsk();
        if (tab.dataset.tab === "coverage") renderCoverage();
        if (tab.dataset.tab === "health") renderHealth();
        if (tab.dataset.tab === "packs") renderPacks();
        if (tab.dataset.tab === "browse") renderSubjects();
    }),
);
$("#pack").addEventListener("change", changeAskPack);
$("#pack-install").addEventListener("click", installPack);
$("#go").addEventListener("click", ask);
$("#clear").addEventListener("click", () => {
    $("#result").innerHTML = "";
    $$("[data-identity], [data-context]").forEach(
        (field) => (field.value = ""),
    );
});
$("#raw-go").addEventListener("click", analyzeRaw);
$("#raw-clear").addEventListener("click", () => {
    ["raw-url", "raw-title", "raw-description"].forEach(
        (id) => ($("#" + id).value = ""),
    );
    $("#raw-fields").value = "{}";
    $("#raw-result").innerHTML = "";
});
$("#search").addEventListener("input", () => {
    clearTimeout(window.__searchTimer);
    window.__searchTimer = setTimeout(renderSubjects, 180);
});
renderDashboard();
prepareAsk();
