"use strict";

const PAGE_DUP = 20;
const PAGE_DAYS = 10;

const S = {
  tab: "dup",
  status: null,
  dup: { groups: [], total: 0, open: 0, keep: {}, sel: new Set(), includeDone: false, loaded: false },
  loc: { days: [], totalDays: 0, sel: new Set(), hours: null, only: false, loaded: false, info: null },
  tags: { rules: [], sel: new Set(), loaded: false, error: null, warnings: [] },
};

/* ------------------------------------------------------------ Hilfen */
const $ = (sel) => document.querySelector(sel);

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "disabled") el[k] = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

class ApiError extends Error {
  constructor(message, details) { super(message); this.details = details || []; }
}

async function api(path, options = {}) {
  const opts = { headers: { Accept: "application/json" }, ...options };
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, opts);
  let data = null;
  try { data = await resp.json(); } catch (_) { /* leer */ }
  if (!resp.ok) {
    let msg = (data && (data.fehler || data.detail)) || `Fehler ${resp.status}`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg || JSON.stringify(d)).join("; ");
    throw new ApiError(msg, data && data.details);
  }
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = isError ? "err" : ""; }, isError ? 6000 : 3500);
}

function fmtDateTime(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtDay(day) {
  if (!day) return "Ohne Datum";
  const d = new Date(day + "T12:00:00");
  return d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
}

function fmtTaken(s) { return s ? s.slice(8, 10) + "." + s.slice(5, 7) + "." + s.slice(0, 4) + " " + s.slice(11, 16) : "ohne Datum"; }
function fmtTime(s) { return s ? s.slice(11, 16) : ""; }
function n(count, one, many) { return `${count} ${count === 1 ? one : many}`; }
function fmtSize(b) { return b ? (b / 1048576).toFixed(1).replace(".", ",") + " MB" : ""; }

function thumb(m, alt) {
  return h("img", { src: m.thumb || ("thumb/" + m.id), loading: "lazy", decoding: "async", alt: alt || m.dateiname || "" });
}

function busy(btn, on) {
  btn.disabled = on;
  btn.classList.toggle("busy", on);
}

function confirmDialog({ title, body, okLabel = "OK", danger = false, checkLabel = null }) {
  const dlg = $("#confirm");
  $("#confirm-title").textContent = title;
  const b = $("#confirm-body");
  b.replaceChildren(...(Array.isArray(body) ? body : [body]));
  const ok = $("#confirm-ok");
  ok.textContent = okLabel;
  ok.className = "btn " + (danger ? "danger" : "primary");
  const wrap = $("#confirm-check-wrap");
  const check = $("#confirm-check");
  check.checked = false;
  if (checkLabel) {
    wrap.hidden = false;
    $("#confirm-check-label").textContent = checkLabel;
    ok.disabled = true;
    check.onchange = () => { ok.disabled = !check.checked; };
  } else {
    wrap.hidden = true;
    ok.disabled = false;
  }
  return new Promise((resolve) => {
    dlg.onclose = () => resolve(dlg.returnValue === "ok");
    dlg.returnValue = "";
    dlg.showModal();
  });
}

/* ------------------------------------------------------------ Status */
async function loadStatus(server = true) {
  try {
    const prev = S.status;
    S.status = await api("api/status?server=" + server);
    if (!server && prev && prev.server) S.status.server = prev.server;
  } catch (e) {
    $("#status").textContent = "Status nicht verfügbar: " + e.message;
    return;
  }
  const st = S.status;
  const parts = [];
  if (st.bibliothek) parts.push("Stand " + fmtDateTime(st.bibliothek.stand), st.bibliothek.gesamt + " Medien");
  else parts.push("Noch nicht eingelesen");
  if (st.server && st.server.version) parts.push("Immich " + st.server.version);
  parts.push(st.benutzer.join(" & "));
  $("#status").textContent = parts.join(" · ");

  const warns = [...(st.warnungen || [])];
  if (st.letzter_fehler) warns.push(st.letzter_fehler);
  if (st.server) {
    if (!st.server.erreichbar) warns.push("Immich ist nicht erreichbar (" + st.immich_url + ")");
    for (const [name, k] of Object.entries(st.server.schluessel || {})) {
      if (!k.ok) warns.push("API-Key " + name + ": " + k.fehler);
    }
  }
  $("#warnings").replaceChildren(...warns.map((w) => h("div", { class: "banner warn" }, w)));
  if (S.loc.hours === null) {
    S.loc.hours = st.ort_max_stunden;
    $("#loc-hours").value = st.ort_max_stunden;
  }
}

async function rescan() {
  const btn = $("#scan-btn");
  busy(btn, true);
  try {
    const r = await api("api/scan", { method: "POST", body: { wait: true } });
    toast(`${r.gesamt} Medien in ${r.dauer_s.toFixed(1).replace(".", ",")} s eingelesen`);
    S.dup.loaded = S.loc.loaded = S.tags.loaded = false;
    await loadStatus(false);
    await loadTab(S.tab, true);
    loadOtherCounts();
  } catch (e) {
    toast("Einlesen fehlgeschlagen: " + e.message, true);
  } finally {
    busy(btn, false);
  }
}

/* --------------------------------------------------------- Duplikate */
async function loadDuplicates(reset) {
  const d = S.dup;
  if (reset) { d.groups = []; d.sel.clear(); d.keep = {}; $("#dup-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const r = await api(`api/duplicates?offset=${d.groups.length}&limit=${PAGE_DUP}&include_done=${d.includeDone}`);
  if (reset) $("#dup-list").replaceChildren();
  d.total = r.gesamt; d.open = r.offen; d.loaded = true;
  for (const g of r.gruppen) {
    d.groups.push(g);
    $("#dup-list").append(renderGroup(g));
  }
  if (!d.groups.length) $("#dup-list").replaceChildren(h("p", { class: "empty" }, "Keine Duplikate gefunden 🎉"));
  $("#dup-summary").textContent = `${r.offen} offen · ${r.gesamt} Gruppen · ${r.benutzeruebergreifend} benutzerübergreifend`;
  $("#count-dup").textContent = r.offen ? `(${r.offen})` : "";
  $("#dup-more").hidden = d.groups.length >= d.total;
  updateActionbar();
}

const SOURCE_LABEL = { immich: "Immich", pruefsumme: "Prüfsumme", name_zeit: "Name + Zeit" };

function renderGroup(g) {
  const d = S.dup;
  const keep = d.keep[g.id] || g.behalten;
  const card = h("article", { class: "card" + (d.sel.has(g.id) ? " selected" : ""), "data-group": g.id });
  const head = h("div", { class: "card-head" },
    h("label", {}, h("input", {
      type: "checkbox", checked: d.sel.has(g.id),
      onchange: (e) => { e.target.checked ? d.sel.add(g.id) : d.sel.delete(g.id); card.classList.toggle("selected", e.target.checked); updateActionbar(); },
    }), `${g.medien.length} Kopien`),
    ...g.quellen.map((q) => h("span", { class: "chip" }, SOURCE_LABEL[q] || q)),
    g.benutzeruebergreifend ? h("span", { class: "chip accent" }, g.benutzer.join(" + ")) : null,
    g.erledigt ? h("span", { class: "chip ok" }, "erledigt") : null,
  );
  const grid = h("div", { class: "grid" });
  for (const m of g.medien) {
    const isKeep = m.id === keep;
    const badge = isKeep ? "★ bleibt" : (m.im_pruef_album ? "im Prüf-Album" : "weg");
    grid.append(h("button", {
      type: "button", class: "tile " + (isKeep ? "keep" : "drop"),
      "aria-pressed": isKeep ? "true" : "false",
      title: m.pfad,
      onclick: () => {
        d.keep[g.id] = m.id;
        d.sel.add(g.id);
        card.replaceWith(renderGroup(g));
        updateActionbar();
      },
    },
    thumb(m),
    h("span", { class: "badge" }, badge),
    h("div", { class: "meta" },
      h("div", { class: "name" }, m.dateiname),
      h("div", {}, `${m.benutzer} · ${m.extern ? "extern" : "Upload"}${m.typ === "video" ? " · Video" : ""}`),
      h("div", {}, fmtTaken(m.aufnahme)),
      h("div", {}, [m.breite && m.hoehe ? `${m.breite}×${m.hoehe}` : "", fmtSize(m.groesse)].filter(Boolean).join(" · ")),
      h("div", { class: "muted" }, `${m.punkte} P.` + (m.gruende.length ? " · " + m.gruende.join(", ") : "")),
    )));
  }
  card.append(head, grid);
  return card;
}

function selectedGroups() {
  return [...S.dup.sel].map((id) => ({ id, keep: S.dup.keep[id] || (S.dup.groups.find((g) => g.id === id) || {}).behalten }));
}

async function applyDuplicates(action, btn) {
  const groups = selectedGroups();
  if (!groups.length) return;
  busy(btn, true);
  let plan;
  try {
    plan = await api("api/duplicates/apply", { method: "POST", body: { action, groups, dry_run: true } });
  } catch (e) {
    toast(e.message, true); busy(btn, false); return;
  }
  busy(btn, false);
  const album = S.status ? S.status.pruef_album : "Duplikat-Prüfung";
  const items = [];
  if (plan.papierkorb) items.push(h("li", {}, h("b", {}, plan.papierkorb), " in den Papierkorb (nur Uploads, 30 Tage wiederherstellbar)"));
  if (plan.album) items.push(h("li", {}, h("b", {}, plan.album), ` ins Album „${album}“`));
  if (plan.keine) items.push(h("li", {}, plan.keine, " unverändert (schon im Prüf-Album)"));
  const reasons = [...new Set(plan.schritte.filter((s) => s.aktion === "album" && s.grund !== "Kopie").map((s) => s.grund))];
  const body = [h("p", {}, `${plan.gruppen} Gruppe(n):`), h("ul", {}, items)];
  if (action === "papierkorb" && reasons.length) body.push(h("p", { class: "muted" }, "Statt Papierkorb ins Prüf-Album: " + reasons.join("; ")));
  if (!plan.papierkorb && !plan.album) { toast("Nichts zu tun – alles schon erledigt."); return; }
  const trash = action === "papierkorb" && plan.papierkorb > 0;
  const ok = await confirmDialog({
    title: trash ? "In den Papierkorb verschieben?" : "Ins Prüf-Album legen?",
    body,
    okLabel: trash ? "Papierkorb" : "Ins Album",
    danger: trash,
    checkLabel: trash ? `Ja, ${n(plan.papierkorb, "Medium", "Medien")} in den Papierkorb verschieben` : null,
  });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/duplicates/apply", { method: "POST", body: { action, groups, confirm: trash ? "PAPIERKORB" : null } });
    const e = r.ergebnis;
    toast(`Erledigt: ${e.papierkorb} im Papierkorb, ${e.album} im Prüf-Album` + (e.fehler.length ? `, ${e.fehler.length} Fehler` : ""), e.fehler.length > 0);
    await loadDuplicates(true);
    loadStatus(false);
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

/* ---------------------------------------------------------- Ohne Ort */
async function loadLocation(reset) {
  const l = S.loc;
  if (reset) { l.days = []; l.sel.clear(); $("#loc-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const params = new URLSearchParams({ offset: l.days.length, limit: PAGE_DAYS, only_suggestions: l.only });
  if (l.hours) params.set("max_hours", l.hours);
  const r = await api("api/no-location?" + params);
  if (reset) $("#loc-list").replaceChildren();
  l.totalDays = r.tage_gesamt; l.loaded = true; l.info = r;
  for (const day of r.tage) {
    l.days.push(day);
    $("#loc-list").append(renderDay(day));
  }
  if (!l.days.length) $("#loc-list").replaceChildren(h("p", { class: "empty" }, "Alle Medien haben einen Ort 🎉"));
  $("#loc-summary").textContent = `${r.medien} Medien ohne Ort an ${r.tage_gesamt} Tagen · ${r.mit_vorschlag} mit Vorschlag` +
    (r.extern_erlaubt ? "" : " · externe Bibliotheken gesperrt");
  $("#count-loc").textContent = r.mit_vorschlag ? `(${r.mit_vorschlag})` : "";
  $("#loc-more").hidden = l.days.length >= l.totalDays;
  updateActionbar();
}

function selectable(m) { return m.vorschlag && m.aenderbar; }

function renderDay(day) {
  const l = S.loc;
  const sec = h("section", { class: "card" });
  const pick = day.medien.filter(selectable);
  const allBtn = h("button", {
    type: "button", class: "btn small", disabled: !pick.length,
    onclick: () => {
      const all = pick.every((m) => l.sel.has(m.id));
      pick.forEach((m) => (all ? l.sel.delete(m.id) : l.sel.add(m.id)));
      sec.replaceWith(renderDay(day));
      updateActionbar();
    },
  }, pick.length && pick.every((m) => l.sel.has(m.id)) ? "Keine" : "Alle");
  sec.append(h("div", { class: "day-head" },
    h("div", {}, h("h2", {}, fmtDay(day.datum)), h("span", { class: "muted" }, `${n(day.anzahl, "Medium", "Medien")} · ${n(day.mit_vorschlag, "Vorschlag", "Vorschläge")}`)),
    allBtn));
  const grid = h("div", { class: "grid" });
  for (const m of day.medien) {
    const v = m.vorschlag;
    const can = selectable(m);
    const sel = l.sel.has(m.id);
    let info;
    if (v && !m.aenderbar) info = h("div", { class: "nosug" }, `📍 ${v.ort || "Ort"} · extern gesperrt`);
    else if (v) info = h("div", { class: "sug" }, `📍 ${v.ort || v.breite.toFixed(4) + ", " + v.laenge.toFixed(4)}`, h("br"), `${v.abstand_text} Abstand · ${v.quelle_benutzer}`);
    else info = h("div", { class: "nosug" }, "kein Foto mit GPS im Zeitfenster");
    grid.append(h("button", {
      type: "button", class: "tile" + (can ? "" : " locked") + (sel ? " selected" : ""), "aria-pressed": sel ? "true" : "false",
      title: m.pfad,
      onclick: () => {
        if (!can) return;
        sel ? l.sel.delete(m.id) : l.sel.add(m.id);
        sec.replaceWith(renderDay(day));
        updateActionbar();
      },
    },
    thumb(m),
    can ? h("span", { class: "check" + (sel ? " on" : ""), "aria-hidden": "true" }, sel ? "✓" : "") : null,
    h("div", { class: "meta" },
      h("div", { class: "name" }, m.dateiname),
      h("div", {}, `${fmtTime(m.aufnahme)} · ${m.benutzer}${m.extern ? " · extern" : ""}`),
      info)));
  }
  sec.append(grid);
  return sec;
}

async function applyLocation(btn) {
  const ids = [...S.loc.sel];
  if (!ids.length) return;
  const places = new Map();
  for (const d of S.loc.days) for (const m of d.medien) if (S.loc.sel.has(m.id)) {
    const k = m.vorschlag.ort || "Koordinaten";
    places.set(k, (places.get(k) || 0) + 1);
  }
  const ok = await confirmDialog({
    title: "Ort übernehmen?",
    body: [h("p", {}, `${ids.length} Medien erhalten die Koordinaten des zeitlich nächsten Fotos:`),
      h("ul", {}, [...places].map(([k, n]) => h("li", {}, `${k}: ${n}`)))],
    okLabel: "Übernehmen",
  });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/no-location/apply", { method: "POST", body: { ids, max_hours: S.loc.hours } });
    toast(`Ort für ${r.aktualisiert} Medien übernommen` + (r.uebersprungen.length ? `, ${r.uebersprungen.length} übersprungen` : ""));
    await loadLocation(true);
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

/* -------------------------------------------------------------- Tags */
const COND_LABEL = { pfad: "Pfad", dateiname: "Dateiname", von: "von", bis: "bis", album: "Album", person: "Person",
  hersteller: "Hersteller", modell: "Modell", bibliothek: "Bibliothek", typ: "Typ", benutzer: "Benutzer" };

async function loadTags() {
  const t = S.tags;
  t.sel.clear();
  $("#tags-list").replaceChildren(h("p", { class: "empty" }, "Lade …"));
  $("#tags-errors").replaceChildren();
  try {
    const r = await api("api/tags");
    t.rules = r.regeln; t.warnings = r.warnungen; t.error = null;
    $("#tags-file").textContent = r.regeldatei;
  } catch (e) {
    t.rules = []; t.error = e;
  }
  t.loaded = true;
  renderTags();
}

function renderTags() {
  const t = S.tags;
  const boxes = [];
  if (t.error) {
    boxes.push(h("div", { class: "banner err" }, h("b", {}, t.error.message),
      t.error.details.length ? h("ul", {}, t.error.details.map((d) => h("li", {}, d))) : null));
  }
  if (t.warnings.length) boxes.push(h("div", { class: "banner warn" }, h("ul", {}, t.warnings.map((w) => h("li", {}, w)))));
  $("#tags-errors").replaceChildren(...boxes);
  const list = $("#tags-list");
  list.replaceChildren();
  if (!t.rules.length && !t.error) list.append(h("p", { class: "empty" }, "Keine Regeln definiert."));
  let totalNew = 0;
  for (const r of t.rules) {
    totalNew += r.neu || 0;
    const card = h("article", { class: "card" + (t.sel.has(r.name) ? " selected" : "") });
    const cond = Object.entries(r.bedingungen).map(([k, v]) => `${COND_LABEL[k] || k}: ${Array.isArray(v) ? v.join(", ") : v}`).join(" · ");
    card.append(
      h("div", { class: "card-head" },
        h("label", {}, h("input", {
          type: "checkbox", checked: t.sel.has(r.name), disabled: !r.aktiv || !r.neu,
          onchange: (e) => { e.target.checked ? t.sel.add(r.name) : t.sel.delete(r.name); card.classList.toggle("selected", e.target.checked); updateActionbar(); },
        }), r.name),
        r.aktiv ? null : h("span", { class: "chip" }, "inaktiv"),
        ...r.tags.map((tag) => h("span", { class: "chip accent" }, "🏷 " + tag))),
      h("div", { class: "cond" }, cond),
    );
    if (r.aktiv) {
      card.append(h("div", { class: "stats" },
        h("span", {}, h("b", {}, r.treffer), " Treffer"),
        h("span", {}, h("b", {}, r.schon_getaggt), " schon getaggt"),
        h("span", { class: r.neu ? "sug" : "" }, h("b", {}, r.neu), " neu")),
        h("div", { class: "muted" }, Object.entries(r.benutzer).map(([u, c]) => `${u}: ${c.neu} neu von ${c.treffer}`).join(" · ")));
      if (r.beispiele.length) card.append(h("div", { class: "strip" }, r.beispiele.map((m) => thumb(m))));
    }
    list.append(card);
  }
  $("#count-tags").textContent = totalNew ? `(${totalNew})` : "";
  updateActionbar();
}

async function applyTags(btn) {
  const names = [...S.tags.sel];
  if (!names.length) return;
  const rules = S.tags.rules.filter((r) => S.tags.sel.has(r.name));
  const ok = await confirmDialog({
    title: "Tags anwenden?",
    body: [h("p", {}, "Tags werden nur ergänzt, nie entfernt."),
      h("ul", {}, rules.map((r) => h("li", {}, `${r.name}: ${r.neu} Medien → ${r.tags.join(", ")}`)))],
    okLabel: "Anwenden",
  });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/tags/apply", { method: "POST", body: { rules: names } });
    toast(`${r.getaggt} Medien getaggt`);
    await loadTags();
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

/* ------------------------------------------------------ Aktionsleiste */
function updateActionbar() {
  const info = $("#ab-info");
  const buttons = [];
  if (S.tab === "dup") {
    const cnt = S.dup.sel.size;
    const open = S.dup.groups.filter((g) => !g.erledigt);
    info.textContent = cnt ? `${cnt} gewählt` : "Nichts gewählt";
    const allSel = open.length && open.every((g) => S.dup.sel.has(g.id));
    buttons.push(h("button", { class: "btn small", type: "button", disabled: !open.length, onclick: () => {
      open.forEach((g) => (allSel ? S.dup.sel.delete(g.id) : S.dup.sel.add(g.id)));
      $("#dup-list").replaceChildren(...S.dup.groups.map(renderGroup));
      updateActionbar();
    } }, allSel ? "Keine" : "Alle"));
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !cnt, onclick: (e) => applyDuplicates("album", e.currentTarget) }, "Ins Prüf-Album"));
    buttons.push(h("button", { class: "btn small danger", type: "button", disabled: !cnt, onclick: (e) => applyDuplicates("papierkorb", e.currentTarget) }, "Papierkorb"));
  } else if (S.tab === "loc") {
    const cnt = S.loc.sel.size;
    info.textContent = cnt ? n(cnt, "Medium", "Medien") + " gewählt" : "Bilder mit 📍 antippen";
    const all = S.loc.days.flatMap((d) => d.medien).filter(selectable);
    const allSel = all.length && all.every((m) => S.loc.sel.has(m.id));
    buttons.push(h("button", { class: "btn small", type: "button", disabled: !all.length, onclick: () => {
      all.forEach((m) => (allSel ? S.loc.sel.delete(m.id) : S.loc.sel.add(m.id)));
      $("#loc-list").replaceChildren(...S.loc.days.map(renderDay));
      updateActionbar();
    } }, allSel ? "Keine" : "Alle"));
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !cnt, onclick: (e) => applyLocation(e.currentTarget) }, "Ort übernehmen"));
  } else {
    const cnt = S.tags.sel.size;
    const total = S.tags.rules.filter((r) => S.tags.sel.has(r.name)).reduce((a, r) => a + (r.neu || 0), 0);
    info.textContent = cnt ? `${n(cnt, "Regel", "Regeln")} · ${n(total, "Medium", "Medien")}` : "Regeln anhaken";
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !cnt, onclick: (e) => applyTags(e.currentTarget) }, "Tags anwenden"));
  }
  $("#ab-buttons").replaceChildren(...buttons);
}

/* -------------------------------------------------------------- Tabs */
const inflight = {};
function loadTab(tab, force = false) {
  if (inflight[tab] && !force) return inflight[tab];
  const p = (inflight[tab] || Promise.resolve())
    .then(() => doLoadTab(tab, force))
    .finally(() => { if (inflight[tab] === p) delete inflight[tab]; });
  inflight[tab] = p;
  return p;
}

async function doLoadTab(tab, force) {
  try {
    if (tab === "dup" && (force || !S.dup.loaded)) await loadDuplicates(true);
    if (tab === "loc" && (force || !S.loc.loaded)) await loadLocation(true);
    if (tab === "tags" && (force || !S.tags.loaded)) await loadTags();
  } catch (e) {
    const target = { dup: "#dup-list", loc: "#loc-list", tags: "#tags-list" }[tab];
    $(target).replaceChildren(h("div", { class: "banner err" }, "Laden fehlgeschlagen: " + e.message));
  }
  updateActionbar();
}

function showTab(tab) {
  S.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"));
  document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== "tab-" + tab; });
  try { localStorage.setItem("pflege-tab", tab); } catch (_) { /* egal */ }
  updateActionbar();
  loadTab(tab);
}

function loadOtherCounts() {
  for (const t of ["dup", "loc", "tags"]) if (t !== S.tab) loadTab(t).then(updateActionbar);
}

/* ------------------------------------------------------------- Start */
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#scan-btn").addEventListener("click", rescan);
$("#dup-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadDuplicates(false).finally(() => busy(e.currentTarget, false)); });
$("#loc-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadLocation(false).finally(() => busy(e.currentTarget, false)); });
$("#dup-done").addEventListener("change", (e) => { S.dup.includeDone = e.target.checked; loadTab("dup", true); });
$("#loc-only").addEventListener("change", (e) => { S.loc.only = e.target.checked; loadTab("loc", true); });
$("#loc-hours").addEventListener("change", (e) => {
  const v = parseFloat(String(e.target.value).replace(",", "."));
  if (v > 0 && v <= 48) { S.loc.hours = v; loadTab("loc", true); } else { e.target.value = S.loc.hours; }
});
$("#tags-reload").addEventListener("click", () => loadTab("tags", true));

(async function init() {
  let tab = "dup";
  try { tab = localStorage.getItem("pflege-tab") || "dup"; } catch (_) { /* egal */ }
  await loadStatus(true);
  showTab(["dup", "loc", "tags"].includes(tab) ? tab : "dup");
  // Nach dem ersten Laden (ggf. Einlesen) Status aktualisieren und Zähler der anderen Tabs holen
  await loadTab(S.tab);
  loadStatus(false);
  loadOtherCounts();
})();
