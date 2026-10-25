"use strict";

const PAGE_DUP = 20;
const PAGE_DAYS = 10;

const S = {
  tab: "dup",
  status: null,
  dup: { groups: [], total: 0, open: 0, keep: {}, sel: new Set(), includeDone: false, loaded: false },
  loc: { days: [], totalDays: 0, sel: new Set(), hours: null, only: false, loaded: false, info: null },
  tags: { rules: [], sel: new Set(), loaded: false, error: null, warnings: [], items: [], fileErrors: [], users: [], yaml: "" },
  set: { data: null, loaded: false },
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
  constructor(message, details, status, setup) { super(message); this.details = details || []; this.status = status; this.setup = !!setup; }
}

async function api(path, options = {}) {
  const opts = { headers: { Accept: "application/json", "X-Requested-With": "pflege" }, ...options };
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const resp = await fetch(path, opts);
  let data = null;
  try { data = await resp.json(); } catch (_) { /* leer */ }
  if (resp.status === 401 && data && data.anmeldung) {
    // Sitzung abgelaufen oder abgemeldet: zur Anmeldeseite und danach hierher zurück
    location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
    throw new ApiError("Anmeldung erforderlich", [], 401);
  }
  if (!resp.ok) {
    let msg = (data && (data.fehler || data.detail)) || `Fehler ${resp.status}`;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg || JSON.stringify(d)).join("; ");
    throw new ApiError(msg, data && data.details, resp.status, data && data.einrichtung);
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
  if (st.auto_einlesen && st.auto_einlesen.modus !== "aus" && st.auto_einlesen.naechstes) {
    const nx = new Date(st.auto_einlesen.naechstes);
    parts.push("auto " + nx.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }));
  }
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
const COND_KEYS = ["von", "bis", "bibliothek", "typ", "album", "person", "hersteller", "modell", "dateiname", "pfad", "benutzer"];

function asList(v) { return v === undefined || v === null || v === "" ? [] : (Array.isArray(v) ? v : [v]); }
function ruleTags(item) { return asList(item.tags !== undefined ? item.tags : item.tag).map(String); }

async function loadTags() {
  const t = S.tags;
  t.sel.clear();
  $("#tags-list").replaceChildren(h("p", { class: "empty" }, "Lade …"));
  $("#tags-errors").replaceChildren();
  const ed = await api("api/rules");
  t.items = ed.regeln || []; t.fileErrors = ed.fehler || []; t.users = ed.benutzer || []; t.yaml = ed.yaml || "";
  t.rules = []; t.warnings = []; t.error = null;
  if (!t.fileErrors.length && t.items.length) {
    try {
      const r = await api("api/tags");
      t.rules = r.regeln; t.warnings = r.warnungen;
    } catch (e) {
      t.error = e;
    }
  }
  t.loaded = true;
  renderTags();
}

function renderTags() {
  const t = S.tags;
  const boxes = [];
  if (t.fileErrors.length) {
    boxes.push(h("div", { class: "banner err" }, h("b", {}, "Die Regeln enthalten Fehler – bitte korrigieren:"),
      h("ul", {}, t.fileErrors.map((d) => h("li", {}, d)))));
  }
  if (t.error) boxes.push(h("div", { class: "banner err" }, "Vorschau nicht möglich: " + t.error.message));
  if (t.warnings.length) boxes.push(h("div", { class: "banner warn" }, h("ul", {}, t.warnings.map((w) => h("li", {}, w)))));
  $("#tags-errors").replaceChildren(...boxes);
  const list = $("#tags-list");
  list.replaceChildren();
  if (!t.items.length && !t.fileErrors.length) {
    list.append(h("div", { class: "empty" }, h("p", {}, "Noch keine Regeln."),
      h("p", {}, "Lege mit „+ Neue Regel“ eine an oder übernimm die Beispiele.")));
  }
  let totalNew = 0;
  t.items.forEach((item, idx) => {
    const r = t.rules.find((x) => x.name === item.name);
    const name = item.name || `Regel ${idx + 1}`;
    const aktiv = item.aktiv !== false;
    totalNew += (r && r.neu) || 0;
    const card = h("article", { class: "card" + (t.sel.has(name) ? " selected" : "") });
    const cond = COND_KEYS.filter((k) => item[k] !== undefined).map((k) => `${COND_LABEL[k]}: ${asList(item[k]).join(", ")}`).join(" · ");
    card.append(
      h("div", { class: "card-head" },
        h("label", {}, h("input", {
          type: "checkbox", checked: t.sel.has(name), disabled: !r || !r.aktiv || !r.neu,
          onchange: (e) => { e.target.checked ? t.sel.add(name) : t.sel.delete(name); card.classList.toggle("selected", e.target.checked); updateActionbar(); },
        }), name),
        aktiv ? null : h("span", { class: "chip" }, "inaktiv"),
        ...ruleTags(item).map((tag) => h("span", { class: "chip accent" }, "🏷 " + tag)),
        h("button", { type: "button", class: "btn small edit", onclick: () => openRule(idx) }, "Bearbeiten")),
      h("div", { class: "cond" }, cond || "keine Bedingung"),
    );
    if (r && r.aktiv) {
      card.append(h("div", { class: "stats" },
        h("span", {}, h("b", {}, r.treffer), " Treffer"),
        h("span", {}, h("b", {}, r.schon_getaggt), " schon getaggt"),
        h("span", { class: r.neu ? "sug" : "" }, h("b", {}, r.neu), " neu")),
        h("div", { class: "muted" }, Object.entries(r.benutzer).map(([u, c]) => `${u}: ${c.neu} neu von ${c.treffer}`).join(" · ")));
      if (r.beispiele.length) card.append(h("div", { class: "strip" }, r.beispiele.map((m) => thumb(m))));
    }
    list.append(card);
  });
  $("#count-tags").textContent = totalNew ? `(${totalNew})` : "";
  updateActionbar();
}

async function saveRules(items, errorBox) {
  try {
    await api("api/rules", { method: "PUT", body: { regeln: items } });
    return true;
  } catch (e) {
    // Zeilennummern und YAML-Tipps betreffen die Datei, nicht das Formular
    const list = (e.details.length ? e.details : [e.message])
      .map((d) => d.replace(/ \(Zeile \d+\)/, "").replace(/ Tipp: .*$/, ""));
    if (errorBox) errorBox.replaceChildren(h("div", { class: "banner err" }, h("ul", {}, list.map((d) => h("li", {}, d)))));
    else toast(list.join(" · "), true);
    return false;
  }
}

let editIndex = null;
function openRule(idx) {
  const t = S.tags;
  editIndex = idx;
  const item = idx === null ? { aktiv: true } : t.items[idx];
  $("#rule-title").textContent = idx === null ? "Neue Regel" : "Regel bearbeiten";
  $("#rule-errors").replaceChildren();
  $("#r-name").value = item.name || "";
  $("#r-tags").value = ruleTags(item).join(", ");
  $("#r-aktiv").checked = item.aktiv !== false;
  for (const k of ["von", "bis", "bibliothek", "typ", "hersteller", "modell", "dateiname", "pfad"]) $("#r-" + k).value = item[k] || "";
  $("#r-album").value = asList(item.album).join(", ");
  $("#r-person").value = asList(item.person).join(", ");
  const chosen = asList(item.benutzer).map((u) => String(u).toLowerCase());
  $("#r-benutzer").replaceChildren(...t.users.map((u) => h("label", { class: "toggle" },
    h("input", { type: "checkbox", value: u, checked: chosen.includes(u) }), u)));
  $("#rule-delete").hidden = idx === null;
  const adv = ["modell", "dateiname", "pfad"].some((k) => item[k]);
  $("#rule-form details").open = adv;
  $("#rule-dlg").showModal();
}

function readRuleForm() {
  const split = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);
  const item = { name: $("#r-name").value.trim() };
  const tags = split($("#r-tags").value);
  if (tags.length === 1) item.tag = tags[0]; else if (tags.length) item.tags = tags;
  for (const k of ["von", "bis", "bibliothek", "typ", "hersteller", "modell", "dateiname", "pfad"]) {
    const v = $("#r-" + k).value.trim();
    if (v) item[k] = v;
  }
  for (const k of ["album", "person"]) {
    const v = split($("#r-" + k).value);
    if (v.length) item[k] = v.length === 1 ? v[0] : v;
  }
  const users = [...$("#r-benutzer").querySelectorAll("input:checked")].map((i) => i.value);
  if (users.length) item.benutzer = users.length === 1 ? users[0] : users;
  if (!$("#r-aktiv").checked) item.aktiv = false;
  return item;
}

async function saveRuleFromDialog(btn) {
  const item = readRuleForm();
  const items = S.tags.items.slice();
  if (editIndex === null) items.push(item); else items[editIndex] = item;
  busy(btn, true);
  const ok = await saveRules(items, $("#rule-errors"));
  busy(btn, false);
  if (!ok) { $("#rule-dlg").scrollTop = 0; return; }
  $("#rule-dlg").close();
  toast("Regel gespeichert");
  await loadTab("tags", true);
}

async function deleteRule() {
  const item = S.tags.items[editIndex];
  $("#rule-dlg").close();
  const ok = await confirmDialog({ title: "Regel löschen?", body: h("p", {}, `„${item.name}“ wird entfernt. Bereits gesetzte Tags bleiben erhalten.`), okLabel: "Löschen", danger: true });
  if (!ok) return;
  const items = S.tags.items.filter((_, i) => i !== editIndex);
  if (await saveRules(items)) { toast("Regel gelöscht"); await loadTab("tags", true); }
}

async function addExamples() {
  const ex = (await api("api/rules/example")).regeln;
  const names = new Set(S.tags.items.map((i) => i.name));
  const fresh = ex.filter((e) => !names.has(e.name));
  if (!fresh.length) { toast("Beispiele sind schon vorhanden"); return; }
  const ok = await confirmDialog({ title: "Beispielregeln übernehmen?",
    body: [h("p", {}, `${n(fresh.length, "Beispielregel wird", "Beispielregeln werden")} ausgeschaltet hinzugefügt. Passe sie an und schalte sie dann ein:`),
      h("ul", {}, fresh.map((e) => h("li", {}, e.name)))], okLabel: "Übernehmen" });
  if (!ok) return;
  if (await saveRules([...S.tags.items, ...fresh])) { toast("Beispiele übernommen"); await loadTab("tags", true); }
}

function openYaml() {
  $("#yaml-errors").replaceChildren();
  $("#yaml-text").value = S.tags.yaml || "regeln:\n";
  $("#yaml-dlg").showModal();
}

async function saveYaml(btn) {
  busy(btn, true);
  try {
    await api("api/rules", { method: "PUT", body: { yaml: $("#yaml-text").value } });
    $("#yaml-dlg").close();
    toast("Regeln gespeichert");
    await loadTab("tags", true);
  } catch (e) {
    const list = e.details.length ? e.details : [e.message];
    $("#yaml-errors").replaceChildren(h("div", { class: "banner err" }, h("ul", {}, list.map((d) => h("li", {}, d)))));
  } finally {
    busy(btn, false);
  }
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

/* ------------------------------------------------------ Einstellungen */
async function loadSettings() {
  const d = await api("api/settings");
  S.set.data = d; S.set.loaded = true;
  const lock = (id, key) => {
    const el = $(id);
    el.disabled = d.gesperrt.includes(key);
    el.title = el.disabled ? "In der .env festgelegt" : "";
  };
  $("#set-url").value = d.immich_url; lock("#set-url", "immich_url");
  $("#set-album").value = d.review_album; lock("#set-album", "review_album");
  $("#set-hours").value = d.location_max_hours; lock("#set-hours", "location_max_hours");
  $("#set-ext").checked = d.location_include_external; lock("#set-ext", "location_include_external");
  $("#set-web-user").value = d.web_user; lock("#set-web-user", "web_user");
  $("#set-web-pw").value = ""; lock("#set-web-pw", "web_password");
  $("#set-logout").hidden = !d.login_aktiv;
  $("#set-login-hint").textContent = d.login_aktiv
    ? "Login ist aktiv. Benutzername leeren und speichern schaltet ihn ab."
    : "Ohne Login kann jeder im Heimnetz das Tool bedienen. Für Zugriff von außen unbedingt setzen.";
  $("#set-auto").value = d.auto_scan; lock("#set-auto", "auto_scan");
  $("#set-auto-time").value = d.auto_scan_time; lock("#set-auto-time", "auto_scan_time");
  $("#set-auto-hours").value = d.auto_scan_hours; lock("#set-auto-hours", "auto_scan_hours");
  $("#set-tz").value = d.timezone; lock("#set-tz", "timezone");
  updateAutoFields();
  $("#set-upd-check").checked = d.update_check; lock("#set-upd-check", "update_check");
  $("#set-upd-repo").value = d.update_repo; lock("#set-upd-repo", "update_repo");
  $("#set-upd-token").value = ""; lock("#set-upd-token", "update_github_token");
  $("#set-upd-token").placeholder = d.update_github_token_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-upd-url").value = d.update_webhook_url; lock("#set-upd-url", "update_webhook_url");
  $("#set-upd-header").value = d.update_webhook_header; lock("#set-upd-header", "update_webhook_header");
  $("#set-upd-secret").value = ""; lock("#set-upd-secret", "update_webhook_secret");
  $("#set-upd-secret").placeholder = !d.update_webhook_header ? "ohne Auth" : (d.update_webhook_secret_gesetzt ? "gespeichert" : "nicht gesetzt");
  $("#set-users").replaceChildren(...(d.benutzer.length ? d.benutzer : [{ name: "", key_gesetzt: false }]).map(userRow));
  $("#set-add-user").disabled = d.gesperrt.includes("users");
  $("#set-test-result").replaceChildren();
  $("#set-env-hint").textContent = d.gesperrt.length
    ? "Ausgegraute Felder sind in der .env festgelegt und haben Vorrang. Gespeichert wird in " + d.datenordner + "/einstellungen.json."
    : "Gespeichert wird in " + d.datenordner + "/einstellungen.json.";
  $("#set-welcome").replaceChildren(...(d.eingerichtet ? [] : [h("div", { class: "banner warn" },
    h("b", {}, "Willkommen! "), "Trage die Immich-Adresse und für jeden Benutzer einen API-Key ein, teste die Verbindung und speichere.")]));
}

function updateAutoFields() {
  const mode = $("#set-auto").value;
  $("#set-auto-time-wrap").hidden = mode !== "taeglich";
  $("#set-auto-hours-wrap").hidden = mode !== "intervall";
  $("#set-tz").closest("label").hidden = mode === "aus";
  const a = S.status && S.status.auto_einlesen;
  const parts = [];
  if (a && a.modus !== "aus" && a.naechstes) parts.push("Nächstes Einlesen: " + fmtDateTime(a.naechstes));
  if (a && a.letztes) parts.push("zuletzt automatisch: " + fmtDateTime(a.letztes));
  if (a && a.fehler) parts.push("Fehler: " + a.fehler);
  $("#set-auto-info").textContent = parts.join(" · ");
}

function userRow(u) {
  const locked = S.set.data && S.set.data.gesperrt.includes("users");
  const row = h("div", { class: "user-row", "data-alt": u.name || "" },
    h("input", { type: "text", class: "u-name", value: u.name || "", placeholder: "Name, z. B. frank", autocapitalize: "off", disabled: locked, "aria-label": "Benutzername" }),
    h("input", { type: "password", class: "u-key", autocomplete: "off", disabled: locked, "aria-label": "API-Key",
      placeholder: u.key_gesetzt ? "gespeichert" + (u.key_ende ? " …" + u.key_ende : "") : "API-Key einfügen" }),
    h("button", { type: "button", class: "btn small", disabled: locked, "aria-label": "Entfernen", title: "Entfernen", onclick: () => row.remove() }, "✕"));
  return row;
}

function readUsers() {
  return [...document.querySelectorAll("#set-users .user-row")].map((r) => ({
    name: r.querySelector(".u-name").value.trim().toLowerCase(),
    key: r.querySelector(".u-key").value.trim(),
    alt: r.dataset.alt,
  })).filter((u) => u.name || u.key);
}

function readSettingsForm() {
  const d = S.set.data;
  const body = {};
  const put = (key, val) => { if (!d.gesperrt.includes(key)) body[key] = val; };
  put("immich_url", $("#set-url").value.trim());
  put("review_album", $("#set-album").value.trim());
  put("location_max_hours", $("#set-hours").value);
  put("location_include_external", $("#set-ext").checked);
  if (!d.gesperrt.includes("users")) body.benutzer = readUsers();
  put("auto_scan", $("#set-auto").value);
  put("auto_scan_time", $("#set-auto-time").value);
  put("auto_scan_hours", $("#set-auto-hours").value);
  put("timezone", $("#set-tz").value.trim());
  put("update_check", $("#set-upd-check").checked);
  put("update_repo", $("#set-upd-repo").value.trim());
  put("update_webhook_url", $("#set-upd-url").value.trim());
  put("update_webhook_header", $("#set-upd-header").value.trim());
  if ($("#set-upd-token").value.trim()) put("update_github_token", $("#set-upd-token").value.trim());
  if ($("#set-upd-secret").value.trim()) put("update_webhook_secret", $("#set-upd-secret").value.trim());
  if (!d.gesperrt.includes("web_user")) {
    body.web_user = $("#set-web-user").value.trim();
    if ($("#set-web-pw").value) body.web_password = $("#set-web-pw").value;
  }
  return body;
}

async function testConnection(btn) {
  const box = $("#set-test-result");
  const body = {};
  if (!$("#set-url").disabled) body.immich_url = $("#set-url").value.trim();
  if (!S.set.data.gesperrt.includes("users")) body.benutzer = readUsers();
  busy(btn, true);
  try {
    const r = await api("api/settings/test", { method: "POST", body });
    const lines = [h("li", { class: r.erreichbar ? "test-ok" : "test-bad" },
      r.erreichbar ? `✓ Immich erreichbar${r.version ? " – Version " + r.version : ""}` : `✗ ${r.immich_url} nicht erreichbar`)];
    for (const [name, k] of Object.entries(r.schluessel)) {
      lines.push(h("li", { class: k.ok ? "test-ok" : "test-bad" }, k.ok ? `✓ ${name}: ${k.konto}` : `✗ ${name}: ${k.fehler}`));
    }
    for (const w of r.warnungen) lines.push(h("li", { class: "test-bad" }, "⚠ " + w));
    box.replaceChildren(h("ul", {}, lines));
  } catch (e) {
    box.replaceChildren(h("div", { class: "banner err" }, (e.details.length ? e.details.join(" · ") : e.message)));
  } finally {
    busy(btn, false);
  }
}

async function saveSettings(btn) {
  busy(btn, true);
  try {
    const before = S.set.data;
    const r = await api("api/settings", { method: "PUT", body: readSettingsForm() });
    toast(r.login_geaendert ? "Gespeichert – Login ist aktiv, du bleibst angemeldet" : "Einstellungen gespeichert");
    const accessChanged = before.immich_url !== r.immich_url ||
      JSON.stringify(before.benutzer) !== JSON.stringify(r.benutzer) || before.review_album !== r.review_album;
    S.loc.hours = null;
    await loadStatus(true);
    await loadSettings();
    loadVersion();
    S.dup.loaded = S.loc.loaded = S.tags.loaded = false;
    if (accessChanged && r.eingerichtet) toast("Gespeichert – Bibliothek wird beim nächsten Öffnen neu eingelesen");
  } catch (e) {
    toast(e.details.length ? e.details.join(" · ") : e.message, true);
  } finally {
    busy(btn, false);
  }
}

/* ------------------------------------------------------------ Version */
const short = (c) => (c ? c.slice(0, 7) : "?");

async function loadVersion(force = false) {
  let v;
  try {
    v = await api(force ? "api/version/check" : "api/version", force ? { method: "POST" } : {});
  } catch (e) {
    $("#version-info").textContent = "Version nicht ermittelbar: " + e.message;
    return null;
  }
  S.version = v;
  $(".tabs button.gear").classList.toggle("dot", !!v.update_available);
  $(".tabs button.gear").title = v.update_available ? "Einstellungen – Update verfügbar" : "Einstellungen";
  if (S.tab !== "set" && !force) return v;
  const cur = v.current || {};
  const parts = [`Läuft: ${short(cur.commit)}${cur.branch ? " (" + cur.branch + ")" : ""}`];
  if (cur.updated_at) parts.push("Stand " + fmtDateTime(cur.updated_at));
  if (!v.enabled) parts.push("Update-Prüfung aus");
  else if (v.error) parts.push("Prüfung fehlgeschlagen: " + v.error);
  else if (v.status === "update") parts.push(`${v.behind} neue ${v.behind === 1 ? "Änderung" : "Änderungen"} auf GitHub`);
  else if (v.status === "current") parts.push("aktuell ✓");
  else if (v.status === "unknown") parts.push("lokaler Stand ist GitHub unbekannt");
  $("#version-info").textContent = parts.join(" · ");
  $("#version-commits").replaceChildren(...(v.commits && v.commits.length
    ? [h("ul", { class: "commits" }, v.commits.map((c) => h("li", {}, h("code", {}, short(c.commit)), " ", c.message)))] : []));
  $("#version-check").hidden = !v.enabled;
  const btn = $("#version-update");
  btn.hidden = !v.update_moeglich;
  btn.className = "btn small" + (v.update_available ? " primary" : "");
  if (!v.update_moeglich) {
    $("#version-out").textContent = "Für den Update-Knopf: n8n-Workflow n8n/immich-pflege-update.json importieren und unten unter „Updates“ die Webhook-Adresse eintragen.";
  } else if (!btn.disabled) {
    $("#version-out").textContent = "";
  }
  return v;
}

async function startUpdate(btn) {
  const ok = await confirmDialog({ title: "Jetzt aktualisieren?",
    body: h("p", {}, "n8n holt den neuen Stand von GitHub, baut den Container neu und startet ihn. Das Tool ist dabei 1–3 Minuten nicht erreichbar."),
    okLabel: "Aktualisieren" });
  if (!ok) return;
  const from = ((S.version || {}).current || {}).commit;
  const out = $("#version-out");
  btn.disabled = true;
  out.textContent = "Starte Update …";
  try {
    await api("api/version/update", { method: "POST" });
  } catch (e) {
    out.textContent = "Update konnte nicht gestartet werden: " + e.message;
    btn.disabled = false;
    return;
  }
  out.textContent = "Update gestartet – der Container wird neu gebaut und startet neu. Die Seite lädt danach von selbst neu (meist 1–3 Minuten).";
  const started = Date.now();
  const poll = async () => {
    const now = await fetch("api/version", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (now && now.current && now.current.commit && now.current.commit !== from) return location.reload();
    if (Date.now() - started > 10 * 60 * 1000) {
      out.textContent = "Noch keine neue Version – bitte in n8n die Ausführung des Workflows prüfen.";
      btn.disabled = false;
      return;
    }
    setTimeout(poll, 10000);
  };
  setTimeout(poll, 15000);
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
  } else if (S.tab === "set") {
    const locked = S.set.data && S.set.data.gesperrt.length;
    info.textContent = locked ? "Gesperrte Felder stammen aus der .env" : "Änderungen gelten sofort";
    buttons.push(h("button", { class: "btn small primary", type: "button", onclick: (e) => saveSettings(e.currentTarget) }, "Speichern"));
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

const TAB_TARGET = { dup: "#dup-list", loc: "#loc-list", tags: "#tags-list", set: "#set-welcome" };

async function doLoadTab(tab, force) {
  try {
    if (tab === "dup" && (force || !S.dup.loaded)) await loadDuplicates(true);
    if (tab === "loc" && (force || !S.loc.loaded)) await loadLocation(true);
    if (tab === "tags" && (force || !S.tags.loaded)) await loadTags();
    if (tab === "set" && (force || !S.set.loaded)) { await loadSettings(); loadVersion(); }
    if (tab !== "set" && S.status && !S.status.bibliothek) loadStatus(false);
  } catch (e) {
    const box = e.setup
      ? h("div", { class: "banner warn" }, "Noch nicht eingerichtet. ",
        h("button", { type: "button", class: "btn small", onclick: () => showTab("set") }, "Zu den Einstellungen"))
      : h("div", { class: "banner err" }, "Laden fehlgeschlagen: " + e.message);
    $(TAB_TARGET[tab]).replaceChildren(box);
  }
  updateActionbar();
}

function showTab(tab) {
  S.tab = tab;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab ? "true" : "false"));
  document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== "tab-" + tab; });
  try { localStorage.setItem("pflege-tab", tab); } catch (_) { /* egal */ }
  updateActionbar();
  return loadTab(tab);
}

function loadOtherCounts() {
  if (S.status && !S.status.eingerichtet) return;
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
$("#rule-new").addEventListener("click", () => openRule(null));
$("#rule-examples").addEventListener("click", () => addExamples().catch((e) => toast(e.message, true)));
$("#rule-yaml").addEventListener("click", openYaml);
$("#rule-save").addEventListener("click", (e) => saveRuleFromDialog(e.currentTarget));
$("#rule-delete").addEventListener("click", deleteRule);
$("#yaml-save").addEventListener("click", (e) => saveYaml(e.currentTarget));
$("#set-add-user").addEventListener("click", () => $("#set-users").append(userRow({ name: "", key_gesetzt: false })));
$("#set-test").addEventListener("click", (e) => testConnection(e.currentTarget));
$("#set-auto").addEventListener("change", updateAutoFields);
$("#set-logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" }).catch(() => null);
  location.href = "/login";
});
$("#version-check").addEventListener("click", async (e) => { busy(e.currentTarget, true); await loadVersion(true); busy(e.currentTarget, false); });
$("#version-update").addEventListener("click", (e) => startUpdate(e.currentTarget));

(async function init() {
  let tab = "dup";
  try { tab = localStorage.getItem("pflege-tab") || "dup"; } catch (_) { /* egal */ }
  await loadStatus(true);
  loadVersion();
  setTimeout(loadVersion, 6000); // Ergebnis der Hintergrundprüfung abholen
  setInterval(loadVersion, 3600 * 1000);
  if (S.status && !S.status.eingerichtet) {
    await showTab("set");
    return;
  }
  await showTab(["dup", "loc", "tags", "set"].includes(tab) ? tab : "dup");
  // Nach dem ersten Laden (ggf. Einlesen) Status aktualisieren und Zähler der anderen Tabs holen
  loadStatus(false);
  loadOtherCounts();
})();
