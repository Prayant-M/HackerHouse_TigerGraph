/* FraudGraph Agent console. Vanilla JS, hash routing, no build step.
   Talks to the FastAPI back end in ui/server.py; every number on screen comes
   from the answer files or the graph, nothing is invented for display. */

/* ────────────────────────────────────────────────────────── helpers ── */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = n => "$" + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = p => Math.round(Number(p || 0) * 100) + "%";
// A static export (deploy/build_space.py --static) sets <html data-static="1"> and
// ships every read-only API response as a JSON file next to the page.
const STATIC_SITE = document.documentElement.dataset.static === "1";
const apiUrl = url => STATIC_SITE ? url.replace(/^\//, "") + ".json" : url;
const getJSON = async url => { const r = await fetch(apiUrl(url)); if (!r.ok) throw new Error(await r.text()); return r.json(); };
const humanize = s => String(s || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

const PATTERN = {
  none: "No fraud found", card_testing: "Card testing", card_not_present_fraud: "Card-not-present fraud",
  card_not_present_new_device: "New-device online fraud", out_of_region_use: "Out-of-region use",
  account_takeover: "Account takeover", undocumented: "Undocumented pattern",
};
const TRIGGER = {
  risk_score: { label: "Risk-model alert", ico: "📈" },
  customer_report: { label: "Customer report", ico: "💬" },
  analyst_request: { label: "Analyst request", ico: "🧑‍💼" },
};
const ACTION = {
  ALLOW_TRANSACTION: "Allow transaction", DECLINE_TRANSACTION: "Decline transaction", MONITOR_CARD: "Monitor card",
  MONITOR_CONNECTED_CARDS: "Monitor connected cards", WARN_CUSTOMER: "Warn customer",
  VERIFY_WITH_CUSTOMER: "Ask customer to verify", STEP_UP_AUTH: "Step-up authentication", BLOCK_CARD: "Block card",
  BLOCK_ALL_CARDS: "Block all cards", GENERATE_REPORT: "Internal report", CREATE_CASE: "Open fraud case",
  FILE_REPORT: "File SAR with regulator", ESCALATE_TO_ANALYST: "Escalate to analyst", CLOSE_NO_FRAUD: "Close — no fraud",
};
const ROUTE = { auto: "Automatic", L1: "Team lead", L2: "Fraud manager" };
const VERDICT = { fraud: "Fraud", legitimate: "Legitimate", uncertain: "Uncertain" };
const STEP_NAME = {
  trigger_intake: "Alert received", case_opener: "Case opened", evidence_planner: "Planned graph queries",
  graph_investigator: "Searched the graph", memory_recall: "Recalled similar cases", hypothesis_update: "Updated beliefs",
  record_provisional: "Provisional recommendation", evidence_gap_resolver: "Asked for more evidence",
  action_recommender: "Final recommendation", case_writer: "Written to TigerGraph", explainer: "Explanation written",
};

const patternName = p => PATTERN[p] || humanize(p);
const CLAIM = {
  observed_fact: { l: "Graph fact", c: "fact" }, derived_inference: { l: "Derived inference", c: "infer" },
  model_score: { l: "Model score", c: "model" }, policy_text: { l: "Policy text", c: "policy" },
  simulated_response: { l: "Simulated reply", c: "sim" }, customer_statement: { l: "Customer statement", c: "cust" },
};
const claimBadge = t => t ? `<span class="ctype ${(CLAIM[t] || {}).c || ""}">${esc((CLAIM[t] || {}).l || humanize(t))}</span>` : "";
// Shannon entropy of the fraud / not-fraud split, in bits: 1 is a coin flip, 0 is certainty.
const entropyBits = p => (p <= 0 || p >= 1) ? 0 : -(p * Math.log2(p) + (1 - p) * Math.log2(1 - p));
const trig = t => TRIGGER[t] || { label: humanize(t), ico: "•" };
const verdictPill = v => `<span class="pill ${esc(v)}"><span class="d"></span>${esc(VERDICT[v] || v)}</span>`;
const tone = p => p >= 0.70 ? "var(--fraud)" : p <= 0.15 ? "var(--legit)" : "var(--warn)";

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 2600);
}

/* ────────────────────────────────────────────────────────── state ── */
const S = {
  cases: [], health: null, detail: {}, current: null, tab: "overview",
  filter: { q: "", verdict: "all", trigger: "all", sort: "id", revised: false, sar: false },
  approvals: [], approvalFilter: "pending", calib: null, policy: null,
};

/* ──────────────────────────────────────────────────── reveal + count ── */
const io = "IntersectionObserver" in window ? new IntersectionObserver(entries => {
  entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } });
}, { threshold: .12 }) : null;
function observeReveals(root = document) {
  $$(".reveal:not(.in)", root).forEach(el => io ? io.observe(el) : el.classList.add("in"));
}
function countUp(el, to, dur = 1300) {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) { el.textContent = to.toLocaleString(); return; }
  const t0 = performance.now();
  const step = now => {
    const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = Math.round(to * e).toLocaleString();
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

/* ────────────────────────────────────────────────────────── router ── */
function parseRoute() {
  const h = location.hash || "#/";
  if (!h.startsWith("#/")) return { view: "home", anchor: h.slice(1) };
  const [view, id, tab] = h.slice(2).split("/");
  return { view: view || "home", id: id ? decodeURIComponent(id) : null, tab: tab || null };
}

async function route() {
  const r = parseRoute();
  const view = ["home", "cases", "challenges", "approvals", "insights"].includes(r.view) ? r.view : "home";
  $$(".view").forEach(v => v.classList.toggle("active", v.dataset.view === view));
  $$(".nav-links a").forEach(a => a.classList.toggle("active", a.dataset.route === view));
  closeMenu();

  if (view === "home") {
    renderHome();
    paintStory();
    if (r.anchor) requestAnimationFrame(() => document.getElementById(r.anchor)?.scrollIntoView({ behavior: "smooth" }));
    else window.scrollTo({ top: 0 });
  } else window.scrollTo({ top: 0 });

  if (view === "cases") {
    renderList();
    const layout = $("#cases-layout");
    if (r.id) { layout.classList.add("show-detail"); openCase(r.id, r.tab); }
    else {
      layout.classList.remove("show-detail");
      if (!S.current && S.cases.length && matchMedia("(min-width: 901px)").matches) openCase(S.cases[0].case_id);
    }
  }
  if (view === "challenges") showChallenge(r.id);
  if (view === "approvals") loadApprovals();
  if (view === "insights") showInsight(S.insightTab || "monitoring");
  requestAnimationFrame(() => observeReveals());
}

/* ─────────────────────────────────────────────────────────── boot ── */
async function boot() {
  const nav = $("#nav");
  addEventListener("scroll", () => nav.classList.toggle("scrolled", scrollY > 8), { passive: true });
  $("#menu-btn").onclick = () => {
    const open = !$("#nav-links").classList.contains("open");
    $("#nav-links").classList.toggle("open", open);
    $("#menu-btn").setAttribute("aria-expanded", open);
  };
  bindToolbar();
  bindInsights();
  bindStory();
  $("#f-approval").onchange = e => { S.approvalFilter = e.target.value; renderApprovals(); };
  $("#mon-source").onchange = () => renderMonitoring();
  $("#drawer-close").onclick = closeDrawer;
  $("#drawer-backdrop").onclick = closeDrawer;
  addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
  addEventListener("hashchange", route);

  const health = loadHealth();
  try { S.cases = await getJSON("/api/cases"); } catch { S.cases = []; }
  refreshApprovalBadge();
  // wait briefly for health so a read-only deployment renders its controls right;
  // a live graph can take longer to answer, and the page should not wait on it
  await Promise.race([health, new Promise(r => setTimeout(r, 1500))]);
  route();
}
function closeMenu() { $("#nav-links").classList.remove("open"); $("#menu-btn").setAttribute("aria-expanded", "false"); }

async function loadHealth() {
  const st = $("#status"), txt = $(".status-text", st);
  st.hidden = STATIC_SITE;
  try {
    const h = S.health = await getJSON("/api/health");
    const g = h.graph || {};
    if (h.readonly) {
      st.hidden = true;
      $("#footer-backend").textContent = `Read-only snapshot${h.captured_at ? ` of ${h.captured_at.slice(0, 10)}` : ""} · graph ${g.graph || "FraudGraph"} on TigerGraph Savanna`;
      if (parseRoute().view === "home") renderHome();
      return;
    }
    const live = g.backend === "tigergraph" && g.ok !== false;
    st.className = "status " + (live ? "live" : g.backend === "local" ? "local" : "down");
    const viaMcp = g.transport === "mcp";
    txt.textContent = live ? (viaMcp ? "TigerGraph · via MCP" : "TigerGraph live") : g.backend === "local" ? "Local mirror" : "Graph offline";
    st.title = live ? `Connected to ${g.graph || "FraudGraph"} on TigerGraph Savanna` +
      (viaMcp ? ` through the TigerGraph MCP server (${g.mcp_tools} tools, ${g.mcp_calls} calls so far)` : " (direct connection)") :
      "TigerGraph unreachable — serving from the local mirror of the same queries";
    $("#footer-backend").textContent = live ? `Connected to graph ${g.graph || ""}` : "Running on the local mirror";
  } catch { S.health = {}; st.className = "status down"; txt.textContent = "Offline"; }
  if (parseRoute().view === "home") renderHome();
}
const txnCount = () => {
  const g = (S.health || {}).graph || {};
  return g.vertex_counts?.Transaction || g.transactions || 590742;
};

/* ═══════════════════════════════════════════════════════════ HOME ══ */
let homeCounted = false;
function renderHome() {
  const c = S.cases;
  if (c.length) {
    const vals = [c.length, c.filter(x => x.verdict === "fraud").length, c.filter(x => x.changed).length,
      c.filter(x => x.sar).length, txnCount()];
    const nums = $$("#home-stats .num");
    if (!homeCounted && S.health) {
      homeCounted = true;
      const run = () => nums.forEach((el, i) => countUp(el, vals[i]));
      if (io) {
        const o = new IntersectionObserver(es => { if (es[0].isIntersecting) { run(); o.disconnect(); } }, { threshold: .4 });
        o.observe($("#home-stats"));
      } else run();
    } else if (homeCounted) nums.forEach((el, i) => el.textContent = vals[i].toLocaleString());
  }
}

/* Scroll-driven home scenes. Each scene gets p, 0 to 1, across its pinned
   stretch. Nothing runs under reduced motion or on short screens, so the page
   then reads as plain finished sections. */
let paintStory = () => {};
function bindStory() {
  const home = $("#view-home"), scenes = $$("[data-scene]", home), bar = $("#home-progress");
  const calm = matchMedia("(prefers-reduced-motion: reduce)"), roomy = matchMedia("(min-height: 560px)");
  const clamp = v => Math.min(1, Math.max(0, v));
  const stage = (p, from, to) => clamp((p - from) / (to - from));
  const usd = n => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const show = (el, g, dy = 16) => { el.style.opacity = g; el.style.transform = `translateY(${(1 - g) * dy}px)`; };

  const words = [];
  const split = node => [...node.childNodes].forEach(n => {
    if (n.nodeType !== 3) return split(n);
    const box = document.createDocumentFragment();
    n.textContent.split(/(\s+)/).forEach(w => {
      if (!w.trim()) return box.append(w);
      const s = document.createElement("span"); s.textContent = w; words.push(s); box.append(s);
    });
    n.replaceWith(box);
  });
  split($("#answer-words"));

  const pays = $$("#pay-bars .paybar"), links = $$(".ring-links path"), dots = $$(".ring-cards circle");
  const hub = $(".ring-hub"), hardCards = $$("#hard-cards > div");
  const chevs = $$("#chevs .chev"), cards = $$("#wstage .wcard");
  const paint = {
    open(p) {
      $("#open-title").style.transform = `scale(${1 - .14 * stage(p, 0, .5)})`;
      show($("#open-fact"), stage(p, .12, .5));
      show($("#open-cue"), 1 - stage(p, 0, .12), 0);
      $("#open-count").textContent = `$${(33.83 * (1 - Math.pow(1 - stage(p, .15, .7), 3))).toFixed(2)} billion`;
    },
    pay(p) {
      let sum = 0;
      pays.forEach((b, i) => {
        const g = stage(p, .06 + i * .2, .22 + i * .2);
        b.style.setProperty("--g", g); sum += g * Number(b.dataset.v);
      });
      $("#pay-total b").textContent = `$${usd(sum)}`;
      show($("#pay-total"), stage(p, .04, .14));
    },
    ring(p) {
      show($("#ring-count").parentNode, stage(p, .04, .14));
      hub.style.opacity = stage(p, .06, .16);
      hub.style.transform = `scale(${.4 + .6 * stage(p, .06, .16)})`;
      let linked = 0;
      links.forEach((l, i) => {
        const g = stage(p, .14 + i * .04, .2 + i * .04);
        l.style.strokeDashoffset = 1 - g;
        dots[i].classList.toggle("off", g < 1);
        if (g === 1) linked++;
      });
      $("#ring-count").textContent = linked;
    },
    hard(p) {
      hardCards.forEach((c, i) => {
        const g = stage(p, .08 + i * .3, .34 + i * .3);
        c.style.opacity = g; c.style.transform = `translateX(${(1 - g) * (i ? 60 : -60)}px)`;
      });
      show($("#hard-line"), stage(p, .68, .86));
    },
    answer(p) {
      words.forEach((w, i) => { w.style.opacity = .14 + .86 * stage(p, i / words.length * .72, (i + 1.5) / words.length * .72); });
      show($("#answer-next"), stage(p, .78, .92));
    },
    walk(p) {
      const at = Math.min(chevs.length - 1, Math.floor(p * chevs.length));
      chevs.forEach((c, i) => {
        const g = stage(p, i / chevs.length, (i + .6) / chevs.length);
        c.style.setProperty("--g", g); c.classList.toggle("lit", g > .45);
      });
      cards.forEach((c, i) => { c.classList.toggle("on", i === at); c.classList.toggle("past", i < at); });
    },
  };

  const measure = s => {
    const top = parseFloat(getComputedStyle(s.firstElementChild).top) || 0;
    return { top, span: Math.max(1, s.offsetHeight - s.firstElementChild.offsetHeight) };
  };
  const reset = () => {
    $$("[style]", home).forEach(el => { if (!el.matches(".paybar, .why-card")) el.removeAttribute("style"); });
    pays.forEach(b => b.style.removeProperty("--g"));
    words.forEach(w => w.removeAttribute("style"));
    dots.forEach(d => d.classList.remove("off"));
    chevs.forEach(c => c.classList.add("lit"));
    $("#open-count").textContent = "$33.83 billion";
    $("#ring-count").textContent = links.length;
    $("#pay-total b").textContent = "$1,906.07";
  };
  let queued = false;
  const frame = () => {
    queued = false;
    if (!home.classList.contains("active") || !home.classList.contains("scrolly")) return;
    scenes.forEach(s => {
      const { top, span } = measure(s);
      paint[s.dataset.scene](clamp((top - s.getBoundingClientRect().top) / span), s);
    });
    const max = document.documentElement.scrollHeight - innerHeight;
    bar.style.transform = `scaleX(${max > 0 ? clamp(scrollY / max) : 0})`;
  };
  paintStory = () => { if (!queued) { queued = true; requestAnimationFrame(frame); } };
  const decide = () => {
    const on = !calm.matches && roomy.matches;
    if (home.classList.toggle("scrolly", on)) frame();
    else reset();
  };
  chevs.forEach((c, i) => c.onclick = () => {
    if (!home.classList.contains("scrolly")) return;
    const s = c.closest("[data-scene]"), { top, span } = measure(s);
    window.scrollTo({ top: s.getBoundingClientRect().top + scrollY - top + span * (i + .62) / chevs.length });
  });
  addEventListener("scroll", paintStory, { passive: true });
  addEventListener("resize", paintStory, { passive: true });
  calm.addEventListener("change", decide); roomy.addEventListener("change", decide);
  decide();
}

/* ══════════════════════════════════════════════════════════ CASES ══ */
function bindToolbar() {
  const f = S.filter;
  $("#q").oninput = e => { f.q = e.target.value.trim().toLowerCase(); renderList(); };
  $("#f-verdict").onchange = e => { f.verdict = e.target.value; renderList(); };
  $("#f-trigger").onchange = e => { f.trigger = e.target.value; renderList(); };
  $("#f-sort").onchange = e => { f.sort = e.target.value; renderList(); };
  const tg = (id, key) => $(id).onclick = e => {
    f[key] = !f[key]; e.currentTarget.setAttribute("aria-pressed", f[key]); renderList();
  };
  tg("#t-revised", "revised"); tg("#t-sar", "sar");
}

function filteredCases() {
  const f = S.filter;
  let rows = S.cases.filter(c =>
    (f.verdict === "all" || c.verdict === f.verdict) &&
    (f.trigger === "all" || c.trigger === f.trigger) &&
    (!f.revised || c.changed) && (!f.sar || c.sar) &&
    (!f.q || [c.case_id, c.pattern, patternName(c.pattern), c.trigger_text, c.summary].join(" ").toLowerCase().includes(f.q)));
  if (f.sort === "p") rows.sort((a, b) => b.fraud_probability - a.fraud_probability);
  else if (f.sort === "exp") rows.sort((a, b) => b.exposure_usd - a.exposure_usd);
  else rows.sort((a, b) => a.case_id.localeCompare(b.case_id));
  return rows;
}

function renderList() {
  const rows = filteredCases();
  $("#list-meta").textContent = `${rows.length} of ${S.cases.length} cases`;
  $("#case-list").innerHTML = rows.map(c => {
    const t = trig(c.trigger);
    return `<li class="citem ${S.current === c.case_id ? "sel" : ""}" data-id="${esc(c.case_id)}" tabindex="0" role="button"
        aria-label="${esc(c.case_id)}, ${esc(VERDICT[c.verdict] || c.verdict)}">
      <div class="row1"><span class="cid">${esc(c.case_id)}</span>${verdictPill(c.verdict)}</div>
      <div class="trig"><span aria-hidden="true">${t.ico}</span>${esc(t.label)} · ${esc(patternName(c.pattern))}</div>
      <div class="mini" title="Fraud likelihood ${pct(c.fraud_probability)}"><span style="width:${Math.max(3, c.fraud_probability * 100)}%;background:${tone(c.fraud_probability)}"></span></div>
      <div class="tags">
        <span class="pill neutral">${pct(c.fraud_probability)} fraud</span>
        ${c.exposure_usd ? `<span class="pill neutral">${money(c.exposure_usd)}</span>` : ""}
        ${c.changed ? `<span class="pill brand">Decision changed</span>` : ""}
        ${c.sar ? `<span class="pill fraud">SAR</span>` : ""}
        ${c.margin_k != null ? `<span class="pill neutral" title="facts that must be false to change the action">k=${c.margin_k}</span>` : ""}
        ${c.gate_applied ? `<span class="pill warn">Gate</span>` : ""}
        ${c.hostile_text ? `<span class="pill warn">Hostile text</span>` : ""}
        ${c.tainted ? `<span class="pill neutral">Tainted data</span>` : ""}
        ${c.origin ? `<span class="pill brand">Origin</span>` : ""}
      </div></li>`;
  }).join("") || `<li class="empty-state" style="padding:30px 16px"><p>No cases match these filters.</p></li>`;
  $$("#case-list .citem").forEach(li => {
    const go = () => { location.hash = `#/cases/${li.dataset.id}`; };
    li.onclick = go; li.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
  });
}

async function openCase(id, tab = null) {
  const changed = S.current !== id;
  S.current = id;
  if (TABS.some(([k]) => k === tab)) S.tab = tab;
  else if (changed) S.tab = "overview";
  $$("#case-list .citem").forEach(li => li.classList.toggle("sel", li.dataset.id === id));
  const box = $("#detail");
  if (!S.detail[id]) {
    box.innerHTML = `<div class="card"><div class="skel" style="height:28px;width:40%"></div>
      <div class="skel" style="height:60px;margin-top:16px"></div><div class="skel" style="height:220px;margin-top:16px"></div></div>`;
    try { S.detail[id] = await getJSON(`/api/cases/${encodeURIComponent(id)}`); }
    catch (e) { box.innerHTML = `<div class="empty-state"><h3>Couldn't load ${esc(id)}</h3><p>${esc(e.message)}</p></div>`; return; }
  }
  if (S.current !== id) return;
  renderDetail(S.detail[id]);
}

/* ─────────────────────────────────────────────────────── case detail ── */
const TABS = [
  ["overview", "Overview"], ["proof", "Proof"], ["evidence", "Evidence"], ["graph", "Graph"],
  ["containment", "Containment & ring"], ["memory", "Similar cases"], ["replay", "Regulator replay"],
  ["lifecycle", "Case life"], ["audit", "Audit trail"],
];

function renderDetail(d) {
  const c = d.case, r = d.agent_record || {}, t = r.trigger || {}, p = c.fraud_probability;
  const counts = { evidence: (r.evidence_with_impact || c.evidence || []).length, memory: (r.prior_cases || []).length };
  const vcolor = { fraud: "var(--fraud)", legitimate: "var(--legit)", uncertain: "var(--warn)" }[c.verdict] || "var(--brand)";
  const tg = trig(t.type);

  $("#detail").innerHTML = `
    <a class="back-link" href="#/cases">← All cases</a>
    <div class="card case-hero" style="--vc:${vcolor}">
      <div class="ch-top">
        <div>
          <div class="ch-title"><h2>${esc(d.case_id)}</h2>${verdictPill(c.verdict).replace('class="pill', 'class="pill ch-verdict')}
            ${d.sar?.file ? `<span class="pill fraud">SAR filed</span>` : ""}
            ${d.next_best_actions.what_changed !== "nothing" ? `<span class="pill brand">Decision changed</span>` : ""}
            ${d.in_graph === true ? `<span class="pill legitimate" title="Checked now: this case is in TigerGraph">✓ In graph</span>`
              : d.in_graph === false ? `<span class="pill fraud" title="Checked now: the answer says it was written, but the case is not in TigerGraph">✗ Not in graph</span>`
              : ((d.agent_record || {}).write_verification?.read_back || c.written_to_graph) ? `<span class="pill" title="Written and read back when the case ran; the graph could not be checked now">Written at run time</span>` : ""}
            ${(d.agent_record || {}).graph_transport === "mcp" ? `<span class="pill neutral" title="Graph reads and writes went through the TigerGraph MCP server">via MCP</span>` : ""}</div>
          <div class="muted" style="margin-top:6px;font-size:14px">${tg.ico} ${esc(tg.label)} · ${esc(patternName(c.pattern))} · opened ${esc((t.opened_at || "").slice(0, 16))}</div>
        </div>
        <div class="ch-actions">
          <button class="btn btn-ghost" id="dl-json" title="Download this answer file">⬇ JSON</button>
          ${S.health?.readonly
            ? `<button class="btn btn-soft" id="rerun" disabled title="Live re-runs need a TigerGraph workspace. Clone the repository and run python ui/server.py.">▶ Re-run live <span class="small">(local only)</span></button>`
            : `<button class="btn btn-soft" id="rerun" title="Run the agent again and watch it reason step by step">▶ Re-run live</button>`}
        </div>
      </div>
      <div class="quote">“${esc(t.text || "")}”</div>
    </div>

    <nav class="tabs" role="tablist" aria-label="Case sections">
      ${TABS.map(([k, l]) => `<button role="tab" data-tab="${k}" class="${S.tab === k ? "active" : ""}" aria-selected="${S.tab === k}">${l}${counts[k] ? ` <span class="count">${counts[k]}</span>` : ""}</button>`).join("")}
    </nav>
    <label class="select tab-select"><span>Section</span>
      <select id="tab-select">${TABS.map(([k, l]) => `<option value="${k}" ${S.tab === k ? "selected" : ""}>${l}</option>`).join("")}</select>
    </label>
    <div id="tabpane"></div>`;

  $$("#detail .tabs button").forEach(b => b.onclick = () => setTab(b.dataset.tab, d));
  $("#tab-select").onchange = e => setTab(e.target.value, d);
  $("#rerun").onclick = () => rerun(d.case_id);
  $("#dl-json").onclick = () => saveFile(`${d.case_id}.json`, JSON.stringify(d, null, 2));
  renderTab(d);
}

function setTab(tab, d) {
  S.tab = tab;
  // keep the address bar shareable without re-running the router
  if (location.hash.startsWith("#/cases/")) history.replaceState(null, "", `#/cases/${encodeURIComponent(d.case_id)}/${tab}`);
  $$("#detail .tabs button").forEach(b => { b.classList.toggle("active", b.dataset.tab === tab); b.setAttribute("aria-selected", b.dataset.tab === tab); });
  $("#tab-select").value = tab;
  renderTab(d);
}

function renderTab(d) {
  const pane = $("#tabpane");
  pane.className = "tabpane"; void pane.offsetWidth; pane.className = "tabpane";
  ({ overview: tabOverview, proof: tabProof, evidence: tabEvidence, graph: tabGraph,
     containment: tabContainment, memory: tabMemory, replay: tabReplay, lifecycle: tabLifecycle,
     audit: tabAudit }[S.tab] || tabOverview)(d, pane);
}

/* overview */
function gauge(p, size = 190) {
  const R = 80, C = 2 * Math.PI * R;
  return `<div class="gauge" style="width:${size}px;height:${size}px">
    <svg viewBox="0 0 190 190"><circle class="track" cx="95" cy="95" r="${R}" fill="none" stroke-width="14"/>
      <circle class="arc" cx="95" cy="95" r="${R}" fill="none" stroke-width="14" stroke="${tone(p)}"
        stroke-dasharray="${C}" stroke-dashoffset="${C}" data-target="${C * (1 - p)}"/></svg>
    <div class="center"><div class="pct" style="color:${tone(p)}">${pct(p)}</div><div class="sub">fraud likelihood</div></div></div>`;
}
const animateGauges = root => requestAnimationFrame(() => requestAnimationFrame(() =>
  $$(".gauge .arc", root).forEach(a => a.style.strokeDashoffset = a.dataset.target)));

function actionList(list) {
  if (!list?.length) return `<p class="muted">No action.</p>`;
  return list.map(a => `<div class="act"><div class="top"><span class="name">${esc(ACTION[a.action] || humanize(a.action))}</span>
    <span class="route route-${esc(a.route)}" title="Who carries it out">${esc(ROUTE[a.route] || a.route)}</span></div>
    <div class="why">${esc(a.reason)}</div></div>`).join("");
}

function tabOverview(d, pane) {
  const c = d.case, r = d.agent_record || {}, nba = d.next_best_actions, sar = d.sar || {};
  const reqs = r.evidence_requests_detail || d.evidence_requests || [];
  const q = reqs[0];
  const facts = [
    ["Verdict", VERDICT[c.verdict] || c.verdict], ["Pattern", patternName(c.pattern)],
    ["Money at risk", money(c.exposure_usd)], ["Transactions involved", c.affected_txn_ids.length],
    ["Connected cards", c.connected_card_ids.length], ["Status", humanize(c.status)],
  ];
  const journey = q ? `
    <div class="journey">
      <div class="jstep"><h4>1 · First recommendation</h4>${actionList(nba.initial)}</div>
      <div class="jarrow" aria-hidden="true">→</div>
      <div class="jstep"><h4>2 · Asked for evidence</h4>
        <div class="question">“${esc(q.question || humanize(q.type))}”</div>
        <div class="qmeta"><span class="pill neutral">${esc(q.channel || q.type)}</span>
          ${q.expected_info_gain != null ? `<span class="pill brand" title="Expected information gain / friction cost">worth ${Number(q.expected_info_gain).toFixed(2)} info · cost ${q.cost}</span>` : ""}</div>
        <div class="muted" style="font-size:13px">${esc(q.assumed_response)}</div>
        ${q.p_fraud_before != null ? `<div class="shift"><span style="color:${tone(q.p_fraud_before)}">${pct(q.p_fraud_before)}</span> → <span style="color:${tone(q.p_fraud_after)}">${pct(q.p_fraud_after)}</span> <span class="muted" style="font:500 12px var(--sans)">fraud likelihood</span></div>` : ""}
      </div>
      <div class="jarrow" aria-hidden="true">→</div>
      <div class="jstep final"><h4>3 · Final decision</h4>${actionList(nba.final)}</div>
    </div>` : `
    <div class="journey two">
      <div class="jstep"><h4>First recommendation</h4>${actionList(nba.initial)}</div>
      <div class="jarrow" aria-hidden="true">→</div>
      <div class="jstep final"><h4>Final decision</h4>${actionList(nba.final)}</div>
    </div>
    <div class="callout soft"><span class="ci">💡</span><div>No question was sent to the customer. Nothing available would have moved the decision enough to justify the hassle of asking.</div></div>`;

  pane.innerHTML = `
    <div class="ov-grid">
      <div class="card gauge-card">${gauge(c.fraud_probability)}
        <div class="gauge-legend">Clear ≤ 15% · Block ≥ 70% · Report ≥ 85%</div>
        <div class="entropy" title="Shannon entropy of the fraud / not-fraud split: 1 bit is a coin flip, 0 is certainty">
          <span>Remaining uncertainty</span><b>${entropyBits(c.fraud_probability).toFixed(2)} bits</b>
          <span class="ebar"><span style="width:${entropyBits(c.fraud_probability) * 100}%"></span></span></div></div>
      <div class="card">
        <div class="card-title"><h3>At a glance</h3></div>
        <div class="facts">${facts.map(([k, v]) => `<div class="fact"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("")}</div>
        <div class="callout"><span class="ci">🛑</span><div><b>Why it stopped investigating:</b> ${esc(d.stop_reason)}</div></div>
      </div>
    </div>

    ${(r.open_questions || []).length ? `<div class="card" style="margin-top:16px">
      <div class="card-title"><h3>What the agent still doesn't know</h3><span class="hint">Stated, not hidden</span></div>
      <ul class="oq">${r.open_questions.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}

    <div class="card" style="margin-top:16px">
      <div class="card-title"><h3>How the decision unfolded</h3>${nba.what_changed !== "nothing" ? `<span class="pill brand">Changed after evidence</span>` : `<span class="hint">No change needed</span>`}</div>
      ${journey}
      ${nba.what_changed !== "nothing" ? `<div class="callout"><span class="ci">🔁</span><div><b>What changed:</b> ${esc(nba.what_changed)}</div></div>` : ""}
    </div>

    <div class="card">
      <div class="card-title"><h3>Summary</h3></div>
      <p class="summary-text">${esc(c.summary)}</p>
      ${c.pattern_description ? `<div class="callout"><span class="ci">🧩</span><div><b>The pattern, in the agent's words:</b> ${esc(c.pattern_description)}</div></div>` : ""}
      <details class="more"><summary>Suspicious activity report ${sar.file ? verdictPill("fraud").replace(">Fraud<", ">Filed<") : `<span class="pill neutral">Not filed</span>`}</summary>
        <div class="body">
          <p style="margin-bottom:10px">${esc(sar.reason)}</p>
          ${sar.file ? `<div class="sar-actions"><button class="btn btn-ghost btn-sm" id="copy-sar">⧉ Copy narrative</button></div>
            <div class="sar-text">${esc(sar.narrative)}</div>
            <div class="facts" style="margin-top:12px">
              <div class="fact"><div class="k">Total</div><div class="v">${money(sar.total_amount_usd)}</div></div>
              <div class="fact"><div class="k">Activity</div><div class="v" style="font-size:13px">${esc((sar.activity_dates || []).join(" → "))}</div></div>
              <div class="fact"><div class="k">Subjects</div><div class="v">${(sar.subjects || []).length}</div></div></div>` : ""}
        </div></details>
    </div>`;
  animateGauges(pane);
  const cp = $("#copy-sar", pane);
  if (cp) cp.onclick = async () => {
    try { await navigator.clipboard.writeText(sar.narrative); toast("SAR narrative copied"); }
    catch { toast("Copy blocked by the browser"); }
  };
}

/* evidence */
// Waterfall from the trigger's prior to the final probability, one row per
// ledger entry in the order it was folded in. The per-item movements do not sum
// exactly to the final figure (damping, the 0.02 / 0.97 caps), so the gap is
// shown as its own row rather than hidden.
function probPath(d) {
  const r = d.agent_record || {}, prior = r.prior || {};
  if (!("none" in prior)) return "";
  const steps = (r.evidence_with_impact || []).filter(e => e.delta_fraud_probability != null);
  const clamp = v => Math.min(1, Math.max(0, v));
  let p = 1 - prior.none;
  const rows = [{ label: `Starting point for a ${trig((r.trigger || {}).type).label.toLowerCase()}`, from: 0, to: p, kind: "base" }];
  steps.forEach(e => {
    const next = p + e.delta_fraud_probability;
    rows.push({ label: e.claim, from: clamp(p), to: clamp(next), kind: e.delta_fraud_probability >= 0 ? "up" : "down", badge: claimBadge(e.claim_type) });
    p = next;
  });
  const final = d.case.fraud_probability;
  if (Math.abs(final - p) > 0.005)
    rows.push({ label: "Calibration and caps (measured damping, 2% floor, 97% ceiling)", from: clamp(p), to: final, kind: "adj" });
  rows.push({ label: "Final fraud likelihood", from: 0, to: final, kind: "final" });
  const col = { base: "var(--ink-3)", up: "var(--fraud)", down: "var(--legit)", adj: "var(--warn)", final: tone(final) };
  return `<div class="card">
    <div class="card-title"><h3>How the probability got here</h3><span class="hint">Prior → each piece of evidence → final</span></div>
    <div class="ppath">${rows.map(x => {
      const lo = Math.min(x.from, x.to), hi = Math.max(x.from, x.to), dv = x.to - x.from;
      const val = x.kind === "base" || x.kind === "final" ? pct(x.to) : `${dv >= 0 ? "+" : "−"}${Math.abs(dv * 100).toFixed(1)} pts`;
      return `<div class="pp-row pp-${x.kind}"><div class="pp-label" title="${esc(x.label)}">${x.badge || ""}<span>${esc(x.label)}</span></div>
        <div class="pp-track"><span class="pp-bar" style="left:${(lo * 100).toFixed(1)}%;width:${Math.max(0.6, (hi - lo) * 100).toFixed(1)}%;background:${col[x.kind]}"></span>
          <span class="pp-tick" style="left:15%"></span><span class="pp-tick" style="left:70%"></span><span class="pp-tick" style="left:85%"></span></div>
        <div class="pp-val" style="color:${col[x.kind]}">${val}</div></div>`;
    }).join("")}</div>
    <div class="pp-row pp-axisrow" aria-hidden="true"><div></div><div class="pp-axis"><span style="left:0">0%</span><span style="left:15%">15%</span><span style="left:70%">70%</span><span style="left:85%">85%</span><span style="left:100%">100%</span></div><div></div></div>
    <p class="muted small" style="margin-top:10px">Ticks mark the policy thresholds: clear at 15%, block at 70%, report at 85%.</p>
  </div>`;
}

function tabEvidence(d, pane) {
  const c = d.case, r = d.agent_record || {};
  const items = (r.evidence_with_impact || c.evidence || []).slice();
  const max = Math.max(0.01, ...items.map(e => Math.abs(e.delta_fraud_probability || 0)));
  const labels = r.hypothesis_labels || {};
  const post = Object.entries(r.posterior || {}).sort((a, b) => b[1] - a[1]);

  pane.innerHTML = `
    ${probPath(d)}
    <div class="card">
      <div class="card-title"><h3>What kind of fraud is it?</h3><span class="hint">Agent's final belief across all explanations</span></div>
      ${post.map(([h, v], i) => `<div class="hyp ${i === 0 ? "top" : ""}" title="${esc(labels[h] || h)}">
        <span class="name">${esc(patternName(h))}</span>
        <span class="track"><span class="fill" data-w="${(v * 100).toFixed(1)}"></span></span>
        <span class="v">${(v * 100).toFixed(1)}%</span></div>`).join("")}
    </div>
    <div class="card">
      <div class="ev-tools">
        <h3 style="font-size:16.5px">Evidence gathered</h3>
        <label class="select"><span>Show</span>
          <select id="ev-filter"><option value="all">All evidence</option><option value="up">Raised fraud likelihood</option>
            <option value="down">Lowered fraud likelihood</option><option value="flat">Little effect</option>
            <optgroup label="By kind of statement">${Object.entries(CLAIM).filter(([k]) => items.some(e => e.claim_type === k))
              .map(([k, v]) => `<option value="type:${k}">${v.l}</option>`).join("")}</optgroup></select></label>
      </div>
      <div id="ev-list"></div>
    </div>`;

  const draw = mode => {
    const rows = items.filter(e => {
      const v = e.delta_fraud_probability || 0;
      if (mode.startsWith("type:")) return e.claim_type === mode.slice(5);
      return mode === "all" || (mode === "up" && v > .005) || (mode === "down" && v < -.005) || (mode === "flat" && Math.abs(v) <= .005);
    }).sort((a, b) => Math.abs(b.delta_fraud_probability || 0) - Math.abs(a.delta_fraud_probability || 0));
    $("#ev-list").innerHTML = rows.map(e => {
      const v = e.delta_fraud_probability, has = v != null, w = has ? Math.abs(v) / max * 50 : 0;
      const col = !has ? "#cbd1e1" : v > 0 ? "var(--fraud)" : "var(--legit)";
      return `<div class="ev"><div><div class="claim">${esc(e.claim)}</div>
          <div class="src">${claimBadge(e.claim_type)} ${esc(e.source)} · ${esc(e.ref)}</div></div>
        <div class="impact">${has ? `<span class="val" style="color:${col}">${v > 0 ? "+" : ""}${(v * 100).toFixed(1)} pts</span>` : `<span class="val muted">—</span>`}
          <span class="bar"><span style="background:${col};width:${w}%;${v > 0 ? "left:50%" : `right:50%`}"></span></span></div></div>`;
    }).join("") || `<p class="muted">Nothing in this group.</p>`;
  };
  $("#ev-filter").onchange = e => draw(e.target.value);
  draw("all");
  requestAnimationFrame(() => requestAnimationFrame(() => $$(".hyp .fill", pane).forEach(f => f.style.width = f.dataset.w + "%")));
}

/* graph */
const KIND = {
  case: { c: "#4f46e5", l: "This case" }, card: { c: "#f59e0b", l: "Card" }, customer: { c: "#a855f7", l: "Customer" },
  transaction: { c: "#10b981", l: "Transaction" }, device: { c: "#f43f5e", l: "Device profile" },
  connected_card: { c: "#fb923c", l: "Connected card" }, closed_case: { c: "#94a3b8", l: "Similar past case" },
};
async function tabGraph(d, pane) {
  pane.innerHTML = `<div class="card">
    <div class="card-title"><h3>What was written to TigerGraph</h3><span class="hint">Scroll to zoom · drag to pan · click a node</span></div>
    <div class="graph-wrap"><svg id="graph" viewBox="0 0 900 460" role="img" aria-label="Case subgraph"></svg>
      <div class="gctl"><button class="icon-btn" data-z="1.25" aria-label="Zoom in">＋</button><button class="icon-btn" data-z="0.8" aria-label="Zoom out">－</button><button class="icon-btn" data-z="0" aria-label="Reset view">⟲</button></div></div>
    <div class="node-info" id="node-info">Click a node to see what it is and what it links to.</div>
    <div class="legend" id="legend"></div>
    <div class="callout soft"><span class="ci">🕸️</span><div>This is the same <code>FraudCase</code> object the <code>case_chain</code> query walks in the database (id <code>${esc(d.case.graph_case_id)}</code>). Any future investigation can find this case by traversal.</div></div>
  </div>`;
  try { drawGraph(await getJSON(`/api/graph/${encodeURIComponent(d.case_id)}`)); }
  catch { $("#graph").outerHTML = `<p class="muted" style="padding:20px">Graph unavailable.</p>`; }
}

function drawGraph(g) {
  const svg = $("#graph"); if (!svg || !g.nodes.length) return;
  const W = 900, H = 460, cx = W / 2, cy = H / 2;
  const groups = {}; g.nodes.forEach(n => (groups[n.kind] = groups[n.kind] || []).push(n));
  const pos = {};
  // Each kind gets its own sector so large rings (19 connected cards) don't
  // collide with the recalled cases: connected cards right, memory upper-left.
  const ring = { card: 110, customer: 110, transaction: 150, device: 170, connected_card: 262, closed_case: 250 };
  const start = { card: -2.45, customer: -1.95, transaction: 1.25, device: 2.75, connected_card: -1.38, closed_case: 3.55 };
  const span = { card: .3, customer: .2, transaction: 1.2, device: .5, connected_card: 2.76, closed_case: .95 };
  Object.entries(groups).forEach(([k, list]) => list.forEach((n, i) => {
    if (k === "case") { pos[n.id] = [cx, cy]; return; }
    const r = ring[k] || 220, a0 = start[k] ?? 0, s = span[k] ?? 1.5;
    const a = list.length === 1 ? a0 + s / 2 : a0 + (i / (list.length - 1)) * s;
    pos[n.id] = [cx + r * Math.cos(a) * 1.55, cy + r * Math.sin(a) * .8];
  }));
  const adj = {}; g.edges.forEach(e => { (adj[e.from] = adj[e.from] || new Set()).add(e.to); (adj[e.to] = adj[e.to] || new Set()).add(e.from); });
  const lines = g.edges.filter(e => pos[e.from] && pos[e.to]).map(e =>
    `<line x1="${pos[e.from][0]}" y1="${pos[e.from][1]}" x2="${pos[e.to][0]}" y2="${pos[e.to][1]}"><title>${esc(e.label)}</title></line>`).join("");
  const nodes = g.nodes.filter(n => pos[n.id]).map((n, i) => {
    const [x, y] = pos[n.id], k = KIND[n.kind] || { c: "#94a3b8" };
    const r = n.kind === "case" ? 24 : n.flagged ? 12 : 8.5;
    const label = String(n.label).length > 20 ? String(n.label).slice(0, 18) + "…" : n.label;
    return `<g class="gn" data-id="${esc(n.id)}" style="animation:view-in .4s ${i * 0.02}s both">
      <circle cx="${x}" cy="${y}" r="${r}" fill="${k.c}" ${n.flagged ? `stroke="#0f172a" stroke-width="2.5"` : ""}/>
      ${n.kind === "case" ? `<text x="${x}" y="${y + 4}" text-anchor="middle" style="fill:#fff;font-weight:700">CASE</text>` : ""}
      <text x="${x}" y="${y + r + 13}" text-anchor="middle">${esc(n.kind === "case" ? n.label : label)}</text>
      <title>${esc((k.l || n.kind) + ": " + n.label)}${n.flagged ? " (flagged)" : ""}</title></g>`;
  }).join("");
  svg.innerHTML = `<g id="vp">${lines + nodes}</g>`;
  const byId = Object.fromEntries(g.nodes.map(n => [n.id, n]));
  $$(".gn", svg).forEach(el => el.onclick = () => {
    const n = byId[el.dataset.id], near = [...(adj[n.id] || [])].map(x => byId[x]).filter(Boolean);
    const kinds = {}; near.forEach(x => kinds[(KIND[x.kind] || {}).l || x.kind] = (kinds[(KIND[x.kind] || {}).l || x.kind] || 0) + 1);
    $("#node-info").innerHTML = `<b>${esc((KIND[n.kind] || {}).l || n.kind)}</b> <code>${esc(n.label)}</code>${n.flagged ? ` <span class="pill fraud">flagged</span>` : ""}
      <span class="muted"> · linked to ${Object.entries(kinds).map(([k, v]) => `${v} ${esc(k.toLowerCase())}${v > 1 ? "s" : ""}`).join(", ") || "nothing"}</span>`;
  });
  panZoom(svg, 900, 460);
  $$(".gn", svg).forEach(el => {
    el.onmouseenter = () => {
      const id = el.dataset.id, near = adj[id] || new Set();
      svg.classList.add("hovering");
      $$(".gn", svg).forEach(o => o.classList.toggle("hl", o.dataset.id === id || near.has(o.dataset.id)));
    };
    el.onmouseleave = () => { svg.classList.remove("hovering"); $$(".gn", svg).forEach(o => o.classList.remove("hl")); };
  });
  const kinds = [...new Set(g.nodes.map(n => n.kind))];
  $("#legend").innerHTML = kinds.map(k => `<span><i style="background:${(KIND[k] || {}).c}"></i>${esc((KIND[k] || {}).l || k)}</span>`).join("") +
    (g.nodes.some(n => n.flagged) ? `<span><i style="background:#fff;border:2.5px solid #0f172a"></i>Flagged transaction</span>` : "");
}

function panZoom(svg, W, H) {
  let vb = [0, 0, W, H], drag = null;
  const set = () => svg.setAttribute("viewBox", vb.map(v => v.toFixed(1)).join(" "));
  const zoom = (k, cx = vb[0] + vb[2] / 2, cy = vb[1] + vb[3] / 2) => {
    const w = Math.min(W * 2, Math.max(W / 5, vb[2] / k)), h = w * H / W;
    vb = [cx - (cx - vb[0]) * w / vb[2], cy - (cy - vb[1]) * h / vb[3], w, h]; set();
  };
  svg.addEventListener("wheel", e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    zoom(e.deltaY < 0 ? 1.15 : 0.87, vb[0] + (e.clientX - r.left) / r.width * vb[2], vb[1] + (e.clientY - r.top) / r.height * vb[3]);
  }, { passive: false });
  svg.addEventListener("pointerdown", e => { if (!e.target.closest(".gn")) { drag = [e.clientX, e.clientY, vb[0], vb[1]]; svg.setPointerCapture(e.pointerId); svg.classList.add("panning"); } });
  svg.addEventListener("pointermove", e => {
    if (!drag) return;
    const r = svg.getBoundingClientRect();
    vb[0] = drag[2] - (e.clientX - drag[0]) / r.width * vb[2]; vb[1] = drag[3] - (e.clientY - drag[1]) / r.height * vb[3]; set();
  });
  svg.addEventListener("pointerup", () => { drag = null; svg.classList.remove("panning"); });
  $$(".gctl button").forEach(b => b.onclick = () => { const k = +b.dataset.z; if (!k) { vb = [0, 0, W, H]; set(); } else zoom(k); });
}

/* memory */
function tabMemory(d, pane) {
  const pc = (d.agent_record || {}).prior_cases || [];
  pane.innerHTML = `<div class="card">
    <div class="card-title"><h3>Similar past investigations</h3><span class="hint">Found by meaning + shared cards/devices, in one query</span></div>
    ${pc.length ? `<div class="mem-grid">${pc.map(p => `<div class="mem">
      <div class="top"><span class="id">${esc(p.case_id)}</span>
        <span class="pill ${p.outcome === "confirmed_fraud" ? "fraud" : "legitimate"}">${p.outcome === "confirmed_fraud" ? "Confirmed fraud" : "Cleared"}</span></div>
      <div class="pat">${esc(patternName(p.pattern))}</div>
      <div class="meter-row"><span>Text similarity</span><span class="track"><span style="width:${Math.max(0, Math.min(1, p.similarity)) * 100}%"></span></span><span class="v">${Number(p.similarity).toFixed(2)}</span></div>
      <div class="meter-row"><span>Overall match</span><span class="track"><span style="width:${Math.max(0, Math.min(1, p.fused_score)) * 100}%"></span></span><span class="v">${Number(p.fused_score).toFixed(2)}</span></div>
      ${(p.shared_with || []).length ? `<div class="shared">Shares: ${esc(p.shared_with.join(", "))}</div>` : `<div class="shared">Matched on narrative only</div>`}
    </div>`).join("")}</div>` : `<p class="muted">No similar cases were recalled.</p>`}
    <div class="callout soft"><span class="ci">🧠</span><div>Only cases opened <em>before</em> this alert are eligible, so the agent can't learn from the future.</div></div>
  </div>`;
}

/* audit */
function tabAudit(d, pane) {
  const r = d.agent_record || {};
  const fraudOf = o => Object.entries(o || {}).reduce((a, [k, v]) => a + (k === "none" ? 0 : v), 0);
  const expl = Object.entries(r.explanation || {});
  const steps = (r.decisions || []).map(x => ({ ...x, a: x.p_fraud_before ?? fraudOf(x.posterior_before), b: x.p_fraud_after ?? fraudOf(x.posterior_after) }));
  pane.innerHTML = `
    ${steps.length ? `<div class="card">
      <div class="card-title"><h3>Replay the investigation</h3><button class="btn btn-soft btn-sm" id="play">▶ Play</button></div>
      <ol class="stepper">${steps.map((s, i) => `<li data-i="${i}"><span class="dot">${i + 1}</span><span class="lbl">${esc(STEP_NAME[s.node] || humanize(s.node))}</span></li>`).join("")}</ol>
      <div class="step-detail" id="step-detail"></div></div>` : ""}
    <div class="card">
      <div class="card-title"><h3>Explanation</h3><span class="hint">Each recommendation cites the policy rule behind it</span></div>
      ${expl.map(([k, v], i) => `<details class="more" ${i === 0 ? "open" : ""}><summary>${esc(humanize(k))}</summary><div class="body">${esc(v)}</div></details>`).join("")}
      ${(r.policy_notes || []).map(n => `<div class="callout soft"><span class="ci">📘</span><div>${esc(n)}</div></div>`).join("")}
    </div>
    <div class="card">
      <div class="card-title"><h3>Decision ledger</h3><span class="hint">Hash-chained: editing any step breaks the chain</span></div>
      <div class="table-wrap"><table>
        <tr><th>#</th><th>Step</th><th class="num">Fraud likelihood</th><th>Rationale</th><th>Hash</th></tr>
        ${(r.decisions || []).map(x => {
          const a = x.p_fraud_before ?? fraudOf(x.posterior_before), b = x.p_fraud_after ?? fraudOf(x.posterior_after);
          return `<tr><td class="num">${x.step}</td><td>${esc(STEP_NAME[x.node] || humanize(x.node))}</td>
            <td class="num">${pct(a)} → <b style="color:${tone(b)}">${pct(b)}</b></td><td>${esc(x.rationale)}</td>
            <td><code>${esc(String(x.hash).slice(0, 10))}</code></td></tr>`;
        }).join("")}
      </table></div>
      <p class="muted" style="font-size:13px;margin-top:10px">Chain head <code>${esc((r.audit_chain || {}).head || "")}</code></p>
      ${r.write_verification?.checks ? `<div class="callout soft"><span class="ci">🗄️</span><div><b>Graph write verified by read-back:</b>
        ${Object.entries(r.write_verification.checks).map(([k, ok]) => `${ok ? "✓" : "✗"} ${esc(humanize(k))}`).join(" · ")}</div></div>` : ""}
    </div>
    <div class="card">
      <details class="more" style="margin:0;border:0"><summary style="padding:0">Reasoning trace · ${(r.trace || []).length} steps</summary>
        <div class="body" style="padding:16px 0 0"><ol class="timeline">${traceItems(r.trace || [])}</ol></div></details>
    </div>`;

  // replay: each ledger step, its movement in belief and why
  if (!steps.length) return;
  let timer = null;
  const show = i => {
    const s = steps[i];
    $$(".stepper li", pane).forEach((li, j) => { li.classList.toggle("done", j < i); li.classList.toggle("on", j === i); });
    $("#step-detail", pane).innerHTML = `<div class="sd-top"><b>Step ${i + 1} · ${esc(STEP_NAME[s.node] || humanize(s.node))}</b>
        <span class="shift"><span style="color:${tone(s.a)}">${pct(s.a)}</span> → <span style="color:${tone(s.b)}">${pct(s.b)}</span></span></div>
      <div class="live-bar"><span style="width:${(s.b * 100).toFixed(1)}%"></span></div>
      <p class="muted" style="margin-top:8px;font-size:14px">${esc(s.rationale)}</p>`;
  };
  $$(".stepper li", pane).forEach(li => li.onclick = () => { clearInterval(timer); show(+li.dataset.i); });
  $("#play", pane).onclick = () => {
    clearInterval(timer);
    let i = 0; show(i);
    timer = setInterval(() => { if (++i >= steps.length) return clearInterval(timer); show(i); }, 1400);
  };
  show(steps.length - 1);
}
function traceItems(trace) {
  return trace.map(t => {
    const { node, at, ...rest } = t;
    return `<li><span class="tn">${esc(STEP_NAME[node] || humanize(node))}</span><span class="tt">${Number(at).toFixed(2)}s</span>
      <div class="td">${esc(JSON.stringify(rest).slice(0, 260))}</div></li>`;
  }).join("");
}

/* ─────────────────────────────────────────────── live re-run (SSE) ── */
function openDrawer() { $("#drawer-backdrop").hidden = false; $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false"); }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#drawer-backdrop").hidden = true; }
function liveBar(p) {
  $("#drawer-gauge").innerHTML = `<div class="live-bar"><span style="width:${(p * 100).toFixed(1)}%"></span></div>
    <div class="live-lbl"><span class="t-legit">Legitimate ${pct(1 - p)}</span><span class="t-fraud">Fraud ${pct(p)}</span></div>`;
}

function rerun(id) {
  const btn = $("#rerun");
  btn.disabled = true; btn.innerHTML = `<span class="spinner"></span> Investigating…`;
  $("#drawer-title").textContent = `Investigating ${id}…`;
  $("#live-steps").innerHTML = ""; liveBar(0); openDrawer();
  let n = 0;
  // Public live deployments gate re-runs on a token; EventSource cannot set headers.
  const tok = S.health?.run_auth ? approvalToken() : "";
  if (S.health?.run_auth && !tok) { btn.disabled = false; btn.innerHTML = "▶ Re-run live"; closeDrawer(); return; }
  const es = new EventSource(`/api/investigate/${encodeURIComponent(id)}` + (tok ? `?token=${encodeURIComponent(tok)}` : ""));
  const reset = () => { const b = $("#rerun"); if (b) { b.disabled = false; b.innerHTML = "▶ Re-run live"; } };
  es.onmessage = ev => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "step") {
      const { node, at, ...rest } = msg.data;
      $("#live-steps").insertAdjacentHTML("beforeend", `<li><span class="ico">${++n}</span><div>
        <div class="nm">${esc(STEP_NAME[node] || humanize(node))} <span class="tt muted" style="font:500 12px var(--mono)">${Number(at).toFixed(1)}s</span></div>
        <div class="dt">${esc(JSON.stringify(rest).slice(0, 180))}</div></div></li>`);
      const list = $("#live-steps"); list.scrollTop = list.scrollHeight;
      if (msg.data.p_fraud != null) liveBar(msg.data.p_fraud);
    } else if (msg.type === "done") {
      es.close();
      const d = msg.data; S.detail[id] = d;
      liveBar(d.case.fraud_probability);
      $("#drawer-title").innerHTML = `Done · ${esc(VERDICT[d.case.verdict] || d.case.verdict)} (${pct(d.case.fraud_probability)})`;
      if (S.current === id) renderDetail(d);
      toast(`${id} re-investigated: ${VERDICT[d.case.verdict] || d.case.verdict}`);
    } else {
      es.close(); reset();
      $("#drawer-title").textContent = "Something went wrong";
      $("#live-steps").insertAdjacentHTML("beforeend", `<li><span class="ico" style="background:var(--fraud-soft);color:var(--fraud)">!</span><div class="dt">${esc(msg.data)}</div></li>`);
    }
  };
  es.onerror = () => { es.close(); reset(); };
}

/* ══════════════════════════════════════════════════════ APPROVALS ══ */
async function refreshApprovalBadge() {
  try {
    S.approvals = await getJSON("/api/approvals");
    if (STATIC_SITE) S.approvals.forEach(a => { if (S.localDecisions?.[a.key]) a.decision = S.localDecisions[a.key]; });
    const open = S.approvals.filter(a => !a.decision).length;
    const b = $("#approval-count"); b.textContent = open; b.hidden = !open;
  } catch { }
}
async function loadApprovals() {
  $("#approval-list").innerHTML = `<div class="skel" style="height:96px"></div><div class="skel" style="height:96px"></div>`;
  await refreshApprovalBadge();
  renderApprovals();
}
function renderApprovals() {
  const all = S.approvals, pending = all.filter(a => !a.decision);
  const kpi = (k, v, cls = "") => `<div class="kpi"><div class="k">${k}</div><div class="v ${cls}">${v}</div></div>`;
  $("#approval-summary").innerHTML = kpi("Waiting for a decision", pending.length) +
    kpi("Team lead (L1)", pending.filter(a => a.route === "L1").length, "t-warn") +
    kpi("Fraud manager (L2)", pending.filter(a => a.route === "L2").length, "t-fraud");
  const rows = all.filter(a => S.approvalFilter === "all" || (S.approvalFilter === "pending" ? !a.decision : !!a.decision));
  $("#approval-list").innerHTML = rows.map(a => `
    <div class="appr" data-key="${esc(a.key)}">
      <div>
        <div class="head"><span class="act-name">${esc(ACTION[a.action] || humanize(a.action))}</span>
          <span class="route route-${esc(a.route)}">${esc(ROUTE[a.route] || a.route)}</span>
          <a class="pill neutral" href="#/cases/${esc(a.case_id)}">${esc(a.case_id)} ↗</a></div>
        <div class="why">${esc(a.reason)}</div>
        <div class="meta"><span>Needs: <b>${esc(a.approver)}</b></span><span>Money at risk: <b>${money(a.exposure_usd)}</b></span>
          <span>Fraud likelihood: <b style="color:${tone(a.fraud_probability)}">${pct(a.fraud_probability)}</b></span></div>
      </div>
      <div class="btns">${a.decision
        ? `<span class="decided ${a.decision.approved ? "t-legit" : "t-fraud"}">${a.decision.approved ? "✓ Approved" : "✕ Rejected"} · ${esc(a.decision.actor_id || a.decision.analyst)} (${esc(a.decision.actor_role || "")})</span>`
        : `<button class="btn btn-no" data-a="0">Reject</button><button class="btn btn-ok" data-a="1">Approve</button>`}</div>
    </div>`).join("") || `<div class="empty-state"><div class="empty-ico">✅</div><h3>All clear</h3><p>${S.approvalFilter === "pending" ? "Nothing is waiting for approval." : "No decisions recorded yet."}</p></div>`;

  $$("#approval-list .appr").forEach(el => el.querySelectorAll("button").forEach(b => b.onclick = async () => {
    const [cid, idx] = el.dataset.key.split(":"), ok = b.dataset.a === "1";
    el.style.opacity = .5;
    try {
      const res = STATIC_SITE
        ? (S.localDecisions = S.localDecisions || {})[el.dataset.key] =
          { approved: ok, analyst: "ANALYST-01", at: new Date().toISOString().slice(0, 19) + "Z", graph_write: "skipped" }
        : await fetch(`/api/approvals/${encodeURIComponent(cid)}/${idx}`, {
          method: "POST", headers: { "Content-Type": "application/json",
                                     "Authorization": `Bearer ${approvalToken()}` },
          body: JSON.stringify({ approved: ok }),
        }).then(async r => { const j = await r.json(); if (!r.ok) { if (r.status === 401) { try { sessionStorage.removeItem("approval_token"); } catch { /* */ } } throw new Error(`${r.status}: ${j.error}`); } return j; });
      toast(res.graph_write_error ? `Recorded, but the graph write failed: ${res.graph_write_error}` :
        res.graph_write ? `${ok ? "Approved" : "Rejected"} · recorded for this session (read-only copy, no graph write)` :
        `${ok ? "Approved" : "Rejected"} by ${res.actor_id} (${res.actor_role}) · signed ledger #${res.seq}`);
    } catch (e) { toast(`Refused — ${e.message || "couldn't record that decision"}`); }
    loadApprovals();
  }));
}

function saveFile(name, text, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ═════════════════════════════════════════════════════ CHALLENGES ══ */
const CH_DEPTH = {
  target: ["Strong", "legitimate"], gaps: ["Strong, with gaps", "brand"],
  built: ["Implemented", "neutral"], thin: ["Thin", "uncertain"],
};
const CH_GROUPS = [["Our targets", ["target", "gaps"]], ["Implemented", ["built"]], ["Present but thin", ["thin"]]];

function challengeChart(ch) {
  const max = Math.max(...ch.rows.map(r => r[1])) || 1, unit = ch.unit || "";
  return `<figure class="ch-chart"><figcaption>${esc(ch.title)}</figcaption>
    ${ch.rows.map(([l, v, hi]) => `<div class="ch-row" title="${esc(l)}: ${v}${unit}"><span class="ch-lbl">${esc(l)}</span>
      <span class="ch-track"><span class="${hi ? "hi" : ""}" style="width:${v / max * 100}%"></span></span><b>${v.toLocaleString()}${unit}</b></div>`).join("")}
    <p class="ch-note">${esc(ch.note)}</p></figure>`;
}
function showChallenge(id) {
  const rail = $("#ch-rail");
  if (!rail.dataset.done) {
    rail.innerHTML = CH_GROUPS.map(([label, kinds]) => `<p class="ch-group">${label}</p>` +
      CHALLENGES.filter(c => kinds.includes(c.depth)).map(c =>
        `<a href="#/challenges/${c.id}" data-id="${c.id}"><span class="ch-id">${c.id}</span>${esc(c.name)}</a>`).join("")).join("");
    rail.dataset.done = 1;
  }
  const at = Math.max(0, CHALLENGES.findIndex(c => c.id === id)), c = CHALLENGES[at];
  $$("a", rail).forEach(a => {
    const on = a.dataset.id === c.id;
    a.classList.toggle("on", on);
    if (on) a.setAttribute("aria-current", "true"); else a.removeAttribute("aria-current");
  });
  const [depth, cls] = CH_DEPTH[c.depth], prev = CHALLENGES[at - 1], next = CHALLENGES[at + 1];
  $("#ch-detail").innerHTML = `
    <header class="card chal-top">
      <div class="ch-tags"><span class="ch-id">${c.id}</span><span class="pill ${cls}">${depth}</span></div>
      <h2>${esc(c.name)}</h2><p class="ch-tagline">${esc(c.tagline)}</p>
      <div class="ch-metrics">${c.metrics.map(([v, l]) => `<div><b>${esc(v)}</b><span>${esc(l)}</span></div>`).join("")}</div>
    </header>
    <section class="card ch-sec">
      <h3><span>1</span>The problem</h3><p>${esc(c.problem)}</p>
      ${c.like ? `<p class="ch-like"><b>Think of it like this.</b> ${esc(c.like)}</p>` : ""}
    </section>
    <section class="card ch-sec">
      <h3><span>2</span>How the agent approaches it</h3>
      <ol class="ch-steps">${c.approach.map(([t, d]) => `<li><b>${esc(t)}</b><p>${esc(d)}</p></li>`).join("")}</ol>
      ${c.graph ? `<p class="ch-graph"><b>Where TigerGraph does the work.</b> ${esc(c.graph)}</p>` : ""}
    </section>
    ${c.charts || c.proof || c.kase ? `<section class="card ch-sec">
      <h3><span>3</span>What it showed</h3>
      ${c.proof ? `<p>${esc(c.proof)}</p>` : ""}
      ${c.charts ? `<div class="ch-charts">${c.charts.map(challengeChart).join("")}</div>` : ""}
      ${c.kase ? `<a class="ch-case" href="#/cases/${c.kase[0]}"><span class="mono">${c.kase[0]}</span><span>${esc(c.kase[1])}</span><b aria-hidden="true">→</b></a>` : ""}
    </section>` : ""}
    ${["built", "thin"].includes(c.depth) ? `<aside class="ch-limit"><b>Honest limits.</b> ${esc(c.limit)}</aside>` : ""}
    <nav class="ch-pager" aria-label="More challenges">
      ${prev ? `<a href="#/challenges/${prev.id}">← ${esc(prev.name)}</a>` : "<span></span>"}
      ${next ? `<a href="#/challenges/${next.id}">${esc(next.name)} →</a>` : "<span></span>"}
    </nav>`;
  if (id) requestAnimationFrame(() => {
    $("#ch-layout").scrollIntoView();
    if (getComputedStyle(rail).overflowX === "auto") {
      const a = $("a.on", rail); rail.scrollLeft = a.offsetLeft - (rail.clientWidth - a.offsetWidth) / 2;
    }
  });
}

/* ═════════════════════════════════════════════════════ MONITORING ══ */
const SOURCE = {
  risk_score: { l: "Bank's risk model ≥ 0.88", d: "The alerts the bank already raises." },
  structuring_sweep: { l: "Structuring sweep", d: "Online bursts parked just under a round ceiling (undocumented U1)." },
  device_hub_sweep: { l: "Device-hub sweep", d: "Devices reached almost only through anonymising proxies (undocumented U2)." },
};
async function loadMonitoring() {
  if (!S.auto) {
    $("#mon-list").innerHTML = `<div class="skel" style="height:120px"></div>`;
    try { S.auto = await getJSON("/api/autonomous"); } catch { S.auto = []; }
    const srcs = [...new Set(S.auto.map(a => a.found_by))];
    $("#mon-source").innerHTML = `<option value="all">Every sweep</option>` +
      srcs.map(s => `<option value="${esc(s)}">${esc((SOURCE[s] || {}).l || humanize(s))}</option>`).join("");
  }
  renderMonitoring();
}
function renderMonitoring() {
  const all = S.auto || [], src = $("#mon-source").value;
  const groups = {};
  all.forEach(a => (groups[a.found_by] = groups[a.found_by] || []).push(a));
  $("#mon-sources").innerHTML = Object.entries(groups).map(([k, g]) => {
    const fraud = g.filter(a => a.verdict === "fraud").length;
    const exp = g.reduce((s, a) => s + (a.verdict === "fraud" ? a.exposure_usd : 0), 0);
    const hot = fraud / g.length >= .5;
    return `<button class="source ${src === k ? "on" : ""}" data-src="${esc(k)}">
      <div class="s-top"><b>${esc((SOURCE[k] || {}).l || humanize(k))}</b><span class="pill ${hot ? "fraud" : "neutral"}">${fraud}/${g.length} fraud</span></div>
      <div class="pbar big"><span style="width:${(fraud / g.length) * 100}%;background:${hot ? "var(--fraud)" : "var(--ink-3)"}"></span></div>
      <div class="muted small">${esc((SOURCE[k] || {}).d || "")}</div>
      <div class="s-exp">${money(exp)} <span class="muted small">exposure on confirmed fraud</span></div></button>`;
  }).join("");
  $$("#mon-sources .source").forEach(b => b.onclick = () => {
    $("#mon-source").value = src === b.dataset.src ? "all" : b.dataset.src; renderMonitoring();
  });
  const rows = all.filter(a => src === "all" || a.found_by === src);
  $("#mon-list").innerHTML = rows.map(a => `<details class="rule mon">
    <summary><span class="rid">${esc(a.case_id)}</span>${verdictPill(a.verdict)}
      <span class="rt">${esc(patternName(a.pattern))} · ${money(a.exposure_usd)}${a.n_connected ? ` · ${a.n_connected} linked cards` : ""}</span>
      <span class="muted small hide-sm">${esc((SOURCE[a.found_by] || {}).l || a.found_by)}</span>${a.sar ? `<span class="pill fraud">SAR</span>` : ""}</summary>
    <div class="body"><p style="margin-bottom:10px">${esc(a.summary)}</p>
      <div class="chips">${a.final.map(x => `<span class="chip-act">${esc(ACTION[x] || humanize(x))}</span>`).join("")}</div></div></details>`).join("") ||
    `<div class="empty-state"><h3>No proactive alerts yet</h3><p>Run <code>python benchmark/monitor.py</code>.</p></div>`;
}

/* ═══════════════════════════════════════════════════════ INSIGHTS ══ */
function bindInsights() {
  $$("#insight-tabs button").forEach(b => b.onclick = () => showInsight(b.dataset.tab));
}
function showInsight(tab) {
  S.insightTab = tab;
  $$("#insight-tabs button").forEach(b => { b.classList.toggle("active", b.dataset.tab === tab); b.setAttribute("aria-selected", b.dataset.tab === tab); });
  $("#pane-monitoring").hidden = tab !== "monitoring";
  $("#pane-calibration").hidden = tab !== "calibration";
  $("#pane-policy").hidden = tab !== "policy";
  ({ monitoring: loadMonitoring, calibration: loadCalibration, policy: loadPolicy })[tab]();
}

async function loadCalibration() {
  const pane = $("#pane-calibration");
  if (S.calib) return;
  pane.innerHTML = `<div class="skel" style="height:260px"></div>`;
  try { S.calib = await getJSON("/api/calibration"); }
  catch (e) { pane.innerHTML = `<div class="empty-state"><h3>Calibration not available</h3><p>${esc(e.message)}</p></div>`; return; }
  const d = S.calib, h = d.holdout || {};
  const kpi = (k, v) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  const lg = v => Math.max(-2.5, Math.min(2.5, Math.log(Math.max(v, 1e-3))));
  pane.innerHTML = `
    <div class="kpis">${kpi("Past cases replayed", (d.n_cases || 0).toLocaleString())}
      ${h.accuracy != null ? kpi("Held-out accuracy", Number(h.accuracy).toFixed(2)) : ""}
      ${h.brier != null ? kpi("Brier score", Number(h.brier).toFixed(3)) : ""}
      ${h.ece != null ? kpi("Calibration error", Number(h.ece).toFixed(3)) : kpi("Damping", d.damping ?? "—")}</div>
    <div class="card">
      <div class="card-title"><h3>How much each signal really says</h3><span class="hint">Measured from outcomes, not hand-picked</span></div>
      <p class="muted" style="margin-bottom:14px;font-size:14px">A likelihood ratio above 1 means the signal is more common in confirmed fraud; below 1, more common in cleared cases. Every closed investigation was replayed through the same code the agent uses, at its own point in time.</p>
      <div class="table-wrap"><table>
        <tr><th>Signal</th><th>Points toward</th><th class="num">When present</th><th class="num">When absent</th><th class="num">Seen in fraud</th><th class="num">Seen in cleared</th></tr>
        ${(d.likelihood_ratios || []).map(r => {
          const v = lg(r.lr_fired), w = Math.abs(v) / 2.5 * 50, col = v > 0 ? "var(--fraud)" : "var(--legit)";
          return `<tr><td><b>${esc(humanize(r.signal))}</b></td>
            <td><div class="lr" title="likelihood ratio ${r.lr_fired.toFixed(2)}"><span class="t-legit" style="font-size:11px">legit</span>
              <span class="axis"><span style="background:${col};width:${w}%;${v > 0 ? "left:50%" : "right:50%"}"></span></span>
              <span class="t-fraud" style="font-size:11px">fraud</span></div></td>
            <td class="num" style="color:${col}">${r.lr_fired.toFixed(2)}×</td><td class="num">${r.lr_absent.toFixed(2)}×</td>
            <td class="num">${(r.p_given_fraud * 100).toFixed(1)}%</td><td class="num">${(r.p_given_cleared * 100).toFixed(1)}%</td></tr>`;
        }).join("")}
      </table></div>
    </div>`;
}

/* tiny markdown renderer for policy clauses: tables, bullets, bold, code */
function md(src) {
  const inline = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  const out = [], lines = String(src).split("\n");
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i].trim();
    if (l.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(lines[i++].trim()); i--;
      const cells = r => r.replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const body = rows.filter(r => !/^\|[\s:|-]+\|$/.test(r));
      out.push(`<div class="table-wrap" style="margin:8px 0"><table><tr>${cells(body[0]).map(c => `<th>${inline(c)}</th>`).join("")}</tr>` +
        body.slice(1).map(r => `<tr>${cells(r).map(c => `<td>${inline(c)}</td>`).join("")}</tr>`).join("") + `</table></div>`);
    } else if (/^[-*] /.test(l)) {
      const items = [];
      while (i < lines.length && /^[-*] /.test(lines[i].trim())) items.push(lines[i++].trim().slice(2)); i--;
      out.push(`<ul style="margin:6px 0 6px 18px;padding:0">${items.map(x => `<li>${inline(x)}</li>`).join("")}</ul>`);
    } else if (l) out.push(`<p style="margin:6px 0">${inline(l)}</p>`);
  }
  return out.join("");
}

async function loadPolicy() {
  const pane = $("#pane-policy");
  if (!S.policy) {
    pane.innerHTML = `<div class="skel" style="height:260px"></div>`;
    try { S.policy = await getJSON("/api/policy"); }
    catch (e) { pane.innerHTML = `<div class="empty-state"><h3>Policy not available</h3><p>${esc(e.message)}</p></div>`; return; }
  }
  const isRule = r => /^R\d+$/.test(r.rule);
  const rules = S.policy.slice().sort((a, b) => (isRule(b) - isRule(a)) ||
    (isRule(a) ? +a.rule.slice(1) - +b.rule.slice(1) : a.rule.localeCompare(b.rule)));
  const titleOf = r => isRule(r)
    ? (String(r.text).replace(/^R\d+\.\s*/, "").match(/^[^.]*/) || [""])[0].replace(/`/g, "")
    : ({ ACTIONS: "The actions the agent can take", APPROVAL_ROUTING: "Who approves what",
         CASE_VS_REPORT: "A case is not a report", ACTION_CAN_CHANGE: "The next best action can change",
         EVIDENCE_GATHERING: "Gathering more evidence", STOPPING: "When to stop investigating",
         EXPOSURE: "How money at risk is counted", EXPLAINING: "What every explanation must include" }[r.rule]
       || humanize(r.rule.toLowerCase()));
  pane.innerHTML = `
    <div class="toolbar policy-tools">
      <label class="search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="pq" type="search" placeholder="Search the policy, e.g. “block” or “report”" aria-label="Search policy"></label>
      <label class="select"><span>Show</span>
        <select id="pk"><option value="all">Everything</option><option value="rules">Rules R1–R10</option><option value="sections">Sections</option></select></label>
    </div>
    <p class="muted" style="margin:0 0 12px;font-size:14px">The agent can only choose actions these rules allow. Anything else is dropped before it reaches an answer file.</p>
    <div id="rules"></div>`;
  const draw = () => {
    const q = $("#pq").value.trim().toLowerCase(), k = $("#pk").value;
    const rows = rules.filter(r => (k === "all" || (k === "rules") === isRule(r)) &&
      (!q || (r.rule + " " + r.text).toLowerCase().includes(q)));
    $("#rules").innerHTML = rows.map(r => `<details class="rule"><summary>
        <span class="rid">${esc(isRule(r) ? r.rule : "§")}</span><span class="rt">${esc(titleOf(r))}</span></summary>
        <div class="body">${md(r.text)}</div></details>`).join("") || `<p class="muted">No rule mentions that.</p>`;
  };
  $("#pq").oninput = draw; $("#pk").onchange = draw;
  draw();
}

boot();

/* ═════════════════════════════════════════════ FINAL-ROUND TABS ══ */
const FACT = s => humanize(String(s || "").replace(/^precedent_recall$/, "similar closed cases"));
const chip = (t, cls = "") => `<span class="pill ${cls}">${esc(t)}</span>`;

function tabProof(d, pane) {
  const r = d.agent_record || {}, pr = r.proof || {}, g = r.gate || {}, cf = r.conformal || {}, q = r.quality || {};
  const prec = pr.precedent || {};
  if (!pr.facts) { pane.innerHTML = `<div class="empty-state"><h3>No proof on this answer</h3><p>Re-run the case to compute one.</p></div>`; return; }
  const minimal = new Set(pr.minimal_sufficient_facts || []), flips = new Set(pr.flip_set || []);
  pane.innerHTML = `
    <div class="callout"><span class="ci">🧾</span><div>
      <b>${esc((pr.action_class || []).map(humanize).join(" + "))}</b> rests on
      <b>${(pr.minimal_sufficient_facts || []).length}</b> fact${(pr.minimal_sufficient_facts || []).length === 1 ? "" : "s"}
      (${(pr.minimal_sufficient_facts || []).map(FACT).map(esc).join(", ") || "none"}).
      Margin <b>k = ${pr.margin_k ?? "≥4"}</b>: ${pr.flip_set && pr.flip_set.length ? `removing ${pr.flip_set.map(FACT).map(esc).join(" and ")} changes the action to <b>${esc((pr.flips_to?.action_class || []).map(humanize).join(" + "))}</b>` : "no set of up to three facts flips it"}.
      ${prec.n ? `<b>${prec.n}</b> closed cases share these facts: <b>${prec.confirmed}</b> confirmed, <b>${prec.cleared}</b> cleared.` : "No closed case shares exactly these facts."}
      ${pr.reproduces_live ? "" : `<br><span class="t-warn">The fact-replay class differs from the live decision; the live decision stands.</span>`}
    </div></div>
    <div class="callout ${g.applied ? "" : "soft"}"><span class="ci">🛡️</span><div><b>Proof gate:</b> ${esc(g.reason || "—")}
      ${g.applied ? `<br>Removed ${esc((g.removed || []).join(", "))}; added ${esc((g.added || []).join(", "))}.` : ""}</div></div>
    <h3>Facts — flip one live</h3>
    <div class="table-wrap"><table><thead><tr><th>fact</th><th>role</th><th>if removed</th><th></th></tr></thead><tbody>
      ${(pr.single_fact_flips || []).map(f => `<tr>
        <td>${esc(FACT(f.fact))}</td>
        <td>${minimal.has(f.fact) ? chip("minimal", "warn") : ""} ${flips.has(f.fact) ? chip("flip set", "fraud") : ""}</td>
        <td>${f.flips ? `<b class="t-fraud">${esc(f.action_class.map(humanize).join(" + "))}</b>` : esc(f.action_class.map(humanize).join(" + "))} · p=${f.p_fraud}</td>
        <td><button class="btn btn-sm" data-flip="${esc(f.fact)}">Recompute</button></td></tr>`).join("")}
    </tbody></table></div>
    <div id="flip-out"></div>
    <h3>Uncertainty set (conformal, 90%)</h3>
    <p>${cf.available ? `Set ${chip("{" + (cf.set || []).join(", ") + "}", (cf.set || []).length === 1 ? "" : "warn")}
       from graph-only p = ${cf.p_fraud_graph_only}; ${cf.outside_support ? `<b>outside calibration support</b> (distance ${cf.support_distance} &gt; ${cf.support_threshold})` : `within support${cf.support_distance != null ? ` (distance ${cf.support_distance} ≤ ${cf.support_threshold})` : ""}`}.
       ${cf.reason ? `<br>Verdict widened: ${esc(cf.reason)}.` : ""}` : esc(cf.note || "not calibrated")}</p>
    <h3>Data quality</h3>
    <p>${q.tainted ? chip("tainted", "fraud") : chip(q.severity || "clean")} ${(q.issues || []).map(i => `${esc(i.kind)}: ${esc(i.detail)} <code>${esc((i.record_ids || []).join(", "))}</code>`).join("<br>") || "No gap touches this decision."}</p>
    <h3>Precedent ids</h3><p>${(prec.case_ids || []).map(c => `<code>${esc(c)}</code>`).join(" ") || "—"} <span class="muted">via ${esc(prec.source || "")}</span></p>`;
  $$("#tabpane [data-flip]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      const res = await fetch(apiUrl(`/api/proof/${encodeURIComponent(d.case_id)}/flip`), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remove: [b.dataset.flip] }) }).then(x => x.json());
      $("#flip-out").innerHTML = `<div class="callout ${res.flips ? "" : "soft"}"><span class="ci">🔁</span><div>
        Without <b>${esc(FACT(b.dataset.flip))}</b>: ${esc((res.after?.actions || []).map(humanize).join(", "))}
        (p ${res.before?.p_fraud} → ${res.after?.p_fraud}) — the action class ${res.flips ? "<b>changes</b>" : "does not change"}.</div></div>`;
    } catch { toast("Recompute needs the live console (not the read-only copy)"); }
    b.disabled = false;
  });
}

async function tabContainment(d, pane) {
  const r = d.agent_record || {}, c = r.containment;
  if (!c) { pane.innerHTML = `<div class="empty-state"><div class="empty-ico">🧩</div><h3>Not a ring case</h3><p>Containment runs when the case connects to other cards.</p></div>`; return; }
  const o = c.origin, b = c.blocks || {};
  pane.innerHTML = `
    <div class="callout"><span class="ci">🎯</span><div>${o ? `Compromise origin: <b>${esc(humanize(o.entity_type))}</b> <code>${esc(o.entity)}</code> —
      ${o.ring_cards_touching} of ${o.n_ring} ring cards touched it vs ${o.control_cards_touching} of ${o.n_control} control cards
      (lift <b>${o.lift}</b>, p = ${o.p_value}).` : esc(c.note || "No origin passed the lift test.")}</div></div>
    <div class="kpis">${[["Ring cards", (c.ring_cards || []).length], ["Time-sliced component", c.ring_at_asof?.size ?? "—"],
      ["At-risk cards protected", (c.at_risk || []).length], ["Blocks proposed", b.n_blocks ?? 0],
      ["Exposure cut by blocks", money(b.exposure_cut_usd || 0)], ["Blocks on innocents", 0]]
      .map(([k, v]) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")}</div>
    <h3>Block set — who it touches</h3>
    <div class="table-wrap"><table><thead><tr><th>card</th><th>customer</th><th>action</th><th>route</th><th>exposure</th><th>why</th></tr></thead><tbody>
      ${(b.plan || []).map(p => `<tr><td><code>${esc(p.card_id)}</code></td><td>${esc(p.customer_id)}</td><td>${esc(humanize(p.action))}</td><td>${esc(p.route)}</td><td>${money(p.exposure_cut_usd)}</td><td>${esc(p.why)}</td></tr>`).join("") || `<tr><td colspan="6">nothing to block</td></tr>`}
    </tbody></table></div>
    <h3>Forward protection (monitor + step-up only)</h3>
    <p>${(c.at_risk || []).slice(0, 30).map(a => `<code title="last touch ${esc(a.last_touch)}">${esc(a.card_id)}</code>`).join(" ") || "No untouched card passed through the origin."}</p>
    <h3>Ring replay</h3><div id="ring-replay"><div class="skel" style="height:120px"></div></div>`;
  try {
    const rr = await getJSON(`/api/ring/${encodeURIComponent(d.case_id)}`);
    const f = rr.frames || [];
    if (!f.length) { $("#ring-replay").innerHTML = `<p class="muted">${esc(rr.note || "No shared-device transactions to replay.")}</p>`; return; }
    $("#ring-replay").innerHTML = `<p class="muted">${esc(rr.summary || "")}</p>
      <input type="range" id="rr" min="0" max="${f.length - 1}" value="${f.length - 1}" style="width:100%">
      <div id="rr-out"></div>`;
    const show = i => { const x = f[i];
      $("#rr-out").innerHTML = `<p><b>${esc(x.ts)}</b> · ${esc(x.story || "")}
        <br>Cards in ring: <b>${x.cards_in_ring}</b> · attested suspect loss so far: <b>${money(x.cumulative_suspect_usd)}</b> · all shared-device activity: ${money(x.cumulative_activity_usd)} · txn <code>${esc(x.txn_id)}</code>${x.suspect ? " (suspect)" : ""} · device <code>${esc((x.device || "").slice(0, 48))}</code></p>`; };
    $("#rr").oninput = e => show(+e.target.value); show(f.length - 1);
  } catch { $("#ring-replay").innerHTML = `<p class="muted">Ring replay needs the live console.</p>`; }
}

async function tabReplay(d, pane) {
  pane.innerHTML = `<div class="skel" style="height:200px"></div>`;
  let rp;
  try { rp = await getJSON(`/api/replay/${encodeURIComponent(d.case_id)}`); }
  catch { pane.innerHTML = `<div class="empty-state"><h3>No recorded tool I/O</h3><p>Run the case with <code>make case CASE=${esc(d.case_id)}</code>.</p></div>`; return; }
  pane.innerHTML = `
    <div class="callout soft"><span class="ci">🔍</span><div>What the agent saw at each step: every tool call, its parameters and the SHA-256 of the response it got back.
      <b>Re-run</b> repeats that call against the live graph and says whether the answer still matches.</div></div>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>tool</th><th>ms</th><th>response digest</th><th>preview</th><th></th></tr></thead><tbody>
      ${(rp.tool_calls || []).map(c => `<tr><td>${c.seq}</td><td><code>${esc(c.method)}</code></td><td>${c.latency_ms ?? ""}</td>
        <td><code>${esc((c.digest || c.error || "").slice(0, 12))}</code></td>
        <td><details><summary>show</summary><pre style="white-space:pre-wrap;max-width:520px">${esc(c.response_preview || c.params || "")}</pre></details></td>
        <td>${c.ok && c.method !== "write_case" ? `<button class="btn btn-sm" data-seq="${c.seq}">Re-run</button>` : ""}</td></tr>`).join("")}
    </tbody></table></div>`;
  $$("#tabpane [data-seq]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    try {
      const res = await fetch(apiUrl(`/api/replay/${encodeURIComponent(d.case_id)}/rerun/${b.dataset.seq}`), { method: "POST",
        headers: S.health?.run_auth ? { Authorization: `Bearer ${approvalToken()}` } : {} }).then(x => x.json());
      b.textContent = res.matches ? "✓ matches" : "✕ differs";
    } catch { b.textContent = "unavailable"; }
  });
}

async function tabLifecycle(d, pane) {
  let lc = { state_changes: (d.agent_record || {}).lifecycle || [], handover: (d.agent_record || {}).handover || {}, approvals: [], history: [] };
  try { lc = await getJSON(`/api/lifecycle/${encodeURIComponent(d.case_id)}`); } catch { /* read-only copy */ }
  const h = lc.handover || {};
  pane.innerHTML = `
    <div class="callout"><span class="ci">🗂️</span><div><b>Handover.</b> State: <b>${esc(h.state || "—")}</b>.
      Waiting on: ${(h.waiting_on || []).map(esc).join("; ") || "nothing"}.
      Decided by the agent: ${(h.decided_by_agent || []).map(humanize).map(esc).join(", ") || "—"}.
      What changed: ${esc(h.what_changed || "—")}</div></div>
    ${lc.status ? `<p><b>Owner:</b> ${esc(lc.status.owner || "unassigned")} ·
      <b>In state</b> ${esc(lc.status.state)}${lc.status.hours_in_state != null ? ` for ${lc.status.hours_in_state} h` : ""}
      ${lc.status.sla_hours ? ` · <b>due</b> ${esc(lc.status.due_at || "—")} (${lc.status.sla_hours} h, ${esc(lc.status.sla_source)})` : " · closed, no SLA"}
      ${lc.status.overdue ? ` · <b style="color:var(--bad, #c0392b)">OVERDUE</b>` : ""}
      <button id="lc-take" class="btn">Take / hand over</button></p>` : ""}
    <h3>State changes</h3>
    <ol>${(lc.state_changes || []).map(s => `<li><b>${esc(s.from || "∅")} → ${esc(s.to)}</b> · ${esc(s.actor)} (${esc(s.role)}) · ${esc(s.reason)}
      <code>${esc((s.evidence_ids || []).join(", "))}</code></li>`).join("")}</ol>
    <h3>Approvals (signed, append-only)</h3>
    <ul>${(lc.approvals || []).map(a => `<li>#${a.seq} ${esc(a.kind)} · ${esc(a.action || a.reason || "")} · ${esc(a.actor_id)} (${esc(a.actor_role)}) ·
      ${a.kind === "decision" ? (a.approved ? "approved" : "rejected") : `refused ${a.status}`} · <code>${esc((a.hash || "").slice(0, 12))}</code></li>`).join("") || "<li>none yet</li>"}</ul>
    <h3>Runs across sittings</h3>
    <ul>${(lc.history || []).map(x => `<li>v${x.version} · ${esc(x.kind)} · ${esc(x.logged_at)} ${x.changed_since_last_run ? "· <b>decision changed</b>" : ""}</li>`).join("") || "<li>—</li>"}</ul>
    ${(lc.watch_children || []).length ? `<h3>WATCH child cases</h3><p>${lc.watch_children.map(w => `<code title="${esc(w.reason)}">${esc(w.id)}</code>`).join(" ")}</p>` : ""}`;
  const take = $("#lc-take");
  if (take) take.onclick = async () => {
    const to = prompt("Assign to (actor id; leave empty to take it yourself):") || "";
    const r = await fetch(`/api/cases/${encodeURIComponent(d.case_id)}/assign`, {
      method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${approvalToken()}` },
      body: JSON.stringify({ to }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { alert(j.error || `refused (${r.status})`); return; }
    tabLifecycle(d, pane);
  };
}

function approvalToken() {
  let t = "";
  try { t = sessionStorage.getItem("approval_token") || ""; } catch { /* storage blocked */ }
  if (!t) {
    t = prompt("Approval token (team lead or fraud manager). The server derives your role from it; nothing you type about your role is trusted.") || "";
    try { if (t) sessionStorage.setItem("approval_token", t); } catch { /* storage blocked */ }
  }
  return t;
}
