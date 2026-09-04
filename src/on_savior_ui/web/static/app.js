/* Save Library — vanilla front end for the /api endpoints.
   State lives in `data` (last library payload) and `ui` (view preferences,
   persisted to localStorage). Any mutation re-fetches the library so the
   filesystem stays the single source of truth. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

let data = { saves: [], continuities: [], tags: [], capabilities: {} };
const ui = loadPrefs();

function loadPrefs() {
  const base = {
    groupBy: "continuity", sort: "saved_desc", view: "cards",
    search: "", hideAuto: false, starredOnly: false, notedOnly: false,
    character: "", version: "", tags: [], collapsed: [], selected: null,
  };
  try { return { ...base, ...JSON.parse(localStorage.getItem("osui.library") || "{}") }; }
  catch { return base; }
}
function savePrefs() {
  try { localStorage.setItem("osui.library", JSON.stringify(ui)); } catch { /* private mode */ }
}

/* ---------- formatting ---------- */
const fmtMoney = (n) => "$" + Math.round(n || 0).toLocaleString();
const fmtHours = (h) => (h >= 10 ? h.toFixed(0) : h.toFixed(1)) + "h";
function fmtBytes(b) {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1000)), u.length - 1);
  const v = b / 1000 ** i;
  return (v >= 100 || i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + u[i];
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const days = (Date.now() - d) / 86400000;
  if (days < 1) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (days < 7) return Math.floor(days) + "d ago";
  return d.toLocaleDateString([], { year: "2-digit", month: "short", day: "numeric" });
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const url = (key, suffix = "") => `/api/saves/${encodeURIComponent(key)}${suffix}`;

/* ---------- api ---------- */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : {},
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}
function toast(msg, isError = false) {
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " err" : "");
  el.textContent = msg;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), isError ? 6000 : 3200);
}
async function guard(fn) {
  try { return await fn(); }
  catch (err) { toast(err.message, true); }
}

async function refresh() {
  data = await api("/api/library");
  $("#root-path").textContent = data.root;
  const bytes = data.saves.reduce((a, s) => a + s.size_bytes, 0);
  $("#totals").textContent = `${data.saves.length} saves · ${fmtBytes(bytes)}`;
  renderCapabilities();
  renderFilterOptions();
  render();
}

/* ---------- filtering, sorting, grouping ---------- */
function visibleSaves() {
  const q = ui.search.trim().toLowerCase();
  return data.saves.filter((s) => {
    if (ui.hideAuto && s.is_autosave) return false;
    if (ui.starredOnly && !s.starred) return false;
    if (ui.notedOnly && !s.note) return false;
    if (ui.character && s.player !== ui.character) return false;
    if (ui.version && s.version !== ui.version) return false;
    if (ui.tags.length && !ui.tags.every((t) => s.tags.includes(t))) return false;
    if (q) {
      const hay = [s.name, s.player, s.ship, s.ship_reg, s.occupation, s.note, ...s.tags]
        .join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

const SORTERS = {
  saved_desc: (a, b) => b.created_epoch - a.created_epoch,
  saved_asc: (a, b) => a.created_epoch - b.created_epoch,
  play_desc: (a, b) => b.play_time - a.play_time,
  play_asc: (a, b) => a.play_time - b.play_time,
  money_desc: (a, b) => b.money - a.money,
  size_desc: (a, b) => b.size_bytes - a.size_bytes,
  name_asc: (a, b) => a.name.localeCompare(b.name),
};

function groupSaves(saves) {
  if (ui.groupBy === "none") return [{ id: "", title: "All saves", saves }];
  const keyOf = {
    continuity: (s) => s.continuity,
    character: (s) => s.player || "Unnamed",
    ship: (s) => s.ship || "No ship",
    version: (s) => s.version || "Unknown build",
  }[ui.groupBy];

  const buckets = new Map();
  for (const s of saves) {
    const k = keyOf(s) ?? "";
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(s);
  }
  const groups = [...buckets].map(([id, list]) => {
    const cont = data.continuities.find((c) => c.id === id);
    return {
      id,
      title: ui.groupBy === "continuity" ? (cont?.label ?? id) : id,
      continuity: ui.groupBy === "continuity" ? cont : null,
      saves: list,
    };
  });
  groups.sort((a, b) =>
    Math.max(...b.saves.map((s) => s.created_epoch)) -
    Math.max(...a.saves.map((s) => s.created_epoch)));
  return groups;
}

/* ---------- lineage layout ---------- */
/* Chronological rows, git-log style: the line leading to a continuity's newest
   save keeps its lane, every other fork steps one lane to the right. */
function laneMap(saves) {
  const byKey = new Map(saves.map((s) => [s.key, s]));
  const kids = new Map(saves.map((s) => [s.key, []]));
  const roots = [];
  for (const s of saves) {
    if (s.parent && byKey.has(s.parent)) kids.get(s.parent).push(s.key);
    else roots.push(s.key);
  }
  const tipMemo = new Map();
  const tip = (k) => {
    if (tipMemo.has(k)) return tipMemo.get(k);
    const v = Math.max(byKey.get(k).created_epoch, ...kids.get(k).map(tip), 0);
    tipMemo.set(k, v);
    return v;
  };
  const lanes = new Map();
  const walk = (k, lane) => {
    lanes.set(k, lane);
    const children = [...kids.get(k)].sort((a, b) => tip(b) - tip(a));
    children.forEach((c, i) => walk(c, i === 0 ? lane : lane + 1));
  };
  roots.sort((a, b) => byKey.get(a).play_time - byKey.get(b).play_time)
       .forEach((r) => walk(r, 0));
  return { lanes, kids };
}

/* ---------- rendering ---------- */
function render() {
  const saves = visibleSaves().sort(SORTERS[ui.sort]);
  const host = $("#content");
  if (!saves.length) {
    host.innerHTML = `<p class="muted pad">No saves match these filters.</p>`;
    return;
  }
  const collapsed = new Set(ui.collapsed);
  host.innerHTML = groupSaves(saves).map((g) => {
    const isOpen = !collapsed.has(g.id);
    return `<section class="group">
      ${groupHead(g, isOpen)}
      ${isOpen ? groupBody(g) : ""}
    </section>`;
  }).join("");
  wireContent();
}

function groupHead(g, isOpen) {
  const c = g.continuity;
  const bytes = g.saves.reduce((a, s) => a + s.size_bytes, 0);
  const bits = [`${g.saves.length} saves`, fmtBytes(bytes)];
  if (c) {
    bits.push(fmtHours(c.play_time_max) + " played", fmtMoney(c.money_latest));
    if (c.branch_points.length) bits.push(`${c.branch_points.length} fork${c.branch_points.length > 1 ? "s" : ""}`);
    if (c.seed_ids.length > 1) bits.push(`${c.seed_ids.length} seeds`);
  }
  const pol = c?.policy;
  let meter = "";
  if (pol?.max_bytes) {
    const pct = Math.min(100, (c.size_bytes / pol.max_bytes) * 100);
    meter = `<span class="pill mono" title="Rotation budget">${fmtBytes(c.size_bytes)} / ${fmtBytes(pol.max_bytes)}</span>
      <span class="meter"><i class="${pct >= 100 ? "over" : ""}" style="width:${pct}%"></i></span>`;
  }
  return `<div class="group-head">
    <button class="caret" data-toggle="${esc(g.id)}">${isOpen ? "▾" : "▸"}</button>
    <div class="grow">
      <h3>${esc(g.title)}</h3>
      <p class="muted small mono">${bits.join(" · ")}</p>
    </div>
    ${meter}
    ${c ? `<button class="ghost small" data-policy="${esc(c.id)}">
        ${pol?.enabled ? "⟳ Auto-rotate on" : "Auto-rotate…"}</button>` : ""}
  </div>`;
}

function groupBody(g) {
  if (ui.view === "lineage") return lineageView(g);
  if (ui.view === "table") return tableView(g);
  return `<div class="cards">${g.saves.map(card).join("")}</div>`;
}

function card(s) {
  const shot = s.has_screenshot ? `background-image:url('${url(s.key, "/screenshot.png")}')` : "";
  return `<article class="card ${ui.selected === s.key ? "sel" : ""}" data-key="${esc(s.key)}">
    <div class="shot" style="${shot}">
      ${s.is_autosave ? `<span class="badge">auto ${s.autosave_counter}</span>` : ""}
      <button class="star" data-star="${esc(s.key)}" title="Star (protects it from rotation)">${s.starred ? "★" : "☆"}</button>
    </div>
    <div class="card-body">
      <div class="card-title">${esc(s.name)}</div>
      <div class="stats">
        <span><b>${fmtMoney(s.money)}</b></span>
        <span>${fmtHours(s.play_time)}</span>
        <span>${fmtBytes(s.size_bytes)}</span>
      </div>
      <div class="stats"><span>${esc(s.player)}</span><span>${fmtDate(s.saved_at)}</span></div>
      ${s.tags.length ? `<div class="tags">${s.tags.map((t) => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
      ${s.note ? `<div class="note-line">${esc(s.note.slice(0, 80))}</div>` : ""}
    </div>
  </article>`;
}

function lineageView(g) {
  const { lanes, kids } = laneMap(g.saves);
  const rows = [...g.saves].sort((a, b) => a.play_time - b.play_time || a.created_epoch - b.created_epoch);
  return `<div class="lineage">${rows.map((s) => {
    const lane = lanes.get(s.key) ?? 0;
    const forked = (kids.get(s.key) || []).length > 1;
    const rail = "│ ".repeat(lane) + (lane ? "└╴" : "");
    return `<div class="lin-row ${ui.selected === s.key ? "sel" : ""}" data-key="${esc(s.key)}">
      <span class="lin-rail">${rail}</span>
      <span>${s.starred ? "★" : forked ? "◆" : s.is_autosave ? "·" : "●"}</span>
      <span class="nm ${s.is_autosave ? "auto" : ""}">${esc(s.name)}</span>
      ${forked ? `<span class="fork">fork</span>` : ""}
      <span class="muted col play">${fmtHours(s.play_time)}</span>
      <span class="muted col money">${fmtMoney(s.money)}</span>
      <span class="muted col size">${fmtBytes(s.size_bytes)}</span>
    </div>`;
  }).join("")}</div>`;
}

function tableView(g) {
  return `<div class="scroll-x"><table>
    <thead><tr><th>Save</th><th>Character</th><th>Ship</th><th class="num">Money</th>
      <th class="num">Played</th><th class="num">In-game</th><th class="num">Size</th>
      <th>Saved</th><th>Tags</th></tr></thead>
    <tbody>${g.saves.map((s) => `<tr data-key="${esc(s.key)}">
      <td>${s.starred ? "★ " : ""}${esc(s.name)}</td>
      <td>${esc(s.player)}</td><td>${esc(s.ship)}</td>
      <td class="num">${fmtMoney(s.money)}</td>
      <td class="num">${fmtHours(s.play_time)}</td>
      <td class="num">${fmtHours(s.sim_time)}</td>
      <td class="num">${fmtBytes(s.size_bytes)}</td>
      <td>${fmtDate(s.saved_at)}</td>
      <td>${esc(s.tags.join(", "))}</td>
    </tr>`).join("")}</tbody></table></div>`;
}

function wireContent() {
  $$("[data-key]").forEach((el) => el.addEventListener("click", (e) => {
    if (e.target.closest("[data-star]")) return;
    openDrawer(el.dataset.key);
  }));
  $$("[data-star]").forEach((el) => el.addEventListener("click", async (e) => {
    e.stopPropagation();
    const s = data.saves.find((x) => x.key === el.dataset.star);
    await guard(async () => {
      await api(url(s.key), { method: "PATCH", body: JSON.stringify({ starred: !s.starred }) });
      await refresh();
    });
  }));
  $$("[data-toggle]").forEach((el) => el.addEventListener("click", () => {
    const id = el.dataset.toggle;
    const set = new Set(ui.collapsed);
    set.has(id) ? set.delete(id) : set.add(id);
    ui.collapsed = [...set];
    savePrefs();
    render();
  }));
  $$("[data-policy]").forEach((el) =>
    el.addEventListener("click", () => openPolicy(el.dataset.policy)));
}

function renderCapabilities() {
  const c = data.capabilities;
  const lines = [
    `delete: ${c.delete ? (c.trash ? "to trash" : "permanent") : "disabled"}`,
    `archive: ${c.archive ? "on" : "disabled"}`,
    `auto-rotate: ${c.auto_rotate ? "running" : "manual only"}`,
  ];
  $("#caps").innerHTML = "<h2>Server</h2>" + lines.map((l) => `<div class="mono">${esc(l)}</div>`).join("");
}

function renderFilterOptions() {
  const fill = (sel, values, current, anyLabel) => {
    sel.innerHTML = `<option value="">${anyLabel}</option>` +
      values.map((v) => `<option value="${esc(v)}"${v === current ? " selected" : ""}>${esc(v)}</option>`).join("");
  };
  fill($("#f-character"), [...new Set(data.saves.map((s) => s.player).filter(Boolean))].sort(),
       ui.character, "Any character");
  fill($("#f-version"), [...new Set(data.saves.map((s) => s.version).filter(Boolean))].sort(),
       ui.version, "Any build");
  $("#tag-filters").innerHTML = data.tags.map((t) =>
    `<button class="tag ${ui.tags.includes(t) ? "on" : ""}" data-tag="${esc(t)}">${esc(t)}</button>`).join("")
    || `<span class="muted small">No tags yet</span>`;
  $$("#tag-filters [data-tag]").forEach((el) => el.addEventListener("click", () => {
    const t = el.dataset.tag;
    ui.tags = ui.tags.includes(t) ? ui.tags.filter((x) => x !== t) : [...ui.tags, t];
    savePrefs(); renderFilterOptions(); render();
  }));
}

/* ---------- drawer ---------- */
function openDrawer(key) {
  const s = data.saves.find((x) => x.key === key);
  if (!s) return;
  ui.selected = key;
  savePrefs();
  $("#drawer").hidden = false;
  $("#d-name").textContent = s.name;
  $("#d-sub").textContent = `${s.player} · ${s.ship || "no ship"} · ${s.version}`;
  const cont = data.continuities.find((c) => c.id === s.continuity);
  const parent = data.saves.find((x) => x.key === s.parent);
  const caps = data.capabilities;

  $("#d-body").innerHTML = `
    <section class="actions">
      <a class="ghost" style="text-decoration:none" href="${url(key, "/download")}">Download zip</a>
      <button class="ghost" id="a-rename">Rename…</button>
      ${caps.archive ? `<button class="ghost" id="a-archive">Archive copy</button>` : ""}
      ${caps.delete ? `<button class="ghost danger" id="a-delete">Delete${caps.trash ? " (to trash)" : ""}</button>` : ""}
    </section>
    <section>
      <h2>Headline</h2>
      <dl class="kv">
        <dt>Money</dt><dd>${fmtMoney(s.money)}</dd>
        <dt>Play time</dt><dd>${s.play_time.toFixed(2)} h</dd>
        <dt>In-game time</dt><dd>${s.sim_time.toFixed(1)} h</dd>
        <dt>Age</dt><dd>${s.age}</dd>
        <dt>Saved</dt><dd>${s.saved_at ? new Date(s.saved_at).toLocaleString() : "—"}</dd>
        <dt>On disk</dt><dd>${fmtBytes(s.size_bytes)}</dd>
        <dt>Occupation</dt><dd>${esc(s.occupation)}</dd>
      </dl>
    </section>
    <section>
      <h2>Continuity</h2>
      <dl class="kv">
        <dt>Playthrough</dt><dd>${esc(cont?.label ?? "—")}</dd>
        <dt>Continues from</dt><dd>${esc(parent ? parent.name : "start of the run")}</dd>
        <dt>Seed</dt><dd title="${esc(s.seed_id)}">${esc(s.seed_id.slice(0, 8))}</dd>
      </dl>
    </section>
    <section>
      <h2>Your notes</h2>
      <div class="field">
        <label for="d-tags">Tags (comma separated)</label>
        <input type="text" id="d-tags" value="${esc(s.tags.join(", "))}">
      </div>
      <div class="field">
        <label for="d-note">Note</label>
        <textarea id="d-note">${esc(s.note)}</textarea>
      </div>
      <button class="primary" id="a-meta">Save notes</button>
    </section>
    <section id="d-detail"><h2>Inside the save</h2>
      <p class="muted small">Reading the archive…</p></section>`;

  $("#a-meta").addEventListener("click", () => guard(async () => {
    await api(url(key), {
      method: "PATCH",
      body: JSON.stringify({
        tags: $("#d-tags").value.split(",").map((t) => t.trim()).filter(Boolean),
        note: $("#d-note").value,
      }),
    });
    toast("Notes saved");
    await refresh();
  }));
  $("#a-rename").addEventListener("click", () => guard(async () => {
    const name = prompt("New name for this save", s.name);
    if (!name || name === s.name) return;
    toast("Rewriting the archive…");
    const out = await api(url(key, "/rename"), { method: "POST", body: JSON.stringify({ name }) });
    toast(`Renamed to ${out.name}`);
    await refresh();
    openDrawer(key);
  }));
  const archiveBtn = $("#a-archive");
  if (archiveBtn) archiveBtn.addEventListener("click", () => guard(async () => {
    const out = await api(url(key, "/archive"), { method: "POST" });
    toast(`Copied to ${out.archived_to}`);
  }));
  const delBtn = $("#a-delete");
  if (delBtn) delBtn.addEventListener("click", () => guard(async () => {
    if (!confirm(`Delete "${s.name}" (${fmtBytes(s.size_bytes)})?` +
                 (caps.trash ? "\nIt moves to the trash folder." : "\nThis cannot be undone."))) return;
    await api(url(key), { method: "DELETE" });
    toast(`Deleted ${s.name}`);
    closeDrawer();
    await refresh();
  }));

  loadDetail(key);
  render();
}

async function loadDetail(key) {
  let detail;
  try { detail = await api(url(key, "/detail")); }
  catch (err) {
    const host = $("#d-detail");
    if (host && ui.selected === key) host.innerHTML = `<h2>Inside the save</h2><p class="muted small">${esc(err.message)}</p>`;
    return;
  }
  if (ui.selected !== key) return;
  const m = detail.metrics;
  const plots = Object.entries(m.plots || {});
  const crew = detail.crew.sort((a, b) => (b.is_player ? 1 : 0) - (a.is_player ? 1 : 0));
  $("#d-detail").innerHTML = `<h2>Inside the save</h2>
    <dl class="kv">
      <dt>Objectives</dt><dd>${m.objectives_done} / ${m.objectives_total}</dd>
      <dt>Open jobs</dt><dd>${m.jobs}</dd>
      <dt>Ledger entries</dt><dd>${m.ledger_entries}</dd>
      <dt>Billed to you</dt><dd>${fmtMoney(m.ledger_expense)}</dd>
      <dt>Owed to you</dt><dd>${fmtMoney(m.ledger_income)}</dd>
      <dt>Aboard your ship</dt><dd>${crew.length}</dd>
      <dt>People known</dt><dd>${detail.people_known}</dd>
    </dl>
    ${plots.length ? `<h2 style="margin-top:14px">Plot beats</h2>
      <dl class="kv">${plots.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : ""}
    <h2 style="margin-top:14px">Aboard</h2>
    <div class="crew">${crew.slice(0, 40).map((p) =>
      `<div class="${p.is_player ? "me" : ""}">${esc(p.name)}
        <span class="muted small">${p.traits.length} traits · ${Object.keys(p.skills).length} skills</span></div>`).join("")}
      ${crew.length > 40 ? `<div class="muted small">+ ${crew.length - 40} more</div>` : ""}</div>`;
}

function closeDrawer() {
  $("#drawer").hidden = true;
  ui.selected = null;
  savePrefs();
  render();
}

/* ---------- retention policy ---------- */
function openPolicy(groupId) {
  const c = data.continuities.find((x) => x.id === groupId);
  if (!c) return;
  const p = c.policy || {};
  $("#modal").hidden = false;
  $("#m-title").textContent = `Auto-rotate — ${c.label}`;
  $("#m-body").innerHTML = `
    <p class="muted small">Rotation keeps recent history at full resolution and thins
      older saves as they age, until the continuity fits its budget. Manual saves, starred
      saves, forks and timeline tips are protected unless you say otherwise.</p>
    <div class="field" style="margin-top:12px">
      <label class="check"><input type="checkbox" id="p-enabled" ${p.enabled ? "checked" : ""}>
        Rotate this playthrough automatically${data.capabilities.auto_rotate ? "" : " (server sweep is off — preview and apply by hand)"}</label>
    </div>
    <div class="row">
      <div class="field"><label for="p-label">Name this playthrough</label>
        <input type="text" id="p-label" value="${esc(p.label || "")}" placeholder="${esc(c.label)}"></div>
      <div class="field"><label for="p-bytes">Size budget (GB, blank = none)</label>
        <input type="number" id="p-bytes" step="0.1" min="0" value="${p.max_bytes ? (p.max_bytes / 1e9).toFixed(2) : ""}"></div>
      <div class="field"><label for="p-count">Max saves (blank = none)</label>
        <input type="number" id="p-count" min="1" value="${p.max_count ?? ""}"></div>
    </div>
    <div class="row">
      <div class="field"><label for="p-recent">Always keep newest</label>
        <input type="number" id="p-recent" min="0" value="${p.keep_recent ?? 5}"></div>
      <div class="field">
        <label>Protect</label>
        <label class="check"><input type="checkbox" id="p-manual" ${p.keep_manual ? "checked" : ""}> Manual saves</label>
        <label class="check"><input type="checkbox" id="p-branch" ${p.keep_branch_points ? "checked" : ""}> Forks &amp; timeline tips</label>
      </div>
    </div>
    <div class="actions" style="margin:14px 0">
      <button class="primary" id="p-save">Save policy</button>
      <button class="ghost" id="p-preview">Preview rotation</button>
      <button class="ghost danger" id="p-apply" ${data.capabilities.delete ? "" : "disabled title='server started without --allow-delete'"}>Apply now</button>
    </div>
    <div id="p-plan"></div>`;

  const body = () => ({
    enabled: $("#p-enabled").checked,
    label: $("#p-label").value.trim(),
    max_bytes: $("#p-bytes").value ? Math.round(parseFloat($("#p-bytes").value) * 1e9) : null,
    max_count: $("#p-count").value ? parseInt($("#p-count").value, 10) : null,
    keep_recent: parseInt($("#p-recent").value || "0", 10),
    keep_manual: $("#p-manual").checked,
    keep_branch_points: $("#p-branch").checked,
  });
  const put = () => api(`/api/continuities/${encodeURIComponent(groupId)}/policy`,
    { method: "PUT", body: JSON.stringify(body()) });

  $("#p-save").addEventListener("click", () => guard(async () => {
    await put(); toast("Policy saved"); await refresh();
  }));
  $("#p-preview").addEventListener("click", () => guard(async () => {
    await put();
    showPlan(await api(`/api/continuities/${encodeURIComponent(groupId)}/rotate`, { method: "POST" }));
    await refresh();
  }));
  $("#p-apply").addEventListener("click", () => guard(async () => {
    await put();
    const preview = await api(`/api/continuities/${encodeURIComponent(groupId)}/rotate`, { method: "POST" });
    if (!preview.remove.length) { toast("Already within budget — nothing to remove"); return; }
    if (!confirm(`Remove ${preview.remove.length} saves, freeing ${fmtBytes(preview.freed_bytes)}?`)) return;
    const done = await api(`/api/continuities/${encodeURIComponent(groupId)}/rotate?apply=true`, { method: "POST" });
    showPlan(done);
    toast(`Rotated: ${done.remove.length} saves removed, ${fmtBytes(done.freed_bytes)} freed`);
    await refresh();
  }));
}

function showPlan(plan) {
  $("#p-plan").innerHTML = `
    <h2>${plan.applied ? "Removed" : "Would remove"} ${plan.remove.length} of ${plan.count_before}</h2>
    <p class="muted small">${fmtBytes(plan.size_before)} → ${fmtBytes(plan.size_after)}
      ${plan.over_budget ? "· <b>budget not reachable</b> without dropping protected saves" : ""}</p>
    <div class="scroll-x"><table><thead><tr><th></th><th>Save</th><th class="num">Played</th>
      <th class="num">Size</th><th>Reason</th></tr></thead><tbody>
      ${plan.decisions.map((d) => `<tr>
        <td class="${d.keep ? "plan-keep" : "plan-drop"}">${d.keep ? "keep" : "drop"}</td>
        <td>${esc(d.name)}</td>
        <td class="num">${fmtHours(d.play_time)}</td>
        <td class="num">${fmtBytes(d.size_bytes)}</td>
        <td class="muted wrap">${esc(d.reason)}</td></tr>`).join("")}
    </tbody></table></div>`;
}

/* ---------- wiring ---------- */
function bindSegmented(id, prop) {
  $$(`#${id} button`).forEach((b) => {
    b.classList.toggle("on", ui[prop] === b.dataset.value);
    b.addEventListener("click", () => {
      ui[prop] = b.dataset.value;
      $$(`#${id} button`).forEach((x) => x.classList.toggle("on", x === b));
      savePrefs(); render();
    });
  });
}
function bindCheck(id, prop) {
  const el = $(id);
  el.checked = ui[prop];
  el.addEventListener("change", () => { ui[prop] = el.checked; savePrefs(); render(); });
}
function bindSelect(id, prop) {
  const el = $(id);
  el.addEventListener("change", () => { ui[prop] = el.value; savePrefs(); render(); });
}

bindSegmented("group-by", "groupBy");
bindSegmented("view-mode", "view");
bindCheck("#f-autosaves", "hideAuto");
bindCheck("#f-starred", "starredOnly");
bindCheck("#f-noted", "notedOnly");
bindSelect("#f-character", "character");
bindSelect("#f-version", "version");
$("#sort-by").value = ui.sort;
$("#sort-by").addEventListener("change", (e) => { ui.sort = e.target.value; savePrefs(); render(); });
$("#search").value = ui.search;
$("#search").addEventListener("input", (e) => { ui.search = e.target.value; savePrefs(); render(); });
$("#refresh").addEventListener("click", () => guard(refresh));
$("#filters-toggle").addEventListener("click", (e) => {
  const open = document.body.classList.toggle("filters-open");
  e.target.classList.toggle("on", open);
});
$("#clear-filters").addEventListener("click", () => {
  Object.assign(ui, { search: "", hideAuto: false, starredOnly: false, notedOnly: false, character: "", version: "", tags: [] });
  savePrefs(); $("#search").value = ""; renderFilterOptions();
  ["#f-autosaves", "#f-starred", "#f-noted"].forEach((s) => ($(s).checked = false));
  ["#f-character", "#f-version"].forEach((s) => ($(s).value = ""));
  render();
});
$("#d-close").addEventListener("click", closeDrawer);
$("#m-close").addEventListener("click", () => ($("#modal").hidden = true));
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").hidden = true; });
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#modal").hidden) $("#modal").hidden = true;
  else if (!$("#drawer").hidden) closeDrawer();
});

guard(refresh);
