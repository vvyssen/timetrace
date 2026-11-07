// Timetrace dashboard: overview, calendar and setup wizard. Plain JS + SVG, no dependencies.
"use strict";
let META = null, LANG = "zh", EVALS = [], ROLE = {}, data = null, cal = null, timer = null;
const ROLE_ORDER = ["create", "grow", "keep", "leisure"];

// ---------- i18n ----------
function t(key, vars = {}) {
  const dict = I18N[LANG] || I18N.en;
  let s = dict[key] ?? I18N.en[key] ?? key;
  if (typeof s !== "string") return s;
  return s.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
}
function applyStatic() {
  document.documentElement.lang = LANG === "zh" ? "zh-CN" : "en";
  document.title = t("title");
  document.querySelectorAll("[data-t]").forEach(n => { n.textContent = t(n.dataset.t); });
  document.getElementById("views").setAttribute("aria-label", t("views"));
  document.getElementById("ranges").setAttribute("aria-label", t("range"));
  document.getElementById("date").setAttribute("aria-label", t("pickDay"));
  document.getElementById("device").setAttribute("aria-label", t("device"));
  const slot = document.getElementById("slot");
  slot.setAttribute("aria-label", t("slot"));
  [...slot.options].forEach(o => { o.textContent = o.value === "60" ? t("slot60") : t("slotN", { n: o.value }); });
  document.querySelectorAll("#langs button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.l === LANG)));
  if (window.TT_READONLY) document.querySelector("header .sub").textContent = t("roSub");
  deviceOptions();
}
// Device menu from the devices ActivityWatch actually has: one device of a kind shows just the kind
// ("iPhone"); several of a kind show each by name ("iPhone（Work phone）") and filter by exact name.
function deviceOptions() {
  const sel = document.getElementById("device");
  if (!META) return;
  const devs = META.devices || [], count = {};
  devs.forEach(d => { count[d.kind] = (count[d.kind] || 0) + 1; });
  const [l, r] = LANG === "zh" ? ["（", "）"] : [" (", ")"];
  const opts = [["all", t("allDevices")], ...devs.map(d => count[d.kind] > 1
    ? ["name:" + d.name, `${d.kind}${l}${d.name.replace(/\.local$/, "")}${r}`] : [d.kind.toLowerCase(), d.kind])];
  const key = JSON.stringify(opts);
  if (sel.dataset.key !== key) {
    sel.replaceChildren(...opts.map(([v, txt]) => el("option", { value: v, text: txt })));
    sel.dataset.key = key;
  }
  if (!opts.some(([v]) => v === state.device)) state.device = "all";  // e.g. a saved "ipad" on a Mac with no iPad
  sel.value = state.device;
}
function setMeta(m) {
  if (!m) return;
  META = m;
  EVALS = m.evaluations.map(e => e.name);
  ROLE = Object.fromEntries(m.evaluations.map(e => [e.name, e.role]));
  if (LANG !== m.lang) { LANG = m.lang; applyStatic(); } else deviceOptions();
}

// ---------- helpers ----------
const col = e => `var(--e-${ROLE[e] && ROLE_ORDER.includes(ROLE[e]) ? ROLE[e] : "none"})`;
const onCol = e => `var(--on-${ROLE[e] && ROLE_ORDER.includes(ROLE[e]) ? ROLE[e] : "none"})`;
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "style") n.style.cssText = v; else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? "" : v);
  }
  kids.flat().forEach(c => c != null && c !== false && n.append(c instanceof Node ? c : document.createTextNode(c)));
  return n;
};
const NS = "http://www.w3.org/2000/svg";
const sv = (tag, attrs = {}) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
const sum = o => EVALS.reduce((a, e) => a + (o[e] || 0), 0);
function fmt(sec) {
  sec = Math.round(sec || 0);
  if (sec < 60) return sec > 0 ? "<1m" : "0m";
  const tm = Math.round(sec / 60), h = Math.floor(tm / 60), m = tm % 60;  // round once: never "60m"
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}
const pct = (a, b) => b > 0 ? `${(a / b * 100).toFixed(a / b < 0.1 ? 1 : 0)}%` : "—";
const localDate = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const hm = x => new Date(x).toTimeString().slice(0, 5);
const weekdayName = d => { const w = t("weekdays"); return t("weekday", { d: w[d.getDay()] }); };
async function api(path) { const r = await fetch(path); const j = await r.json(); if (!r.ok || j.error) throw new Error(j.error || r.statusText); return j; }
async function post(name, body = {}) {
  const r = await fetch(`/api/action/${name}`, { method: "POST", headers: { "Content-Type": "application/json", "X-Timetrace-Token": TT_TOKEN }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error(j.error || r.statusText);
  return j;
}

// ---------- tooltip ----------
const tip = document.getElementById("tip");
function showTip(ev, title, rows, extra) {
  tip.replaceChildren(el("div", { class: "t", text: title }));
  rows.forEach(([name, val, color]) => tip.append(el("div", { class: "r" }, el("b", { text: val }), el("i", { style: `background:${color}` }), el("span", { text: name }))));
  if (extra) tip.append(el("div", { class: "x", text: extra }));
  tip.style.display = "block";
  moveTip(ev);
}
function moveTip(ev) {
  const r = ev.target.getBoundingClientRect ? ev.target.getBoundingClientRect() : null;
  const x = ev.clientX ?? (r ? r.left + r.width / 2 : 0), y = ev.clientY ?? (r ? r.top : 0);
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 14)) + "px";
  tip.style.top = (y + h + 20 > window.innerHeight ? y - h - 12 : y + 14) + "px";
}
const hideTip = () => { tip.style.display = "none"; };
function hover(node, fn) {
  node.setAttribute("tabindex", "0"); node.classList.add("hit");
  node.addEventListener("pointerenter", e => fn(e)); node.addEventListener("pointermove", moveTip);
  node.addEventListener("pointerleave", e => { if (e.pointerType !== "touch") hideTip(); });  // a tap keeps the tip open
  node.addEventListener("focus", e => fn(e)); node.addEventListener("blur", hideTip);
}
document.addEventListener("pointerdown", e => { if (e.pointerType === "touch" && !(e.target.closest && e.target.closest(".hit"))) hideTip(); }, { passive: true });
window.addEventListener("scroll", hideTip, { passive: true });
const evalRows = (o, total) => EVALS.filter(e => o[e] > 0).map(e => [`${e}${total ? " · " + pct(o[e], total) : ""}`, fmt(o[e]), col(e)]);

function card(id, title, note) {
  const c = document.getElementById(id); c.replaceChildren(); c.hidden = false;
  c.append(el("h2", { text: title }));
  if (note !== null) c.append(el("p", { class: "note", text: note || "" }));
  return c;
}

// ---------- agent hand-off (tagging) ----------
const AGENT_CMD = 'claude "$(timetrace agent prompt)"';
let AGENT = null;
async function agentInfo() { if (!AGENT) AGENT = await api("/api/setup/agent"); return AGENT; }
async function copyText(text, btn) {
  try { await navigator.clipboard.writeText(text); }
  catch (e) {  // clipboard API unavailable: fall back to a selected textarea
    const ta = el("textarea", { style: "position:fixed;opacity:0" }); ta.value = text; document.body.append(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  if (btn) { const o = btn.textContent; btn.textContent = t("copied"); setTimeout(() => { btn.textContent = o; }, 1500); }
}
function cmdRow(text) {
  const b = el("button", { class: "btn", type: "button" }, t("copy"));
  b.addEventListener("click", () => copyText(text, b));
  return el("div", { class: "cmdrow" }, el("pre", { class: "cmd", text }), b);
}
function agentBox(onSkip) {
  const status = el("div", { class: "st", text: t("agentConnected") + "…" });
  const promptPre = el("pre", { class: "cmd prompt", text: "…" });
  const copyP = el("button", { class: "btn", type: "button" }, t("copyPrompt"));
  agentInfo().then(a => {
    const names = { claude: "Claude Code", codex: "Codex", opencode: "opencode", hermes: "Hermes" };
    status.textContent = t("agentConnected") + Object.entries(a.agents).map(([k, v]) =>
      `${names[k] || k} ${v.found ? (v.mcp ? "✓ " + t("agentOk") : "✗ " + t("agentNoMcp")) : "– " + t("agentMissing")}`).join(" · ");
    promptPre.textContent = a.prompt;
    copyP.onclick = () => copyText(a.prompt, copyP);
  }).catch(e => { status.textContent = e.message; });
  const box = el("div", { class: "agentbox" },
    el("b", { text: t("agentTitle") }), el("div", { class: "lead", text: t("agentLead") }), status,
    el("ol", {},
      el("li", {}, t("agentStep1"), cmdRow("timetrace agent install")),
      el("li", {}, t("agentStep2"), cmdRow(AGENT_CMD)),
      el("li", {}, t("agentStep3"), " ", copyP)),
    el("details", {}, el("summary", { text: t("agentShowPrompt") }), promptPre));
  if (onSkip) box.append(el("div", { class: "wiz-nav", style: "margin-top:10px" }, el("button", { class: "btn primary", type: "button", onclick: onSkip }, t("skipForNow"))));
  return box;
}

async function renderPending() {
  const b = document.getElementById("c-pending");
  b.hidden = true;
  if (!META || !META.setup_done || state.view !== "overview" || window.TT_READONLY) return;
  try { if (sessionStorage.getItem("tt-pending-dismissed")) return; } catch (e) {}
  let p;
  try { p = await api("/api/setup/pending"); } catch (e) { return; }
  if (!p.count || state.view !== "overview") return;
  const copyB = el("button", { class: "btn", type: "button" }, t("pendingAgent"));
  copyB.addEventListener("click", async () => copyText((await agentInfo()).prompt, copyB));
  b.replaceChildren(el("div", { class: "msg", text: t("pendingBanner", { n: p.count, v: fmt(p.seconds) }) }),
    el("button", { class: "btn", type: "button", onclick: () => { state.view = "setup"; wiz.step = 3; load(); } }, t("pendingTag")), copyB,
    el("button", { class: "btn", type: "button", "aria-label": t("dismiss"), onclick: () => { try { sessionStorage.setItem("tt-pending-dismissed", "1"); } catch (e) {} b.hidden = true; } }, "×"));
  b.hidden = false;
}

const OVERVIEW_CARDS = ["c-summary", "c-timeline", "c-daily", "c-heat", "c-hourly", "c-domains", "c-projects", "c-table"];
const hideCards = ids => ids.forEach(id => { document.getElementById(id).hidden = true; });

// ---------- overview ----------
function deviceLabel() { return data.device === "all" ? t("allDevicesShort") : t("onlyDevice", { d: { mac: "Mac", iphone: "iPhone", ipad: "iPad" }[data.device] || data.device.replace(/^name:/, "") }); }

function renderSummary() {
  const c = card("c-summary", t("period"), rangeLabel());
  const total = data.total, days = data.range.days;
  if (total <= 0) { c.append(el("div", { class: "empty", text: t("emptyRange") })); return; }
  const hero = el("div", { class: "hero" },
    el("div", { class: "label", text: t("totalActive") }),
    el("div", { class: "value", text: fmt(total) }),
    el("div", { class: "meta", text: days > 1 ? t("perDayN", { v: fmt(total / days), n: days }) : deviceLabel() }));
  const tiles = el("div", { class: "tiles" });
  EVALS.slice(0, 4).forEach(e => {
    const v = data.by_eval[e] || 0;
    tiles.append(el("div", { class: "tile" },
      el("div", { class: "k" }, el("span", { class: "sw", style: `background:${col(e)}` }), e),
      el("div", { class: "v", text: fmt(v) }),
      el("div", { class: "d", text: `${pct(v, total)}${days > 1 ? " · " + t("perDay", { v: fmt(v / days) }) : ""}` })));
  });
  c.append(el("div", { class: "hero-row" }, hero, tiles));
  const bar = el("div", { class: "segbar", role: "img", "aria-label": EVALS.filter(e => data.by_eval[e] > 0).map(e => `${e} ${pct(data.by_eval[e], total)}`).join(", ") });
  EVALS.forEach(e => {
    const v = data.by_eval[e] || 0; if (v <= 0) return;
    const part = el("div", { style: `flex:${v} 1 0;background:${col(e)};color:${onCol(e)}` });
    bar.append(part);
    hover(part, ev => showTip(ev, e, [[pct(v, total), fmt(v), col(e)]]));
    requestAnimationFrame(() => { const s = pct(v, total); if (part.offsetWidth > s.length * 8 + 16) { part.textContent = s; part.style.paddingLeft = "8px"; } });
  });
  c.append(bar);
  const legend = el("div", { class: "legend" });
  META.evaluations.slice(0, 4).forEach(({ name, desc }) => legend.append(el("div", { class: "item" },
    el("span", { class: "sw", style: `background:${col(name)}` }), el("span", { text: name }), el("span", { class: "desc", text: (desc || "").split(/——| — /)[0] }))));
  c.append(legend);
  const devs = Object.keys(data.by_device).sort((a, b) => ["Mac", "iPhone", "iPad"].indexOf(a) - ["Mac", "iPhone", "iPad"].indexOf(b));
  if (data.device === "all" && devs.length > 1) {
    const rows = el("div", { class: "devrows" });
    const devMax = Math.max(...devs.map(d => sum(data.by_device[d])));
    devs.forEach(d => {
      const o = data.by_device[d], tt = sum(o);
      const thin = el("div", { class: "thin", style: `width:${Math.max(1, tt / devMax * 100)}%` });
      EVALS.forEach(e => { if (o[e] > 0) { const p = el("div", { style: `flex:${o[e]} 1 0;background:${col(e)}` }); thin.append(p); hover(p, ev => showTip(ev, `${d} · ${e}`, [[pct(o[e], tt), fmt(o[e]), col(e)]])); } });
      rows.append(el("div", { text: d }), thin, el("div", { class: "num", text: fmt(tt) }));
    });
    c.append(rows);
  }
  const rules = (META.duration_rules.rules || []);
  if (rules.length) c.append(el("div", { class: "rules", text: t("durationRules", { rules: rules.map(r => t("durationRule", { subs: r.subdomains.join("/"), m: r.over_minutes, ev: r.evaluation })).join(LANG === "zh" ? "；" : "; ") }) }));
}

function stackedColumns(container, vals, { divisor = 1, tickLabel = v => v.label, everyNth = 1, title = v => v.label } = {}) {
  const W = container.clientWidth || 800, H = 220, padL = 44, padB = 24, padT = 8;
  const plotW = W - padL - 4, plotH = H - padB - padT;
  const totals = vals.map(v => sum(v.evals) / divisor);
  const maxH = Math.max(...totals, 60) / 3600, steps = [0.25, 0.5, 1, 2, 3, 4, 6, 8, 12];
  const step = steps.find(s => maxH / s <= 4) || 12, top = Math.ceil(maxH / step) * step;
  const y = sec => padT + plotH - (sec / 3600) / top * plotH;
  const svg = sv("svg", { width: W, height: H, role: "img" });
  for (let k = 0; k <= top + 1e-9; k += step) {
    svg.append(sv("line", { x1: padL, x2: W - 4, y1: y(k * 3600), y2: y(k * 3600), stroke: k === 0 ? "var(--axis)" : "var(--grid)", "stroke-width": 1 }));
    const lab = sv("text", { x: padL - 6, y: y(k * 3600) + 4, "text-anchor": "end" }); lab.textContent = step < 1 ? `${Math.round(k * 60)}m` : `${k}h`; svg.append(lab);
  }
  const band = plotW / vals.length, bw = Math.min(24, band * 0.62);
  vals.forEach((v, i) => {
    const x = padL + band * i + (band - bw) / 2;
    let acc = 0; const segs = EVALS.map(e => [e, (v.evals[e] || 0) / divisor]).filter(([, s]) => s > 0);
    segs.forEach(([e, s], k) => {
      const y0 = y(acc), y1 = y(acc + s); acc += s;
      const h = y0 - y1 - (k > 0 ? 2 : 0); if (h < 0.6) return;
      if (k === segs.length - 1) {
        const r = Math.min(4, h, bw / 2);
        svg.append(sv("path", { d: `M${x},${y1 + h} V${y1 + r} Q${x},${y1} ${x + r},${y1} H${x + bw - r} Q${x + bw},${y1} ${x + bw},${y1 + r} V${y1 + h} Z`, fill: col(e) }));
      } else svg.append(sv("rect", { x, y: y1, width: bw, height: h, fill: col(e) }));
    });
    if (i % everyNth === 0) { const lab = sv("text", { x: padL + band * i + band / 2, y: H - 6, "text-anchor": "middle" }); lab.textContent = tickLabel(v); svg.append(lab); }
    const hit = sv("rect", { x: padL + band * i, y: padT, width: band, height: plotH, fill: "transparent" });
    hover(hit, ev => showTip(ev, `${title(v)} · ${fmt(totals[i])}`, evalRows(Object.fromEntries(EVALS.map(e => [e, (v.evals[e] || 0) / divisor])), totals[i])));
    svg.append(hit);
  });
  container.append(svg);
}

function renderDaily() {
  const c = document.getElementById("c-daily");
  if (data.range.days <= 1) { c.hidden = true; return; }
  card("c-daily", t("daily"), t("dailyNote"));
  const box = el("div"); c.append(box);
  stackedColumns(box, data.daily.map(d => ({ label: d.date, evals: d.evals })), {
    tickLabel: v => v.label.slice(5).replace("-", "/"), everyNth: data.daily.length > 14 ? 3 : 1,
    title: v => `${v.label} ${weekdayName(new Date(v.label + "T12:00"))}`,
  });
}

function renderHourly() {
  const days = data.range.days;
  const c = card("c-hourly", t("hourly"), days > 1 ? t("hourlyAvg", { n: days }) : t("hourlyOne"));
  const box = el("div"); c.append(box);
  stackedColumns(box, data.hourly.map(h => ({ label: String(h.hour), evals: h.evals })), {
    divisor: days, everyNth: 3, tickLabel: v => v.label.padStart(2, "0"),
    title: v => `${v.label.padStart(2, "0")}:00–${String(+v.label + 1).padStart(2, "0")}:00${days > 1 ? t("avgSuffix") : ""}`,
  });
}

// ---------- heatmap: hour of day x day (7 days) or weekday (longer ranges), one evaluation at a time ----------
function richT(key, vars) {  // t() with the filled-in values in bold
  const s = (I18N[LANG] || I18N.en)[key] ?? I18N.en[key] ?? key;
  return s.split(/(\{\w+\})/).filter(Boolean).map(part => { const m = part.match(/^\{(\w+)\}$/); return m ? el("b", { text: vars[m[1]] ?? "" }) : part; });
}
const clock = h => h === 24 ? "24:00" : `${String(h % 24).padStart(2, "0")}:00`;
const HEAT_OPACITY = v => 0.15 + 0.85 * Math.pow(v, 0.7);  // one hue, light -> dark; empty cells stay blank
function renderHeat() {
  const c = document.getElementById("c-heat");
  const H = data.heat;
  if (!H || data.range.days <= 1 || data.total <= 0) { c.hidden = true; return; }
  c.replaceChildren(); c.hidden = false;
  const ix = Object.fromEntries(H.evals.map((e, i) => [e, i]));
  const evs = EVALS.slice(0, 4);
  const sel = evs.find(e => ROLE[e] === state.heat) || null;
  const cellVal = hr => sel ? (hr[ix[sel]] || 0) : hr.reduce((a, b) => a + b, 0);
  const byWd = H.days.length > 14;
  let rows;
  if (!byWd) rows = H.days.map(d => { const dt = new Date(d.date + "T12:00"); return { label: `${weekdayName(dt)} ${d.date.slice(5).replace("-", "/")}`, title: `${d.date} ${weekdayName(dt)}`, h: d.h }; });
  else {
    rows = [1, 2, 3, 4, 5, 6, 0].map(w => ({ w, n: 0, label: t("weekday", { d: t("weekdays")[w] }), h: Array.from({ length: 24 }, () => H.evals.map(() => 0)) }));
    H.days.forEach(d => { const r = rows.find(x => x.w === new Date(d.date + "T12:00").getDay()); r.n++; d.h.forEach((hr, h) => hr.forEach((v, i) => { r.h[h][i] += v; })); });
    rows.forEach(r => { if (r.n) r.h = r.h.map(hr => hr.map(v => v / r.n)); r.title = `${r.label} · ${t("heatAvgN", { n: r.n })}`; });
  }
  // header: title + evaluation filter
  const seg = el("div", { class: "seg small", role: "group", "aria-label": t("heatFilter") });
  [["all", t("heatAll"), null], ...evs.map(e => [ROLE[e], e, col(e)])].forEach(([k, name, color]) => {
    const b = el("button", { type: "button", "aria-pressed": String((sel ? ROLE[sel] : "all") === k) }, color ? el("span", { class: "sw", style: `background:${color}` }) : null, name);
    b.addEventListener("click", () => { state.heat = k; saveState(); renderHeat(); });
    seg.append(b);
  });
  const title = `${sel || t("heatAll")} · ${data.range.key === "7d" ? t("heatTitle7") : t("heatTitleN", { n: data.range.days })}`;
  c.append(el("div", { class: "heat-head" }, el("div", {}, el("h2", { text: title }), el("p", { class: "note", text: byWd ? t("heatNoteWd", { n: H.days.length }) : t("heatNote7") })), seg));
  // one-line summary: where the selected time concentrates, and how much of it is late at night
  const colTot = Array(24).fill(0);
  H.days.forEach(d => d.h.forEach((hr, h) => { colTot[h] += cellVal(hr); }));
  const tot = colTot.reduce((a, b) => a + b, 0);
  if (tot <= 0) { c.append(el("div", { class: "empty", text: t("heatEmpty", { ev: sel || t("heatAll") }) })); return; }
  let best = -1, bi = 0;
  for (let i = 0; i < 24; i++) { const v = colTot[i] + colTot[(i + 1) % 24] + colTot[(i + 2) % 24]; if (v > best) { best = v; bi = i; } }
  const night = [22, 23, 0, 1, 2, 3, 4].reduce((a, h) => a + colTot[h], 0);
  c.append(el("div", { class: "heat-sum" }, ...richT("heatSum", { ev: sel || t("heatAllTime"), v: fmt(tot), a: clock(bi), b: clock(bi + 3 > 24 ? (bi + 3) % 24 : bi + 3), p: pct(best, tot), q: pct(night, tot) })));
  // grid
  const box = el("div"); c.append(box);
  const W = box.clientWidth || c.clientWidth - 36 || 800, narrow = W < 520;
  const padL = narrow ? 64 : 88, padT = 16, gap = 2, cw = (W - padL) / 24, ch = Math.max(18, Math.min(30, cw * 0.95));
  const max = Math.max(...rows.flatMap(r => r.h.map(cellVal)), 1);
  const color = sel ? col(sel) : "var(--ink-2)";
  const svg = sv("svg", { width: W, height: padT + rows.length * ch, role: "img", "aria-label": `${title}. ${c.querySelector(".heat-sum").textContent}` });
  for (let h = 0; h < 24; h += narrow ? 6 : 3) { const lab = sv("text", { x: padL + h * cw + 1, y: 10 }); lab.textContent = String(h).padStart(2, "0"); svg.append(lab); }
  rows.forEach((r, i) => {
    const y = padT + i * ch;
    const lab = sv("text", { x: 0, y: y + ch / 2 + 4 }); lab.textContent = r.label; lab.style.fill = "var(--ink-2)"; svg.append(lab);
    r.h.forEach((hr, h) => {
      const v = cellVal(hr), x = padL + h * cw, g = sv("g", { class: "heat-cell" });
      g.append(sv("rect", { x: x + gap / 2, y: y + gap / 2, width: cw - gap, height: ch - gap, rx: 3, fill: "var(--wash)" }));
      if (v > 0) g.append(sv("rect", { x: x + gap / 2, y: y + gap / 2, width: cw - gap, height: ch - gap, rx: 3, fill: color, "fill-opacity": HEAT_OPACITY(v / max).toFixed(3) }));
      const when = `${r.title} · ${clock(h)}–${clock(h + 1)}${byWd ? t("heatAvg") : ""}`;
      hover(g, ev => showTip(ev, when, sel ? [[sel, fmt(v), col(sel)]] : evalRows(Object.fromEntries(H.evals.map((e, k) => [e, hr[k]])), v)));
      svg.append(g);
    });
  });
  box.append(svg);
  const ramp = el("div", { class: "ramp" }, t("heatLess"));
  [0, 0.25, 0.5, 0.75, 1].forEach(f => ramp.append(el("i", { style: `background:${color};opacity:${HEAT_OPACITY(f).toFixed(3)}` })));
  ramp.append(t("heatMore"), " · ", t("heatMax", { v: fmt(max) }));
  c.append(ramp);
}

function barRow(parent, name, small, evals, maxTotal, { sub = false, onclick = null, tipTitle = name } = {}) {
  const tt = sum(evals);
  const nm = el("div", { class: "name" + (sub ? " sub" : "") + (onclick ? " row-btn" : ""), title: name }, name, small ? el("small", { text: small }) : null);
  if (onclick) { nm.addEventListener("click", onclick); nm.setAttribute("role", "button"); nm.setAttribute("tabindex", "0"); nm.addEventListener("keydown", e => (e.key === "Enter" || e.key === " ") && onclick()); }
  const track = el("div", { class: "track" + (sub ? " sub" : "") });
  const wrap = el("div", { style: `width:${Math.max(0.5, tt / maxTotal * 100)}%;display:flex;gap:2px;height:100%` });
  EVALS.forEach(e => {
    if (!(evals[e] > 0)) return;
    const s = el("div", { style: `flex:${evals[e]} 1 0;background:${col(e)}` });
    hover(s, ev => showTip(ev, `${tipTitle} · ${fmt(tt)}`, evalRows(evals, tt)));
    wrap.append(s);
  });
  if (wrap.lastChild) wrap.lastChild.style.borderRadius = "0 4px 4px 0";
  track.append(wrap);
  parent.append(nm, track, el("div", { class: "num", text: fmt(tt) }));
}

const expanded = new Set();
function renderDomains() {
  const c = card("c-domains", t("domains"), t("domainsNote"));
  if (!data.domains.length) { c.append(el("div", { class: "empty", text: t("noData") })); return; }
  const bars = el("div", { class: "bars" });
  const max = Math.max(...data.domains.map(d => sum(d.evals)));
  data.domains.forEach(d => {
    const toggle = () => { expanded.has(d.name) ? expanded.delete(d.name) : expanded.add(d.name); renderDomains(); };
    barRow(bars, `${expanded.has(d.name) ? "▾" : "▸"} ${d.name}`, pct(sum(d.evals), data.total), d.evals, max, { onclick: toggle, tipTitle: d.name });
    if (expanded.has(d.name)) d.subs.forEach(s => barRow(bars, s.name, "", s.evals, max, { sub: true, tipTitle: `${d.name} / ${s.name}` }));
  });
  c.append(bars);
}

function renderProjects() {
  const c = card("c-projects", t("projects"), t("projectsNote"));
  if (!data.projects.length) { c.append(el("div", { class: "empty", text: t("noData") })); return; }
  const bars = el("div", { class: "bars wide" });
  const max = Math.max(...data.projects.map(p => sum(p.evals)));
  data.projects.forEach(p => barRow(bars, p.project, `${[p.domain, p.subdomain].filter(Boolean).join("/")} · ${p.devices.join("+")}`, p.evals, max, { tipTitle: p.project }));
  c.append(bars);
}

function renderTimeline() {
  const c = document.getElementById("c-timeline");
  if (data.range.days > 1 || !data.timeline.length) { c.hidden = true; return; }
  card("c-timeline", t("timeline"), t("timelineNote"));
  const box = el("div"); c.append(box);
  const W = box.clientWidth || c.clientWidth - 36 || 900, padL = 56, laneH = 22, gap = 14;
  const lanes = ["Mac", "iPhone", "iPad"].filter(d => data.timeline.some(s => s.device === d));
  const H = lanes.length * (laneH + gap) + 18;
  const day0 = new Date(data.range.start).getTime();
  const x = v => padL + (v - day0) / 86400000 * (W - padL - 4);
  const svg = sv("svg", { width: W, height: H, role: "img", "aria-label": t("timelineAria") });
  for (let h = 0; h <= 24; h += 2) {
    const xx = x(day0 + h * 3600000);
    svg.append(sv("line", { x1: xx, x2: xx, y1: 0, y2: H - 18, stroke: "var(--grid)", "stroke-width": 1 }));
    const lab = sv("text", { x: xx, y: H - 4, "text-anchor": "middle" }); lab.textContent = String(h).padStart(2, "0"); svg.append(lab);
  }
  lanes.forEach((d, i) => {
    const y0 = i * (laneH + gap);
    const lab = sv("text", { x: 0, y: y0 + laneH / 2 + 4 }); lab.textContent = d; lab.style.fill = "var(--ink-2)"; lab.style.fontSize = "12px"; svg.append(lab);
    svg.append(sv("rect", { x: padL, y: y0, width: W - padL - 4, height: laneH, fill: "var(--wash)", rx: 4 }));
    data.timeline.filter(s => s.device === d).forEach(s => {
      const a = new Date(s.start).getTime(), b = new Date(s.end).getTime();
      const xa = x(a), w = Math.max(1.5, x(b) - xa);
      const r = sv("rect", { x: xa, y: y0, width: w, height: laneH, fill: col(s.evaluation), rx: w > 6 ? 2 : 0 });
      hover(r, ev => showTip(ev, `${hm(a)}–${hm(b)} · ${fmt((b - a) / 1000)}`, [[s.evaluation, s.app, col(s.evaluation)]],
        `${[s.domain, s.subdomain, s.project].filter(Boolean).join(" / ")}${s.rule ? "  · " + s.rule : ""}`));
      svg.append(r);
    });
  });
  box.append(svg);
}

function renderTable() {
  const c = card("c-table", t("table"), t("tableNote"));
  const det = el("details"); det.append(el("summary", { text: t("tableExpand", { n: data.apps.length }) }));
  const tbl = el("table");
  tbl.append(el("thead", {}, el("tr", {}, el("th", { text: t("colDevice") }), el("th", { text: t("colApp") }), el("th", { text: t("colDomain") }), el("th", { text: t("colProject") }),
    ...EVALS.slice(0, 4).map(e => el("th", { class: "n", text: e })), el("th", { class: "n", text: t("colTotal") }))));
  const tb = el("tbody");
  data.apps.forEach(a => tb.append(el("tr", {}, el("td", { text: a.device }), el("td", { text: a.app }), el("td", { text: a.domain }), el("td", { text: a.project }),
    ...EVALS.slice(0, 4).map(e => el("td", { class: "n", text: a.evals[e] > 0 ? fmt(a.evals[e]) : "" })), el("td", { class: "n", text: fmt(sum(a.evals)) }))));
  tbl.append(tb); det.append(el("div", { class: "tablewrap" }, tbl)); c.append(det);
}

// ---------- phone access (read-only link on the local network) ----------
async function renderPhone() {
  hideCards([...OVERVIEW_CARDS, "c-calendar", "c-setup", "c-pending"]);
  const c = card("c-phone", t("phoneTitle"), null);
  c.append(el("p", { class: "note", style: "max-width:820px;font-size:13px", text: t("phoneLead") }));
  let st;
  try { st = await api("/api/lan"); } catch (e) { c.append(el("div", { class: "err", text: e.message })); return; }
  const toast = el("span", { class: "toast" });
  const act = async body => {
    try { await post("lan", body); } catch (e) { toast.textContent = e.message; toast.className = "toast err"; return; }
    await new Promise(r => setTimeout(r, 800));  // the server is listening again on the new address
    if (state.view === "phone") renderPhone();
  };
  c.append(el("div", { class: "phone-state" },
    el("span", { class: "pill" + (st.enabled ? " on" : "") }, el("i"), st.enabled ? t("phoneOn") : t("phoneOff")),
    el("button", { class: "btn" + (st.enabled ? "" : " primary"), type: "button", onclick: () => act({ enabled: !st.enabled }) }, st.enabled ? t("phoneDisable") : t("phoneEnable")),
    st.enabled ? el("button", { class: "btn", type: "button", onclick: () => act({ rotate: true }) }, t("phoneRotate")) : null, toast));
  if (st.enabled) {
    if (!st.listening) c.append(el("p", { class: "err", text: t("phoneRestart") }));
    if (!st.urls.length) c.append(el("p", { class: "err", text: t("phoneNoNet") }));
    st.urls.forEach((u, i) => c.append(el("div", { class: "linkrow" }, el("div", { class: "lbl", text: i === 0 && st.hostname ? t("phoneLinkMain") : t("phoneLinkIp") }), cmdRow(u))));
    c.append(el("p", { class: "note", text: t("phoneRotateNote") }),
      el("div", { style: "font-weight:600;margin-top:14px", text: t("phoneDaily") }), el("p", { class: "note", text: t("phoneDailyBody") }), cmdRow("timetrace lan url --date today"));
  }
  const tips = el("ul", { class: "tips" }, el("li", { text: t("phoneTipSafari") }), el("li", { text: t("phoneTipHome") }));
  if (st.firewall) tips.append(el("li", { text: t("phoneTipFirewall") }));
  c.append(el("div", { style: "font-weight:600;margin-top:14px", text: t("phoneTips") }), tips,
    el("div", { class: "wiz-nav" }, el("button", { class: "btn", type: "button", onclick: () => { state.view = "overview"; load(); } }, t("phoneBack"))));
}

function rangeLabel() {
  const s = data.range.start.slice(0, 10), e = new Date(new Date(data.range.end).getTime() - 1);
  const names = { today: t("today"), yesterday: t("yesterday"), "7d": t("last7"), "30d": t("last30"), day: "" };
  const nm = names[data.range.key];
  if (data.range.days <= 1) return nm ? `${s} (${nm})` : s;
  return `${s} – ${localDate(e)} (${nm})`;
}

function render() {
  hideCards(["c-calendar", "c-setup", "c-phone"]);
  renderPending();
  if (data.error) { hideCards(OVERVIEW_CARDS); const c = card("c-summary", t("error")); c.append(el("div", { class: "err", text: data.error })); return; }
  renderSummary(); renderTimeline(); renderDaily(); renderHeat(); renderHourly(); renderDomains(); renderProjects(); renderTable();
  document.getElementById("updated").textContent = t("updated", { t: hm(data.generated_at) });
}

// ---------- calendar ----------
let calScrolledWeek = null;
function renderCalendar() {
  hideCards([...OVERVIEW_CARDS, "c-setup", "c-pending", "c-phone"]);
  if (cal.error) { const c = card("c-calendar", t("error")); c.append(el("div", { class: "err", text: cal.error })); return; }
  const ws = new Date(cal.week.start), we = new Date(new Date(cal.week.end).getTime() - 1);
  const c = card("c-calendar", t("calTitle"), t("calNote", { a: localDate(ws), b: localDate(we), n: cal.slot_minutes }));
  const devs = cal.lanes;
  const hourH = 44, today = localDate(new Date());
  const maxDay = Math.max(...cal.days.map(d => d.total), 1);
  const head = el("div", { class: "cal-head" }, el("div"));
  cal.days.forEach(d => {
    const thin = el("div", { class: "thin", style: `width:${Math.max(0, d.total / maxDay * 100)}%` });
    EVALS.forEach(e => { if (d.evals[e] > 0) thin.append(el("div", { style: `flex:${d.evals[e]} 1 0;background:${col(e)}` })); });
    const h = el("div", { class: "cal-dh" + (d.date === today ? " today" : ""), role: "button", tabindex: "0", title: t("calDayTip") },
      el("div", { class: "wd" }, el("b", { text: d.weekday }), " " + d.date.slice(5).replace("-", "/")),
      el("div", { class: "tot", text: d.total > 0 ? fmt(d.total) : "—" }), thin,
      devs.length > 1 ? el("div", { class: "lanes-lbl", style: `grid-template-columns:repeat(${devs.length},1fr)` }, ...devs.map(v => el("span", { text: v }))) : null);
    const go = () => { state.view = "overview"; setDay(d.date); };
    h.addEventListener("click", go);
    h.addEventListener("keydown", e => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), go()));
    head.append(h);
  });
  const body = el("div", { class: "cal-body", style: `--hh:${hourH}px;height:${24 * hourH}px` });
  const gutter = el("div", { class: "cal-gutter" });
  for (let h = 1; h < 24; h++) gutter.append(el("span", { style: `top:${h * hourH}px`, text: `${String(h).padStart(2, "0")}:00` }));
  body.append(gutter);
  const dayCols = cal.days.map(d => {
    const dcol = el("div", { class: "cal-day" });
    const lanes = el("div", { class: "cal-lanes", style: `grid-template-columns:repeat(${devs.length},1fr)` });
    const laneEls = {};
    devs.forEach(v => { laneEls[v] = el("div", { class: "cal-lane" }); lanes.append(laneEls[v]); });
    dcol.append(lanes); body.append(dcol);
    return { t0: new Date(d.date + "T00:00").getTime(), laneEls, dcol };
  });
  const sep = t("sep");
  cal.blocks.forEach(b => {
    const s = new Date(b.start).getTime(), e = new Date(b.end).getTime();
    const dc = dayCols.find(x => s >= x.t0 && s < x.t0 + 86400000);
    if (!dc || !dc.laneEls[b.device]) return;
    const top = (s - dc.t0) / 3600000 * hourH, h = Math.max(3, (e - s) / 3600000 * hourH - 2);
    const blk = el("div", { class: "cal-block", style: `top:${top + 1}px;height:${h}px;background:${col(b.evaluation)};color:${onCol(b.evaluation)}` });
    if (h >= 15) blk.append(el("div", { class: "p", text: b.project }));
    if (h >= 30) blk.append(el("div", { class: "s", text: fmt((e - s) / 1000) }));
    const others = b.top_projects.length > 1 ? t("calProjects", { v: b.top_projects.map(([n, v]) => `${n} ${fmt(v)}`).join(sep) }) : "";
    const apps = t("calApps", { v: b.top_apps.map(([n, v]) => `${n} ${fmt(v)}`).join(sep) });
    hover(blk, ev => showTip(ev, `${hm(s)}–${hm(e)} · ${b.device} · ${b.project} (${t("calActual", { v: fmt(b.seconds) })})`, evalRows(b.evals, b.seconds),
      [[b.domain, b.subdomain].filter(Boolean).join(" / "), others, apps].filter(Boolean).join("\n")));
    dc.laneEls[b.device].append(blk);
  });
  const nowT = Date.now(), dcNow = dayCols.find(x => nowT >= x.t0 && nowT < x.t0 + 86400000);
  if (dcNow) dcNow.dcol.append(el("div", { class: "cal-now", style: `top:${(nowT - dcNow.t0) / 3600000 * hourH}px` }));
  const scroller = el("div", { class: "cal" }, head, body);
  c.append(scroller);
  const legend = el("div", { class: "legend", style: "margin-top:12px" });
  META.evaluations.slice(0, 4).forEach(({ name, desc }) => legend.append(el("div", { class: "item" }, el("span", { class: "sw", style: `background:${col(name)}` }), el("span", { text: name }), el("span", { class: "desc", text: (desc || "").split(/——| — /)[0] }))));
  c.append(legend);
  if (calScrolledWeek !== cal.week.start) {
    calScrolledWeek = cal.week.start;
    requestAnimationFrame(() => requestAnimationFrame(() => {  // after layout: put 07:00 just under the sticky day header
      const off = body.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      scroller.scrollTop = off + 7 * hourH - head.offsetHeight;
    }));
  } else if (renderCalendar._top != null) {
    requestAnimationFrame(() => { scroller.scrollTop = renderCalendar._top; });
  }
  scroller.addEventListener("scroll", () => { renderCalendar._top = scroller.scrollTop; });
  document.getElementById("updated").textContent = t("updated", { t: hm(cal.generated_at) });
}

// ---------- setup wizard ----------
const STEPS = ["stepWelcome", "stepChecks", "stepLook", "stepTag", "stepRules", "stepDone"];
const wiz = { step: 0, timer: null, edits: {} };

function renderSetup() {
  hideCards([...OVERVIEW_CARDS, "c-calendar", "c-pending"]);
  clearInterval(wiz.timer);
  const c = card("c-setup", t("wizard"), null);
  const nav = el("div", { class: "steps" });
  STEPS.forEach((s, i) => nav.append(el("button", { "aria-current": i === wiz.step ? "step" : null, class: i < wiz.step ? "done" : null, onclick: () => { wiz.step = i; renderSetup(); } }, `${i + 1}. ${t(s)}`)));
  const body = el("div", { class: "wiz-body" });
  c.append(nav, body);
  const navBtns = el("div", { class: "wiz-nav" });
  if (wiz.step > 0) navBtns.append(el("button", { class: "btn", onclick: () => { wiz.step--; renderSetup(); } }, t("back")));
  if (wiz.step < STEPS.length - 1) navBtns.append(el("button", { class: "btn primary", onclick: () => { wiz.step++; renderSetup(); } }, t("next")));
  [stepWelcome, stepChecks, stepLook, stepTag, stepRules, stepDone][wiz.step](body, navBtns);
  c.append(navBtns);
  document.getElementById("updated").textContent = "";
}

function stepWelcome(body) {
  body.append(el("h3", { text: t("welcomeTitle") }), el("p", { text: t("welcomeBody") }), el("p", { text: t("welcomePrivacy") }));
  body.append(el("div", { class: "note", text: t("evalIntro") }));
  const g = el("div", { class: "evals-intro" });
  META.evaluations.slice(0, 4).forEach(({ name, desc }) => g.append(el("div", { class: "tile" },
    el("div", { class: "k" }, el("span", { class: "sw", style: `background:${col(name)}` }), el("b", { text: name })), el("div", { class: "d", text: desc }))));
  body.append(g, el("p", { class: "note", style: "margin-top:14px", text: t("langNote") }));
}

function checkRow(state_, name, desc, actions = []) {
  const icon = { ok: "✓", todo: "!", wait: "…" }[state_];
  return el("div", { class: "check" },
    el("div", { class: `st ${state_}` }, el("i", { text: icon }), t(state_ === "ok" ? "ok" : state_ === "todo" ? "todo" : "waiting")),
    el("div", { class: "nm", text: name }), el("div", { class: "ds", text: desc }),
    actions.length ? el("div", { class: "acts" }, ...actions) : null);
}
const actBtn = (label, name) => el("button", { class: "btn", onclick: async e => { e.target.disabled = true; try { await post(name); } catch (err) { alertInline(e.target, err); } setTimeout(() => { e.target.disabled = false; }, 1500); } }, label);
function alertInline(node, err) { node.after(el("span", { class: "toast err", text: " " + err.message })); }

async function stepChecks(body, navBtns) {
  body.append(el("h3", { text: t("checksTitle") }), el("p", { text: t("checksNote") }));
  const list = el("div", { class: "checks" }, el("div", { class: "empty", text: "…" }));
  body.append(list);
  navBtns.prepend(el("button", { class: "btn", onclick: () => refresh() }, t("recheck")));
  async function refresh() {
    let s;
    try { s = await api("/api/setup/status"); } catch (e) { list.replaceChildren(el("div", { class: "err", text: e.message })); return; }
    const rows = [];
    rows.push(s.aw.ok ? checkRow("ok", t("chkAw"), t("chkAwOk", { v: s.aw.version || "" })) : checkRow("todo", t("chkAw"), t("chkAwNo"), [actBtn(t("openAw"), "open-aw")]));
    if (!s.mac.ok) rows.push(checkRow("todo", t("chkMac"), t("chkMacNo")));
    else {
      rows.push(checkRow(s.mac.fresh ? "ok" : "todo", t("chkMac"), s.mac.fresh ? t("chkMacOk", { t: hm(s.mac.last) }) : t("chkMacStale")));
      const p = Math.round((s.mac.title_ratio ?? 1) * 100);
      rows.push(checkRow(p > 30 ? "ok" : "todo", t("chkTitles"), p > 30 ? t("chkTitlesOk", { p }) : t("chkTitlesNo", { p }), p > 30 ? [] : [actBtn(t("openAccessibility"), "open-accessibility")]));
    }
    const imp = s.importer || {};
    const fdaActs = [actBtn(t("openFda"), "open-fda"), actBtn(t("revealHelper"), "reveal-helper")];
    if (imp.fda && imp.state === "running") rows.push(checkRow("ok", t("chkFda"), t("chkFdaOk")));
    else if (imp.state === "waiting-for-full-disk-access") rows.push(checkRow("todo", t("chkFda"), t("chkFdaNo"), fdaActs));
    else if (imp.state === "no-screen-time-sync") rows.push(checkRow("todo", t("chkFda"), t("chkSync")));
    else rows.push(checkRow("wait", t("chkFda"), t("chkNotStarted"), [actBtn(t("restartImporter"), "restart-importer"), ...fdaActs]));
    rows.push(s.ios.length ? checkRow("ok", t("chkIos"), t("chkIosOk", { d: s.ios.map(d => `${d.name} (${d.kind})`).join(t("sep")) })) : checkRow("wait", t("chkIos"), "—"));
    const down = Object.entries(s.services).filter(([, up]) => !up).map(([n]) => n);
    rows.push(checkRow(down.length ? "todo" : "ok", t("chkServices"), down.length ? t("chkServicesNo", { s: down.join(", ") }) : t("chkServicesOk")));
    list.replaceChildren(...rows);
  }
  refresh();
  wiz.timer = setInterval(refresh, 10000);
}

async function stepLook(body) {
  body.append(el("div", { class: "empty", text: "…" }));
  let f;
  try { f = await api("/api/setup/first-look?days=14"); } catch (e) { body.replaceChildren(el("div", { class: "err", text: e.message })); return; }
  body.replaceChildren(el("h3", { text: t("lookTitle", { n: f.days }) }),
    el("p", {}, el("b", { text: t("lookCoverage", { p: pct(f.coverage * f.total, f.total) }) }), " " + t("lookCoverageNote")));
  const cards = el("div", { class: "devcards" });
  f.devices.forEach(d => cards.append(el("div", { class: "devcard" },
    el("div", { class: "k", text: `${d.kind} · ${d.name}` }),
    el("div", { class: "v", text: t("lookPerDay", { v: fmt(d.per_day) }) }),
    el("div", { class: "meter", role: "img", "aria-label": pct(d.coverage * d.seconds, d.seconds) }, el("div", { style: `width:${Math.round(d.coverage * 100)}%` })),
    el("div", { class: "k", text: t("lookCoverage", { p: pct(d.coverage * d.seconds, d.seconds) }) }),
    el("div", { class: "k", style: "margin-top:8px", text: t("lookTopApps") }),
    el("ol", {}, ...d.top_apps.map(([a, s]) => el("li", { text: `${a} · ${fmt(s)}` }))))));
  body.append(cards);
}

function tagRow(g, domains, evals) {
  const isUnc = g.current.domain === META.uncategorized;
  const st = { dom: isUnc ? "" : g.current.domain, sub: isUnc ? "" : g.current.subdomain, ev: isUnc ? "" : g.current.evaluation,
               project: g.kind === "mac_context" ? g.keyword : "", keyword: g.keyword || "", ignore: false };
  const row = el("div", { class: "tagrow" });
  const markDirty = () => { wiz.edits[g.id] = { g, st }; row.classList.add("dirty"); updateSave(); };
  const kind = { ios_app: t("kindIos"), mac_app: t("kindMacApp"), mac_context: t("kindContext") }[g.kind];
  const who = el("div", { class: "who" }, el("div", { class: "lb", text: g.label }),
    el("div", { class: "mt", text: `${kind} · ${g.devices.join("+")} · ${fmt(g.seconds)} · ${t("tagNow", { v: [g.current.domain, g.current.subdomain, g.current.evaluation].filter(Boolean).join(" / ") })}` }),
    g.samples && g.samples.length ? el("div", { class: "smp", title: g.samples.join("\n"), text: t("tagSamples") + g.samples.join(" | ") }) : null);
  const domSel = el("select", { class: "ctl" }, el("option", { value: "", text: "—" }), ...Object.keys(domains).filter(d => d !== META.uncategorized).map(d => el("option", { value: d, text: d })));
  domSel.value = st.dom;
  const listId = "subs-" + Math.random().toString(36).slice(2);
  const subIn = el("input", { class: "ctl", list: listId, placeholder: t("subPlaceholder"), value: st.sub });
  const dl = el("datalist", { id: listId });
  const fillSubs = () => dl.replaceChildren(...(domains[domSel.value] || []).map(s => el("option", { value: s })));
  fillSubs();
  domSel.addEventListener("change", () => { st.dom = domSel.value; fillSubs(); markDirty(); });
  subIn.addEventListener("input", () => { st.sub = subIn.value; markDirty(); });
  const pick = el("div", { class: "evalpick", role: "group" });
  evals.forEach(e => {
    const b = el("button", { type: "button", "aria-pressed": String(st.ev === e) }, el("span", { class: "sw", style: `background:${col(e)}` }), e);
    b.addEventListener("click", () => { st.ev = e; pick.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b))); markDirty(); });
    pick.append(b);
  });
  const ctrls = el("div", { class: "ctrls" }, domSel, subIn, dl, pick);
  if (g.kind === "mac_context") {
    const kw = el("input", { class: "ctl", value: st.keyword, title: t("tagKeyword"), placeholder: t("tagKeyword") });
    kw.addEventListener("input", () => { st.keyword = kw.value; markDirty(); });
    ctrls.append(el("label", { class: "chk" }, t("tagKeyword"), kw));
  }
  const pj = el("input", { class: "ctl", value: st.project, placeholder: t("tagProject"), title: t("tagProject") });
  pj.addEventListener("input", () => { st.project = pj.value; markDirty(); });
  ctrls.append(el("label", { class: "chk" }, t("tagProject"), pj));
  if (g.kind !== "mac_context") {
    const ig = el("input", { type: "checkbox" });
    ig.addEventListener("change", () => { st.ignore = ig.checked; markDirty(); });
    ctrls.append(el("label", { class: "chk" }, ig, t("tagIgnore")));
  }
  row.append(who, ctrls);
  return row;
}

let updateSave = () => {};
async function stepTag(body) {
  wiz.edits = {};
  body.append(el("div", { class: "empty", text: "…" }));
  let c;
  try { c = await api("/api/setup/candidates?days=14"); } catch (e) { body.replaceChildren(el("div", { class: "err", text: e.message })); return; }
  const saveBtn = el("button", { class: "btn primary", disabled: true });
  const toast = el("span", { class: "toast" });
  updateSave = () => { const n = Object.keys(wiz.edits).length; saveBtn.disabled = n === 0; saveBtn.textContent = t("tagSaveN", { n }); };
  updateSave();
  saveBtn.addEventListener("click", async () => {
    const tags = Object.values(wiz.edits).map(({ g, st }) => st.ignore
      ? { kind: g.kind, bundle: g.bundle, app: g.app, ignore: true }
      : { kind: g.kind, bundle: g.bundle, app: g.app, apps: g.apps, keyword: st.keyword, domain: st.dom, subdomain: st.sub, evaluation: st.ev, project: st.project })
      .filter(x => x.ignore || (x.domain && x.evaluation));
    if (!tags.length) return;
    saveBtn.disabled = true; saveBtn.textContent = t("saving");
    try { const r = await post("tags", { tags }); toast.textContent = t("tagSavedN", { n: r.applied.length }); setTimeout(() => { wiz.step = 3; renderSetup(); }, 900); }
    catch (e) { toast.textContent = e.message; toast.className = "toast err"; updateSave(); }
  });
  body.replaceChildren(el("h3", { text: t("tagTitle") }), el("p", { text: t("tagNote") }));
  body.append(agentBox(() => { wiz.skipped = true; wiz.step = 4; renderSetup(); }));
  body.append(el("div", { class: "wiz-nav", style: "margin:0 0 10px" }, saveBtn, toast));
  body.append(el("h2", { style: "font-size:14px;margin:8px 0 0", text: `${t("tagNeed")} (${c.needs_tag.length})` }));
  const need = el("div", { class: "tagrows" });
  if (!c.needs_tag.length) need.append(el("div", { class: "empty", text: t("tagNone") }));
  c.needs_tag.forEach(g => need.append(tagRow(g, c.domains, c.evaluations)));
  body.append(need);
  if (c.review.length) {
    const det = el("details", { style: "margin-top:16px" }, el("summary", { text: `${t("tagReview")} (${c.review.length})` }));
    const rv = el("div", { class: "tagrows" });
    c.review.forEach(g => rv.append(tagRow(g, c.domains, c.evaluations)));
    det.append(rv); body.append(det);
  }
}

function stepRules(body) {
  const dr = META.duration_rules || {};
  body.append(el("h3", { text: t("rulesTitle") }), el("p", { text: t("rulesNote") }));
  const form = el("div", { class: "rules-form" });
  const gap = el("input", { class: "ctl", type: "number", min: "1", max: "60", step: "1", value: String(Math.round((dr.session_gap_seconds || 300) / 60)) });
  form.append(el("label", {}, el("span", { text: t("rulesGap") }), gap));
  const inputs = {};
  (dr.rules || []).forEach(r => {
    const i = el("input", { class: "ctl", type: "number", min: "1", max: "600", step: "1", value: String(r.over_minutes) });
    inputs[r.name] = i;
    form.append(el("label", {}, el("span", { text: t("rulesOver", { subs: r.subdomains.join(" / "), ev: r.evaluation }) }), i));
  });
  const toast = el("span", { class: "toast" });
  const save = el("button", { class: "btn primary" }, t("save"));
  save.addEventListener("click", async () => {
    try {
      await post("duration", { gap_minutes: +gap.value, thresholds: Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, +i.value])) });
      setMeta(await api("/api/meta")); toast.textContent = t("saved");
    } catch (e) { toast.textContent = e.message; toast.className = "toast err"; }
  });
  body.append(form, el("div", { class: "wiz-nav" }, save, toast));
}

function stepDone(body, navBtns) {
  body.append(el("h3", { text: t("doneTitle") }), el("p", { text: t("doneBody") }),
    el("div", { class: "nm", style: "font-weight:600", text: t("doneAgents") }), el("p", { text: t("doneAgentsBody") }), cmdRow("timetrace agent install"),
    el("div", { style: "font-weight:600;margin-top:14px", text: t("doneAgentTag") }), el("p", { text: t("doneAgentTagBody") }), cmdRow(AGENT_CMD),
    el("div", { style: "font-weight:600", text: t("doneAw") }), el("p", { text: t("doneAwBody") }), cmdRow("timetrace sync-aw"));
  navBtns.append(el("button", { class: "btn primary", onclick: async () => {
    try { await post("settings", { setup_done: true }); } catch (e) { /* stays usable */ }
    state.view = "overview"; load();
  } }, t("openDashboard")));
}

// ---------- state & loading ----------
const state = { view: "overview", range: "today", date: null, device: "all", slot: "15", calDate: null, heat: "all" };
let lastQuery = "";
function saveState() {
  try { localStorage.setItem("tt-dash", JSON.stringify(state)); } catch (e) {}
  const h = new URLSearchParams(lastQuery);
  if (state.view === "overview" && state.heat && state.heat !== "all") h.set("heat", state.heat);
  if (lastQuery) history.replaceState(null, "", "#" + h.toString());
}
function syncControls() {
  const calv = state.view === "calendar", setupv = state.view === "setup" || state.view === "phone";
  document.getElementById("filters").hidden = setupv;
  document.querySelectorAll("#views button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === state.view)));
  document.querySelectorAll("#ranges button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.r === state.range)));
  document.getElementById("ranges").hidden = calv;
  document.getElementById("thisweek").hidden = !calv;
  document.getElementById("slot").hidden = !calv;
  document.getElementById("slot").value = state.slot;
  deviceOptions();
  document.getElementById("prev").setAttribute("aria-label", t(calv ? "prevWeek" : "prevDay"));
  document.getElementById("next").setAttribute("aria-label", t(calv ? "nextWeek" : "nextDay"));
  if (calv) {
    document.getElementById("date").value = state.calDate || localDate(new Date());
    const nw = new Date((state.calDate || localDate(new Date())) + "T12:00"); nw.setDate(nw.getDate() + 7 - ((nw.getDay() + 6) % 7));
    document.getElementById("next").disabled = localDate(nw) > localDate(new Date());
    return;
  }
  const single = ["today", "yesterday", "day"].includes(state.range);
  const d = state.range === "today" ? new Date() : state.range === "yesterday" ? new Date(Date.now() - 86400000) : state.date ? new Date(state.date + "T12:00") : new Date();
  document.getElementById("date").value = single ? localDate(d) : "";
  document.getElementById("next").disabled = !single || state.range === "today";
}
async function load() {
  syncControls();
  clearTimeout(timer); clearInterval(wiz.timer);
  if (state.view === "setup") {
    if (!META) setMeta(await api("/api/meta"));
    history.replaceState(null, "", "#setup");
    renderSetup();
    return;
  }
  if (state.view === "phone") {
    if (!META) setMeta(await api("/api/meta"));
    history.replaceState(null, "", "#phone");
    renderPhone();
    return;
  }
  document.getElementById("app").classList.add("loading");
  let q, live;
  if (state.view === "calendar") {
    q = new URLSearchParams({ view: "calendar", device: state.device, slot: state.slot });
    if (state.calDate) q.set("date", state.calDate);
    try { cal = await api("/api/calendar?" + q); setMeta(cal.meta); } catch (e) { cal = { error: e.message }; }
    document.getElementById("app").classList.remove("loading");
    renderCalendar();
    live = !cal.error && new Date(cal.week.end).getTime() > Date.now();
  } else {
    q = new URLSearchParams({ range: state.range, device: state.device });
    if (state.range === "day") q.set("date", state.date);
    try { data = await api("/api/data?" + q); setMeta(data.meta); } catch (e) { data = { error: e.message }; }
    document.getElementById("app").classList.remove("loading");
    render();
    live = state.range === "today";
  }
  lastQuery = q.toString();
  saveState();
  if (live) timer = setTimeout(load, 5 * 60 * 1000);
}
function setDay(dateStr) {
  const today = localDate(new Date()), yest = localDate(new Date(Date.now() - 86400000));
  if (dateStr >= today) { state.range = "today"; state.date = null; }
  else if (dateStr === yest) { state.range = "yesterday"; state.date = null; }
  else { state.range = "day"; state.date = dateStr; }
  load();
}
const addDays = (s, n) => { const d = new Date(s + "T12:00"); d.setDate(d.getDate() + n); return localDate(d); };
document.querySelectorAll("#views button").forEach(b => b.addEventListener("click", () => {
  if (state.view === b.dataset.v) return;
  state.view = b.dataset.v;
  if (state.view === "calendar") state.calDate = state.range === "day" ? state.date : state.range === "yesterday" ? addDays(localDate(new Date()), -1) : null;
  load();
}));
document.querySelectorAll("#ranges button").forEach(b => b.addEventListener("click", () => { state.range = b.dataset.r; state.date = null; load(); }));
document.getElementById("thisweek").addEventListener("click", () => { state.calDate = null; load(); });
document.getElementById("slot").addEventListener("change", e => { state.slot = e.target.value; load(); });
document.getElementById("date").addEventListener("change", e => {
  if (!e.target.value) return;
  if (state.view === "calendar") { state.calDate = e.target.value; load(); } else setDay(e.target.value);
});
document.getElementById("device").addEventListener("change", e => { state.device = e.target.value; load(); });
const shift = n => {
  if (state.view === "calendar") { const x = addDays(state.calDate || localDate(new Date()), 7 * n); state.calDate = x >= localDate(new Date()) ? null : x; load(); return; }
  setDay(addDays(document.getElementById("date").value || localDate(new Date()), n));
};
document.getElementById("prev").addEventListener("click", () => shift(-1));
document.getElementById("next").addEventListener("click", () => shift(1));
document.getElementById("setupBtn").addEventListener("click", () => { state.view = "setup"; wiz.step = 0; load(); });
document.getElementById("phoneBtn").addEventListener("click", () => { state.view = "phone"; load(); });
document.querySelectorAll("#langs button").forEach(b => b.addEventListener("click", async () => {
  if (b.dataset.l === LANG) return;
  if (!window.TT_READONLY) try { await post("settings", { lang: b.dataset.l }); } catch (e) { /* still switch locally */ }
  LANG = b.dataset.l; if (META) META.lang = LANG; applyStatic(); syncControls();
  if (state.view === "setup") renderSetup(); else if (state.view === "calendar") { calScrolledWeek = null; load(); } else load();
}));
let rz; window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (state.view === "calendar") cal && !cal.error && renderCalendar(); else if (state.view === "overview") data && render(); }, 150); });

(async function boot() {
  try { Object.assign(state, JSON.parse(localStorage.getItem("tt-dash") || "{}")); } catch (e) {}
  if (state.view === "setup" || state.view === "phone") state.view = "overview";
  try { setMeta(await api("/api/meta")); } catch (e) { /* load() will show the error */ }
  LANG = META ? META.lang : (navigator.language || "en").startsWith("zh") ? "zh" : "en";
  applyStatic();
  const hp = new URLSearchParams(location.hash.slice(1));
  const rw = !window.TT_READONLY;  // a phone link gets the overview and calendar only
  if (rw && location.hash.startsWith("#phone")) state.view = "phone";
  else if (rw && (location.hash.startsWith("#setup") || (META && !META.setup_done && !location.hash))) {
    state.view = "setup";
    const n = parseInt(location.hash.split("/")[1], 10);  // #setup/4 opens step 4
    if (n >= 1 && n <= STEPS.length) wiz.step = n - 1;
  }
  else if (hp.get("view") === "calendar") { state.view = "calendar"; state.calDate = hp.get("date"); if (hp.get("slot")) state.slot = hp.get("slot"); }
  else if (hp.get("range")) { state.view = "overview"; state.range = hp.get("range"); state.date = hp.get("date"); }
  if (hp.get("device")) state.device = hp.get("device");
  if (hp.get("heat")) state.heat = hp.get("heat");
  if (state.range === "day" && !state.date) state.range = "today";
  load();
})();
