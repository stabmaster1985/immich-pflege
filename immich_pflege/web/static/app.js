"use strict";

const PAGE_DUP = 20;

const S = {
  tab: "dup",
  status: null,
  dup: { groups: [], total: 0, open: 0, keep: {}, sel: new Set(), includeDone: false, art: null, monat: null, crossUser: false, ignored: false, loaded: false, info: null },
  loc: { series: [], total: 0, sel: new Set(), open: new Set(), hours: null, only: false, minConf: null, ort: null, monat: null, loaded: false, info: null },
  alb: { trips: [], total: 0, status: null, jahr: null, ignored: false, sel: new Set(), choice: {}, loaded: false, info: null },
  tags: { rules: [], sel: new Set(), loaded: false, error: null, warnings: [], items: [], fileErrors: [], users: [], yaml: "" },
  set: { data: null, loaded: false },
  stage: { entries: [], info: null, loaded: false },
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

// Kachel als <div role="button">: darin dürfen Links stehen (in <button> nicht erlaubt)
function tile(attrs, ...children) {
  const click = attrs.onclick;
  const el = h("div", { ...attrs, role: "button", tabindex: "0", onclick: null }, ...children);
  el.addEventListener("click", (e) => { if (!e.target.closest("a")) click(e); });
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); click(e); } });
  return el;
}

// Original öffnen: Immich-App (immich://asset?id=…) oder Weboberfläche (/photos/<id>)
function openLinks(m) {
  const web = S.status && S.status.link_url;
  return h("div", { class: "open-links" },
    h("a", { href: "immich://asset?id=" + encodeURIComponent(m.id), title: "In der Immich-App öffnen" }, "App ↗"),
    web ? h("a", { href: `${web}/photos/${encodeURIComponent(m.id)}`, target: "_blank", rel: "noopener", title: "In Immich im Browser öffnen" }, "Web ↗") : null);
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
  if (st.vorgemerkt) $("#count-stage").textContent = st.vorgemerkt.anzahl ? `(${st.vorgemerkt.anzahl})` : "";
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
    S.dup.loaded = S.loc.loaded = S.alb.loaded = S.tags.loaded = false;
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
  const params = new URLSearchParams({ offset: d.groups.length, limit: PAGE_DUP, include_done: d.includeDone,
    benutzeruebergreifend: d.crossUser, ignoriert: d.ignored });
  if (d.art) params.set("art", d.art);
  if (d.monat) params.set("monat", d.monat);
  const r = await api("api/duplicates?" + params);
  if (d.monat && !r.monate.some((m) => m.key === d.monat)) { d.monat = null; return loadDuplicates(true); }
  if (reset) $("#dup-list").replaceChildren();
  d.total = r.gesamt; d.open = r.offen; d.loaded = true; d.info = r;
  renderDupFilters(r);
  for (const g of r.gruppen) {
    d.groups.push(g);
    $("#dup-list").append(renderGroup(g));
  }
  if (!d.groups.length) {
    $("#dup-list").replaceChildren(h("p", { class: "empty" },
      d.ignored ? "Keine ausgeblendeten Gruppen." : (d.art || d.monat || d.crossUser ? "Nichts mit diesem Filter." : "Keine Duplikate gefunden 🎉")));
  }
  $("#dup-summary").textContent = d.ignored
    ? `${n(r.gesamt, "ausgeblendete Gruppe", "ausgeblendete Gruppen")} („kein Duplikat“)`
    : `${r.offen} offen · ${n(r.gesamt, "Gruppe", "Gruppen")} · ${r.benutzeruebergreifend} benutzerübergreifend`;
  if (!d.art && !d.monat && !d.crossUser && !d.ignored) $("#count-dup").textContent = r.offen ? `(${r.offen})` : "";
  renderFingerprint(r.fingerabdruck);
  $("#dup-more").hidden = d.groups.length >= d.total;
  updateActionbar();
}

let fpTimer = null;
function renderFingerprint(fp) {
  const box = $("#dup-fp");
  clearTimeout(fpTimer);
  if (!fp || !fp.aktiv) { box.replaceChildren(); return; }
  if (fp.laeuft) {
    const pct = fp.gesamt ? Math.round((fp.fertig / fp.gesamt) * 100) : 0;
    box.replaceChildren(h("div", { class: "banner warn" },
      `Bild-Fingerabdrücke werden berechnet: ${fp.fertig} von ${fp.gesamt} (${pct} %). Ähnliche Kopien erscheinen danach hier.`,
      h("progress", { max: fp.gesamt || 1, value: fp.fertig })));
    // während der Berechnung alle 15 s nachsehen (nur solange der Tab offen ist)
    fpTimer = setTimeout(() => { if (S.tab === "dup") loadTab("dup", true); }, 15000);
  } else if (fp.fehlend) {
    box.replaceChildren(h("div", { class: "muted small" }, `${fp.fehlend} Bilder ohne Fingerabdruck. `,
      h("button", { type: "button", class: "btn small", onclick: async () => {
        await api("api/fingerprints/start", { method: "POST" }).catch((e) => toast(e.message, true));
        loadTab("dup", true);
      } }, "Jetzt berechnen")));
  } else {
    box.replaceChildren(fp.fehler ? h("div", { class: "muted small" }, `Bild-Fingerabdruck: ${fp.fehler} Bilder nicht lesbar`) : "");
  }
}

function renderDupFilters(r) {
  const d = S.dup;
  const artSel = h("select", { onchange: (e) => { d.art = e.target.value || null; loadTab("dup", true); } },
    h("option", { value: "" }, "alle Arten"),
    ...Object.entries(r.arten).map(([k, v]) => h("option", { value: k }, `${v.name} (${d.includeDone ? v.anzahl : v.offen})`)));
  artSel.value = d.art || "";
  const monthSel = h("select", { onchange: (e) => { d.monat = e.target.value || null; loadTab("dup", true); } },
    h("option", { value: "" }, "alle Monate"),
    ...r.monate.map((m) => h("option", { value: m.key }, `${m.name} (${m.anzahl})`)));
  monthSel.value = d.monat || "";
  $("#dup-filters").replaceChildren(
    h("label", { class: "field grow" }, "Art", artSel),
    h("label", { class: "field grow" }, "Monat", monthSel),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: d.crossUser,
      onchange: (e) => { d.crossUser = e.target.checked; loadTab("dup", true); } }), "nur benutzerübergreifend"),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: d.ignored,
      onchange: (e) => { d.ignored = e.target.checked; loadTab("dup", true); } }), `ausgeblendete (${r.ignoriert})`));
}

const SOURCE_LABEL = { immich: "Immich-KI", pruefsumme: "Prüfsumme", name_zeit: "Name + Zeit", bildhash: "Bild-Fingerabdruck",
  format: "Format", bearbeitung: "Bearbeitung", raw_paar: "RAW + JPG" };
const KIND_CLASS = { identisch: "conf-hoch", sehr_wahrscheinlich: "conf-mittel", format: "conf-mittel",
  bearbeitung: "conf-mittel", raw_paar: "conf-niedrig", aehnlich: "conf-niedrig" };

async function ignoreGroup(g, undo) {
  if (!undo) {
    const ok = await confirmDialog({
      title: "Kein Duplikat?",
      body: [h("p", {}, "Die Gruppe wird dauerhaft ausgeblendet. Kommt später eine weitere Kopie dazu, taucht sie wieder auf."),
        g.quellen.includes("immich") ? h("p", { class: "muted" }, "Die Medien werden auch in Immich aus der Duplikatliste genommen.") : null],
      okLabel: "Ausblenden",
    });
    if (!ok) return;
  }
  try {
    await api("api/duplicates/ignore", { method: "POST", body: { groups: [g.id], undo } });
    toast(undo ? "Gruppe wieder aufgenommen" : "Als „kein Duplikat“ markiert");
    await loadDuplicates(true);
  } catch (e) {
    toast(e.message, true);
  }
}

async function applyAllDuplicates(action, btn) {
  const d = S.dup;
  const body = { action, all: true, art: d.art, monat: d.monat, benutzeruebergreifend: d.crossUser };
  busy(btn, true);
  let plan;
  try {
    plan = await api("api/duplicates/apply", { method: "POST", body: { ...body, dry_run: true } });
  } catch (e) {
    toast(e.message, true); busy(btn, false); return;
  } finally { busy(btn, false); }
  if (!plan.papierkorb && !plan.album) { toast("Nichts zu tun."); return; }
  const scope = [d.art ? d.info.arten[d.art].name : null, d.monat ? d.info.monate.find((m) => m.key === d.monat).name : null,
    d.crossUser ? "benutzerübergreifend" : null].filter(Boolean).join(", ") || "alle offenen";
  const ok = await confirmDialog({
    title: "Alle vormerken?",
    body: [h("p", {}, `${n(plan.gruppen, "Gruppe", "Gruppen")} (${scope}) mit dem jeweiligen Behalten-Vorschlag:`),
      h("ul", {}, plan.papierkorb ? h("li", {}, h("b", {}, plan.papierkorb), " für den Papierkorb") : null,
        plan.album ? h("li", {}, h("b", {}, plan.album), " fürs Prüf-Album") : null),
      h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter ✓ Vorgemerkt.")],
    okLabel: "Vormerken",
  });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/staged/duplicates", { method: "POST", body });
    toast(`${n(r.vorgemerkt, "Gruppe", "Gruppen")} vorgemerkt`);
    await afterStage("dup");
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

// Gründe für den Behalten-Vorschlag als Häkchen. Hervorgehoben sind die Gründe, die nicht
// alle Kopien der Gruppe haben – nur die machen den Unterschied.
function renderReasons(m, g) {
  const common = g.medien.reduce((acc, x) => acc.filter((r) => x.gruende.includes(r)), [...g.medien[0].gruende]);
  if (!m.gruende.length) return h("div", { class: "reasons muted" }, "keine Vorteile");
  return h("div", { class: "reasons", title: `Wertung: ${m.punkte} Punkte` },
    ...m.gruende.map((r) => h("span", { class: common.includes(r) ? "reason same" : "reason diff" }, "✓ " + r)));
}

function renderGroup(g) {
  const d = S.dup;
  const keep = d.keep[g.id] || g.behalten;
  const card = h("article", { class: "card" + (d.sel.has(g.id) ? " selected" : ""), "data-group": g.id });
  const head = h("div", { class: "card-head" },
    h("label", {}, h("input", {
      type: "checkbox", checked: d.sel.has(g.id),
      onchange: (e) => { e.target.checked ? d.sel.add(g.id) : d.sel.delete(g.id); card.classList.toggle("selected", e.target.checked); updateActionbar(); },
    }), `${g.medien.length} Kopien`),
    h("span", { class: "chip " + (KIND_CLASS[g.art] || ""), title: "Art der Übereinstimmung" }, g.art_text),
    ...g.quellen.map((q) => h("span", { class: "chip" }, SOURCE_LABEL[q] || q)),
    g.benutzeruebergreifend ? h("span", { class: "chip accent" }, g.benutzer.join(" + ")) : null,
    g.erledigt ? h("span", { class: "chip ok" }, "erledigt") : null,
    h("button", { type: "button", class: "btn small edit", onclick: () => ignoreGroup(g, S.dup.ignored) },
      S.dup.ignored ? "Wieder aufnehmen" : "Kein Duplikat"),
  );
  const grid = h("div", { class: "grid" });
  for (const m of g.medien) {
    const isKeep = m.id === keep;
    const badge = isKeep ? "★ bleibt" : (m.im_pruef_album ? "im Prüf-Album" : "weg");
    grid.append(tile({
      class: "tile " + (isKeep ? "keep" : "drop"),
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
      renderReasons(m, g),
      openLinks(m),
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
  if (plan.papierkorb) items.push(h("li", {}, h("b", {}, plan.papierkorb), " für den Papierkorb (nur Uploads, 30 Tage wiederherstellbar)"));
  if (plan.album) items.push(h("li", {}, h("b", {}, plan.album), ` fürs Album „${album}“`));
  if (plan.keine) items.push(h("li", {}, plan.keine, " unverändert (schon im Prüf-Album)"));
  const reasons = [...new Set(plan.schritte.filter((s) => s.aktion === "album" && s.grund !== "Kopie").map((s) => s.grund))];
  const body = [h("p", {}, `${n(plan.gruppen, "Gruppe", "Gruppen")}:`), h("ul", {}, items)];
  if (action === "papierkorb" && reasons.length) body.push(h("p", { class: "muted" }, "Statt Papierkorb ins Prüf-Album: " + reasons.join("; ")));
  body.push(h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter ✓ Vorgemerkt."));
  if (!plan.papierkorb && !plan.album) { toast("Nichts zu tun – alles schon erledigt."); return; }
  const ok = await confirmDialog({ title: "Vormerken?", body, okLabel: "Vormerken" });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/staged/duplicates", { method: "POST", body: { action, groups } });
    toast(`${n(r.vorgemerkt, "Gruppe", "Gruppen")} vorgemerkt`);
    await afterStage("dup");
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

/* ---------------------------------------------------------- Ohne Ort */
const PAGE_SERIES = 15;
const LEVEL_LABEL = { hoch: "sicher", mittel: "wahrscheinlich", niedrig: "unsicher" };
const PREVIEW_TILES = 6;

function confChip(level) {
  return level ? h("span", { class: "chip conf-" + level }, LEVEL_LABEL[level]) : null;
}

function fmtRange(s) {
  if (!s.start) return "Ohne Datum";
  const day = fmtDay(s.datum);
  const a = s.start.slice(11, 16), b = s.ende ? s.ende.slice(11, 16) : a;
  const endDay = s.ende ? s.ende.slice(0, 10) : s.datum;
  if (endDay !== s.datum) return `${day} ${a} – ${fmtDay(endDay)} ${b}`;
  return a === b ? `${day} · ${a}` : `${day} · ${a}–${b}`;
}

async function loadLocation(reset) {
  const l = S.loc;
  const overview = l.ort === null;
  if (reset) { l.series = []; l.sel.clear(); l.open = new Set(); $("#loc-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const params = new URLSearchParams({ offset: l.series.length, limit: PAGE_SERIES, only_suggestions: l.only, overview });
  if (l.hours) params.set("max_hours", l.hours);
  if (l.minConf) params.set("min_confidence", l.minConf);
  if (l.ort && l.ort !== "*") params.set("ort", l.ort);
  if (l.monat) params.set("monat", l.monat);
  const r = await api("api/no-location?" + params);
  l.loaded = true; l.info = r;
  // gewählter Ort/Monat existiert nicht mehr (z. B. nach Übernehmen) -> zurück zur Übersicht
  if (l.ort && l.ort !== "*" && !r.orte.some((o) => o.key === l.ort)) { l.ort = null; l.monat = null; return loadLocation(true); }
  if (l.monat && !r.monate.some((m) => m.key === l.monat)) { l.monat = null; return loadLocation(true); }
  renderLocFilters(r);
  if (reset) $("#loc-list").replaceChildren();
  if (overview) {
    l.total = 0;
    $("#loc-list").append(...r.orte.map(renderPlaceCard));
  } else {
    l.total = r.serien_gesamt;
    if (reset && l.ort !== "*") $("#loc-list").append(renderPlaceHeader(r));
    for (const ser of r.serien) {
      l.series.push(ser);
      $("#loc-list").append(renderSeries(ser));
    }
  }
  if (!r.orte.length) $("#loc-list").replaceChildren(h("p", { class: "empty" }, r.medien ? "Nichts mit diesem Filter." : "Alle Medien haben einen Ort 🎉"));
  const by = r.nach_sicherheit;
  $("#loc-summary").textContent = `${n(r.medien, "Medium", "Medien")} ohne Ort · ` +
    `Vorschläge: ${by.hoch} sicher, ${by.mittel} wahrscheinlich, ${by.niedrig} unsicher` +
    (r.screenshots_ausgeblendet ? ` · ${r.screenshots_ausgeblendet} Screenshots ausgeblendet` : "") +
    (r.extern_erlaubt ? "" : " · externe Bibliotheken gesperrt");
  $("#count-loc").textContent = r.mit_vorschlag ? `(${r.mit_vorschlag})` : "";
  $("#loc-more").hidden = overview || l.series.length >= l.total;
  updateActionbar();
}

function renderLocFilters(r) {
  const l = S.loc;
  const total = r.orte.reduce((a, o) => a + o.anzahl, 0);
  const placeSel = h("select", { id: "loc-ort", onchange: (e) => { l.ort = e.target.value === "" ? null : e.target.value; loadTab("loc", true); } },
    h("option", { value: "" }, `Übersicht nach Ort (${r.orte.length})`),
    h("option", { value: "*" }, `Alle Serien (${total})`),
    ...r.orte.map((o) => h("option", { value: o.key }, `${o.name} (${o.anzahl})`)));
  placeSel.value = l.ort === null ? "" : l.ort;
  const monthSel = h("select", { id: "loc-monat", onchange: (e) => { l.monat = e.target.value || null; loadTab("loc", true); } },
    h("option", { value: "" }, `Alle Monate`),
    ...r.monate.map((m) => h("option", { value: m.key }, `${m.name} (${m.anzahl})`)));
  monthSel.value = l.monat || "";
  $("#loc-filters").replaceChildren(
    h("label", { class: "field grow" }, "Ort", placeSel),
    h("label", { class: "field grow" }, "Monat", monthSel));
}

function confCounts(by) {
  return ["hoch", "mittel", "niedrig"].filter((k) => by[k]).map((k) => h("span", { class: "chip conf-" + k }, `${by[k]} ${LEVEL_LABEL[k]}`));
}

function fmtSpan(von, bis) {
  if (!von) return "";
  const f = (d) => d.slice(8, 10) + "." + d.slice(5, 7) + "." + d.slice(0, 4);
  return von === bis ? f(von) : `${f(von)} – ${f(bis)}`;
}

function renderPlaceCard(o) {
  const special = o.key.startsWith("~");
  const open = () => { S.loc.ort = o.key; loadTab("loc", true); window.scrollTo(0, 0); };
  const card = h("article", { class: "card place-card" });
  card.append(
    h("div", { class: "card-head" },
      h("div", {}, h("h2", {}, (special ? "" : "📍 ") + o.name),
        h("span", { class: "muted" }, `${n(o.anzahl, "Medium", "Medien")} · ${n(o.serien, "Serie", "Serien")}` + (o.von ? ` · ${fmtSpan(o.von, o.bis)}` : "")))),
    h("div", { class: "row-gap" }, ...confCounts(o.nach_sicherheit)),
    h("button", { type: "button", class: "strip strip-btn", onclick: open, "aria-label": o.name + " ansehen" }, o.beispiele.map((m) => thumb(m))),
    h("div", { class: "row-gap" },
      h("button", { type: "button", class: "btn small", onclick: open }, "Ansehen"),
      !special && o.mit_vorschlag ? h("button", { type: "button", class: "btn small primary", onclick: (e) => applyPlace(o, e.currentTarget) },
        `Alle vormerken (${o.mit_vorschlag})`) : null));
  return card;
}

function renderPlaceHeader(r) {
  const o = r.orte.find((x) => x.key === S.loc.ort);
  if (!o) return h("div");
  const special = o.key.startsWith("~");
  const month = S.loc.monat ? r.monate.find((m) => m.key === S.loc.monat) : null;
  const scope = month ? `${o.name} · ${month.name}` : o.name;
  return h("div", { class: "card place-head" },
    h("div", { class: "card-head" },
      h("button", { type: "button", class: "btn small", onclick: () => { S.loc.ort = null; S.loc.monat = null; loadTab("loc", true); } }, "← Alle Orte"),
      h("div", {}, h("h2", {}, scope), h("span", { class: "muted" }, `${n(r.medien_gefiltert, "Medium", "Medien")} in ${n(r.serien_gesamt, "Serie", "Serien")}`))),
    special ? h("div", {},
      h("p", { class: "muted small" }, o.key === "~ohne"
        ? "Keine GPS-Fotos in der Nähe. Pro Serie „Ort suchen …“ nutzen – oder mit dem Monatsfilter eingrenzen und für alle auf einmal suchen."
        : "Die Vorschläge innerhalb dieser Serien widersprechen sich. Bitte einzeln prüfen."),
      o.key === "~ohne" ? h("button", { type: "button", class: "btn small", onclick: () => openPlaceSearch({ ort: o.key, monat: S.loc.monat, count: r.medien_gefiltert, label: scope }) },
        `Ort für alle ${r.medien_gefiltert} suchen …`) : null)
      : h("div", { class: "row-gap" }, ...confCounts(o.nach_sicherheit),
        o.mit_vorschlag ? h("button", { type: "button", class: "btn small primary", onclick: (e) => applyPlace({ ...o, name: scope }, e.currentTarget, S.loc.monat) },
          `Alle vormerken`) : null));
}

async function applyPlace(o, btn, monat = null) {
  const by = o.nach_sicherheit;
  const ok = await confirmDialog({
    title: `Alle für „${o.name}“ vormerken?`,
    body: [h("p", {}, `Medien mit Vorschlag in diesem Ort${monat ? " und Monat" : ""} erhalten den vorgeschlagenen Ort.`),
      h("div", { class: "row-gap" }, ...confCounts(by)),
      h("p", { class: "muted" }, "Tipp: Oben „nur sichere“ wählen, wenn nur sichere Vorschläge vorgemerkt werden sollen.")],
    okLabel: "Vormerken",
  });
  if (!ok) return;
  const body = { ort: o.key };
  if (monat) body.monat = monat;
  if (S.loc.minConf) body.min_confidence = S.loc.minConf;
  await doApplyLocation(body, btn, monat ? `${o.name}` : o.name);
}

function selectable(m) { return m.vorschlag && m.aenderbar; }

function rerenderSeries(ser) {
  const old = document.querySelector(`[data-series="${ser.id}"]`);
  if (old) old.replaceWith(renderSeries(ser));
  updateActionbar();
}

function renderSeries(ser) {
  const l = S.loc;
  const card = h("article", { class: "card", "data-series": ser.id });
  const v = ser.vorschlag;
  const editable = ser.medien.filter((m) => m.aenderbar);
  const withSugg = ser.medien.filter(selectable);
  let placeLine;
  if (v) {
    placeLine = h("div", { class: "series-place" }, h("b", {}, "📍 " + (v.ort || `${v.breite.toFixed(4)}, ${v.laenge.toFixed(4)}`)), " ", confChip(ser.sicherheit),
      h("div", { class: "muted small" }, v.grund));
  } else if (!editable.length) {
    placeLine = h("div", { class: "series-place muted" }, "Nur externe Medien – in den Einstellungen gesperrt");
  } else if (ser.mehrere_orte) {
    placeLine = h("div", { class: "series-place muted" }, "Mehrere Orte in dieser Serie – einzeln prüfen");
  } else {
    placeLine = h("div", { class: "series-place muted" }, "Kein Foto mit GPS in der Nähe – Ort suchen");
  }
  const buttons = h("div", { class: "row-gap" });
  if (withSugg.length) {
    buttons.append(h("button", { type: "button", class: "btn small primary", onclick: (e) => applySeries(ser, e.currentTarget) },
      `Vormerken (${withSugg.length})`));
  }
  if (editable.length) {
    buttons.append(h("button", { type: "button", class: "btn small", onclick: () => openPlaceSearch({ series: [ser.id], count: editable.length, label: fmtRange(ser) }) },
      "Ort suchen …"));
  }
  card.append(
    h("div", { class: "card-head" }, h("div", {}, h("h2", {}, fmtRange(ser)),
      h("span", { class: "muted" }, `${n(ser.anzahl, "Medium", "Medien")} · ${ser.benutzer.join(" & ")}`))),
    placeLine, buttons);

  const showAll = l.open.has(ser.id) || ser.medien.length <= PREVIEW_TILES + 1;
  const shown = showAll ? ser.medien : ser.medien.slice(0, PREVIEW_TILES);
  const grid = h("div", { class: "grid" });
  for (const m of shown) {
    const mv = m.vorschlag;
    const can = selectable(m);
    const sel = l.sel.has(m.id);
    let info;
    if (mv && !m.aenderbar) info = h("div", { class: "nosug" }, `📍 ${mv.ort || "Ort"} · extern gesperrt`);
    else if (mv) info = h("div", {}, h("span", { class: "sug" }, `📍 ${mv.ort || mv.breite.toFixed(3) + ", " + mv.laenge.toFixed(3)}`), " ", confChip(mv.sicherheit));
    else info = h("div", { class: "nosug" }, "kein Vorschlag");
    grid.append(tile({
      class: "tile" + (can ? "" : " locked") + (sel ? " selected" : ""), "aria-pressed": sel ? "true" : "false",
      title: mv ? mv.grund : m.pfad,
      onclick: () => {
        if (!m.aenderbar) return;
        sel ? l.sel.delete(m.id) : l.sel.add(m.id);
        rerenderSeries(ser);
      },
    },
    thumb(m),
    m.aenderbar ? h("span", { class: "check" + (sel ? " on" : ""), "aria-hidden": "true" }, sel ? "✓" : "") : null,
    h("div", { class: "meta" },
      h("div", { class: "name" }, m.dateiname),
      h("div", {}, `${fmtTime(m.aufnahme)} · ${m.benutzer}${m.extern ? " · extern" : ""}`),
      info, openLinks(m))));
  }
  card.append(grid);
  if (!showAll) {
    card.append(h("button", { type: "button", class: "btn more", onclick: () => { l.open.add(ser.id); rerenderSeries(ser); } },
      `Alle ${ser.medien.length} zeigen`));
  }
  return card;
}

async function doApplyLocation(body, btn, label) {
  busy(btn, true);
  try {
    const r = await api("api/staged/no-location", { method: "POST", body: { ...body, label, max_hours: S.loc.hours } });
    toast(`${n(r.vorgemerkt, "Medium", "Medien")} vorgemerkt` + (r.uebersprungen.length ? `, ${r.uebersprungen.length} übersprungen` : ""));
    await afterStage("loc");
    return true;
  } catch (e) {
    toast(e.message, true);
    return false;
  } finally {
    busy(btn, false);
  }
}

async function applySeries(ser, btn) {
  const items = ser.medien.filter(selectable);
  const levels = [...new Set(items.map((m) => LEVEL_LABEL[m.vorschlag.sicherheit]))].join(", ");
  const ok = await confirmDialog({
    title: "Ort für die Serie vormerken?",
    body: [h("p", {}, `${n(items.length, "Medium erhält", "Medien erhalten")} den vorgeschlagenen Ort (${levels}):`),
      h("p", {}, h("b", {}, "📍 " + (ser.vorschlag ? ser.vorschlag.ort || "Koordinaten" : "jeweils eigener Vorschlag")))],
    okLabel: "Vormerken",
  });
  if (ok) await doApplyLocation({ series: [ser.id] }, btn, `${fmtRange(ser)} · ${ser.vorschlag ? ser.vorschlag.ort || "Koordinaten" : ""}`);
}

async function applyLocation(btn) {
  const ids = [...S.loc.sel];
  const all = S.loc.series.flatMap((s) => s.medien).filter((m) => S.loc.sel.has(m.id));
  const withSugg = all.filter(selectable);
  if (!withSugg.length) { toast("Die Auswahl hat keine Vorschläge – nutze „Ort wählen …“", true); return; }
  const places = new Map();
  for (const m of withSugg) {
    const k = m.vorschlag.ort || "Koordinaten";
    places.set(k, (places.get(k) || 0) + 1);
  }
  const ok = await confirmDialog({
    title: "Ort vormerken?",
    body: [h("p", {}, `${n(withSugg.length, "Medium erhält", "Medien erhalten")} den vorgeschlagenen Ort:`),
      h("ul", {}, [...places].map(([k, c]) => h("li", {}, `${k}: ${c}`))),
      all.length > withSugg.length ? h("p", { class: "muted" }, `${all.length - withSugg.length} ohne Vorschlag werden übersprungen.`) : null],
    okLabel: "Vormerken",
  });
  if (ok) await doApplyLocation({ ids: withSugg.map((m) => m.id) }, btn, "Auswahl");
}

async function applyAllSure(btn) {
  const count = S.loc.info ? S.loc.info.nach_sicherheit.hoch : 0;
  const ok = await confirmDialog({
    title: "Alle sicheren Vorschläge vormerken?",
    body: h("p", {}, `${n(count, "Medium erhält", "Medien erhalten")} den Ort eines GPS-Fotos, das höchstens 30 Minuten entfernt ist oder bei dem die Fotos davor und danach am selben Ort entstanden.`),
    okLabel: "Alle vormerken",
  });
  if (ok) await doApplyLocation({ min_confidence: "hoch" }, btn, "Alle sicheren Vorschläge");
}

/* Ortssuche über Immich (eigene Ortsdatenbank, kein Internetdienst) */
let placeTarget = null;
let placeTimer = null;
function openPlaceSearch(target) {
  placeTarget = target;
  $("#place-target").textContent = `${target.label} · ${n(target.count, "Medium", "Medien")}`;
  $("#place-q").value = "";
  $("#place-results").replaceChildren(h("p", { class: "muted" }, "Ortsnamen eingeben, z. B. Siena"));
  $("#place-dlg").showModal();
  setTimeout(() => $("#place-q").focus(), 50);
}

async function searchPlaces() {
  const q = $("#place-q").value.trim();
  const box = $("#place-results");
  if (q.length < 2) { box.replaceChildren(h("p", { class: "muted" }, "Mindestens 2 Buchstaben")); return; }
  try {
    const list = await api("api/places?q=" + encodeURIComponent(q));
    if (!list.length) { box.replaceChildren(h("p", { class: "muted" }, "Nichts gefunden")); return; }
    box.replaceChildren(...list.map((p) => h("button", {
      type: "button", class: "place-item",
      onclick: () => choosePlace(p),
    }, h("b", {}, p.name), p.region ? h("span", { class: "muted" }, " · " + p.region) : null)));
  } catch (e) {
    box.replaceChildren(h("div", { class: "banner err" }, e.message));
  }
}

async function choosePlace(p) {
  $("#place-dlg").close();
  const t = placeTarget;
  const ok = await confirmDialog({
    title: "Ort vormerken?",
    body: h("p", {}, `${n(t.count, "Medium erhält", "Medien erhalten")} den Ort `, h("b", {}, p.name), p.region ? ` (${p.region})` : "", "."),
    okLabel: "Vormerken",
  });
  if (!ok) return;
  const body = { place: { breite: p.breite, laenge: p.laenge, name: p.name } };
  if (t.ort) { body.ort = t.ort; if (t.monat) body.monat = t.monat; }
  else if (t.series) body.series = t.series;
  else body.ids = t.ids;
  await doApplyLocation(body, $("#ab-buttons button.primary") || document.createElement("button"), `${p.name} (von Hand) · ${t.label}`);
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
        h("span", { class: r.neu ? "sug" : "" }, h("b", {}, r.neu), " neu"),
        r.vorgemerkt ? h("span", { class: "chip ok" }, "✓ vorgemerkt") : null),
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
    title: "Tags vormerken?",
    body: [h("p", {}, "Tags werden nur ergänzt, nie entfernt."),
      h("ul", {}, rules.map((r) => h("li", {}, `${r.name}: ${r.neu} Medien → ${r.tags.join(", ")}`))),
      h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter ✓ Vorgemerkt.")],
    okLabel: "Vormerken",
  });
  if (!ok) return;
  busy(btn, true);
  try {
    await api("api/staged/tags", { method: "POST", body: { rules: names } });
    toast(`${n(names.length, "Regel", "Regeln")} vorgemerkt`);
    await afterStage("tags");
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
  $("#set-link-url").value = d.link_url; lock("#set-link-url", "link_url");
  $("#set-hours").value = d.location_max_hours; lock("#set-hours", "location_max_hours");
  $("#set-ext").checked = d.location_include_external; lock("#set-ext", "location_include_external");
  $("#set-shots").checked = d.location_skip_screenshots; lock("#set-shots", "location_skip_screenshots");
  $("#set-fp").checked = d.dup_image_hash; lock("#set-fp", "dup_image_hash");
  $("#set-edit").value = d.dup_edit_keep; lock("#set-edit", "dup_edit_keep");
  $("#set-alb-km").value = d.album_min_km; lock("#set-alb-km", "album_min_km");
  $("#set-alb-min").value = d.album_min_media; lock("#set-alb-min", "album_min_media");
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
  put("link_url", $("#set-link-url").value.trim());
  put("location_max_hours", $("#set-hours").value);
  put("location_include_external", $("#set-ext").checked);
  put("location_skip_screenshots", $("#set-shots").checked);
  put("dup_image_hash", $("#set-fp").checked);
  put("dup_edit_keep", $("#set-edit").value);
  put("album_min_km", $("#set-alb-km").value);
  put("album_min_media", $("#set-alb-min").value);
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
    S.dup.loaded = S.loc.loaded = S.alb.loaded = S.tags.loaded = false;
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
  if (v.dienst && v.dienst.verfuegbar) { /* Stand kommt vom Update-Dienst (siehe unten) */ }
  else if (!v.enabled) parts.push("Update-Prüfung aus");
  else if (v.error) parts.push("Prüfung fehlgeschlagen: " + v.error);
  else if (v.status === "update") parts.push(`${v.behind} neue ${v.behind === 1 ? "Änderung" : "Änderungen"} auf GitHub`);
  else if (v.status === "current") parts.push("aktuell ✓");
  else if (v.status === "unknown") parts.push("lokaler Stand ist GitHub unbekannt");
  $("#version-info").textContent = parts.join(" · ");
  $("#version-commits").replaceChildren(...(v.commits && v.commits.length
    ? [h("ul", { class: "commits" }, v.commits.map((c) => h("li", {}, h("code", {}, short(c.commit)), " ", c.message)))] : []));
  $("#version-check").hidden = !v.enabled;
  if (v.dienst && v.dienst.verfuegbar) { renderUpdater(v); return v; }
  $("#version-host").replaceChildren();
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

/* Update-Dienst auf dem Docker-Server: vorbereiten, ansehen, umschalten */
let updaterTimer = null;
function renderUpdater(v) {
  const d = v.dienst;
  const box = $("#version-host");
  clearTimeout(updaterTimer);
  $("#version-update").hidden = true;
  $("#version-check").hidden = true;
  $("#version-commits").replaceChildren();  // die Liste kommt hier vom Dienst
  const seen = d.zeit ? "zuletzt " + fmtDateTime(d.zeit) : "";
  const parts = [h("div", { class: "muted small" }, `Update-Dienst auf dem Server: verbunden · ${seen}`)];
  const busy = d.phase === "vorbereiten" || d.phase === "umschalten" || d.auftrag_offen;
  if (busy) {
    parts.push(h("div", { class: "banner warn" }, d.auftrag_offen && !["vorbereiten", "umschalten"].includes(d.phase)
      ? "Auftrag übergeben – der Dienst startet gleich …" : d.meldung));
    updaterTimer = setTimeout(() => loadVersion(), 4000);
  } else if (d.phase === "bereit") {
    parts.push(h("div", {}, h("b", {}, `Version ${short(d.bereit)} ist vorbereitet`), " – das Umschalten dauert nur Sekunden."),
      h("ul", { class: "commits" }, (d.commits || []).map((c) => h("li", {}, h("code", {}, short(c.commit)), " ", c.message))),
      h("div", { class: "row-gap" },
        h("button", { type: "button", class: "btn small primary", onclick: (e) => switchVersion(d, e.currentTarget) }, "Jetzt umschalten"),
        h("button", { type: "button", class: "btn small", onclick: (e) => prepareVersion(e.currentTarget) }, "Erneut prüfen")));
  } else {
    if (d.phase === "fehler") {
      parts.push(h("div", { class: "banner err" }, d.meldung, d.log ? h("pre", { class: "log" }, d.log) : null));
    } else {
      parts.push(h("div", {}, d.meldung || "Aktuell."));
    }
    parts.push(h("div", { class: "row-gap" },
      h("button", { type: "button", class: "btn small", onclick: (e) => prepareVersion(e.currentTarget) }, "Jetzt auf Updates prüfen")));
  }
  parts.push(h("p", { class: "muted small" }, "Neue Versionen werden stündlich im Hintergrund vorbereitet. Umgeschaltet wird nur per Klick."));
  box.replaceChildren(...parts);
  $("#version-out").textContent = "";
}

async function prepareVersion(btn) {
  busy(btn, true);
  try {
    await api("api/updater/prepare", { method: "POST" });
    await loadVersion();
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

async function switchVersion(d, btn) {
  const ok = await confirmDialog({
    title: `Auf Version ${short(d.bereit)} umschalten?`,
    body: [h("p", {}, "Diese Änderungen werden aktiv:"),
      h("ul", { class: "commits" }, (d.commits || []).map((c) => h("li", {}, h("code", {}, short(c.commit)), " ", c.message))),
      h("p", { class: "muted" }, "Das Tool ist nur wenige Sekunden weg. Startet die neue Version nicht sauber, schaltet der Dienst automatisch auf die alte zurück.")],
    okLabel: "Umschalten",
  });
  if (!ok) return;
  const from = ((S.version || {}).current || {}).commit;
  busy(btn, true);
  try {
    await api("api/updater/apply", { method: "POST", body: { bereit: d.bereit } });
  } catch (e) {
    toast(e.message, true); busy(btn, false); return;
  }
  $("#version-host").replaceChildren(h("div", { class: "banner warn" }, "Schalte um … die Seite lädt gleich von selbst neu."));
  const started = Date.now();
  const poll = async () => {
    const now = await fetch("api/version", { cache: "no-store", headers: { "X-Requested-With": "pflege" } })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (now && now.current && now.current.commit && now.current.commit !== from) return location.reload();
    if (now && now.dienst && now.dienst.phase === "fehler") { S.version = now; return loadVersion(); }
    if (Date.now() - started > 5 * 60 * 1000) { toast("Umschalten dauert ungewöhnlich lange – Status prüfen", true); return loadVersion(); }
    setTimeout(poll, 3000);
  };
  setTimeout(poll, 3000);
}

/* --------------------------------------------------------------- Hilfe */
// Kleiner Markdown-Renderer für die Hilfetexte (Überschriften, Absätze, Listen, Tabellen,
// **fett**, *kursiv*, `Code`). Der Text wird vorher escaped – kein HTML aus den Dateien.
function mdInline(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
}

function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const head = line.match(/^(#{1,3})\s+(.*)$/);
    if (head) { out.push(`<h${head[1].length}>${mdInline(head[2])}</h${head[1].length}>`); i++; continue; }
    if (line.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith("|")) { rows.push(lines[i]); i++; }
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => mdInline(c.trim()));
      const body = rows.filter((r, idx) => !(idx === 1 && /^\|[\s:|-]+\|$/.test(r.trim())));
      const [first, ...rest] = body;
      out.push(`<div class="table-wrap"><table><thead><tr>${cells(first).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>` +
        rest.map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>");
      continue;
    }
    const list = line.match(/^(\s*)([-*]|\d+\.)\s+/);
    if (list) {
      const ordered = /\d/.test(list[2]);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        const indent = lines[i].match(/^\s*/)[0].length;
        const text = mdInline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        items.push(indent ? `<ul><li>${text}</li></ul>` : `<li>${text}</li>`);
        i++;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.join("").replace(/<\/ul><ul>/g, "")}</${tag}>`);
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#|\||\s*([-*]|\d+\.)\s)/.test(lines[i])) { para.push(lines[i]); i++; }
    out.push(`<p>${mdInline(para.join(" "))}</p>`);
  }
  return out.join("\n");
}

async function openHelp(topic) {
  const body = $("#help-body");
  body.innerHTML = "<p>Lade …</p>";
  $("#help-dlg").showModal();
  try {
    const resp = await fetch("api/help/" + topic, { headers: { "X-Requested-With": "pflege" } });
    if (!resp.ok) throw new Error("Hilfe nicht verfügbar");
    body.innerHTML = renderMarkdown(await resp.text());
  } catch (e) {
    body.replaceChildren(h("div", { class: "banner err" }, e.message));
  }
  $("#help-dlg").scrollTop = 0;
}



/* -------------------------------------------------------------- Alben */
const PAGE_ALB = 20;
const ALB_STATUS = { neu: "Neues Album", ergaenzen: "Album ergänzen", vorhanden: "Schon in Alben" };

async function loadAlbums(reset) {
  const a = S.alb;
  if (reset) { a.trips = []; a.sel.clear(); a.choice = {}; $("#alb-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const params = new URLSearchParams({ offset: a.trips.length, limit: PAGE_ALB, ignoriert: a.ignored });
  if (a.status) params.set("status", a.status);
  if (a.jahr) params.set("jahr", a.jahr);
  const r = await api("api/album-suggestions?" + params);
  if (a.jahr && !r.jahre.some((j) => j.key === a.jahr)) { a.jahr = null; return loadAlbums(true); }
  if (reset) $("#alb-list").replaceChildren();
  a.total = r.gesamt; a.info = r; a.loaded = true;
  renderAlbumFilters(r);
  for (const t of r.reisen) {
    a.trips.push(t);
    $("#alb-list").append(renderTrip(t));
  }
  if (!a.trips.length) {
    $("#alb-list").replaceChildren(h("p", { class: "empty" },
      !r.zuhause.length ? "Noch keine Fotos mit GPS – ohne Zuhause lassen sich keine Reisen erkennen."
        : a.ignored ? "Keine ausgeblendeten Reisen." : a.status === "vorhanden" ? "Noch keine Reise liegt vollständig in Alben."
          : a.jahr || a.status ? "Nichts mit diesem Filter." : "Alle Reisen liegen schon in Alben 🎉"));
  }
  const home = r.zuhause.map((z) => z.name).join(", ");
  $("#alb-summary").textContent = home
    ? `Zuhause: ${home} · Reise ab ${r.min_km} km und ${r.min_medien} Medien · ${n(r.alben, "Album", "Alben")} beider Benutzer abgeglichen`
    : "";
  if (!a.status && !a.jahr && !a.ignored) $("#count-alb").textContent = r.offen ? `(${r.offen})` : "";
  $("#alb-more").hidden = a.trips.length >= a.total;
  updateActionbar();
}

function renderAlbumFilters(r) {
  const a = S.alb;
  const statusSel = h("select", { onchange: (e) => { a.status = e.target.value || null; loadTab("alb", true); } },
    h("option", { value: "" }, `offen (${r.offen})`),
    ...Object.entries(ALB_STATUS).map(([k, v]) => h("option", { value: k }, `${v} (${r.status[k]})`)));
  statusSel.value = a.status || "";
  const yearSel = h("select", { onchange: (e) => { a.jahr = e.target.value || null; loadTab("alb", true); } },
    h("option", { value: "" }, "alle Jahre"),
    ...r.jahre.map((j) => h("option", { value: j.key }, `${j.key} (${j.anzahl})`)));
  yearSel.value = a.jahr || "";
  $("#alb-filters").replaceChildren(
    h("label", { class: "field grow" }, "Zeigen", statusSel),
    h("label", { class: "field grow" }, "Jahr", yearSel),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: a.ignored,
      onchange: (e) => { a.ignored = e.target.checked; loadTab("alb", true); } }), `ausgeblendete (${r.ignoriert})`));
}

function fmtTripRange(t) {
  const f = (s) => s.slice(8, 10) + "." + s.slice(5, 7) + ".";
  const y = t.ende.slice(0, 4);
  return t.tage === 1 ? `${f(t.start)}${y}` : `${f(t.start)}${t.start.slice(0, 4) !== y ? t.start.slice(0, 4) : ""} – ${f(t.ende)}${y}`;
}

function albumLabel(al) {
  const shared = al.geteilt_mit.length ? `, geteilt mit ${al.geteilt_mit.join(", ")}` : "";
  return `„${al.name}“ (${al.besitzer}${shared})`;
}

// Gewähltes Ziel einer Reise: Album-ID oder null (= neues Album)
function tripChoice(t) {
  const c = S.alb.choice[t.id];
  if (c && "album" in c) return c;
  return { album: t.status === "ergaenzen" && t.album ? t.album.id : null, name: t.name };
}

function renderTrip(t) {
  const a = S.alb;
  const card = h("article", { class: "card" + (a.sel.has(t.id) ? " selected" : "") });
  const users = Object.entries(t.benutzer).map(([u, c]) => `${u} ${c}`).join(" · ");
  const status = t.status === "vorhanden" ? "conf-hoch" : t.status === "ergaenzen" ? "conf-mittel" : "conf-niedrig";
  const head = h("div", { class: "card-head" },
    t.status !== "vorhanden" && !a.ignored ? h("input", { type: "checkbox", checked: a.sel.has(t.id), "aria-label": "Reise auswählen",
      onchange: (e) => { e.target.checked ? a.sel.add(t.id) : a.sel.delete(t.id); card.classList.toggle("selected", e.target.checked); updateActionbar(); } }) : null,
    h("div", { class: "grow" }, h("h2", {}, "🧳 " + t.name),
      h("span", { class: "muted" }, `${fmtTripRange(t)} · ${n(t.tage, "Tag", "Tage")} · ${n(t.anzahl, "Medium", "Medien")}`)),
    h("span", { class: "chip " + status }, t.status_text));
  card.append(head,
    h("div", { class: "muted small" }, users + (t.orte.length ? " · " + t.orte.join(", ") : "")));

  // Was es schon gibt
  const found = h("div", { class: "alb-found" });
  if (t.status === "vorhanden") {
    found.append(t.album ? `Liegt schon in ${albumLabel(t.album)}.` : "Liegt schon verteilt in Alben:");
    if (t.fehlend && t.album) found.append(` ${n(t.fehlend, "Medium fehlt", "Medien fehlen")} noch.`);
  } else if (t.status === "ergaenzen") {
    found.append(`Passendes Album gefunden: ${albumLabel(t.album)} – enthält ${t.album.in_reise} von ${t.anzahl}, ${t.fehlend} fehlen.`);
  } else {
    found.append(`Kein passendes Album – geprüft: ${n(S.alb.info.alben, "Album", "Alben")} beider Benutzer.`);
  }
  const others = t.kandidaten.filter((k) => !t.album || k.id !== t.album.id);
  if (others.length) found.append(h("div", { class: "muted small" }, (t.status === "vorhanden" && !t.album ? "" : "Auch Fotos in: ")
    + others.map((k) => `„${k.name}“ (${k.in_reise})`).join(", ")));
  card.append(found);

  if (t.beispiele.length) card.append(h("div", { class: "strip" }, t.beispiele.map((m) => thumb(m))));

  if (a.ignored) {
    card.append(h("div", { class: "row-gap" }, h("button", { type: "button", class: "btn small", onclick: () => ignoreTrip(t, true) }, "Wieder aufnehmen")));
    return card;
  }
  if (t.status === "vorhanden" && !t.fehlend) return card;

  // Ziel wählen: vorhandenes Album ergänzen oder neues anlegen
  const choice = tripChoice(t);
  const nameIn = h("input", { type: "text", value: choice.name || t.name, "aria-label": "Name des neuen Albums",
    oninput: (e) => { a.choice[t.id] = { ...tripChoice(t), name: e.target.value }; } });
  const nameRow = h("label", { class: "f alb-name" }, "Name des neuen Albums", nameIn);
  nameRow.hidden = choice.album !== null;
  const targets = t.kandidaten.filter((k) => k.besitzer !== "anderer Benutzer");
  const sel = h("select", { onchange: (e) => {
    const album = e.target.value || null;
    a.choice[t.id] = { album, name: nameIn.value };
    nameRow.hidden = album !== null;
  } },
    ...targets.map((k) => h("option", { value: k.id }, `„${k.name}“ ergänzen`)),
    h("option", { value: "" }, "Neues Album anlegen"));
  sel.value = choice.album || "";
  card.append(h("label", { class: "f" }, "Ziel", sel), nameRow,
    h("div", { class: "row-gap" },
      h("button", { type: "button", class: "btn small primary", onclick: (e) => stageTrips([t], e.currentTarget) }, "Vormerken"),
      h("button", { type: "button", class: "btn small", onclick: () => ignoreTrip(t, false) }, "Kein Album")));
  return card;
}

async function stageTrips(trips, btn) {
  const body = { trips: trips.map((t) => {
    const c = tripChoice(t);
    return c.album ? { id: t.id, album: c.album } : { id: t.id, album: null, name: (c.name || t.name).trim() };
  }) };
  if (trips.length > 1) {
    const ok = await confirmDialog({
      title: "Alben vormerken?",
      body: [h("ul", {}, trips.map((t) => {
        const c = tripChoice(t);
        const al = t.kandidaten.find((k) => k.id === c.album);
        return h("li", {}, al ? `${t.name}: „${al.name}“ ergänzen` : `${t.name}: neues Album „${(c.name || t.name).trim()}“`);
      })), h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter ✓ Vorgemerkt.")],
      okLabel: "Vormerken",
    });
    if (!ok) return;
  }
  busy(btn, true);
  try {
    const r = await api("api/staged/albums", { method: "POST", body });
    toast(`${n(r.vorgemerkt, "Album", "Alben")} vorgemerkt` + (r.hinweise.length ? " – mit Hinweisen, siehe ✓" : ""));
    await afterStage("alb");
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

async function ignoreTrip(t, undo) {
  try {
    await api("api/album-suggestions/ignore", { method: "POST", body: { trips: [t.id], undo } });
    toast(undo ? "Reise wieder aufgenommen" : "Ausgeblendet – kein Album für diese Reise");
    await loadTab("alb", true);
  } catch (e) {
    toast(e.message, true);
  }
}

/* -------------------------------------------------------- Vorgemerkt */
const STAGE_TYPES = [["duplikat", "Duplikate"], ["ort", "Orte"], ["album", "Alben"], ["tag", "Tags"]];
const STAGE_ACTION = { papierkorb: "Papierkorb", album: "Prüf-Album", keine: "–" };

// Nach dem Vormerken: Quelle neu laden (Vorgemerktes ist dort weg) und Zähler aktualisieren
async function afterStage(tab) {
  S.stage.loaded = false;
  await Promise.all([loadTab(tab, true), loadTab("stage", true)]);
}

async function loadStaged() {
  const r = await api("api/staged");
  S.stage.entries = r.eintraege;
  S.stage.info = r;
  S.stage.loaded = true;
  renderStaged();
}

function stageMedia(e) {
  return h("div", { class: "strip" }, e.medien.map((m) => {
    let cap = "";
    if (e.typ === "duplikat") cap = m.bleibt ? "bleibt" : (STAGE_ACTION[m.aktion] || "–");
    else if (e.typ === "ort") cap = m.neuer_ort || "";
    return h("figure", { class: "stage-fig" + (e.typ === "duplikat" ? (m.bleibt ? " keep" : " drop") : "") },
      thumb(m), cap ? h("figcaption", {}, cap) : null);
  }));
}

function renderStaged() {
  const st = S.stage;
  const cnt = st.info ? st.info.anzahl : 0;
  $("#count-stage").textContent = cnt ? `(${cnt})` : "";
  const list = $("#stage-list");
  list.replaceChildren();
  $("#stage-summary").textContent = cnt
    ? `${n(cnt, "Eintrag", "Einträge")} · ${n(st.info.medien, "Medium", "Medien")}` + (st.info.papierkorb ? ` · ${st.info.papierkorb} in den Papierkorb` : "")
    : "";
  if (!cnt) {
    list.append(h("div", { class: "empty" }, h("p", {}, "Nichts vorgemerkt."),
      h("p", {}, "Was du in den anderen Tabs vormerkst, landet hier – noch ohne Änderung in Immich.")));
    updateActionbar();
    return;
  }
  for (const [typ, label] of STAGE_TYPES) {
    const entries = st.entries.filter((e) => e.typ === typ);
    if (!entries.length) continue;
    list.append(h("h2", { class: "stage-head" }, `${label} (${entries.length})`));
    for (const e of entries) {
      const trash = typ === "duplikat" ? e.daten.schritte.filter((s) => s.aktion === "papierkorb").length : 0;
      list.append(h("article", { class: "card" },
        h("div", { class: "card-head" },
          h("div", {}, h("h2", {}, e.titel),
            h("span", { class: "muted" }, `${n(e.anzahl, "Medium", "Medien")} · vorgemerkt ${fmtDateTime(e.erstellt)}`)),
          trash ? h("span", { class: "chip" }, `🗑 ${trash}`) : null),
        e.fehler ? h("div", { class: "banner err" }, "Letzte Übertragung fehlgeschlagen: " + e.fehler) : null,
        typ === "album" && e.daten.hinweise.length ? h("div", { class: "banner warn" }, e.daten.hinweise.join(" · ")) : null,
        e.medien.length ? stageMedia(e) : null,
        h("div", { class: "row-gap stage-actions" },
          h("button", { type: "button", class: "btn small", onclick: (ev) => unstage(e, ev.currentTarget) }, "Zurücknehmen"),
          h("button", { type: "button", class: "btn small primary", onclick: (ev) => applyStaged([e.id], ev.currentTarget) }, "Übertragen"))));
    }
  }
  updateActionbar();
}

const STAGE_SOURCE = { duplikat: "dup", ort: "loc", album: "alb", tag: "tags" };

async function unstage(e, btn) {
  busy(btn, true);
  try {
    await api("api/staged/" + encodeURIComponent(e.id), { method: "DELETE" });
    toast("Zurückgenommen – wieder in der Übersicht");
    const src = STAGE_SOURCE[e.typ];
    await Promise.all([loadTab("stage", true), S[src].loaded ? loadTab(src, true) : null]);
  } catch (err) {
    toast(err.message, true);
    busy(btn, false);
  }
}

async function applyStaged(ids, btn) {
  const entries = S.stage.entries.filter((e) => !ids || ids.includes(e.id));
  if (!entries.length) return;
  const trash = entries.filter((e) => e.typ === "duplikat")
    .reduce((a, e) => a + e.daten.schritte.filter((s) => s.aktion === "papierkorb").length, 0);
  const lines = STAGE_TYPES.map(([typ, label]) => {
    const es = entries.filter((e) => e.typ === typ);
    return es.length ? h("li", {}, `${label}: ${n(es.length, "Eintrag", "Einträge")}, ${n(es.reduce((a, e) => a + e.anzahl, 0), "Medium", "Medien")}`) : null;
  });
  const ok = await confirmDialog({
    title: ids && ids.length === 1 ? "Eintrag übertragen?" : "Alles übertragen?",
    body: [h("p", {}, "Jetzt werden die Änderungen in Immich ausgeführt:"), h("ul", {}, lines),
      trash ? h("p", {}, `${n(trash, "Medium geht", "Medien gehen")} in den Papierkorb (in Immich wiederherstellbar).`) : null],
    okLabel: "Übertragen",
    danger: !!trash,
    checkLabel: trash ? `Ja, ${trash} in den Papierkorb` : null,
  });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/staged/apply", { method: "POST", body: { ids: entries.map((e) => e.id), confirm: trash ? "PAPIERKORB" : null } });
    if (r.fehler) toast(`${r.uebertragen} übertragen, ${r.fehler} fehlgeschlagen`, true);
    else toast(`${n(r.uebertragen, "Eintrag", "Einträge")} an Immich übertragen`);
    const sources = new Set(entries.map((e) => STAGE_SOURCE[e.typ]));
    await Promise.all([loadTab("stage", true), ...[...sources].filter((t) => S[t].loaded).map((t) => loadTab(t, true))]);
    loadStatus(false);
  } catch (err) {
    toast(err.message, true);
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
    if (S.dup.ignored) {
      info.textContent = "Ausgeblendete Gruppen – „Wieder aufnehmen“ pro Gruppe";
    } else if (cnt) {
      info.textContent = `${cnt} gewählt`;
      buttons.push(h("button", { class: "btn small", type: "button", onclick: () => {
        S.dup.sel.clear();
        $("#dup-list").replaceChildren(...S.dup.groups.map(renderGroup));
        updateActionbar();
      } }, "Keine"));
      buttons.push(h("button", { class: "btn small primary", type: "button", onclick: (e) => applyDuplicates("album", e.currentTarget) }, "Ins Prüf-Album"));
      buttons.push(h("button", { class: "btn small danger", type: "button", onclick: (e) => applyDuplicates("papierkorb", e.currentTarget) }, "Papierkorb"));
    } else {
      const open = S.dup.open || 0;
      info.textContent = open ? "Aktuelle Auswahl:" : "Nichts offen";
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !open, onclick: (e) => applyAllDuplicates("album", e.currentTarget) }, `Alle ins Album (${open})`));
      buttons.push(h("button", { class: "btn small danger", type: "button", disabled: !open, onclick: (e) => applyAllDuplicates("papierkorb", e.currentTarget) }, "Papierkorb …"));
    }
  } else if (S.tab === "loc") {
    const cnt = S.loc.sel.size;
    const sure = S.loc.info ? S.loc.info.nach_sicherheit.hoch : 0;
    info.textContent = cnt ? n(cnt, "Medium", "Medien") + " gewählt" : "Serie vormerken oder Bilder antippen";
    if (cnt) {
      const chosen = S.loc.series.flatMap((s) => s.medien).filter((m) => S.loc.sel.has(m.id));
      buttons.push(h("button", { class: "btn small", type: "button", onclick: () => openPlaceSearch({ ids: [...S.loc.sel], count: cnt, label: "Auswahl" }) }, "Ort wählen …"));
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !chosen.some(selectable), onclick: (e) => applyLocation(e.currentTarget) }, "Vormerken"));
    } else {
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !sure, onclick: (e) => applyAllSure(e.currentTarget) }, `Alle sicheren (${sure})`));
    }
  } else if (S.tab === "alb") {
    const a = S.alb;
    const open = a.trips.filter((t) => t.status !== "vorhanden");
    const chosen = open.filter((t) => a.sel.has(t.id));
    if (a.ignored) {
      info.textContent = "Ausgeblendete Reisen";
    } else if (chosen.length) {
      info.textContent = `${n(chosen.length, "Reise", "Reisen")} gewählt`;
      buttons.push(h("button", { class: "btn small primary", type: "button", onclick: (e) => stageTrips(chosen, e.currentTarget) }, "Vormerken"));
    } else {
      info.textContent = open.length ? "Reisen anhaken oder einzeln vormerken" : "Nichts offen";
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !open.length,
        onclick: (e) => stageTrips(open, e.currentTarget) }, `Alle angezeigten (${open.length})`));
    }
  } else if (S.tab === "stage") {
    const st = S.stage.info;
    const cnt = st ? st.anzahl : 0;
    info.textContent = cnt ? `${n(cnt, "Eintrag", "Einträge")} · ${n(st.medien, "Medium", "Medien")}` : "Nichts vorgemerkt";
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !cnt, onclick: (e) => applyStaged(null, e.currentTarget) }, `Alle übertragen (${cnt})`));
  } else if (S.tab === "set") {
    const locked = S.set.data && S.set.data.gesperrt.length;
    info.textContent = locked ? "Gesperrte Felder stammen aus der .env" : "Änderungen gelten sofort";
    buttons.push(h("button", { class: "btn small primary", type: "button", onclick: (e) => saveSettings(e.currentTarget) }, "Speichern"));
  } else {
    const cnt = S.tags.sel.size;
    const total = S.tags.rules.filter((r) => S.tags.sel.has(r.name)).reduce((a, r) => a + (r.neu || 0), 0);
    info.textContent = cnt ? `${n(cnt, "Regel", "Regeln")} · ${n(total, "Medium", "Medien")}` : "Regeln anhaken";
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !cnt, onclick: (e) => applyTags(e.currentTarget) }, "Tags vormerken"));
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

const TAB_TARGET = { dup: "#dup-list", loc: "#loc-list", alb: "#alb-list", tags: "#tags-list", stage: "#stage-list", set: "#set-welcome" };

async function doLoadTab(tab, force) {
  try {
    if (tab === "dup" && (force || !S.dup.loaded)) await loadDuplicates(true);
    if (tab === "loc" && (force || !S.loc.loaded)) await loadLocation(true);
    if (tab === "alb" && (force || !S.alb.loaded)) await loadAlbums(true);
    if (tab === "tags" && (force || !S.tags.loaded)) await loadTags();
    if (tab === "stage" && (force || !S.stage.loaded)) await loadStaged();
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
  for (const t of ["dup", "loc", "alb", "tags", "stage"]) if (t !== S.tab) loadTab(t).then(updateActionbar);
}

/* ------------------------------------------------------------- Start */
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$("#scan-btn").addEventListener("click", rescan);
$("#dup-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadDuplicates(false).finally(() => busy(e.currentTarget, false)); });
$("#loc-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadLocation(false).finally(() => busy(e.currentTarget, false)); });
$("#dup-done").addEventListener("change", (e) => { S.dup.includeDone = e.target.checked; loadTab("dup", true); });
$("#loc-only").addEventListener("change", (e) => { S.loc.only = e.target.checked; loadTab("loc", true); });
$("#loc-conf").addEventListener("change", (e) => { S.loc.minConf = e.target.value || null; loadTab("loc", true); });
$("#place-q").addEventListener("input", () => { clearTimeout(placeTimer); placeTimer = setTimeout(searchPlaces, 300); });
$("#loc-hours").addEventListener("change", (e) => {
  const v = parseFloat(String(e.target.value).replace(",", "."));
  if (v > 0 && v <= 48) { S.loc.hours = v; loadTab("loc", true); } else { e.target.value = S.loc.hours; }
});
$("#alb-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadAlbums(false).finally(() => busy(e.currentTarget, false)); });
$("#tags-reload").addEventListener("click", () => loadTab("tags", true));
document.querySelectorAll(".help-btn").forEach((b) => b.addEventListener("click", () => openHelp(b.dataset.help)));
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
  await showTab(["dup", "loc", "alb", "tags", "stage", "set"].includes(tab) ? tab : "dup");
  // Nach dem ersten Laden (ggf. Einlesen) Status aktualisieren und Zähler der anderen Tabs holen
  loadStatus(false);
  loadOtherCounts();
})();
