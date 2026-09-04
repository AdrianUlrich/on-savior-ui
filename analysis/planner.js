/* Airlock Diplomat — planner logic.
   Inlined into planner_template.html by build_planner.py; expects a global
   DATA payload (see payload.py) already defined. */

const $ = s => document.querySelector(s);
const SVGNS = "http://www.w3.org/2000/svg";
function el(tag, attrs, parent) {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const fmt = (v, d=1) => (v > 0 ? "+" : "") + v.toFixed(d).replace(/\.0$/, "");
const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

const T = DATA.traits, M = DATA.moves, F = DATA.fams, E = DATA.edges;
const NOEFF = F.length - 1;
const deg = new Array(M.length).fill(0);
const adj = new Array(M.length).fill(null).map(() => []);
for (const [a, b] of E) { deg[a]++; deg[b]++; adj[a].push(b); adj[b].push(a); }
const searchText = M.map(m => (m.t + " " + m.id + " " + F[m.f].label).toLowerCase());
// every need axis any move touches, either side
const AXES = [...new Set(M.flatMap(m => [...Object.keys(m.nu), ...Object.keys(m.nt)]))]
  .filter(a => !a.startsWith("_")).sort();

/* ---------- state ---------- */
const S = new Set();               // selected trait indices
let famIso = -1, hideAnyone = true, hideFlavor = true, focusOn = false, covOn = false;
let dirW = 0, wY = 1, covDir = "us-";
let filterTokens = {inc: [], exc: []};
const enSet = new Set(), fbSet = new Set();   // unlocked / lost under S
let visArr = new Array(M.length).fill(true);

/* ---------- tooltip ---------- */
const tip = $("#tooltip");
let tipPinned = false;
function showTip(html, x, y) {
  tip.innerHTML = html;
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(x + 14, innerWidth - w - 12) + "px";
  tip.style.top = (y + 14 + h > innerHeight ? y - h - 10 : y + 14) + "px";
}
function hideTip(force) { if (!tipPinned || force) { tip.style.display = "none"; if (force) tipPinned = false; } }

/* ---------- build evaluation ---------- */
const inS = arr => arr.some(i => S.has(i));
function evalBuild() {
  enSet.clear(); fbSet.clear();
  M.forEach((m, i) => {
    const blocked = inS(m.fb);
    if (blocked && (m.eb.length === 0 || inS(m.eb))) fbSet.add(i);
    else if (!blocked && m.eb.length > 0 && inS(m.eb)) enSet.add(i);
  });
}

/* Coverage: which axes have at least one UNLOCKED move pushing in `dir`
   ("us-" replenish own, "them+" attack theirs, "them-" soothe theirs).
   Basic (always-available) moves deliberately don't count — they are the
   baseline everyone has. */
function dirDelta(m, dir, axis) {
  const o = dir[0] === "u" ? m.nu : m.nt;
  const v = o[axis];
  if (v === undefined) return 0;
  return dir.endsWith("+") ? (v > 0 ? v : 0) : (v < 0 ? v : 0);
}
function coveredAxes(dir, extraTrait = -1) {
  const has = new Set();
  const sel = j => S.has(j) || j === extraTrait;
  M.forEach(m => {
    if (!m.eb.length || m.fb.some(sel) || !m.eb.some(sel)) return;
    for (const a of AXES) if (dirDelta(m, dir, a) !== 0) has.add(a);
  });
  return has;
}

/* ---------- scoring ---------- */
function moveWeight(i) {
  if (focusOn && !visArr[i]) return 0;
  return 1 + dirW * clamp(-M[i].vt / 15, -1, 1);
}
function marginalOf(ti, baseCov) {
  const t = T[ti];
  let gain = 0, kill = 0;
  for (const i of t.en) {
    const m = M[i];
    if (!enSet.has(i) && !fbSet.has(i) && !inS(m.fb) && !m.fb.includes(ti)) gain += moveWeight(i);
  }
  for (const i of t.fb) {
    const m = M[i];
    const mine = m.eb.length === 0 || inS(m.eb);
    if (mine && !inS(m.fb)) kill += moveWeight(i);
  }
  const yearsTerm = wY * (-t.c);
  let covTerm = 0, covNew = 0;
  if (covOn) {
    const withT = coveredAxes(covDir, ti);
    covNew = [...withT].filter(a => !baseCov.has(a)).length;
    covTerm = 6 * covNew;
  }
  return {gain, kill, yearsTerm, covTerm, covNew, score: gain - kill + yearsTerm + covTerm};
}
function uniqueOf(ti) {
  let u = 0;
  for (const i of T[ti].en) {
    if (enSet.has(i) && !M[i].eb.some(j => j !== ti && S.has(j))) u++;
  }
  return u;
}

/* ---------- visibility ---------- */
function computeVis() {
  const {inc, exc} = filterTokens;
  M.forEach((m, i) => {
    let v = true;
    if (hideAnyone && m.eb.length === 0) v = false;
    if (v && hideFlavor && m.f === NOEFF) v = false;
    if (v && famIso >= 0 && m.f !== famIso) v = false;
    if (v && inc.length && !inc.every(t => searchText[i].includes(t))) v = false;
    if (v && exc.some(t => searchText[i].includes(t))) v = false;
    visArr[i] = v;
  });
}

/* ---------- graph ---------- */
const svg = $("#graph-svg");
const GW = 1200, GH = 800;
let vb = {x: 0, y: 0, w: GW, h: GH};
const setVB = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
const xsAll = M.map(m => m.x), ysAll = M.map(m => m.y);
const xmin = Math.min(...xsAll), xmax = Math.max(...xsAll);
const ymin = Math.min(...ysAll), ymax = Math.max(...ysAll);
const gx = m => 40 + (m.x - xmin) / (xmax - xmin) * (GW - 80);
const gy = m => 40 + (m.y - ymin) / (ymax - ymin) * (GH - 80);
const edgeLayer = el("g", {}, svg);
const nodeLayer = el("g", {}, svg);
const edgeEls = E.map(([a, b]) =>
  el("line", {x1: gx(M[a]), y1: gy(M[a]), x2: gx(M[b]), y2: gy(M[b]),
    stroke: "#223040", "stroke-width": 0.5, opacity: 0.45}, edgeLayer));
const nodeEls = M.map((m, i) => {
  const r = m.f === NOEFF ? 2.2 : 3 + Math.sqrt(deg[i]) * 0.75;
  const c = el("circle", {cx: gx(m), cy: gy(m), r, fill: F[m.f].color,
    stroke: "#0c1116", "stroke-width": 0.8}, nodeLayer);
  c.style.cursor = "pointer";
  return c;
});

function moveTip(i) {
  const m = M[i];
  const needs = (o, who) => Object.entries(o).map(([a, v]) =>
    `<span style="color:${v < 0 ? "#86b6ef" : "#d98b8b"}">${who}·${a} ${fmt(v, 0)}</span>`).join(" · ");
  return `<div class="tt-title">${esc(m.t)}</div>
    <div class="tt-kv"><span class="tag" style="background:${F[m.f].color};color:#0c1116">${F[m.f].label}</span>
    ${m.op ? ' <span class="tag" style="background:#2a3745;color:#c3ced4">opener</span>' : ""}</div>
    ${Object.keys(m.nu).length ? `<div class="tt-kv">${needs(m.nu, "you")}</div>` : ""}
    ${Object.keys(m.nt).length ? `<div class="tt-kv">${needs(m.nt, "them")}</div>` : ""}
    <div class="tt-kv">unlocked by: <b>${m.eb.length ? m.eb.map(ti => T[ti].n).join(", ") : "anyone"}</b></div>
    ${m.fb.length ? `<div class="tt-kv">forbidden to: <b>${m.fb.map(ti => T[ti].n).join(", ")}</b></div>` : ""}
    ${m.ch != null && m.ch < 1 ? `<div class="tt-kv">appears on <b>${Math.round(m.ch * 100)}%</b> of refreshes</div>` : ""}
    <div class="tt-kv" style="color:var(--ink-3)">${adj[i].length} reply links · ${m.id}</div>`;
}

function restyle() {
  let shown = 0;
  M.forEach((m, i) => {
    const n = nodeEls[i];
    if (!visArr[i]) { n.style.display = "none"; return; }
    shown++;
    n.style.display = "";
    let op = 1;
    if (S.size && !enSet.has(i) && !fbSet.has(i)) op = 0.15;
    n.setAttribute("opacity", op);
    if (enSet.has(i)) { n.setAttribute("stroke", "#e5a13c"); n.setAttribute("stroke-width", 2.2); }
    else if (fbSet.has(i)) { n.setAttribute("stroke", "#e66767"); n.setAttribute("stroke-width", 2.2); }
    else { n.setAttribute("stroke", "#0c1116"); n.setAttribute("stroke-width", 0.8); }
  });
  E.forEach(([a, b], k) => {
    const e = edgeEls[k];
    if (!visArr[a] || !visArr[b]) { e.style.display = "none"; return; }
    e.style.display = "";
    const dim = S.size && !enSet.has(a) && !fbSet.has(a) && !enSet.has(b) && !fbSet.has(b);
    e.setAttribute("opacity", dim ? 0.06 : 0.45);
  });
  $("#vis-count").textContent = `${shown}/${M.length} moves shown`;
}

nodeEls.forEach((n, i) => {
  n.addEventListener("pointerenter", e => { if (!tipPinned) showTip(moveTip(i), e.clientX, e.clientY); });
  n.addEventListener("pointerleave", () => hideTip());
  n.addEventListener("click", e => {
    e.stopPropagation();
    tipPinned = false; showTip(moveTip(i), e.clientX, e.clientY); tipPinned = true;
  });
});
svg.addEventListener("click", () => hideTip(true));

$("#famchips").innerHTML = F.map((f, i) =>
  `<button class="chip" data-f="${i}" aria-pressed="false"><span class="swatch" style="background:${f.color}"></span>${f.label} · ${f.n}</button>`).join("");
document.querySelectorAll(".chip").forEach(ch => ch.addEventListener("click", () => {
  const f = +ch.dataset.f;
  famIso = famIso === f ? -1 : f;
  document.querySelectorAll(".chip").forEach(c => c.setAttribute("aria-pressed", String(+c.dataset.f === famIso)));
  refresh();
}));

/* pan / zoom */
let drag = null;
svg.addEventListener("pointerdown", e => {
  drag = {x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y};
  svg.classList.add("dragging");
  svg.setPointerCapture(e.pointerId);
});
svg.addEventListener("pointermove", e => {
  if (!drag) return;
  const r = svg.getBoundingClientRect();
  vb.x = drag.vx - (e.clientX - drag.x) * vb.w / r.width;
  vb.y = drag.vy - (e.clientY - drag.y) * vb.h / r.height;
  setVB();
});
svg.addEventListener("pointerup", e => { drag = null; svg.classList.remove("dragging"); svg.releasePointerCapture(e.pointerId); });
svg.addEventListener("wheel", e => {
  e.preventDefault();
  const r = svg.getBoundingClientRect();
  const mx = vb.x + (e.clientX - r.left) / r.width * vb.w;
  const my = vb.y + (e.clientY - r.top) / r.height * vb.h;
  const k = e.deltaY > 0 ? 1.18 : 1 / 1.18;
  const nw = clamp(vb.w * k, 120, 4000);
  const nh = nw * GH / GW;
  vb = {x: mx - (mx - vb.x) * nw / vb.w, y: my - (my - vb.y) * nh / vb.h, w: nw, h: nh};
  setVB();
}, {passive: false});
$("#reset-view").addEventListener("click", () => { vb = {x: 0, y: 0, w: GW, h: GH}; setVB(); });
setVB();

/* ---------- panels ---------- */
const costStr = c => c > 0 ? `−${c}y` : c < 0 ? `+${-c}y` : "0y";

function renderStats() {
  const years = [...S].reduce((a, i) => a + T[i].c, 0);
  $("#build-stats").innerHTML = S.size === 0
    ? "no traits selected — baseline moveset only"
    : `<b>${S.size}</b> traits · years ${years > 0 ? `<b>−${years}</b> spent` : years < 0 ? `<b>+${-years}</b> refunded` : "<b>±0</b>"}
       · <span class="amber">${enSet.size} moves unlocked</span> · <span class="red">${fbSet.size} lost to forbids</span>`;
  $("#build-chips").innerHTML = [...S].sort((a, b) => T[a].n.localeCompare(T[b].n)).map(i => {
    const u = uniqueOf(i);
    return `<button class="bchip ${u === 0 ? "dead" : ""}" data-i="${i}" title="remove">
      ${T[i].n} <span class="uq">${costStr(T[i].c)} · ${u === 0 ? "0 unique!" : u + " unique"}</span> ✕</button>`;
  }).join("");
  document.querySelectorAll(".bchip").forEach(b =>
    b.addEventListener("click", () => { S.delete(+b.dataset.i); syncChecks(); refresh(); }));
}

/* Coverage table: per axis, the strongest unlocked push in each of the four
   directions; when the build has none, fall back to the best Basic
   (always-available, not blocked) move, shown dimmed with a BAS tag. */
const COV_COLS = [
  {dir: "us+", label: "us ↑ worsen"},
  {dir: "us-", label: "us ↓ replenish"},
  {dir: "them+", label: "them ↑ attack"},
  {dir: "them-", label: "them ↓ soothe"},
];
function bestCell(axis, dir) {
  let best = null, bas = null;
  M.forEach((m, i) => {
    const v = dirDelta(m, dir, axis);
    if (!v) return;
    if (enSet.has(i)) {
      if (!best || Math.abs(v) > Math.abs(best.v)) best = {v, t: m.t};
    } else if (m.eb.length === 0 && !inS(m.fb)) {
      if (!bas || Math.abs(v) > Math.abs(bas.v)) bas = {v, t: m.t};
    }
  });
  return best ? {...best, bas: false} : bas ? {...bas, bas: true} : null;
}
function renderCoverage() {
  const head = `<tr><th>need</th>${COV_COLS.map(c => `<th>${c.label}</th>`).join("")}</tr>`;
  const rows = AXES.map(a => {
    const cells = COV_COLS.map(c => {
      const b = bestCell(a, c.dir);
      if (!b) return `<td class="none">—</td>`;
      const col = b.v < 0 ? "#86b6ef" : "#d98b8b";
      return `<td class="${b.bas ? "bas" : ""}" title="${esc(b.t)}">
        <span style="color:${col}">${fmt(b.v, 0)}</span>
        <span class="mv">${esc(b.t)}</span>${b.bas ? '<span class="btag">BAS</span>' : ""}</td>`;
    }).join("");
    return `<tr><th>${a}</th>${cells}</tr>`;
  }).join("");
  $("#covtable").innerHTML = head + rows;
}

function renderMarginals(baseCov) {
  const cands = T.map((t, i) => ({i, ...marginalOf(i, baseCov)}))
    .filter(c => !S.has(c.i) && Math.abs(c.score) > 0.01)
    .sort((a, b) => b.score - a.score)
    .slice(0, 15);
  $("#marginals").innerHTML = cands.map(c => {
    const t = T[c.i];
    const parts = [];
    if (c.gain || c.kill) parts.push(`moves ${fmt(c.gain - c.kill)}${c.kill ? ` (+${c.gain.toFixed(1)}/−${c.kill.toFixed(1)})` : ""}`);
    if (c.yearsTerm) parts.push(`years ${fmt(c.yearsTerm)}`);
    if (c.covNew) parts.push(`coverage +${c.covNew} need${c.covNew > 1 ? "s" : ""}`);
    return `<li><b>${t.n}</b> <span class="mono" style="color:var(--ink-3)">${costStr(t.c)}</span>
      <span class="score">${fmt(c.score)}</span>
      <span class="brk">${parts.join(" · ")}</span></li>`;
  }).join("") || "<li>nothing scores above zero</li>";
}

function refresh() {
  evalBuild();
  computeVis();
  restyle();
  renderStats();
  renderCoverage();
  renderMarginals(covOn ? coveredAxes(covDir) : new Set());
}

/* trait roster */
const listBox = $("#trait-list");
listBox.innerHTML = T.map((t, i) =>
  `<label data-name="${t.n.toLowerCase()}"><input type="checkbox" data-i="${i}">
   ${t.n} <span class="tcost ${t.c < 0 ? "refund" : ""}">${costStr(t.c)}</span></label>`).join("");
function syncChecks() {
  listBox.querySelectorAll("input").forEach(cb => { cb.checked = S.has(+cb.dataset.i); });
}
listBox.addEventListener("change", e => {
  const i = +e.target.dataset.i;
  if (e.target.checked) S.add(i); else S.delete(i);
  refresh();
});
$("#trait-search").addEventListener("input", e => {
  const q = e.target.value.toLowerCase();
  listBox.querySelectorAll("label").forEach(l => {
    l.style.display = l.dataset.name.includes(q) ? "" : "none";
  });
});
$("#clear-build").addEventListener("click", () => { S.clear(); syncChecks(); refresh(); });

/* move filter + toggles */
$("#move-filter").addEventListener("input", e => {
  const toks = e.target.value.toLowerCase().split(/\s+/).filter(Boolean);
  filterTokens = {
    inc: toks.filter(t => !t.startsWith("-")),
    exc: toks.filter(t => t.startsWith("-") && t.length > 1).map(t => t.slice(1)),
  };
  refresh();
});
$("#hide-anyone").addEventListener("change", e => { hideAnyone = e.target.checked; refresh(); });
$("#hide-flavor").addEventListener("change", e => { hideFlavor = e.target.checked; refresh(); });
$("#focus-on").addEventListener("change", e => { focusOn = e.target.checked; refresh(); });
$("#cov-on").addEventListener("change", e => { covOn = e.target.checked; refresh(); });
$("#cov-dir").addEventListener("change", e => { covDir = e.target.value; refresh(); });
$("#dir").addEventListener("input", e => {
  dirW = +e.target.value;
  $("#dir-out").textContent = dirW === 0 ? "neutral" : (dirW > 0 ? `nice ${(dirW * 100).toFixed(0)}%` : `mean ${(-dirW * 100).toFixed(0)}%`);
  refresh();
});
$("#wy").addEventListener("input", e => {
  wY = +e.target.value;
  $("#wy-out").textContent = wY.toFixed(1) + " mv";
  refresh();
});

refresh();
