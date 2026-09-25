/* Analyst console front end. Vanilla, no framework, no build step. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const money = n => "$" + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

let CASES = [];
let CURRENT = null;
let FILTER = "all";

/* ──────────────────────────────────────────────────────────── boot ── */
async function boot() {
  try {
    const h = await (await fetch("/api/health")).json();
    const g = h.graph || {};
    $("#health").textContent =
      `graph: ${g.backend} · ${(g.transactions || 0).toLocaleString()} txns · ` +
      `${(g.closed_cases || 0).toLocaleString()} closed cases · ${h.answer_files} answer files`;
  } catch { $("#health").textContent = "backend unavailable"; }

  $$(".tab").forEach(t => t.onclick = () => {
    $$(".tab").forEach(x => x.classList.remove("active"));
    $$(".view").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    $("#view-" + t.dataset.view).classList.add("active");
    if (t.dataset.view === "calibration") loadCalibration();
    if (t.dataset.view === "policy") loadPolicy();
    if (t.dataset.view === "approvals") loadApprovals();
  });
  $$(".chip").forEach(c => c.onclick = () => {
    $$(".chip").forEach(x => x.classList.remove("active"));
    c.classList.add("active"); FILTER = c.dataset.filter; renderList();
  });

  CASES = await (await fetch("/api/cases")).json();
  renderList();
  if (CASES.length) openCase(CASES[0].case_id);
  loadApprovals();
}

/* ─────────────────────────────────────────────────────────── inbox ── */
function renderList() {
  const rows = CASES.filter(c => FILTER === "all" || c.verdict === FILTER);
  $("#case-list").innerHTML = rows.map(c => `
    <li data-id="${c.case_id}" class="${CURRENT === c.case_id ? "sel" : ""}">
      <span class="cid">${c.case_id}</span>
      <span><span class="dot v-${c.verdict}"></span></span>
      <span class="meta">${esc(c.trigger)} · p=${c.fraud_probability.toFixed(2)} ·
        ${esc(c.pattern)} · ${money(c.exposure_usd)}${c.sar ? " · SAR" : ""}${c.changed ? " · revised" : ""}</span>
    </li>`).join("") || `<li class="meta" style="padding:16px">no cases match</li>`;
  $$("#case-list li[data-id]").forEach(li => li.onclick = () => openCase(li.dataset.id));
}

async function openCase(id) {
  CURRENT = id; renderList();
  const d = await (await fetch(`/api/cases/${id}`)).json();
  renderDetail(d);
  try { drawGraph(await (await fetch(`/api/graph/${id}`)).json()); } catch { }
}

/* ────────────────────────────────────────────────────────── detail ── */
function renderDetail(d) {
  const c = d.case, r = d.agent_record || {}, nba = d.next_best_actions, sar = d.sar;
  const p = c.fraud_probability;
  const trig = r.trigger || {};

  $("#detail").innerHTML = `
    <div class="case-head">
      <div>
        <h2>${esc(d.case_id)} <span class="t-${c.verdict}">${esc(c.verdict)}</span></h2>
        <div class="sub">${esc(trig.type || "")} · ${esc(trig.text || "")}</div>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn" id="rerun">Re-run investigation live</button>
      </div>
    </div>

    <div class="stat-row">
      ${stat("fraud probability", p.toFixed(2))}
      ${stat("pattern", c.pattern)}
      ${stat("exposure", money(c.exposure_usd))}
      ${stat("affected txns", c.affected_txn_ids.length)}
      ${stat("connected cards", c.connected_card_ids.length)}
      ${stat("SAR", sar.file ? "filed" : "not required")}
      ${stat("status", c.status)}
      ${stat("tool calls", d.tool_calls)}
    </div>

    <div class="panel">
      <h3>Uncertainty</h3>
      <div class="meter">
        <span class="legit-seg" style="width:${((1 - p) * 100).toFixed(1)}%"></span>
        <span class="fraud-seg" style="width:${(p * 100).toFixed(1)}%"></span>
      </div>
      <div class="meter-marks">
        <span>legitimate ${((1 - p) * 100).toFixed(0)}%</span>
        <span>0.15 clear · 0.70 block · 0.85 report</span>
        <span>fraud ${(p * 100).toFixed(0)}%</span>
      </div>
      <div class="bars" style="margin-top:14px">${posteriorBars(r)}</div>
      <p class="note" style="margin:12px 0 0"><strong>Stopped because:</strong> ${esc(d.stop_reason)}</p>
    </div>

    <div class="panel">
      <h3>Next best action — before and after evidence</h3>
      <div class="ba">
        <div class="col"><h4>Initial · before any evidence was requested</h4>${actions(nba.initial)}</div>
        <div class="col"><h4>Final · after the assumed responses</h4>${actions(nba.final)}</div>
      </div>
      <div class="changed"><strong>What changed:</strong> ${esc(nba.what_changed)}</div>
      ${d.evidence_requests.length ? `<div style="margin-top:12px">
        <h4 style="font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-faint);margin-bottom:7px">Evidence requested</h4>
        ${(r.evidence_requests_detail || d.evidence_requests).map(q => `
          <div class="ev">
            <div class="claim"><code>${esc(q.type)}</code>${q.name ? " — " + esc(q.name) : ""}
              ${q.expected_info_gain != null ? `<span class="delta"> · gain ${Number(q.expected_info_gain).toFixed(3)} nats at cost ${q.cost}</span>` : ""}</div>
            <div class="ref">${esc(q.assumed_response)}</div>
            ${q.p_fraud_before != null ? `<div class="ref">posterior ${q.p_fraud_before.toFixed(2)} → ${q.p_fraud_after.toFixed(2)}</div>` : ""}
          </div>`).join("")}
      </div>` : `<p class="note" style="margin-top:10px">No evidence was requested — nothing available
        would have moved the decision enough to justify the friction of asking.</p>`}
    </div>

    <div class="panel">
      <h3>Summary</h3>
      <p style="margin:0">${esc(c.summary)}</p>
      ${c.pattern_description ? `<p style="margin:12px 0 0"><strong>Undocumented pattern:</strong>
        ${esc(c.pattern_description)}</p>` : ""}
    </div>

    <div class="panel">
      <h3>Evidence · ${c.evidence.length} items, ordered by how far each moved belief</h3>
      ${(r.evidence_with_impact || c.evidence).map(e => {
        const dv = e.delta_fraud_probability;
        const cls = dv > 0.005 ? "up" : dv < -0.005 ? "down" : "";
        return `<div class="ev ${cls}">
          <div class="claim">${esc(e.claim)}
            ${dv != null ? `<span class="delta ${dv > 0 ? "t-fraud" : "t-legitimate"}">
              ${dv > 0 ? "+" : ""}${dv.toFixed(3)}</span>` : ""}</div>
          <div class="ref">${esc(e.source)} · ${esc(e.ref)}${(e.entity_ids || []).length ?
            " · " + esc((e.entity_ids || []).slice(0, 6).join(", ")) : ""}</div>
        </div>`;
      }).join("")}
    </div>

    <div class="panel">
      <h3>Case subgraph — what was written to TigerGraph</h3>
      <svg id="graph" viewBox="0 0 900 380" preserveAspectRatio="xMidYMid meet"></svg>
      <p class="note" style="margin:10px 0 0">Graph case id <code>${esc(c.graph_case_id)}</code>.
        The same object <code>case_chain(graph_case_id)</code> walks in the database.</p>
    </div>

    ${sar.file ? `<div class="panel">
      <h3>Suspicious activity report</h3>
      <p class="note">${esc(sar.reason)}</p>
      <div class="sar">${esc(sar.narrative)}</div>
      <div class="stat-row" style="margin-top:12px">
        ${stat("total", money(sar.total_amount_usd))}
        ${stat("activity", (sar.activity_dates || []).join(" → "))}
        ${stat("subjects", (sar.subjects || []).length)}
      </div>
    </div>` : `<div class="panel"><h3>Suspicious activity report</h3>
      <p class="note" style="margin:0">Not filed. ${esc(sar.reason)}</p></div>`}

    <div class="panel">
      <h3>Explanation</h3>
      ${Object.entries(r.explanation || {}).map(([k, v]) =>
        `<p style="margin:0 0 9px"><strong>${esc(k.replace(/_/g, " "))}:</strong> ${esc(v)}</p>`).join("")}
      ${(r.policy_notes || []).map(n => `<p class="note" style="margin:0 0 5px">${esc(n)}</p>`).join("")}
    </div>

    <div class="panel">
      <h3>Prior cases recalled — hybrid graph + vector</h3>
      <div class="scroll-x"><table>
        <tr><th>case</th><th>outcome</th><th>pattern</th><th class="num">cosine</th>
            <th class="num">shared</th><th class="num">fused</th><th>shared with</th></tr>
        ${(r.prior_cases || []).map(p => `<tr>
          <td><code>${esc(p.case_id)}</code></td>
          <td class="t-${p.outcome === "confirmed_fraud" ? "fraud" : "legitimate"}">${esc(p.outcome)}</td>
          <td>${esc(p.pattern)}</td><td class="num">${Number(p.similarity).toFixed(3)}</td>
          <td class="num">${p.shared_entities}</td><td class="num">${Number(p.fused_score).toFixed(3)}</td>
          <td><code>${esc((p.shared_with || []).join(", "))}</code></td></tr>`).join("")}
      </table></div>
    </div>

    <div class="panel">
      <h3>Decision ledger — hash chained</h3>
      <div class="scroll-x"><table>
        <tr><th>#</th><th>node</th><th class="num">P(fraud) before → after</th><th>rationale</th><th>hash</th></tr>
        ${(r.decisions || []).map(x => `<tr>
          <td class="num">${x.step}</td><td><code>${esc(x.node)}</code></td>
          <td class="num">${(x.p_fraud_before ?? fraudOf(x.posterior_before)).toFixed(3)} →
              ${(x.p_fraud_after ?? fraudOf(x.posterior_after)).toFixed(3)}</td>
          <td>${esc(x.rationale)}</td>
          <td><code>${esc(String(x.hash).slice(0, 10))}</code></td></tr>`).join("")}
      </table></div>
      <p class="note" style="margin:10px 0 0">Chain head <code>${esc((r.audit_chain || {}).head || "")}</code>.</p>
    </div>

    <div class="panel">
      <h3>Reasoning trace</h3>
      <div class="trace" id="trace">${traceRows(r.trace || [])}</div>
    </div>`;

  $("#rerun").onclick = () => rerun(d.case_id);
}

const fraudOf = o => Object.entries(o || {}).reduce((a, [k, v]) => a + (k === "none" ? 0 : v), 0);
const stat = (k, v) => `<div class="stat"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`;

function posteriorBars(r) {
  const post = r.posterior || {};
  const labels = r.hypothesis_labels || {};
  const top = Object.entries(post).sort((a, b) => b[1] - a[1])[0]?.[0];
  return Object.entries(post).sort((a, b) => b[1] - a[1]).map(([h, v]) => `
    <div class="bar">
      <span class="name" title="${esc(labels[h] || h)}">${esc(h)}</span>
      <span class="track"><span class="fill ${h === top ? "top" : ""}" style="width:${(v * 100).toFixed(1)}%"></span></span>
      <span class="val">${v.toFixed(3)}</span>
    </div>`).join("");
}

function actions(list) {
  if (!list || !list.length) return `<div class="note">none</div>`;
  return list.map(a => `<div class="act">
    <span class="name">${esc(a.action)}</span>
    <span class="route route-${a.route}">${esc(a.route)}</span>
    <span class="why">${esc(a.reason)}</span></div>`).join("");
}

function traceRows(trace) {
  return trace.map(t => {
    const { node, at, ...rest } = t;
    return `<div class="row"><span class="t">${Number(at).toFixed(2)}s</span>
      <span class="n">${esc(node)}</span>
      <span class="d">${esc(JSON.stringify(rest).slice(0, 320))}</span></div>`;
  }).join("");
}

/* ──────────────────────────────────────────────── live re-run (SSE) ── */
function rerun(id) {
  const btn = $("#rerun");
  btn.disabled = true; btn.textContent = "investigating…";
  const trace = $("#trace");
  trace.innerHTML = "";
  const es = new EventSource(`/api/investigate/${id}`);
  es.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "step") {
      trace.insertAdjacentHTML("beforeend", traceRows([msg.data]));
      trace.scrollTop = trace.scrollHeight;
      if (msg.data.p_fraud != null) {
        const p = msg.data.p_fraud;
        const m = $(".meter");
        if (m) {
          m.children[0].style.width = ((1 - p) * 100).toFixed(1) + "%";
          m.children[1].style.width = (p * 100).toFixed(1) + "%";
          $(".meter-marks").children[0].textContent = `legitimate ${((1 - p) * 100).toFixed(0)}%`;
          $(".meter-marks").children[2].textContent = `fraud ${(p * 100).toFixed(0)}%`;
        }
      }
    } else if (msg.type === "done") {
      es.close(); renderDetail(msg.data);
      fetch(`/api/graph/${id}`).then(r => r.json()).then(drawGraph).catch(() => { });
    } else {
      es.close(); btn.disabled = false; btn.textContent = "Re-run investigation live";
      trace.insertAdjacentHTML("beforeend",
        `<div class="row"><span class="t">!</span><span class="n">error</span>
         <span class="d">${esc(msg.data)}</span></div>`);
    }
  };
  es.onerror = () => { es.close(); btn.disabled = false; btn.textContent = "Re-run investigation live"; };
}

/* ─────────────────────────────────────────────────── graph canvas ── */
const KIND_COLOUR = {
  case: "#5b9dff", card: "#ffb648", customer: "#c08bff", transaction: "#3ecf8e",
  device: "#ff6b6b", connected_card: "#e08a3c", closed_case: "#7b8aa3",
};

function drawGraph(g) {
  const svg = $("#graph");
  if (!svg || !g.nodes.length) return;
  const W = 900, H = 380, cx = W / 2, cy = H / 2;
  const groups = {};
  g.nodes.forEach(n => (groups[n.kind] = groups[n.kind] || []).push(n));
  const pos = {};
  const order = ["case", "card", "customer", "transaction", "device", "connected_card", "closed_case"];
  const rings = { case: 0, card: 95, customer: 95, transaction: 165, device: 165, connected_card: 250, closed_case: 250 };
  let angle = -Math.PI / 2;
  order.forEach(kind => {
    const list = groups[kind] || [];
    list.forEach((n, i) => {
      if (kind === "case") { pos[n.id] = [cx, cy]; return; }
      const r = rings[kind];
      const a = angle + (i / Math.max(list.length, 1)) * Math.PI * 2 * (kind === "connected_card" ? 1 : 0.85);
      pos[n.id] = [cx + r * Math.cos(a) * 1.7, cy + r * Math.sin(a) * 0.82];
    });
    angle += 0.7;
  });

  const lines = g.edges.filter(e => pos[e.from] && pos[e.to]).map(e =>
    `<line x1="${pos[e.from][0]}" y1="${pos[e.from][1]}" x2="${pos[e.to][0]}" y2="${pos[e.to][1]}"
       stroke="#2b3purple" stroke-opacity=".55" stroke-width="1"/>`
      .replace("#2b3purple", "#2b3448")).join("");

  const circles = g.nodes.filter(n => pos[n.id]).map(n => {
    const [x, y] = pos[n.id];
    const r = n.kind === "case" ? 19 : n.flagged ? 10 : 7;
    const fill = KIND_COLOUR[n.kind] || "#7b8aa3";
    const label = String(n.label).length > 22 ? String(n.label).slice(0, 20) + "…" : n.label;
    return `<g><circle cx="${x}" cy="${y}" r="${r}" fill="${fill}"
        fill-opacity="${n.flagged || n.kind === "case" ? 1 : .75}"
        stroke="${n.flagged ? "#fff" : "none"}" stroke-width="1.5"/>
      <title>${esc(n.kind)}: ${esc(n.label)}</title>
      <text x="${x}" y="${y + r + 11}" text-anchor="middle">${esc(label)}</text></g>`;
  }).join("");

  svg.innerHTML = lines + circles;
}

/* ──────────────────────────────────────────────────────── approvals ── */
async function loadApprovals() {
  const rows = await (await fetch("/api/approvals")).json();
  const open = rows.filter(r => !r.decision).length;
  $("#approval-count").textContent = open || "";
  $("#approval-list").innerHTML = rows.map(r => `
    <div class="approval" data-key="${esc(r.key)}">
      <div>
        <code>${esc(r.case_id)}</code> · <strong>${esc(r.action)}</strong>
        <span class="route route-${r.route}">${esc(r.route)}</span>
        <span class="decided"> → ${esc(r.approver)} · exposure ${money(r.exposure_usd)}
          · p=${Number(r.fraud_probability).toFixed(2)}</span>
      </div>
      <div class="actions">${r.decision
        ? `<span class="decided">${r.decision.approved ? "approved" : "rejected"} by
             ${esc(r.decision.analyst)} at ${esc(r.decision.at)}</span>`
        : `<button class="ok" data-a="1">Approve</button><button class="no" data-a="0">Reject</button>`}
      </div>
      <div class="why">${esc(r.reason)}</div>
    </div>`).join("") || `<p class="note">Nothing is waiting — every recommended action was auto-routed.</p>`;

  $$("#approval-list .approval").forEach(el => {
    el.querySelectorAll("button").forEach(b => b.onclick = async () => {
      const [cid, idx] = el.dataset.key.split(":");
      await fetch(`/api/approvals/${cid}/${idx}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved: b.dataset.a === "1", analyst: "ANALYST-01" }),
      });
      loadApprovals();
    });
  });
}

/* ────────────────────────────────────────────────────── calibration ── */
async function loadCalibration() {
  const res = await fetch("/api/calibration");
  if (!res.ok) { $("#calibration-table").innerHTML = `<p class="note">${esc(await res.text())}</p>`; return; }
  const d = await res.json();
  const h = d.holdout || {};
  $("#calibration-head").innerHTML =
    stat("alerts replayed", (d.n_cases || 0).toLocaleString()) +
    stat("held-out accuracy", (h.accuracy ?? 0).toFixed(3)) +
    stat("Brier score", (h.brier ?? 0).toFixed(4)) +
    stat("expected calib. error", (h.ece ?? 0).toFixed(4)) +
    stat("damping", d.damping);
  $("#calibration-table").innerHTML = `<div class="scroll-x"><table>
    <tr><th>signal</th><th class="num">P(s|fraud)</th><th class="num">P(s|cleared)</th>
        <th class="num">LR fired</th><th class="num">LR absent</th>
        <th class="num">n fraud</th><th class="num">n cleared</th></tr>
    ${d.likelihood_ratios.map(r => `<tr>
      <td><code>${esc(r.signal)}</code></td>
      <td class="num">${r.p_given_fraud.toFixed(3)}</td>
      <td class="num">${r.p_given_cleared.toFixed(3)}</td>
      <td class="num ${r.lr_fired > 1.3 ? "t-fraud" : r.lr_fired < 0.77 ? "t-legitimate" : ""}">
        ${r.lr_fired.toFixed(2)}</td>
      <td class="num">${r.lr_absent.toFixed(2)}</td>
      <td class="num">${r.n_fired_fraud}</td><td class="num">${r.n_fired_cleared}</td></tr>`).join("")}
  </table></div>`;
}

/* ─────────────────────────────────────────────────────────── policy ── */
async function loadPolicy() {
  const rows = await (await fetch("/api/policy")).json();
  $("#policy-list").innerHTML = rows.map(r =>
    `<div class="ev"><div class="claim"><code>${esc(r.rule)}</code></div>
     <div class="ref" style="color:var(--ink-dim);font-family:var(--sans);font-size:12.5px">
       ${esc(r.text)}</div></div>`).join("");
}

boot();
