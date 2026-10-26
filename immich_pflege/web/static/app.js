"use strict";

const PAGE_DUP = 20;

const S = {
  tab: "dup",
  status: null,
  dup: { groups: [], total: 0, open: 0, keep: {}, sel: new Set(), includeDone: false, art: null, monat: null, crossUser: false, ignored: false, loaded: false, info: null },
  loc: { series: [], total: 0, sel: new Set(), open: new Set(), hours: null, only: false, minConf: null, ort: null, monat: null, herkunft: null, loaded: false, info: null },
  ovw: { loaded: false },
  cln: { bereich: "speicher", kategorie: null, ignored: false, items: [], total: 0, sel: new Set(), keep: {}, loaded: false, info: null },
  fol: { items: [], status: null, ignored: false, choice: {}, sync: {}, ohne: {} },
  alb: { quelle: "reisen", trips: [], total: 0, status: null, jahr: null, ignored: false, sel: new Set(), choice: {}, ohne: {}, open: {}, loaded: false, info: null },
  sug: { items: [], hidden: false, info: null, smart: null, cut: null, tag: "" },
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
function fmtBig(b) {
  if (!b) return "0 MB";
  return b >= 1073741824 ? (b / 1073741824).toFixed(1).replace(".", ",") + " GB" : Math.round(b / 1048576) + " MB";
}

function fmtDur(s) {
  if (!s) return "";
  const t = Math.round(s), hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = String(t % 60).padStart(2, "0");
  return hh ? `${hh}:${String(mm).padStart(2, "0")}:${ss}` : `${mm}:${ss}`;
}

// Vorschaubild; Videos bekommen ihre Länge als Plakette („▶ 1:23“)
function thumb(m, alt) {
  const img = h("img", { src: m.thumb || ("thumb/" + m.id), loading: "lazy", decoding: "async", alt: alt || m.dateiname || "" });
  img._m = m;  // für die Großansicht
  if (m.typ !== "video") return img;
  return h("span", { class: "thumb-wrap" }, img,
    h("span", { class: "vid-badge", title: m.dauer_s ? `Video, ${fmtDur(m.dauer_s)}` : "Video" }, "▶" + (m.dauer_s ? " " + fmtDur(m.dauer_s) : "")));
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
    h("button", { type: "button", class: "v-open", title: "Groß ansehen" }, "Groß"),
    h("a", { href: "immich://asset?id=" + encodeURIComponent(m.id), title: "In der Immich-App öffnen" }, "App ↗"),
    web ? h("a", { href: `${web}/photos/${encodeURIComponent(m.id)}`, target: "_blank", rel: "noopener", title: "In Immich im Browser öffnen" }, "Web ↗") : null);
}

/* -------------------------------------------------------- Großansicht */
const zoomBtn = () => h("button", { type: "button", class: "v-open zoom", title: "Groß ansehen", "aria-label": "Groß ansehen" }, "⤢");
// Jedes Vorschaubild (img._m) lässt sich groß ansehen: in Streifen per Antippen, in Kacheln über „Groß“.
// Geblättert wird innerhalb derselben Gruppe (Raster bzw. Streifen).
const VW = { list: [], i: 0 };

function openViewerFrom(el) {
  const img = el._m ? el : (el.closest(".tile, .smart-tile, .stage-fig, .thumb-wrap") || el.parentElement).querySelector("img");
  if (!img || !img._m) return;
  const box = img.closest(".grid, .strip, .smart-grid, .rv-grid");
  // box._list: ganze Gruppe, auch wenn nur die ersten Kacheln angezeigt werden
  const list = box && box._list ? box._list : box ? [...box.querySelectorAll("img")].map((x) => x._m).filter(Boolean) : [img._m];
  VW.list = list;
  VW.i = Math.max(0, list.findIndex((x) => x.id === img._m.id));
  renderViewer();
  const dlg = $("#viewer");
  if (!dlg.open) dlg.showModal();
}

function renderViewer() {
  const m = VW.list[VW.i];
  if (!m) return;
  const img = $("#v-img");
  img.src = "thumb/" + m.id;  // kleines Bild sofort, das große lädt darüber
  const big = new Image();
  big.onload = () => { if (VW.list[VW.i] === m) img.src = big.src; };
  big.src = "thumb/" + m.id + "?size=preview";
  img.alt = m.dateiname || "";
  const next = VW.list[VW.i + 1];
  if (next) new Image().src = "thumb/" + next.id + "?size=preview";
  $("#v-count").textContent = VW.list.length > 1 ? `${VW.i + 1} / ${VW.list.length}` : "";
  $("#v-prev").hidden = VW.i === 0;
  $("#v-next").hidden = VW.i >= VW.list.length - 1;
  const when = m.neue_zeit ? `${fmtTaken(m.aufnahme)} → ${fmtTaken(m.neue_zeit)}` : fmtTaken(m.aufnahme);
  $("#v-info").replaceChildren(...[
    h("div", { class: "v-name" }, m.dateiname || ""),
    h("div", {}, [when, m.benutzer, m.extern ? "extern" : "", m.typ === "video" ? `Video${m.dauer_s ? " " + fmtDur(m.dauer_s) : ""} – abspielen in Immich` : ""].filter(Boolean).join(" · ")),
    m.ort ? h("div", {}, "📍 " + m.ort) : null,
    m.pfad ? h("div", { class: "v-path" }, m.pfad) : null,
    m.check ? h("div", { class: "v-check" }, h("button", { type: "button", class: "v-btn small", onclick: (e) => checkAlbum(m, e.currentTarget) },
      "Liegt doch schon im Album? Bei Immich nachfragen")) : null,
    openLinks(m)].filter(Boolean));
}

async function checkAlbum(m, btn) {
  busy(btn, true);
  try {
    const r = await api(`api/album-check?asset=${m.id}&album=${m.check}`);
    btn.replaceWith(h("div", { class: "v-result" + (r.im_album_immich || r.kopie ? " ok" : "") }, r.text));
    if (r.korrigiert) {
      S.alb.loaded = false;
      toast("Album neu gelesen – die Vorschläge werden aktualisiert");
      if (S.tab === "alb") loadTab("alb", true);
      loadCounts();
    }
  } catch (e) { toast(e.message, true); busy(btn, false); }
}

function viewerStep(d) {
  const i = VW.i + d;
  if (i < 0 || i >= VW.list.length) return;
  VW.i = i;
  renderViewer();
}

document.addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof Element) || t.closest("#viewer")) return;
  const zoom = t.closest(".v-open");
  if (zoom) { e.preventDefault(); e.stopPropagation(); openViewerFrom(zoom); return; }
  // Streifen (Beispielbilder, Falsche Zeit, Vorgemerkt): Bild antippen
  if (t.tagName === "IMG" && t._m && t.closest(".strip") && !t.closest("button, [role=button], a")) openViewerFrom(t);
}, true);

// Album öffnen: Immich-App (immich://album?id=…) oder Weboberfläche (/albums/<id>)
function albumLinks(al) {
  const web = S.status && S.status.link_url;
  return h("span", { class: "open-links inline" },
    h("a", { href: "immich://album?id=" + encodeURIComponent(al.id), title: `„${al.name}“ in der Immich-App öffnen` }, "App ↗"),
    web ? h("a", { href: `${web}/albums/${encodeURIComponent(al.id)}`, target: "_blank", rel: "noopener",
      title: `„${al.name}“ in Immich im Browser öffnen` }, "Web ↗") : null);
}

function busy(btn, on) {
  if (!btn) return;
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
  if (st.vorgemerkt) setCount("stage", st.vorgemerkt.anzahl);
  const parts = [];
  if (st.einlesen_laeuft) parts.push("⟳ Einlesen" + (st.fortschritt ? ": " + st.fortschritt : " …"));
  else if (st.alben_laeuft) parts.push("⟳ " + (st.fortschritt || "Alben lesen …"));
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
  // läuft gerade ein Einlesen (z. B. automatisch oder vor dem Neuladen der Seite gestartet): mitverfolgen
  if ((st.einlesen_laeuft || st.alben_laeuft) && !scanWatching) watchScan();
  return st;
}

// Einlesen läuft im Hintergrund (ein großes komplettes Einlesen dauert Minuten – länger, als Browser
// oder Proxy auf eine Antwort warten). Die Oberfläche fragt den Fortschritt ab und lädt danach neu.
async function rescan(full = false, btn = $("#scan-btn")) {
  busy(btn, true);
  try {
    try {
      await api("api/scan", { method: "POST", body: { wait: false, full } });
    } catch (e) {
      if (e.status !== 409) throw e;  // läuft schon: einfach mit beobachten
    }
    toast(full ? "Komplettes Einlesen läuft im Hintergrund – du kannst weiterarbeiten" : "Einlesen läuft im Hintergrund …");
    await watchScan(true);
  } catch (e) {
    toast("Einlesen fehlgeschlagen: " + e.message, true);
  } finally {
    busy(btn, false);
  }
}

let scanWatching = null;
function watchScan(started = false) {
  if (!scanWatching) scanWatching = doWatchScan(started).finally(() => { scanWatching = null; });
  return scanWatching;
}

// started: selbst gestartet (kann schon fertig sein, bevor die erste Abfrage kommt)
async function doWatchScan(started) {
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  $("#scan-btn").disabled = true;
  let scanned = started, reloaded = false;
  try {
    for (;;) {
      await pause(2000);
      let st;
      try { st = await loadStatus(false); } catch (_) { continue; }  // kurze Aussetzer überstehen
      if (!st) continue;
      if (st.einlesen_laeuft) { scanned = true; continue; }
      if (scanned && !reloaded) {
        reloaded = true;
        if (st.letzter_fehler) { toast("Einlesen fehlgeschlagen: " + st.letzter_fehler, true); return; }
        const b = st.bibliothek;
        if (b) toast(`${b.gesamt.toLocaleString("de-DE")} Medien in ${String(b.dauer_s).replace(".", ",")} s eingelesen`);
        S.dup.loaded = S.loc.loaded = S.alb.loaded = S.tags.loaded = S.cln.loaded = S.ovw.loaded = false;
        loadTab(S.tab, true);
        loadCounts();
      }
      if (!st.alben_laeuft) {  // Alben werden nach dem Einlesen im Hintergrund gelesen
        S.alb.loaded = S.ovw.loaded = false;
        if (["alb", "ovw"].includes(S.tab) || (S.tab === "cln" && ["alben", "stapel"].includes(S.cln.bereich))) loadTab(S.tab, true);
        loadCounts();
        return;
      }
    }
  } finally {
    $("#scan-btn").disabled = false;
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
  if (!d.art && !d.monat && !d.crossUser && !d.ignored) setCount("dup", r.offen);
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
      `Bild-Fingerabdrücke werden berechnet: ${fp.fertig} von ${fp.gesamt} (${pct} %). Ähnliche Kopien kommen danach dazu – die Liste bleibt bis dahin, wie sie ist.`,
      h("progress", { max: fp.gesamt || 1, value: fp.fertig })));
    // nur den Fortschritt nachsehen – die Liste nicht neu laden (Auswahl und Scrollposition bleiben)
    fpTimer = setTimeout(async () => {
      if (S.tab !== "dup") { fpTimer = setTimeout(() => renderFingerprint(fp), 15000); return; }
      const now = await api("api/fingerprints").catch(() => null);
      if (!now) return;
      if (now.laeuft) renderFingerprint(now);
      else box.replaceChildren(h("div", { class: "banner" }, "Bild-Fingerabdrücke fertig. ",
        h("button", { type: "button", class: "btn small", onclick: () => loadTab("dup", true) }, "Neue Treffer anzeigen")));
    }, 15000);
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
      h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter Vorgemerkt.")],
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
      h("div", {}, `${m.benutzer} · ${m.extern ? "extern" : "Upload"}${m.typ === "video" ? " · Video" + (m.dauer_s ? " " + fmtDur(m.dauer_s) : "") : ""}`),
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
  body.push(h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter Vorgemerkt."));
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
  if (l.herkunft) params.set("herkunft", l.herkunft);
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
    (r.extern_erlaubt ? "" : " · externe Bibliotheken gesperrt");
  const tx = r.texterkennung;
  if (tx && tx.laeuft && tx.gesamt) {
    $("#loc-summary").append(` · ⟳ Texterkennung: ${tx.fertig.toLocaleString("de-DE")} von ${tx.gesamt.toLocaleString("de-DE")} Bildern geprüft`);
    watchTextScan();
  }
  const hiddenN = r.screenshots_ausgeblendet + r.kein_ort_ausgeblendet + r.archiviert_ausgeblendet;
  if (hiddenN) {
    const parts = [r.archiviert_ausgeblendet ? `${r.archiviert_ausgeblendet} archiviert` : "",
      r.screenshots_ausgeblendet ? `${r.screenshots_ausgeblendet} Screenshots` : ""].filter(Boolean);
    $("#loc-summary").append(" · ", h("button", { type: "button", class: "linklike", onclick: (e) => openHiddenReview(e.currentTarget) },
      `${hiddenN} ausgeblendet` + (parts.length ? ` (${parts.join(", ")})` : "") + " – ansehen"));
  }
  setCount("ort", r.mit_vorschlag);
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
  // in einem Ort steht der Herkunfts-Filter im Kopf des Orts (mit dessen Zahlen), sonst hier
  const inPlace = l.ort !== null && l.ort !== "*";
  $("#loc-filters").replaceChildren(...[
    h("label", { class: "field grow" }, "Ort", placeSel),
    h("label", { class: "field grow" }, "Monat", monthSel),
    ...(inPlace ? [] : herkunftBar(r))].filter(Boolean));
}

// Herkunft: wo kommt das Bild her? Screenshots, Messenger-Bilder & Co. brauchen meist keinen Ort.
// Die Zahlen gelten für die aktuelle Auswahl (alle Orte bzw. den gewählten Ort und Monat).
function herkunftBar(r) {
  const l = S.loc;
  const chips = h("div", { class: "row-gap herkunft" }, h("span", { class: "muted small" }, "Herkunft:"),
    h("button", { type: "button", class: "chip-btn" + (l.herkunft ? "" : " on"), onclick: () => { l.herkunft = null; loadTab("loc", true); } }, "Alle"),
    ...Object.entries(r.herkunft).filter(([k, v]) => v.anzahl || l.herkunft === k).map(([k, v]) =>
      h("button", { type: "button", class: "chip-btn" + (l.herkunft === k ? " on" : ""), onclick: () => { l.herkunft = k; loadTab("loc", true); } },
        `${HERKUNFT_ICON[k]} ${v.name} (${v.anzahl})`)));
  const hint = l.herkunft && l.herkunft !== "kamera" && r.herkunft[l.herkunft].anzahl
    ? h("div", { class: "banner herkunft-hint" }, `${HERKUNFT_PLURAL[l.herkunft]} brauchen meist keinen Ort. `,
      h("button", { type: "button", class: "btn small", onclick: (e) => openOriginReview(l.herkunft, r.herkunft[l.herkunft].name, e.currentTarget) },
        `Alle ${r.herkunft[l.herkunft].anzahl} prüfen & ausblenden`))
    : null;
  return [chips, hint];
}

// Texterkennung läuft im Hintergrund: Zahlen nachziehen, danach einmal neu laden
let textWatch = null;
function watchTextScan() {
  if (textWatch) return;
  textWatch = setInterval(async () => {
    if (S.tab !== "loc") return;
    let r;
    try { r = await api("api/no-location?overview=true&limit=0"); } catch (_) { return; }
    if (r.texterkennung.laeuft) {
      const el = $("#loc-summary");
      el.childNodes.forEach((nd) => { if (nd.nodeType === 3 && nd.textContent.includes("Texterkennung")) nd.textContent = ` · ⟳ Texterkennung: ${r.texterkennung.fertig.toLocaleString("de-DE")} von ${r.texterkennung.gesamt.toLocaleString("de-DE")} Bildern geprüft`; });
      return;
    }
    clearInterval(textWatch); textWatch = null;
    if (r.herkunft.dokument.anzahl) toast(`Texterkennung fertig: ${r.herkunft.dokument.anzahl} Dokumente und Textbilder ohne Ort`);
    loadTab("loc", true);
  }, 8000);
}

const HERKUNFT_ICON = { kamera: "📷", dokument: "📄", messenger: "💬", ohne_kamera: "🖼", screenshot: "📱" };
const HERKUNFT_KURZ = { dokument: "Dokument/Text", messenger: "Messenger", ohne_kamera: "ohne Kameradaten", screenshot: "Screenshot" };
const HERKUNFT_PLURAL = { dokument: "Dokumente und Textbilder", messenger: "Messenger-Bilder", ohne_kamera: "Bilder ohne Kameradaten", screenshot: "Screenshots" };

// Gewählte Bilder archivieren: vormerken (geht erst beim Übertragen an Immich) und hier ausblenden
async function archiveLocSelection(btn) {
  const ids = [...S.loc.sel];
  busy(btn, true);
  try {
    const res = await api("api/staged/archive", { method: "POST", body: { ids, label: "Ohne Ort – Auswahl" } });
    await api("api/no-location/no-place", { method: "POST", body: { ids } });
    toast(`${n(res.vorgemerkt, "Medium", "Medien")} zum Archivieren vorgemerkt – unter Vorgemerkt übertragen`);
    S.loc.sel.clear(); S.stage.loaded = false;
    await loadTab("loc", true); loadCounts();
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

async function noPlaceLocSelection(btn) {
  const ids = [...S.loc.sel];
  busy(btn, true);
  try {
    await api("api/no-location/no-place", { method: "POST", body: { ids } });
    toast(`${n(ids.length, "Medium", "Medien")} ausgeblendet – zurückholen unter „… ausgeblendet – ansehen“`);
    S.loc.sel.clear();
    await loadTab("loc", true); loadCounts();
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

// Alle Medien einer Herkunft prüfen: „kein Ort nötig“ (dauerhaft ausblenden) oder archivieren
async function openOriginReview(herkunft, name, btn) {
  busy(btn, true);
  let r;
  try {
    const scope = new URLSearchParams({ herkunft });
    if (S.loc.hours) scope.set("max_hours", S.loc.hours);
    if (S.loc.ort && S.loc.ort !== "*") scope.set("ort", S.loc.ort);
    if (S.loc.monat) scope.set("monat", S.loc.monat);
    r = await api("api/no-location/origin-media?" + scope);
  } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const after = async () => { S.loc.loaded = false; await loadTab("loc", true); loadCounts(); };
  openReview({
    titel: `Ohne Ort: ${name}`, medien: r.medien, gruppe: "monat",
    hinweis: "Abwählen, was doch einen Ort bekommen soll. Ausgeblendetes lässt sich unter „… ausgeblendet – ansehen“ zurückholen.",
    aktionen: [
      { text: (k) => `${k} archivieren`, run: async (ids) => {
        const res = await api("api/staged/archive", { method: "POST", body: { ids, label: name } });
        await api("api/no-location/no-place", { method: "POST", body: { ids } });
        toast(`${n(res.vorgemerkt, "Medium", "Medien")} zum Archivieren vorgemerkt und hier ausgeblendet`);
        S.stage.loaded = false; await after();
      } },
      { klasse: "primary", text: (k) => `${k} ausblenden – kein Ort nötig`, run: async (ids) => {
        await api("api/no-location/no-place", { method: "POST", body: { ids } });
        toast(`${n(ids.length, "Medium", "Medien")} ausgeblendet`);
        await after();
      } },
    ],
  });
}

// Ausgeblendetes ansehen (erkannte Screenshots und „kein Ort nötig“) und Gewähltes zurückholen
async function openHiddenReview(btn) {
  busy(btn, true);
  let r;
  try { r = await api("api/no-location/hidden" + (S.loc.hours ? `?max_hours=${S.loc.hours}` : "")); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const label = { kein_ort: "🚫 Kein Ort nötig (von dir ausgeblendet)", archiviert: "🗄 In Immich archiviert", screenshot: "📱 Als Screenshot erkannt" };
  openReview({
    titel: "Ohne Ort: ausgeblendet", medien: r.medien, gruppe: (m) => [m.grund, label[m.grund]], ohne: r.medien.map((m) => m.id),
    hinweis: "Anfangs ist nichts gewählt. Antippen, was doch einen Ort bekommen soll – auch Archiviertes oder falsch erkannte Screenshots.",
    aktionen: [{ klasse: "primary", text: (k) => `${k} wieder einblenden`, run: async (ids) => {
      await api("api/no-location/no-place", { method: "POST", body: { ids, undo: true } });
      toast(`${n(ids.length, "Medium", "Medien")} wieder eingeblendet`);
      S.loc.loaded = false; await loadTab("loc", true); loadCounts();
    } }],
  });
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
      h("div", {}, h("h2", {}, scope), h("span", { class: "muted" }, `${n(r.medien_gefiltert, "Medium", "Medien")} in ${n(r.serien_gesamt, "Serie", "Serien")}`
        + (S.loc.herkunft ? ` · nur ${HERKUNFT_PLURAL[S.loc.herkunft] || r.herkunft[S.loc.herkunft].name}` : "")))),
    h("div", { class: "place-herkunft" }, ...herkunftBar(r).filter(Boolean)),
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
  grid._list = ser.medien;
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
      m.herkunft && m.herkunft !== "kamera" ? h("div", { class: "chip", title: m.text || "" }, `${HERKUNFT_ICON[m.herkunft]} ${HERKUNFT_KURZ[m.herkunft]}`) : null,
      m.text ? h("div", { class: "ocr-text" }, `„${m.text}“`) : null,
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
    const r = await api("api/staged/no-location", { method: "POST",
      body: { ...body, label, max_hours: S.loc.hours, ...(S.loc.herkunft ? { herkunft: S.loc.herkunft } : {}) } });
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

// Alle sicheren Vorschläge prüfen: nach neuem Ort gruppiert, einzelne oder ganze Orte abwählen
async function applyAllSure(btn) {
  busy(btn, true);
  let r;
  try { r = await api(`api/no-location/media?min_confidence=hoch&max_hours=${S.loc.hours}`); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  if (!r.medien.length) { toast("Keine sicheren Vorschläge offen"); return; }
  for (const m of r.medien) m.info = "📍 " + m.ort_neu;
  openReview({
    titel: "Alle sicheren Ortsvorschläge", medien: r.medien,
    gruppe: (m) => [m.ort_neu, "📍 " + m.ort_neu],
    hinweis: "Jedes Bild bekommt den Ort eines GPS-Fotos, das höchstens 30 Minuten entfernt ist oder bei dem die Fotos davor und danach am selben Ort entstanden.",
    aktionen: [{ klasse: "primary", text: (k) => `${k.toLocaleString("de-DE")} verorten`, run: async (ids, ohne) =>
      doApplyLocation(ohne.length ? { ids } : { min_confidence: "hoch" }, null, "Alle sicheren Vorschläge") }],
  });
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

function renderHomes() {
  const homes = S.set.homes || [];
  $("#set-homes").replaceChildren(...(homes.length ? homes.map((hm, i) => h("span", { class: "chip accent" }, "🏠 " + hm.name, " ",
    h("button", { type: "button", class: "chip-x", "aria-label": hm.name + " entfernen",
      onclick: () => { homes.splice(i, 1); renderHomes(); } }, "×"))) : [h("span", { class: "muted small" }, "automatisch")]));
}

let homeTimer;
async function searchHome() {
  const q = $("#set-home-q").value.trim();
  const box = $("#set-home-results");
  if (q.length < 2) { box.replaceChildren(); return; }
  try {
    const list = await api("api/places?q=" + encodeURIComponent(q));
    box.replaceChildren(...list.slice(0, 6).map((p) => h("button", { type: "button", class: "place-item",
      onclick: () => {
        S.set.homes = [...(S.set.homes || []), { name: p.name, breite: p.breite, laenge: p.laenge }].slice(0, 5);
        $("#set-home-q").value = ""; box.replaceChildren(); renderHomes();
        toast("Zuhause gesetzt – bitte speichern");
      } }, h("b", {}, p.name), p.region ? h("span", { class: "muted" }, " · " + p.region) : null)));
  } catch (e) {
    box.replaceChildren(h("div", { class: "banner err" }, e.message));
  }
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
  hersteller: "Hersteller", modell: "Modell", bibliothek: "Bibliothek", typ: "Typ", benutzer: "Benutzer",
  land: "Land", region: "Region", ort: "Ort" };
const COND_KEYS = ["von", "bis", "land", "region", "ort", "bibliothek", "typ", "album", "person", "hersteller", "modell", "dateiname", "pfad", "benutzer"];

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
      if (r.neu && !r.vorgemerkt) card.append(h("div", { class: "row-gap", style: "margin-top:8px" },
        h("button", { type: "button", class: "btn small primary", onclick: (e) => openRuleReview(name, e.currentTarget) }, `Prüfen & taggen (${r.neu})`)));
    }
    list.append(card);
  });
  S.tags.openRules = t.rules.filter((r) => r.aktiv && r.neu).length;
  if (t.items.length) $("#rules-details").open = true;
  updateTagsCount();
  updateActionbar();
}

// Eigene Regel prüfen: alle neuen Treffer, abwählen, dann genau diese taggen
async function openRuleReview(name, btn) {
  busy(btn, true);
  let r;
  try { r = await api(`api/tags/rules/${encodeURIComponent(name)}/media`); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  openReview({
    titel: `${name} → ${r.tags.join(", ")}`, medien: r.medien, gruppe: "monat",
    aktionen: [{ klasse: "primary", text: (k) => `${k.toLocaleString("de-DE")} taggen`, run: async (ids, ohne) => {
      await api(`api/staged/tags/${encodeURIComponent(name)}/auswahl`, { method: "POST", body: { ohne } });
      toast(`${n(ids.length, "Medium", "Medien")} zum Taggen vorgemerkt`);
      await afterStage("tags");
    } }],
  });
}

function updateTagsCount() {
  if (!S.sug.hidden) setCount("tags", (S.sug.items.length || 0) + (S.tags.openRules || 0));
}

/* ------------------------------------------------------ Tag-Vorschläge */
const SUG_ICON = { land: "🌍", kamera: "📷", quelle: "📥" };

async function loadSuggestions() {
  const g = S.sug;
  $("#sug-list").replaceChildren(h("p", { class: "empty" }, "Lade …"));
  const r = await api("api/suggestions?ausgeblendet=" + g.hidden);
  g.items = r.vorschlaege; g.info = r;
  $("#sug-summary").textContent = `${n(r.vorschlaege.length, "Vorschlag", "Vorschläge")}`;
  const cards = r.vorschlaege.map(renderSuggestion);
  const toggle = h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: g.hidden,
    onchange: (e) => { g.hidden = e.target.checked; loadSuggestions(); } }), `ausgeblendete (${r.ausgeblendet})`);
  $("#sug-list").replaceChildren(...(cards.length ? cards : [h("p", { class: "empty" }, g.hidden ? "Nichts ausgeblendet." : "Keine offenen Vorschläge 🎉")]), toggle);
  $("#smart-terms").replaceChildren(...r.begriffe.map((b) => h("button", { type: "button", class: "chip-btn" + (g.smart && g.smart.begriff === b.name ? " on" : ""),
    onclick: () => loadSmart({ begriff: b.name }) }, b.name)));
  updateTagsCount();
  updateActionbar();
}

function renderSuggestion(s) {
  const g = S.sug;
  return h("article", { class: "card" },
    h("div", { class: "card-head" }, h("span", {}, SUG_ICON[s.art] || "🏷"), h("b", {}, s.titel),
      h("span", { class: "chip accent" }, "🏷 " + s.tag),
      h("button", { type: "button", class: "btn small edit", onclick: () => hideSuggestion(s, g.hidden) }, g.hidden ? "Wieder zeigen" : "Kein Interesse")),
    h("div", { class: "muted small" }, `${s.grund} · ${s.neu} noch ohne Tag${s.schon_getaggt ? `, ${s.schon_getaggt} schon getaggt` : ""}`),
    s.beispiele.length ? h("div", { class: "strip" }, s.beispiele.map((m) => thumb(m))) : null,
    g.hidden ? null : h("div", { class: "row-gap", style: "margin-top:8px" },
      s.neu ? h("button", { type: "button", class: "btn small primary", onclick: (e) => openSuggestionReview(s, "tag", e.currentTarget) }, `Prüfen & taggen (${s.neu})`) : null,
      s.neu ? h("button", { type: "button", class: "btn small", title: "Ohne Prüfen: alle Treffer taggen", onclick: (e) => stageSuggestions([s], e.currentTarget) }, "Alle taggen") : null,
      s.art === "quelle" && s.archivierbar ? h("button", { type: "button", class: "btn small", title: "Aus der Zeitleiste nehmen – bleibt in Suche und Alben",
        onclick: (e) => openSuggestionReview(s, "archiv", e.currentTarget) }, `Archivieren … (${s.archivierbar})`) : null));
}

async function stageSuggestions(list, btn) {
  busy(btn, true);
  try {
    await api("api/staged/suggestions", { method: "POST", body: { ids: list.map((s) => s.id) } });
    toast(`${n(list.length, "Vorschlag", "Vorschläge")} vorgemerkt`);
    S.stage.loaded = false;
    await Promise.all([loadSuggestions(), loadTab("stage", true)]);
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

/* ------------------------------------------- Prüf-Ansicht (auch Tausende) */
// Viele Medien als dichtes Raster in Gruppen (Monat, Tag, Rang oder eigene). Einzelne Bilder oder ganze
// Gruppen abwählen; Kacheln entstehen erst, wenn ihre Gruppe in die Nähe des sichtbaren Bereichs kommt.
// cfg: { titel, medien, gruppe: "monat" | "tag" | "rang" | (m) => [key, label], ohne?: ids, extra?: Element,
//        rang?: true (Modus „ab hier abwählen“), hinweis?: text,
//        aktionen: [{ text: (n) => "…", klasse?: "primary" | "danger", run: async (ids, ohne) => schließen? }] }
const RV = { cfg: null, medien: [], off: new Set(), groups: [], mode: "waehlen", size: "m", obs: null };
const RV_PX = { s: 46, m: 84, l: 140 };
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];
const RANK_BLOCK = 50;
const RV_NOUN = { monat: ["Monat", "Monate"], tag: ["Tag", "Tage"], rang: ["Block", "Blöcke"] };

function rvGrouper(cfg) {
  if (typeof cfg.gruppe === "function") return cfg.gruppe;
  if (cfg.gruppe === "rang") {
    return (m, i) => {
      const b = Math.floor(i / RANK_BLOCK);
      return [String(b), `Treffer ${b * RANK_BLOCK + 1}–${Math.min((b + 1) * RANK_BLOCK, cfg.medien.length)}` + (b ? "" : " (passen am besten)")];
    };
  }
  if (cfg.gruppe === "tag") {
    return (m) => {
      if (!m.aufnahme) return ["ohne", "Ohne Datum"];
      const d = new Date(m.aufnahme.slice(0, 10) + "T12:00:00");
      return [m.aufnahme.slice(0, 10), `${WEEKDAYS[d.getDay()]} ${fmtTaken(m.aufnahme).slice(0, 10)}`];
    };
  }
  return (m) => (m.aufnahme ? [m.aufnahme.slice(0, 7), `${MONTHS[parseInt(m.aufnahme.slice(5, 7), 10) - 1]} ${m.aufnahme.slice(0, 4)}`] : ["ohne", "Ohne Datum"]);
}

function openReview(cfg) {
  try { RV.size = localStorage.getItem("pflege-rv-size") || "m"; } catch (_) { /* egal */ }
  Object.assign(RV, { cfg, medien: cfg.medien, off: new Set(cfg.ohne || []), mode: "waehlen" });
  const key = rvGrouper(cfg);
  const groups = new Map();
  cfg.medien.forEach((m, i) => {
    m._i = i;
    const [k, label] = key(m, i);
    if (!groups.has(k)) groups.set(k, { label, list: [] });
    groups.get(k).list.push(m);
  });
  RV.groups = [...groups.values()];
  $("#rv-title").textContent = cfg.titel;
  $("#rv-extra").replaceChildren(...[cfg.extra, cfg.hinweis ? h("p", { class: "muted small" }, cfg.hinweis) : null].filter(Boolean));
  $('[data-rv-mode="ab"]').hidden = !cfg.rang;
  renderReview();
  if (!$("#review").open) $("#review").showModal();
}

function rvCols() {
  const w = $("#rv-body").clientWidth || window.innerWidth;
  return Math.max(3, Math.floor((w + 3) / (RV_PX[RV.size] + 3)));
}

function renderReview() {
  document.querySelectorAll("[data-rv-mode]").forEach((b) => b.classList.toggle("on", b.dataset.rvMode === RV.mode));
  document.querySelectorAll("[data-rv-size]").forEach((b) => b.classList.toggle("on", b.dataset.rvSize === RV.size));
  const body = $("#rv-body");
  body.style.setProperty("--rv-px", RV_PX[RV.size] + "px");
  if (RV.obs) RV.obs.disconnect();
  RV.obs = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) { fillGroup(e.target); RV.obs.unobserve(e.target); }
  }, { root: body, rootMargin: "1200px 0px" });
  const cols = rvCols();
  body.replaceChildren(...RV.groups.map((g, i) => {
    const grid = h("div", { class: "rv-grid", "data-i": i,
      style: `min-height:${Math.ceil(g.list.length / cols) * (RV_PX[RV.size] + 3)}px` });
    RV.obs.observe(grid);
    return h("section", { class: "rv-month" }, groupHead(g), grid);
  }));
  rvJump();
  rvCount();
}

function rvJump() {
  const offIn = (g) => g.list.filter((m) => RV.off.has(m.id)).length;
  $("#rv-jump").hidden = RV.groups.length < 2;
  $("#rv-jump").replaceChildren(h("option", { value: "" }, "Springe zu …"), ...RV.groups.map((g, i) =>
    h("option", { value: i }, `${g.label} (${g.list.length}${offIn(g) ? `, ${offIn(g)} ab` : ""})`)));
}

function groupHead(g) {
  const off = g.list.filter((m) => RV.off.has(m.id)).length;
  const box = h("input", { type: "checkbox", checked: off < g.list.length, "aria-label": "Gruppe auswählen",
    onchange: (e) => {
      for (const m of g.list) e.target.checked ? RV.off.delete(m.id) : RV.off.add(m.id);
      refreshGroup(g);
      rvCount();
    } });
  box.indeterminate = off > 0 && off < g.list.length;
  return h("label", { class: "rv-mhead" }, box, h("b", {}, g.label),
    h("span", { class: "muted small" }, `${g.list.length}${off ? ` · ${off} abgewählt` : ""}`));
}

function fillGroup(grid) {
  const g = RV.groups[+grid.dataset.i];
  grid.style.minHeight = "";
  grid.dataset.filled = "1";
  grid._list = g.list;  // Großansicht blättert in der Gruppe
  grid.replaceChildren(...g.list.map((m) => {
    const el = h("button", { type: "button", class: "rv-tile" + (RV.off.has(m.id) ? " off" : ""),
      title: [m.dateiname, fmtTaken(m.aufnahme), m.benutzer, m.info].filter(Boolean).join(" · "),
      onclick: () => {
        if (RV.mode === "ansehen") { openViewerFrom(el.querySelector("img")); return; }
        if (RV.mode === "ab") {  // Rangliste: davor alles an, ab hier alles ab
          RV.medien.forEach((x) => (x._i < m._i ? RV.off.delete(x.id) : RV.off.add(x.id)));
          RV.groups.forEach((x) => refreshGroup(x));
        } else {
          RV.off.has(m.id) ? RV.off.delete(m.id) : RV.off.add(m.id);
          el.classList.toggle("off", RV.off.has(m.id));
          refreshGroup(g, false);
        }
        rvCount();
      } }, thumb(m), m.marke ? h("span", { class: "rv-mark" }, m.marke) : null);
    return el;
  }));
}

function refreshGroup(g, tiles = true) {
  const i = RV.groups.indexOf(g);
  const grid = $(`#rv-body .rv-grid[data-i="${i}"]`);
  if (!grid) return;
  if (tiles && grid.dataset.filled) grid.querySelectorAll(".rv-tile").forEach((el, k) => el.classList.toggle("off", RV.off.has(g.list[k].id)));
  const sec = grid.closest(".rv-month");
  sec.replaceChild(groupHead(g), sec.firstChild);
}

function rvChosen() { return RV.medien.filter((m) => !RV.off.has(m.id)).map((m) => m.id); }

function rvCount() {
  const total = RV.medien.length, chosen = total - RV.medien.filter((m) => RV.off.has(m.id)).length;
  const de = (x) => x.toLocaleString("de-DE");
  const noun = RV_NOUN[RV.cfg.gruppe] || ["Gruppe", "Gruppen"];
  $("#rv-count").textContent = `${de(chosen)} von ${de(total)} ausgewählt · ${RV.groups.length} ${RV.groups.length === 1 ? noun[0] : noun[1]}`;
  $("#rv-foot-info").textContent = chosen === total ? "alle ausgewählt" : `${de(total - chosen)} abgewählt`;
  $("#rv-actions").replaceChildren(...RV.cfg.aktionen.map((a) => h("button", { type: "button", class: "btn " + (a.klasse || ""), disabled: !chosen && !a.leer,
    onclick: async (e) => {
      const btn = e.currentTarget;
      busy(btn, true);
      try {
        const close = await a.run(rvChosen(), RV.medien.filter((m) => RV.off.has(m.id)).map((m) => m.id));
        if (close !== false) $("#review").close();
      } catch (err) { toast(err.message, true); } finally { busy(btn, false); }
    } }, a.text(chosen))));
}

function setAllReview(on) {
  if (on) RV.off.clear(); else RV.medien.forEach((m) => RV.off.add(m.id));
  RV.groups.forEach((g) => refreshGroup(g));
  rvCount();
}

// Vorschlag prüfen: taggen oder archivieren
async function openSuggestionReview(s, aktion, btn) {
  busy(btn, true);
  let r;
  try { r = await api(`api/suggestions/${s.id}/media?aktion=${aktion}`); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  openReview({
    titel: aktion === "archiv" ? `${s.titel}: archivieren` : `${s.titel} → ${r.tag}`, medien: r.medien, gruppe: "monat",
    aktionen: [{ klasse: "primary", text: (k) => `${k.toLocaleString("de-DE")} ${aktion === "archiv" ? "archivieren" : "taggen"}`,
      run: async (ids, ohne) => {
        const res = await api(`api/staged/suggestions/${s.id}/auswahl`, { method: "POST", body: { ohne, aktion } });
        toast(`${n(res.vorgemerkt, "Medium", "Medien")} ${aktion === "archiv" ? "zum Archivieren" : "zum Taggen"} vorgemerkt`);
        S.stage.loaded = false;
        await Promise.all([loadSuggestions(), loadTab("stage", true)]);
        loadCounts();
      } }],
  });
}

async function hideSuggestion(s, undo) {
  try {
    await api("api/suggestions/hide", { method: "POST", body: { ids: [s.id], undo } });
    await loadSuggestions();
  } catch (e) { toast(e.message, true); }
}

const SMART_REVIEW = 400;  // Treffer je Benutzer für die Prüf-Ansicht

async function loadSmart(q) {
  const g = S.sug;
  const box = $("#smart-box");
  box.replaceChildren(h("p", { class: "empty" }, "Frage Immichs KI-Suche …"));
  const params = new URLSearchParams({ anzahl: SMART_REVIEW });
  if (q.begriff) params.set("begriff", q.begriff);
  if (q.suche) params.set("suche", q.suche);
  if (q.tag) params.set("tag", q.tag);
  let r;
  try {
    r = await api("api/suggestions/smart?" + params);
  } catch (e) {
    box.replaceChildren(h("div", { class: "banner err" }, e.message)); return;
  }
  g.smart = r; g.tag = r.tag;
  document.querySelectorAll("#smart-terms .chip-btn").forEach((b) => b.classList.toggle("on", b.textContent === q.begriff));
  const again = h("button", { type: "button", class: "btn small", onclick: () => openSmartReview(r) }, "Wieder öffnen");
  box.replaceChildren(h("p", { class: "muted small" }, r.medien.length ? `${r.medien.length} Treffer für „${r.suche}“ ` : "Keine neuen Treffer – alles schon getaggt?",
    r.medien.length ? again : null));
  if (r.medien.length) openSmartReview(r);
}

// KI-Treffer prüfen: nach Passgenauigkeit sortiert, in Blöcken zu 50. Anfangs ist nichts gewählt –
// das erste Bild antippen, das nicht mehr passt; alles davor wird gewählt. Danach einzeln nachbessern.
function openSmartReview(r) {
  const g = S.sug;
  const tagIn = h("input", { type: "text", value: g.tag, "aria-label": "Tag", oninput: (e) => { g.tag = e.target.value; rvCount(); } });
  openReview({
    titel: `KI-Suche: ${r.begriff || r.suche}`, medien: r.medien, gruppe: "rang", rang: true,
    ohne: r.medien.map((m) => m.id),
    hinweis: "Sortiert nach Passgenauigkeit. Tippe auf das erste Bild, das nicht mehr passt – alles davor wird gewählt. Danach unter „abwählen“ einzeln nachbessern.",
    extra: h("label", { class: "field rv-tag" }, "Tag", tagIn),
    aktionen: [
      { text: (k) => `${k} archivieren`, run: async (ids) => {
        const res = await api("api/staged/archive", { method: "POST", body: { ids, label: r.begriff || r.suche } });
        toast(`${n(res.vorgemerkt, "Medium", "Medien")} zum Archivieren vorgemerkt`);
        await afterSmart(r);
      } },
      { klasse: "primary", text: (k) => `${k} taggen`, run: async (ids) => {
        const tag = g.tag.trim();
        if (!tag) { toast("Bitte einen Tag eintragen", true); return false; }
        await api("api/staged/smart", { method: "POST", body: { tag, ids, begriff: r.begriff || r.suche } });
        toast(`${n(ids.length, "Medium", "Medien")} für „${tag}“ vorgemerkt`);
        await afterSmart(r);
      } },
    ],
  });
  RV.mode = "ab";
  renderReview();
}

async function afterSmart(r) {
  S.stage.loaded = false;
  loadTab("stage", true);
  loadCounts();
  $("#smart-box").replaceChildren(h("p", { class: "muted small" }, `Vorgemerkt. Für weitere Treffer zu „${r.begriff || r.suche}“ den Begriff erneut antippen.`));
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
  for (const k of ["album", "person", "land", "region", "ort"]) $("#r-" + k).value = asList(item[k]).join(", ");
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
  for (const k of ["album", "person", "land", "region", "ort"]) {
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
      h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter Vorgemerkt.")],
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
  S.set.homes = (d.album_home || []).slice();
  renderHomes();
  $("#set-web-user").value = d.web_user; lock("#set-web-user", "web_user");
  $("#set-web-pw").value = ""; lock("#set-web-pw", "web_password");
  $("#set-logout").hidden = !d.login_aktiv;
  $("#set-login-hint").textContent = d.login_aktiv
    ? "Login ist aktiv. Benutzername leeren und speichern schaltet ihn ab."
    : "Ohne Login kann jeder im Heimnetz das Tool bedienen. Für Zugriff von außen unbedingt setzen.";
  $("#set-auto").value = d.auto_scan; lock("#set-auto", "auto_scan");
  $("#set-auto-time").value = d.auto_scan_time; lock("#set-auto-time", "auto_scan_time");
  $("#set-auto-hours").value = d.auto_scan_hours; lock("#set-auto-hours", "auto_scan_hours");
  $("#set-auto-stage").checked = d.auto_stage_locations; lock("#set-auto-stage", "auto_stage_locations");
  $("#set-tz").value = d.timezone; lock("#set-tz", "timezone");
  updateAutoFields();
  $("#set-upd-check").checked = d.update_check; lock("#set-upd-check", "update_check");
  $("#set-upd-repo").value = d.update_repo; lock("#set-upd-repo", "update_repo");
  $("#set-rep-channel").value = d.report_channel; lock("#set-rep-channel", "report_channel");
  $("#set-rep-day").value = String(d.report_day); lock("#set-rep-day", "report_day");
  $("#set-rep-time").value = d.report_time; lock("#set-rep-time", "report_time");
  $("#set-rep-ntfy-url").value = d.report_ntfy_url; lock("#set-rep-ntfy-url", "report_ntfy_url");
  $("#set-rep-ntfy-token").value = ""; lock("#set-rep-ntfy-token", "report_ntfy_token");
  $("#set-rep-ntfy-token").placeholder = d.report_ntfy_token_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-rep-tg-token").value = ""; lock("#set-rep-tg-token", "report_telegram_token");
  $("#set-rep-tg-token").placeholder = d.report_telegram_token_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-rep-tg-chat").value = d.report_telegram_chat; lock("#set-rep-tg-chat", "report_telegram_chat");
  $("#set-mem").checked = d.memories; lock("#set-mem", "memories");
  $("#set-mem-time").value = d.memories_time; lock("#set-mem-time", "memories_time");
  updateReportFields();
  $("#set-upd-token").value = ""; lock("#set-upd-token", "update_github_token");
  $("#set-upd-token").placeholder = d.update_github_token_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-upd-url").value = d.update_webhook_url; lock("#set-upd-url", "update_webhook_url");
  $("#set-n8n").open = !!d.update_webhook_url;
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
  put("album_home", S.set.homes || []);
  if (!d.gesperrt.includes("users")) body.benutzer = readUsers();
  put("auto_scan", $("#set-auto").value);
  put("auto_scan_time", $("#set-auto-time").value);
  put("auto_scan_hours", $("#set-auto-hours").value);
  put("auto_stage_locations", $("#set-auto-stage").checked);
  put("timezone", $("#set-tz").value.trim());
  put("update_check", $("#set-upd-check").checked);
  put("update_repo", $("#set-upd-repo").value.trim());
  put("update_webhook_url", $("#set-upd-url").value.trim());
  put("update_webhook_header", $("#set-upd-header").value.trim());
  put("report_channel", $("#set-rep-channel").value);
  put("report_day", Number($("#set-rep-day").value));
  put("report_time", $("#set-rep-time").value);
  put("report_ntfy_url", $("#set-rep-ntfy-url").value.trim());
  put("report_telegram_chat", $("#set-rep-tg-chat").value.trim());
  put("memories", $("#set-mem").checked);
  put("memories_time", $("#set-mem-time").value);
  if ($("#set-rep-ntfy-token").value.trim()) put("report_ntfy_token", $("#set-rep-ntfy-token").value.trim());
  if ($("#set-rep-tg-token").value.trim()) put("report_telegram_token", $("#set-rep-tg-token").value.trim());
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

function updateReportFields() {
  const ch = $("#set-rep-channel").value;
  $("#set-rep-fields").hidden = ch === "aus";
  $("#set-rep-ntfy").hidden = ch !== "ntfy";
  $("#set-rep-tg").hidden = ch !== "telegram";
}

async function sendTestMemories(btn) {
  busy(btn, true);
  try {
    await api("api/settings", { method: "PUT", body: readSettingsForm() });
    await api("api/memories/test", { method: "POST" });
    toast("„An diesem Tag“ gesendet – schau aufs Handy");
  } catch (e) {
    toast(e.message, true);
  } finally { busy(btn, false); }
}

async function sendTestReport(btn) {
  busy(btn, true);
  try {
    await api("api/settings", { method: "PUT", body: readSettingsForm() });  // erst speichern, dann testen
    await api("api/report/test", { method: "POST" });
    toast("Testnachricht gesendet – schau aufs Handy");
    await loadSettings();
  } catch (e) {
    toast(e.details && e.details.length ? e.details.join(" · ") : e.message, true);
  } finally { busy(btn, false); }
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
  $("#set-btn").classList.toggle("dot", !!v.update_available);
  $("#set-btn").title = v.update_available ? "Einstellungen – Update verfügbar" : "Einstellungen";
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
    $("#version-out").textContent = "Für Updates per Klick einmalig auf dem Server im Projektordner ausführen: sudo ./installieren.sh – danach erscheint hier der Update-Dienst.";
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



/* ---------------------------------------------------------- Aufräumen */
const PAGE_CLN = 30;
async function loadCleanup(reset) {
  const c = S.cln;
  if (c.bereich === "papierkorb") return loadTrash();
  if (c.bereich === "stapel") return loadStacks();
  if (c.bereich === "alben") return loadAlbumCare();
  if (reset) { c.items = []; c.sel.clear(); c.keep = {}; c.edit = {}; $("#cln-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const isTime = c.bereich === "zeit";
  const params = new URLSearchParams({ offset: c.items.length, limit: PAGE_CLN, ignoriert: c.ignored });
  if (c.kategorie) params.set(isTime ? "art" : "kategorie", c.kategorie);
  if (!isTime) params.set("art", c.bereich);
  const [r, counts] = await Promise.all([
    api((isTime ? "api/timefix?" : "api/cleanup?") + params),
    api(isTime ? "api/cleanup?limit=0" : "api/timefix?limit=0"),
  ]);
  const cln = isTime ? counts : r;
  const time = isTime ? r : counts;
  if (reset) $("#cln-list").replaceChildren();
  c.info = r; c.total = r.gesamt; c.loaded = true;
  renderCleanupFilters(cln, time);
  if (isTime) {
    for (const it of r.eintraege) { c.items.push(it); $("#cln-list").append(renderTimeFix(it)); }
    if (!c.items.length) $("#cln-list").replaceChildren(h("p", { class: "empty" }, c.ignored ? "Nichts ausgeblendet." : "Keine falschen Zeiten gefunden 🎉"));
    $("#cln-summary").textContent = `${n(r.gesamt, "Eintrag", "Einträge")}`;
    $("#cln-more").hidden = c.items.length >= c.total;
    updateActionbar();
    return;
  }
  for (const it of r.eintraege) { c.items.push(it); $("#cln-list").append(renderCleanupItem(it)); }
  if (!c.items.length) {
    const fp = r.fingerabdruck;
    const hint = c.bereich === "qualitaet" && fp.aktiv && (fp.laeuft || fp.fehlend)
      ? "Schärfe und Helligkeit werden mit den Bild-Fingerabdrücken berechnet – das läuft noch."
      : c.bereich === "qualitaet" && !fp.aktiv ? "Dafür bitte unter ⚙ Einstellungen den Bild-Fingerabdruck einschalten."
        : c.ignored ? "Nichts ausgeblendet." : "Nichts gefunden 🎉";
    $("#cln-list").replaceChildren(h("p", { class: "empty" }, hint));
  }
  $("#cln-summary").textContent = c.ignored ? `${n(r.gesamt, "ausgeblendeter Eintrag", "ausgeblendete Einträge")}`
    : `${n(r.gesamt, "Eintrag", "Einträge")} · ${fmtBig(r.groesse)} würden frei`;
  for (const [k, a] of Object.entries(r.arten)) setCount(k, a.anzahl);
  setCount("zeit", Object.values(time.arten).reduce((s, x) => s + x, 0));
  $("#cln-more").hidden = c.items.length >= c.total;
  updateActionbar();
}

function renderCleanupFilters(r, time) {
  const c = S.cln;
  const cats = ["papierkorb", "stapel", "alben"].includes(c.bereich) ? [] : c.bereich === "zeit"
    ? Object.entries(time.arten).map(([k, v]) => [k, { name: time.namen[k], anzahl: v }])
    : Object.entries(r.kategorien).filter(([, v]) => v.art === c.bereich);
  const cat = h("select", { onchange: (e) => { c.kategorie = e.target.value || null; loadTab("cln", true); } },
    h("option", { value: "" }, "alle"),
    ...cats.map(([k, v]) => h("option", { value: k }, `${v.name} (${v.anzahl})`)));
  cat.value = c.kategorie || "";
  $("#cln-filters").replaceChildren(...[
    cats.length > 1 ? h("label", { class: "field grow" }, "Art", cat) : null,
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: c.ignored,
      onchange: (e) => { c.ignored = e.target.checked; loadTab("cln", true); } }),
      `behaltene (${c.bereich === "zeit" ? time.ausgeblendet : r.ausgeblendet})`),
  ].filter(Boolean));
}

function fmtOffset(min) {
  const sign = min > 0 ? "+" : "−";
  if (Math.abs(min) >= 48 * 60) return sign + Math.round(Math.abs(min) / 1440) + " Tage";
  const h0 = Math.floor(Math.abs(min) / 60), m = Math.abs(min) % 60;
  return sign + h0 + " h" + (m ? ` ${m} min` : "");
}

// Gewählte Korrektur: Vorschlag, eigene Verschiebung (Minuten) oder Zielzeit (nur Einzelmedium)
function timeChoice(it) {
  const e = S.cln.edit[it.id];
  if (e && (e.minuten || e.ziel)) return e;
  return it.minuten ? { minuten: it.minuten } : null;
}

function renderTimeFix(it) {
  const c = S.cln;
  const card = h("article", { class: "card" + (c.sel.has(it.id) ? " selected" : "") });
  card.append(h("div", { class: "card-head" },
    c.ignored ? null : h("input", { type: "checkbox", checked: c.sel.has(it.id), "aria-label": "Auswählen",
      onchange: (e) => { e.target.checked ? c.sel.add(it.id) : c.sel.delete(it.id); card.classList.toggle("selected", e.target.checked); updateActionbar(); } }),
    h("span", { class: "chip" }, it.art_text),
    it.minuten ? h("b", {}, fmtOffset(it.minuten)) : null,
    h("span", { class: "muted" }, n(it.anzahl, "Medium", "Medien")),
    h("button", { type: "button", class: "btn small edit", onclick: () => keepCleanup(it, c.ignored) }, c.ignored ? "Wieder zeigen" : "Passt so")),
    h("div", { class: "muted small" }, it.grund));
  // Kacheln wie bei „Ohne Ort“: groß genug, um das Motiv zu erkennen; antippen = Großansicht
  c.timeAll = c.timeAll || {};  // Eintrag -> alle Medien (in der Liste steht nur eine Auswahl)
  const media = c.timeAll[it.id] || it.medien;
  const all = !!c.timeAll[it.id] || it.anzahl <= it.medien.length;
  const grid = h("div", { class: "grid" });
  grid._list = media;
  for (const m of media) {
    grid.append(tile({ class: "tile", title: m.pfad, onclick: (e) => openViewerFrom(e.currentTarget.querySelector("img")) },
      thumb(m),
      h("div", { class: "meta" },
        h("div", { class: "name" }, m.dateiname),
        h("div", {}, fmtTaken(m.aufnahme)),
        m.neue_zeit ? h("div", { class: "sug" }, "→ " + fmtTaken(m.neue_zeit)) : null,
        h("div", {}, m.benutzer + (m.extern ? " · extern" : "")),
        openLinks(m))));
  }
  card.append(grid);
  if (!all) {
    card.append(h("button", { type: "button", class: "btn more", onclick: (e) => openTimeReview(it, e.currentTarget) }, `Alle ${it.anzahl} prüfen`));
  }
  if (!c.ignored) {
    const row = h("div", { class: "row-gap", style: "margin-top:8px" });
    if (it.anzahl === 1) {
      const cur = it.medien[0].aufnahme ? it.medien[0].aufnahme.replace(" ", "T").slice(0, 16) : "";
      const sug = it.medien[0].neue_zeit ? it.medien[0].neue_zeit.replace(" ", "T").slice(0, 16) : cur;
      row.append(h("label", { class: "field" }, "Richtige Zeit",
        h("input", { type: "datetime-local", value: sug, style: "min-width:14em", onchange: (e) => { c.edit[it.id] = { ziel: e.target.value }; c.sel.add(it.id); updateActionbar(); } })));
    } else {
      row.append(h("label", { class: "field" }, "Verschieben um Stunden",
        h("input", { type: "number", step: "0.5", value: it.minuten / 60, style: "width:6em",
          onchange: (e) => { c.edit[it.id] = { minuten: Math.round(parseFloat(String(e.target.value).replace(",", ".")) * 60) || 0 }; c.sel.add(it.id); updateActionbar(); } })));
    }
    row.append(h("button", { type: "button", class: "btn small primary", onclick: (e) => stageTimeFixes([it], e.currentTarget) }, "Vormerken"));
    card.append(row);
  }
  return card;
}

// Alle Medien eines Zeit-Eintrags prüfen (nach Tagen) und nur die gewählten verschieben
async function openTimeReview(it, btn) {
  busy(btn, true);
  let r;
  try { r = await api(`api/timefix/${it.id}/media`); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  for (const m of r.medien) { m.info = m.neue_zeit ? "→ " + fmtTaken(m.neue_zeit) : ""; m.marke = m.neue_zeit ? "→ " + m.neue_zeit.slice(11, 16) : null; }
  openReview({
    titel: `${it.art_text}${it.minuten ? " " + fmtOffset(it.minuten) : ""}`, medien: r.medien.slice().reverse(), gruppe: "tag",
    hinweis: it.grund.replace(/\.?$/, ". ") + "Abgewählte bleiben, wie sie sind.",
    aktionen: [{ klasse: "primary", text: (k) => `${k} verschieben`, run: async (ids, ohne) => {
      const choice = timeChoice(it);
      if (!choice) { toast("Bitte zuerst die Verschiebung eintragen", true); return false; }
      await api("api/staged/timefix", { method: "POST", body: { eintraege: [{ id: it.id, ...choice, ohne }] } });
      toast(`${n(ids.length, "Medium", "Medien")} zum Verschieben vorgemerkt`);
      await afterStage("cln");
    } }],
  });
}

async function stageTimeFixes(items, btn) {
  const chosen = items.filter((it) => timeChoice(it));
  if (!chosen.length) { toast("Bitte zuerst die richtige Zeit wählen", true); return; }
  busy(btn, true);
  try {
    const r = await api("api/staged/timefix", { method: "POST", body: { eintraege: chosen.map((it) => ({ id: it.id, ...timeChoice(it) })) } });
    toast(`${n(r.vorgemerkt, "Korrektur", "Korrekturen")} vorgemerkt`);
    await afterStage("cln");
  } catch (e) {
    toast(e.message, true);
  } finally { busy(btn, false); }
}

function renderCleanupItem(it) {
  const c = S.cln;
  const card = h("article", { class: "card" + (c.sel.has(it.id) ? " selected" : "") });
  const keepId = c.keep[it.id];
  const isDrop = (m) => (keepId ? m.id !== keepId : m.aktion === "weg");
  card.append(h("div", { class: "card-head" },
    c.ignored ? null : h("input", { type: "checkbox", checked: c.sel.has(it.id), "aria-label": "Auswählen",
      onchange: (e) => { e.target.checked ? c.sel.add(it.id) : c.sel.delete(it.id); card.classList.toggle("selected", e.target.checked); updateActionbar(); } }),
    h("span", { class: "chip" }, it.kategorie_text),
    it.groesse ? h("b", {}, fmtBig(it.groesse)) : null,
    h("button", { type: "button", class: "btn small edit", onclick: () => keepCleanup(it, c.ignored) }, c.ignored ? "Wieder zeigen" : "Behalten")),
    h("div", { class: "muted small" }, it.grund));
  const grid = h("div", { class: "grid" });
  for (const m of it.medien) {
    const drop = isDrop(m);
    grid.append(tile({
      class: "tile " + (drop ? "drop" : "keep"),
      title: m.pfad,
      onclick: () => {
        if (it.kategorie !== "serien") return;  // nur bei Serien lässt sich das behaltene Bild wählen
        c.keep[it.id] = m.id; c.sel.add(it.id);
        card.replaceWith(renderCleanupItem(it)); updateActionbar();
      },
    }, thumb(m), h("span", { class: "badge" }, drop ? "weg" : "★ bleibt"),
    h("div", { class: "meta" },
      h("div", { class: "name" }, m.dateiname),
      h("div", {}, `${m.benutzer} · ${m.extern ? "extern" : "Upload"}${m.dauer_s ? ` · ${fmtDur(m.dauer_s)}` : ""}`),
      h("div", {}, fmtTaken(m.aufnahme)),
      h("div", {}, fmtSize(m.groesse)),
      openLinks(m))));
  }
  card.append(grid);
  return card;
}

async function keepCleanup(it, undo) {
  try {
    await api("api/cleanup/keep", { method: "POST", body: { ids: [it.id], undo } });
    toast(undo ? "Wieder in der Liste" : "Behalten – taucht hier nicht mehr auf");
    await loadTab("cln", true);
  } catch (e) { toast(e.message, true); }
}

async function stageCleanup(action, items, btn) {
  if (!items.length) return;
  const c = S.cln;
  const media = items.reduce((s, it) => s + it.medien.filter((m) => (c.keep[it.id] ? m.id !== c.keep[it.id] : m.aktion === "weg")).length, 0);
  const size = items.reduce((s, it) => s + it.groesse, 0);
  const ok = await confirmDialog({
    title: "Vormerken?",
    body: [h("p", {}, `${n(media, "Medium", "Medien")} (${fmtBig(size)}) ${action === "papierkorb" ? "für den Papierkorb" : "fürs Prüf-Album"}.`),
      action === "papierkorb" ? h("p", { class: "muted" }, c.bereich === "verwaist"
        ? "Die Dateien fehlen schon auf der Platte – der Papierkorb entfernt nur den Eintrag in Immich."
        : "Medien aus externen Bibliotheken kommen nie in den Papierkorb, sondern ins Prüf-Album.") : null,
      h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter Vorgemerkt.")],
    okLabel: "Vormerken",
  });
  if (!ok) return;
  busy(btn, true);
  try {
    const keep = Object.fromEntries(items.filter((it) => c.keep[it.id]).map((it) => [it.id, c.keep[it.id]]));
    const r = await api("api/staged/cleanup", { method: "POST", body: { action, ids: items.map((it) => it.id), keep } });
    toast(`${n(r.medien, "Medium", "Medien")} vorgemerkt`);
    await afterStage("cln");
  } catch (e) {
    toast(e.message, true);
  } finally { busy(btn, false); }
}

// Alle Treffer eines Aufräum-Bereichs prüfen (je Eintrag ein Medium, das weg soll), dann Prüf-Album oder Papierkorb
async function openCleanupReview(btn) {
  const c = S.cln;
  busy(btn, true);
  let r;
  try {
    const params = new URLSearchParams({ art: c.bereich, limit: 0 });
    if (c.kategorie) params.set("kategorie", c.kategorie);
    r = await api("api/cleanup?" + params);
  } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const itemOf = new Map();
  const media = [];
  for (const it of r.eintraege) {
    for (const m of it.medien) {
      if (m.aktion !== "weg") continue;
      itemOf.set(m.id, it);
      media.push({ ...m, info: `${it.kategorie_text} · ${it.grund}`, marke: it.groesse >= 1048576 ? fmtBig(it.groesse) : null, _kat: it.kategorie_text });
    }
  }
  const stage = (action) => async (ids) => {
    const items = [...new Set(ids.map((i) => itemOf.get(i)))];
    const size = items.reduce((s, it) => s + it.groesse, 0);
    if (action === "papierkorb") {
      const ok = await confirmDialog({ title: "Für den Papierkorb vormerken?", danger: true, okLabel: "Vormerken",
        body: [h("p", {}, `${n(ids.length, "Medium", "Medien")} (${fmtBig(size)}).`),
          h("p", { class: "muted" }, c.bereich === "verwaist" ? "Die Dateien fehlen schon auf der Platte – der Papierkorb entfernt nur den Eintrag in Immich."
            : "Medien aus externen Bibliotheken kommen nie in den Papierkorb, sondern ins Prüf-Album. Übertragen wird erst unter Vorgemerkt.")] });
      if (!ok) return false;
    }
    const res = await api("api/staged/cleanup", { method: "POST", body: { action, ids: items.map((it) => it.id) } });
    toast(`${n(res.medien, "Medium", "Medien")} vorgemerkt`);
    await afterStage("cln");
  };
  openReview({
    titel: VIEWS[S.view] ? VIEWS[S.view].label : "Aufräumen", medien: media,
    gruppe: (m) => [m._kat, m._kat],
    hinweis: `Alles hier soll weg (${fmtBig(r.groesse)}). Abwählen, was bleiben soll – „Behalten“ blendet es in der Liste dauerhaft aus.`,
    aktionen: [
      { text: (k) => `${k} ins Prüf-Album`, klasse: "primary", run: stage("album") },
      { text: (k) => `${k} Papierkorb`, klasse: "danger", run: stage("papierkorb") },
    ],
  });
}

/* ------------------------------------------------------- Alben aufräumen */
async function loadAlbumCare() {
  const c = S.cln;
  c.items = []; c.sel.clear(); c.target = c.target || {}; c.delRest = c.delRest || {}; c.cover = c.cover || {};
  $("#cln-list").replaceChildren(h("p", { class: "empty" }, "Lade …"));
  const [r, counts, time] = await Promise.all([api("api/album-care?ausgeblendet=" + c.ignored), api("api/cleanup?limit=0"), api("api/timefix?limit=0")]);
  renderCleanupFilters(counts, time);
  c.loaded = true; c.info = r; $("#cln-more").hidden = true;
  if (r.laedt) { $("#cln-list").replaceChildren(h("div", { class: "banner warn" }, "Die Alben werden gerade gelesen – gleich noch einmal versuchen.")); return; }
  c.items = r.eintraege;
  $("#cln-summary").textContent = Object.values(r.arten).filter((a) => a.anzahl).map((a) => `${a.anzahl}× ${a.name}`).join(" · ") || "";
  $("#cln-list").replaceChildren(...(c.items.length ? c.items.map(renderCareItem)
    : [h("p", { class: "empty" }, c.ignored ? "Nichts ausgeblendet." : "Alle Alben in Ordnung 🎉")]));
  updateActionbar();
}

function renderCareItem(it) {
  const c = S.cln;
  const merge = it.alben.length > 1;
  const target = c.target[it.id] || it.ziel;
  const card = h("article", { class: "card" });
  card.append(h("div", { class: "card-head" }, h("span", { class: "chip" }, it.art_text),
    h("button", { type: "button", class: "btn small edit", onclick: () => keepCleanup(it, c.ignored) }, c.ignored ? "Wieder zeigen" : "Passt so")),
    h("div", { class: "muted small" }, it.grund));
  for (const al of it.alben) {
    const row = h("div", { class: "care-album" + (merge && al.id === target ? " target" : "") },
      h("div", { class: "care-title" },
        merge ? h("input", { type: "radio", name: "ziel-" + it.id, checked: al.id === target, "aria-label": "Ziel-Album",
          onchange: () => { c.target[it.id] = al.id; card.replaceWith(renderCareItem(it)); } }) : null,
        h("b", {}, `„${al.name}“`), h("span", { class: "muted" }, ` ${al.besitzer}${al.geteilt_mit.length ? ", geteilt mit " + al.geteilt_mit.join(", ") : ""} · ${n(al.anzahl, "Medium", "Medien")} `),
        albumLinks(al),
        merge && al.id === target ? h("span", { class: "chip ok" }, "Ziel") : null),
      al.beispiele.length ? h("div", { class: "strip" }, al.beispiele.map((m) => thumb(m))) : null);
    card.append(row);
  }
  if (it.art === "titelbild") {
    const pick = c.cover[it.id] || it.vorschlag;
    card.append(h("div", { class: "cover-row" },
      h("div", { class: "cover-now" }, h("div", { class: "muted small" }, "Jetzt"),
        it.titelbild ? thumb(it.titelbild) : h("div", { class: "cover-none" }, "–")),
      h("div", { class: "cover-choice" }, h("div", { class: "muted small" }, c.ignored ? "Vorschläge" : "Neues Titelbild – antippen zum Wählen"),
        h("div", { class: "strip" }, it.auswahl.map((m) => h("button", {
          type: "button", class: "cover-pick" + (m.id === pick ? " on" : ""), "aria-pressed": String(m.id === pick), disabled: c.ignored,
          onclick: () => { c.cover[it.id] = m.id; card.replaceWith(renderCareItem(it)); } }, thumb(m)))))));
  }
  if (!c.ignored) {
    const actions = h("div", { class: "row-gap", style: "margin-top:8px" });
    if (it.art === "titelbild") {
      actions.append(h("button", { type: "button", class: "btn small primary", onclick: (e) => stageCare(it, "titelbild", e.currentTarget) }, "Als Titelbild vormerken"));
    } else if (merge) {
      const del = c.delRest[it.id] !== false;
      actions.append(
        h("button", { type: "button", class: "btn small primary", onclick: (e) => stageCare(it, "zusammenfuehren", e.currentTarget) }, "Zusammenführen"),
        h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: del, onchange: (e) => { c.delRest[it.id] = e.target.checked; } }), "die anderen danach löschen"));
    } else {
      actions.append(h("button", { type: "button", class: "btn small danger", onclick: (e) => stageCare(it, "loeschen", e.currentTarget) }, "Album löschen"));
    }
    card.append(actions);
  }
  return card;
}

async function stageCare(it, aktion, btn) {
  const c = S.cln;
  busy(btn, true);
  try {
    await api("api/staged/album-care", { method: "POST", body: { id: it.id, aktion, ziel: c.target[it.id] || it.ziel, loeschen: c.delRest[it.id] !== false, titelbild: c.cover[it.id] || it.vorschlag } });
    toast({ loeschen: "Löschen vorgemerkt – die Fotos bleiben in Immich", titelbild: "Titelbild vorgemerkt" }[aktion] || "Zusammenführen vorgemerkt");
    await afterStage("cln");
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

/* ---------------------------------------------------------- Ordner-Alben */
const FOL_STATUS = { neu: "Neues Album", ergaenzen: "Album ergänzen", abgeglichen: "Wird aktuell gehalten", vorhanden: "Schon in Alben" };

async function loadFolders() {
  const f = S.fol;
  $("#alb-list").replaceChildren(h("p", { class: "empty" }, "Lade …"));
  $("#alb-more").hidden = true;
  const params = new URLSearchParams({ ausgeblendet: f.ignored });
  if (f.status) params.set("status", f.status);
  const r = await api("api/folder-albums?" + params);
  S.alb.loaded = true;
  if (r.laedt) {
    $("#alb-list").replaceChildren(h("div", { class: "banner warn" }, "Die Alben werden gerade gelesen – die Vorschläge erscheinen gleich."));
    S.alb.loaded = false;
    setTimeout(() => { if (S.tab === "alb" && !S.alb.loaded) loadTab("alb", true); }, 10000);
    return;
  }
  f.items = r.ordner;
  const sel = h("select", { onchange: (e) => { f.status = e.target.value || null; loadTab("alb", true); } },
    h("option", { value: "" }, `offen (${r.status.neu + r.status.ergaenzen})`),
    ...Object.entries(FOL_STATUS).map(([k, v]) => h("option", { value: k }, `${v} (${r.status[k]})`)));
  sel.value = f.status || "";
  $("#alb-filters").replaceChildren(h("label", { class: "field grow" }, "Zeigen", sel),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: f.ignored,
      onchange: (e) => { f.ignored = e.target.checked; loadTab("alb", true); } }), `ausgeblendete (${r.ausgeblendet})`));
  $("#alb-summary").textContent = "Ordner der externen Bibliothek mit mindestens 5 Medien";
  $("#alb-list").replaceChildren(...(f.items.length ? f.items.map(renderFolder)
    : [h("p", { class: "empty" }, f.ignored ? "Nichts ausgeblendet." : "Keine Ordner ohne Album 🎉")]));
  updateActionbar();
}

function renderFolder(p) {
  const f = S.fol;
  const card = h("article", { class: "card" });
  const chip = { neu: "conf-niedrig", ergaenzen: "conf-mittel", abgeglichen: "conf-hoch", vorhanden: "conf-hoch" }[p.status];
  card.append(h("div", { class: "card-head" }, h("div", { class: "grow" }, h("h2", {}, "📂 " + p.name),
    h("span", { class: "muted small" }, `${p.ordner} · ${p.benutzer} · ${n(p.anzahl, "Medium", "Medien")}`)),
    h("span", { class: "chip " + chip }, FOL_STATUS[p.status])));
  if (p.album) card.append(h("div", { class: "alb-found" }, `Album „${p.album.name}“` + (p.fehlend ? ` – ${p.fehlend} fehlen. ` : ". "), albumLinks(p.album)));
  if (p.beispiele.length) card.append(h("div", { class: "strip" }, p.beispiele.map((m) => thumb(m))));
  if (f.ignored || p.status === "abgeglichen" || p.status === "vorhanden") {
    if (f.ignored) card.append(h("button", { type: "button", class: "btn small", onclick: () => keepFolder(p, true) }, "Wieder zeigen"));
    return card;
  }
  const choice = f.choice[p.id] || {};
  if (p.status === "neu") {
    card.append(h("label", { class: "f alb-name" }, "Name des Albums", h("input", { type: "text", value: choice.name || p.name,
      oninput: (e) => { f.choice[p.id] = { ...f.choice[p.id], name: e.target.value }; } })));
  }
  card.append(h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: !!f.sync[p.id],
    onchange: (e) => { f.sync[p.id] = e.target.checked; } }), "neue Dateien aus dem Ordner automatisch hinzufügen"),
  h("div", { class: "row-gap", style: "margin-top:8px" },
    h("button", { type: "button", class: "btn small primary", onclick: (e) => stageFolders([p], e.currentTarget) },
      f.ohne[p.id] && f.ohne[p.id].length ? `Vormerken (${p.fehlend - f.ohne[p.id].length})` : "Vormerken"),
    h("button", { type: "button", class: "btn small", onclick: (e) => openFolderReview(p, card, e.currentTarget) }, `Alle ${p.fehlend} prüfen`),
    h("button", { type: "button", class: "btn small", onclick: () => keepFolder(p, false) }, "Kein Album")),
  f.ohne[p.id] && f.ohne[p.id].length ? h("div", { class: "muted small" }, `${f.ohne[p.id].length} abgewählt – kommen auch beim automatischen Abgleich nicht ins Album`) : null);
  return card;
}

// Alle Dateien eines Ordners prüfen, die ins Album kämen; Abgewählte bleiben dauerhaft draußen
async function openFolderReview(p, card, btn) {
  const f = S.fol;
  busy(btn, true);
  let r;
  try { r = await api(`api/folder-albums/${p.id}/media?album=` + encodeURIComponent(p.album ? p.album.id : "")); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const keep = (ohne) => { f.ohne[p.id] = ohne; card.replaceWith(renderFolder(p)); };
  openReview({
    titel: "📂 " + p.name, medien: r.medien, gruppe: "monat", ohne: f.ohne[p.id] || [],
    hinweis: `${p.ordner} – abgewählte Dateien kommen nicht ins Album, auch nicht beim automatischen Abgleich.`,
    aktionen: [
      { text: () => "Übernehmen", leer: true, run: async (ids, ohne) => keep(ohne) },
      { klasse: "primary", text: (k) => `${k} vormerken`, run: async (ids, ohne) => { keep(ohne); await stageFolders([p], null); } },
    ],
  });
}

async function stageFolders(list, btn) {
  const f = S.fol;
  busy(btn, true);
  try {
    const body = { ordner: list.map((p) => ({ id: p.id, sync: !!f.sync[p.id], ...(f.ohne[p.id] && f.ohne[p.id].length ? { ohne: f.ohne[p.id] } : {}),
      ...(p.status === "neu" && f.choice[p.id] && f.choice[p.id].name ? { name: f.choice[p.id].name } : {}) })) };
    const r = await api("api/staged/folder-albums", { method: "POST", body });
    toast(`${n(r.vorgemerkt, "Ordner", "Ordner")} vorgemerkt`);
    await afterStage("alb");
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

async function keepFolder(p, undo) {
  try {
    await api("api/cleanup/keep", { method: "POST", body: { ids: [p.id], undo } });
    await loadTab("alb", true);
  } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------------- Stapeln */
async function loadStacks() {
  const c = S.cln;
  c.items = []; c.sel.clear(); c.top = c.top || {};
  $("#cln-list").replaceChildren(h("p", { class: "empty" }, "Lade …"));
  const params = new URLSearchParams({ ganz: !!c.whole });
  if (c.album) params.set("album", c.album);
  const [r, counts, time] = await Promise.all([api("api/stacks?" + params), api("api/cleanup?limit=0"), api("api/timefix?limit=0")]);
  renderCleanupFilters(counts, time);
  c.loaded = true; c.info = r; $("#cln-more").hidden = true;
  if (r.laedt) {
    $("#cln-list").replaceChildren(h("div", { class: "banner warn" }, "Die Alben werden gerade gelesen – gleich noch einmal versuchen."));
    $("#cln-summary").textContent = ""; updateActionbar(); return;
  }
  const sel = h("select", { onchange: (e) => { c.album = e.target.value || null; c.top = {}; loadTab("cln", true); } },
    h("option", { value: "" }, "Album wählen …"),
    ...r.alben.map((a) => h("option", { value: a.id }, `${a.name} (${a.anzahl}${a.gestapelt ? `, ${a.gestapelt} gestapelt` : ""})`)));
  sel.value = c.album || "";
  const opts = h("div", { class: "toolbar" },
    h("label", { class: "field grow" }, "Album", sel),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: !!c.whole,
      onchange: (e) => { c.whole = e.target.checked; c.top = {}; loadTab("cln", true); } }), "ganzes Album als einen Stapel"),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: !!c.fromAlbum,
      onchange: (e) => { c.fromAlbum = e.target.checked; } }), "danach aus dem Album nehmen"));
  const list = [opts];
  if (!c.album) {
    list.push(h("p", { class: "empty" }, r.alben.length ? "Wähle das Album, in dem du Zusammengehöriges gesammelt hast." : "Keine Alben gefunden."));
    $("#cln-summary").textContent = `${n(r.alben.length, "Album", "Alben")}`;
  } else {
    c.items = r.vorschlaege;
    const z = r.zahlen || {};
    $("#cln-summary").textContent = `${n(c.items.length, "Stapel", "Stapel")} vorgeschlagen` +
      (z.medien ? ` · ${z.medien} Medien im Album${z.gestapelt ? `, ${z.gestapelt} schon gestapelt` : ""}${!c.whole && z.einzeln ? `, ${z.einzeln} ohne Partner` : ""}` : "");
    if (!c.items.length) list.push(h("p", { class: "empty" }, c.whole ? "Nichts zu stapeln (je Benutzer mindestens 2 ungestapelte Medien nötig)." : "Keine zusammengehörigen Fotos gefunden – „ganzes Album“ probieren?"));
    for (const p of c.items) list.push(renderStackProposal(p));
  }
  $("#cln-list").replaceChildren(...list);
  updateActionbar();
}

function renderStackProposal(p) {
  const c = S.cln;
  const top = c.top[p.id] || p.oben;
  const card = h("article", { class: "card" + (c.sel.has(p.id) ? " selected" : "") });
  card.append(h("div", { class: "card-head" },
    h("input", { type: "checkbox", checked: c.sel.has(p.id), "aria-label": "Auswählen",
      onchange: (e) => { e.target.checked ? c.sel.add(p.id) : c.sel.delete(p.id); card.classList.toggle("selected", e.target.checked); updateActionbar(); } }),
    h("b", {}, n(p.anzahl, "Medium", "Medien")), h("span", { class: "chip" }, p.benutzer)),
    h("div", { class: "muted small" }, p.grund + " · antippen, um das obere Bild zu wählen"));
  const grid = h("div", { class: "grid" });
  for (const m of p.medien) {
    const isTop = m.id === top;
    grid.append(tile({ class: "tile " + (isTop ? "keep" : ""), title: m.pfad,
      onclick: () => { c.top[p.id] = m.id; c.sel.add(p.id); card.replaceWith(renderStackProposal(p)); updateActionbar(); } },
    thumb(m), h("span", { class: "badge" }, isTop ? "★ oben" : "im Stapel"),
    h("div", { class: "meta" }, h("div", { class: "name" }, m.dateiname), h("div", {}, fmtTaken(m.aufnahme)),
      h("div", {}, [m.breite && m.hoehe ? `${m.breite}×${m.hoehe}` : "", fmtSize(m.groesse)].filter(Boolean).join(" · ")), openLinks(m))));
  }
  card.append(grid);
  return card;
}

async function stageStacks(props, btn) {
  const c = S.cln;
  if (!props.length) return;
  const media = props.reduce((s, p) => s + p.anzahl, 0);
  const ok = await confirmDialog({ title: "Stapeln vormerken?",
    body: [h("p", {}, `${n(props.length, "Stapel", "Stapel")} aus ${n(media, "Medium", "Medien")}. Gelöscht wird nichts – in Immich liegt das obere Bild in der Zeitleiste, die anderen dahinter.`),
      c.fromAlbum ? h("p", {}, "Danach werden sie aus dem Album genommen.") : null,
      h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter Vorgemerkt.")].filter(Boolean),
    okLabel: "Vormerken" });
  if (!ok) return;
  busy(btn, true);
  try {
    const all = props.length === c.items.length;
    const top = Object.fromEntries(props.filter((p) => c.top[p.id]).map((p) => [p.id, c.top[p.id]]));
    const r = await api("api/staged/stacks", { method: "POST", body: { album: c.album, ganz: !!c.whole, ids: all ? null : props.map((p) => p.id), oben: top, aus_album: !!c.fromAlbum } });
    toast(`${n(r.vorgemerkt, "Stapel", "Stapel")} vorgemerkt`);
    await afterStage("cln");
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

async function stageBurstStacks(items, btn) {
  busy(btn, true);
  try {
    const keep = Object.fromEntries(items.filter((it) => S.cln.keep[it.id]).map((it) => [it.id, S.cln.keep[it.id]]));
    const r = await api("api/staged/cleanup", { method: "POST", body: { action: "stapel", ids: items.map((it) => it.id), keep } });
    toast(`${n(r.vorgemerkt, "Stapel", "Stapel")} vorgemerkt – nichts wird gelöscht`);
    await afterStage("cln");
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

/* ---------------------------------------------------------- Papierkorb */
async function loadTrash() {
  const c = S.cln;
  c.items = []; c.sel.clear();
  $("#cln-list").replaceChildren(h("p", { class: "empty" }, "Frage Immich …"));
  const [t, counts, time] = await Promise.all([api("api/trash"), api("api/cleanup?limit=0"), api("api/timefix?limit=0")]);
  renderCleanupFilters(counts, time);
  c.loaded = true; c.items = t.medien; c.info = t;
  $("#cln-summary").textContent = `${n(t.anzahl, "Medium", "Medien")} · ${fmtBig(t.groesse)}` +
    (t.tage ? ` · Immich löscht nach ${t.tage} Tagen endgültig` : "");
  $("#cln-more").hidden = true;
  if (!t.anzahl) { $("#cln-list").replaceChildren(h("p", { class: "empty" }, "Der Papierkorb ist leer.")); updateActionbar(); return; }
  const per = Object.entries(t.benutzer).map(([u, v]) => `${u}: ${v.anzahl} (${fmtBig(v.groesse)})`).join(" · ");
  const grid = h("div", { class: "grid" });
  for (const m of t.medien) {
    const el = tile({ class: "tile" + (c.sel.has(m.id) ? " selected" : ""), title: m.pfad,
      onclick: () => { c.sel.has(m.id) ? c.sel.delete(m.id) : c.sel.add(m.id); el.classList.toggle("selected", c.sel.has(m.id)); updateActionbar(); } },
    thumb(m),
    h("div", { class: "meta" }, h("div", { class: "name" }, m.dateiname),
      h("div", {}, `${m.benutzer} · ${fmtSize(m.groesse)}`),
      m.verschoben ? h("div", {}, "vom Tool: " + fmtDateTime(m.verschoben)) : null,
      m.endgueltig ? h("div", { class: "muted" }, "weg ab " + fmtDateTime(m.endgueltig)) : null));
    grid.append(el);
  }
  $("#cln-list").replaceChildren(h("p", { class: "muted small" }, per + (t.anzahl > t.medien.length ? ` – gezeigt: die ${t.medien.length} neuesten` : "")), grid);
  updateActionbar();
}

async function restoreTrash(ids, btn) {
  const ok = await confirmDialog({ title: "Wiederherstellen?",
    body: h("p", {}, ids ? `${n(ids.length, "Medium kommt", "Medien kommen")} aus dem Papierkorb zurück.` : "Alles im Papierkorb kommt zurück."),
    okLabel: "Wiederherstellen" });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/trash/restore", { method: "POST", body: { ids } });
    toast(`${r.wiederhergestellt} wiederhergestellt – nach dem nächsten Einlesen wieder in den Listen`);
    await loadTrash();
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

/* ----------------------------------------------------------- Übersicht */

async function loadOverview() {
  const [d, counts] = await Promise.all([api("api/dashboard"), api("api/nav-counts").catch(() => ({}))]);
  for (const [k, value] of Object.entries(counts)) if (value !== null) S.counts[k] = value;
  renderNav();
  S.ovw.loaded = true;
  const box = $("#ovw-body");
  const g = d.gesamt;
  const stat = (value, label, sub) => h("div", { class: "stat" }, h("div", { class: "stat-v" }, value), h("div", { class: "stat-l" }, label), sub ? h("div", { class: "muted small" }, sub) : null);
  const tiles = h("div", { class: "stats-grid" },
    stat(g.medien.toLocaleString("de-DE"), "Medien", `${g.fotos.toLocaleString("de-DE")} Fotos · ${g.videos.toLocaleString("de-DE")} Videos`),
    stat(fmtBig(g.groesse), "Speicher"),
    stat(g.ohne_gps.toLocaleString("de-DE"), "ohne Ort", g.medien ? `${Math.round((g.ohne_gps / g.medien) * 100)} %` : null));
  const users = h("table", { class: "tbl" },
    h("thead", {}, h("tr", {}, ...["Benutzer", "Medien", "Videos", "extern", "Speicher"].map((x) => h("th", {}, x)))),
    h("tbody", {}, ...Object.entries(d.benutzer).map(([u, v]) => h("tr", {}, h("td", {}, u),
      h("td", {}, v.medien.toLocaleString("de-DE")), h("td", {}, v.videos.toLocaleString("de-DE")),
      h("td", {}, v.extern.toLocaleString("de-DE")), h("td", {}, fmtBig(v.groesse))))));
  // Zu tun: jeder Menüpunkt mit offenen Einträgen
  const todo = h("div", { class: "todo-grid" }, ...NAV.filter((sec) => sec.id !== "start").flatMap((sec) => sec.views
    .filter(([id]) => S.counts[id])
    .map(([id, label]) => h("button", { type: "button", class: "todo", onclick: () => go(id) },
      icon(sec.icon), h("b", {}, S.counts[id].toLocaleString("de-DE")),
      h("span", {}, label)))));
  const rep = d.bericht;
  box.replaceChildren(...[
    tiles,
    h("h2", { class: "stage-head" }, "Zu tun"),
    todo.childElementCount ? todo : h("p", { class: "muted" }, "Alles aufgeräumt 🎉"),
    h("h2", { class: "stage-head" }, "Benutzer"), users,
    h("h2", { class: "stage-head" }, "Aufnahmen je Jahr"), yearChart(d.jahre),
    d.erledigt.length ? h("h2", { class: "stage-head" }, "Erledigt je Monat") : null,
    d.erledigt.length ? doneTable(d.erledigt) : null,
    h("p", { class: "muted small" }, rep.kanal === "aus" ? "Wochenbericht: aus (⚙ Einstellungen)"
      : `Wochenbericht per ${rep.kanal}: ${rep.tag}s ${rep.uhrzeit}` + (rep.letzter ? ` · zuletzt ${fmtDateTime(rep.letzter)}` : "") + (rep.fehler ? ` · Fehler: ${rep.fehler}` : "")),
  ].filter(Boolean));
}

// Einfarbiges Säulendiagramm (eine Reihe): Höhe = Anzahl, Tooltip mit Anzahl und Speicher
function yearChart(years) {
  if (!years.length) return h("p", { class: "muted" }, "Keine Daten");
  const max = Math.max(...years.map((y) => y.medien));
  const wrap = h("div", { class: "ychart", role: "img", "aria-label": "Aufnahmen je Jahr" });
  const tip = h("div", { class: "ychart-tip", hidden: true });
  for (const y of years) {
    const bar = h("div", { class: "ybar", tabindex: "0", "aria-label": `${y.jahr}: ${y.medien} Medien, ${fmtBig(y.groesse)}` },
      h("div", { class: "ybar-fill", style: `height:${Math.max(2, (y.medien / max) * 100)}%` }),
      h("div", { class: "ybar-x" }, years.length > 12 ? "’" + y.jahr.slice(2) : y.jahr));
    const show = () => { tip.hidden = false; tip.textContent = `${y.jahr}: ${y.medien.toLocaleString("de-DE")} Medien · ${fmtBig(y.groesse)}`; };
    bar.addEventListener("mouseenter", show); bar.addEventListener("focus", show);
    bar.addEventListener("click", show);
    bar.addEventListener("mouseleave", () => { tip.hidden = true; });
    wrap.append(bar);
  }
  const peak = years.find((y) => y.medien === max);
  return h("div", {}, h("div", { class: "muted small" }, `meiste Aufnahmen: ${peak.jahr} (${max.toLocaleString("de-DE")})`), wrap, tip);
}

const DONE_LABEL = { duplikat: "Duplikate", aufraeumen: "Aufgeräumt", archiv: "Archiviert", stapel: "Gestapelt", albenpflege: "Alben", zeit: "Zeit", ort: "Verortet", album: "In Alben", tag: "Getaggt", papierkorb: "Wiederhergestellt" };
function doneTable(rows) {
  const keys = Object.keys(DONE_LABEL).filter((k) => rows.some((r) => r[k]));
  return h("table", { class: "tbl" },
    h("thead", {}, h("tr", {}, h("th", {}, "Monat"), ...keys.map((k) => h("th", {}, DONE_LABEL[k])))),
    h("tbody", {}, ...rows.slice().reverse().map((r) => h("tr", {}, h("td", {}, month(r.monat)),
      ...keys.map((k) => h("td", {}, r[k] ? r[k].toLocaleString("de-DE") : "–"))))));
}
function month(m) { return new Date(m + "-15").toLocaleDateString("de-DE", { month: "short", year: "numeric" }); }

/* -------------------------------------------------------------- Alben */
const PAGE_ALB = 20;
const ALB_STATUS = { neu: "Neues Album", ergaenzen: "Album ergänzen", vorhanden: "Schon in Alben" };

async function loadAlbums(reset) {
  const a = S.alb;
  if (a.quelle === "ordner") return loadFolders();
  if (reset) { a.trips = []; a.sel.clear(); a.choice = {}; a.ohne = {}; a.open = {}; $("#alb-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const params = new URLSearchParams({ offset: a.trips.length, limit: PAGE_ALB, ignoriert: a.ignored });
  if (a.status) params.set("status", a.status);
  if (a.jahr) params.set("jahr", a.jahr);
  const r = await api("api/album-suggestions?" + params);
  if (r.laedt) {
    // Album-Inhalte werden nach dem Einlesen im Hintergrund gelesen – gleich noch einmal fragen
    $("#alb-list").replaceChildren(h("div", { class: "banner warn" },
      "Die Alben beider Benutzer werden gerade gelesen, um sie mit den Reisen abzugleichen. Das dauert bei vielen Alben ein paar Minuten – die Vorschläge erscheinen dann von selbst."));
    $("#alb-filters").replaceChildren(); $("#alb-summary").textContent = ""; $("#alb-more").hidden = true;
    a.loaded = false;
    setTimeout(() => { if (S.tab === "alb" && !a.loaded) loadTab("alb", true); }, 10000);
    updateActionbar();
    return;
  }
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
  if (!a.status && !a.jahr && !a.ignored) setCount("reisen", r.offen);
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
    found.append(t.album ? `Liegt schon in ${albumLabel(t.album)}. ` : "Liegt schon verteilt in Alben:");
    if (t.fehlend && t.album) found.append(`${n(t.fehlend, "Medium fehlt", "Medien fehlen")} noch. `);
    if (t.album) found.append(albumLinks(t.album));
  } else if (t.status === "ergaenzen") {
    found.append(`Passendes Album gefunden: ${albumLabel(t.album)} – enthält ${t.album.in_reise} von ${t.anzahl}, ${t.fehlend} fehlen. `, albumLinks(t.album));
  } else {
    found.append(`Kein passendes Album – geprüft: ${n(S.alb.info.alben, "Album", "Alben")} beider Benutzer.`);
  }
  const others = t.kandidaten.filter((k) => !t.album || k.id !== t.album.id);
  if (others.length) found.append(h("div", { class: "muted small" }, (t.status === "vorhanden" && !t.album ? "" : "Auch Fotos in: "),
    ...others.map((k, i) => h("span", { class: "alb-other" }, (i ? " · " : "") + `„${k.name}“ (${k.in_reise}) `, albumLinks(k)))));
  card.append(found);

  if (t.beispiele.length) {
    if (t.beispiele_fehlend) for (const m of t.beispiele) m.check = t.album && t.album.id;
    card.append(h("div", { class: "muted small" }, t.beispiele_fehlend ? "Beispiele, die im Album fehlen:" : "Beispiele aus der Reise:"),
      h("div", { class: "strip" }, t.beispiele.map((m) => thumb(m))));
  }
  const allBtn = h("button", { type: "button", class: "btn small", onclick: (e) => openTripReview(t, card, e.currentTarget) }, `Alle ${t.anzahl} prüfen`);
  card.append(h("div", { class: "row-gap", style: "margin-top:8px" }, allBtn, h("span", { class: "muted small trip-sel" }, tripSelText(t))));

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

function tripSelText(t) {
  const off = (S.alb.ohne[t.id] || new Set()).size;
  return off ? `${t.anzahl - off} von ${t.anzahl} ausgewählt` : "";
}

// Alle Medien einer Reise prüfen, nach Tagen; Abgewählte gehören danach nicht mehr zu dieser Reise
async function openTripReview(t, card, btn) {
  const a = S.alb;
  const c = tripChoice(t);
  busy(btn, true);
  let r;
  try {
    r = await api(`api/album-suggestions/${t.id}/media?album=` + encodeURIComponent(c.album || ""));  // leer = neues Album
  } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const inside = r.medien.filter((m) => m.im_album).length;
  const copies = r.medien.filter((m) => m.kopie_im_album).length;
  const media = r.medien.filter((m) => !m.im_album);
  if (r.album) for (const m of media) m.check = r.album;  // Großansicht: „bei Immich nachfragen“
  const keep = (ohne) => { a.ohne[t.id] = new Set(ohne); card.replaceWith(renderTrip(t)); };
  openReview({
    titel: `${t.name}`, medien: media, gruppe: "tag", ohne: [...(a.ohne[t.id] || [])].filter((i) => media.some((m) => m.id === i)),
    hinweis: (inside ? `${inside} liegen schon im Album${copies ? ` (${copies} davon als Kopie oder im Stapel)` : ""} und fehlen hier. ` : "")
      + "Abgewählte gehören danach nicht mehr zu dieser Reise. Liegt doch eins schon drin: groß ansehen → „Bei Immich nachfragen“.",
    aktionen: [
      { text: () => "Übernehmen", leer: true, run: async (ids, ohne) => keep(ohne) },
      { klasse: "primary", text: (k) => `${k} vormerken`, run: async (ids, ohne) => { keep(ohne); await stageTrips([t], null); } },
    ],
  });
}

async function stageTrips(trips, btn) {
  const body = { trips: trips.map((t) => {
    const c = tripChoice(t);
    const ohne = [...(S.alb.ohne[t.id] || [])];
    const sel = c.album ? { id: t.id, album: c.album } : { id: t.id, album: null, name: (c.name || t.name).trim() };
    return ohne.length ? { ...sel, ohne } : sel;
  }) };
  if (trips.length > 1) {
    const ok = await confirmDialog({
      title: "Alben vormerken?",
      body: [h("ul", {}, trips.map((t) => {
        const c = tripChoice(t);
        const al = t.kandidaten.find((k) => k.id === c.album);
        return h("li", {}, al ? `${t.name}: „${al.name}“ ergänzen` : `${t.name}: neues Album „${(c.name || t.name).trim()}“`);
      })), h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter Vorgemerkt.")],
      okLabel: "Vormerken",
    });
    if (!ok) return;
  }
  busy(btn, true);
  try {
    const r = await api("api/staged/albums", { method: "POST", body });
    toast(`${n(r.vorgemerkt, "Album", "Alben")} vorgemerkt` + (r.hinweise.length ? " – mit Hinweisen, siehe Vorgemerkt" : ""));
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
const STAGE_TYPES = [["duplikat", "Duplikate"], ["aufraeumen", "Aufräumen"], ["archiv", "Archivieren"], ["stapel", "Stapel"], ["albenpflege", "Alben aufräumen"], ["zeit", "Aufnahmezeit"], ["ort", "Orte"], ["album", "Alben"], ["tag", "Tags"]];
const STAGE_ACTION = { papierkorb: "Papierkorb", album: "Prüf-Album", keine: "–" };

// Nach dem Vormerken: Quelle neu laden (Vorgemerktes ist dort weg) und Zähler aktualisieren
async function afterStage(tab) {
  S.stage.loaded = false;
  await Promise.all([loadTab(tab, true), loadTab("stage", true)]);
  loadCounts();
}

async function loadStaged() {
  const [r, hist] = await Promise.all([api("api/staged"), api("api/history?limit=40")]);
  S.stage.entries = r.eintraege;
  S.stage.info = r;
  S.stage.loaded = true;
  renderStaged();
  renderHistory(hist.eintraege);
}

const HIST_SOURCE = { oberflaeche: "Oberfläche", api: "API/Kommandozeile", automatisch: "automatisch" };

function renderHistory(entries) {
  const list = $("#history-list");
  if (!entries.length) { list.replaceChildren(h("p", { class: "muted" }, "Noch nichts übertragen.")); return; }
  list.replaceChildren(...entries.map((e) => {
    let status;
    if (e.rueckgaengig) status = h("span", { class: "chip" }, "↩ rückgängig gemacht " + fmtDateTime(e.rueckgaengig));
    else if (e.rueckgaengig_moeglich) status = h("button", { type: "button", class: "btn small", onclick: (ev) => undoHistory(e, ev.currentTarget) }, "Rückgängig");
    else status = h("span", { class: "muted small" }, e.nicht_rueckgaengig || "");
    return h("div", { class: "hist-row" + (e.rueckgaengig ? " undone" : "") },
      h("div", { class: "grow" }, h("div", {}, e.titel),
        h("div", { class: "muted small" }, `${fmtDateTime(e.zeit)} · ${n(e.anzahl, "Medium", "Medien")} · ${HIST_SOURCE[e.quelle] || e.quelle}`),
        e.rueck_fehler && e.rueck_fehler.length ? h("div", { class: "banner err" }, e.rueck_fehler.join(" · ")) : null),
      status);
  }));
}

async function undoHistory(e, btn) {
  const ok = await confirmDialog({
    title: "Rückgängig machen?",
    body: [h("p", {}, e.titel), h("p", { class: "muted" }, {
      duplikat: "Kopien kommen aus dem Papierkorb zurück bzw. wieder aus dem Prüf-Album heraus.",
      album: "Neu angelegte Alben werden gelöscht (die Fotos bleiben), ergänzte Fotos wieder herausgenommen, Freigaben zurückgenommen.",
      tag: "Die gesetzten Tags werden wieder entfernt.",
      zeit: "Die Aufnahmezeit wird wieder zurückverschoben.",
      aufraeumen: "Medien kommen aus dem Papierkorb zurück bzw. wieder aus dem Prüf-Album heraus.",
      stapel: "Die Stapel werden aufgelöst; aus dem Album genommene Fotos kommen wieder hinein.",
      archiv: "Die Medien kommen zurück in die Zeitleiste.",
      albenpflege: "Hinzugefügte Fotos kommen wieder heraus, Freigaben werden zurückgenommen, gelöschte Alben mit Inhalt neu angelegt, das alte Titelbild kommt zurück.",
    }[e.typ] || "")],
    okLabel: "Rückgängig",
  });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api(`api/history/${e.id}/undo`, { method: "POST" });
    toast(r.fehler.length ? `Rückgängig mit ${r.fehler.length} Fehlern` : "Rückgängig gemacht", !!r.fehler.length);
    S.dup.loaded = S.loc.loaded = S.alb.loaded = S.tags.loaded = S.cln.loaded = false;
    await loadTab("stage", true);
    loadCounts();
  } catch (err) {
    toast(err.message, true);
    busy(btn, false);
  }
}

function stageMedia(e) {
  return h("div", { class: "strip" }, e.medien.map((m) => {
    let cap = "";
    if (e.typ === "duplikat") cap = m.bleibt ? "bleibt" : (STAGE_ACTION[m.aktion] || "–");
    else if (e.typ === "aufraeumen") cap = STAGE_ACTION[m.aktion] || "–";
    else if (e.typ === "stapel") cap = "oben";
    else if (e.typ === "zeit") cap = m.neue_zeit ? fmtTaken(m.neue_zeit) : "";
    else if (e.typ === "ort") cap = m.neuer_ort || "";
    return h("figure", { class: "stage-fig" + (e.typ === "duplikat" ? (m.bleibt ? " keep" : " drop") : "") },
      thumb(m), cap ? h("figcaption", {}, cap) : null);
  }));
}

function renderStaged() {
  const st = S.stage;
  const cnt = st.info ? st.info.anzahl : 0;
  setCount("stage", cnt);
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
      const trash = e.daten.schritte ? e.daten.schritte.filter((s) => s.aktion === "papierkorb").length : 0;
      list.append(h("article", { class: "card" },
        h("div", { class: "card-head" },
          h("div", {}, h("h2", {}, e.titel),
            h("span", { class: "muted" }, `${n(e.anzahl, "Medium", "Medien")} · vorgemerkt ${fmtDateTime(e.erstellt)}`)),
          trash ? h("span", { class: "chip" }, `🗑 ${trash}`) : null),
        e.fehler ? h("div", { class: "banner err" }, "Letzte Übertragung fehlgeschlagen: " + e.fehler) : null,
        typ === "album" && e.daten.hinweise.length ? h("div", { class: "banner warn" }, e.daten.hinweise.join(" · ")) : null,
        typ === "album" && e.daten.album_id ? h("div", { class: "small" }, "Album ansehen: ", albumLinks({ id: e.daten.album_id, name: e.daten.name })) : null,
        e.medien.length ? stageMedia(e) : null,
        h("div", { class: "row-gap stage-actions" },
          h("button", { type: "button", class: "btn small", onclick: (ev) => unstage(e, ev.currentTarget) }, "Zurücknehmen"),
          h("button", { type: "button", class: "btn small primary", onclick: (ev) => applyStaged([e.id], ev.currentTarget) }, "Übertragen"))));
    }
  }
  updateActionbar();
}

const STAGE_SOURCE = { duplikat: "dup", aufraeumen: "cln", archiv: "tags", stapel: "cln", albenpflege: "cln", zeit: "cln", ort: "loc", album: "alb", tag: "tags" };

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
  const trash = entries.filter((e) => e.daten.schritte)
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
    loadCounts();
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
      // gewählte Bilder ohne Ort-Vorschlag: archivieren (vormerken) oder „kein Ort nötig“
      buttons.push(h("button", { class: "btn small", type: "button", title: "Aus der Zeitleiste nehmen – bleibt in Suche und Alben",
        onclick: (e) => archiveLocSelection(e.currentTarget) }, "Archivieren"));
      buttons.push(h("button", { class: "btn small", type: "button", title: "Hier dauerhaft ausblenden",
        onclick: (e) => noPlaceLocSelection(e.currentTarget) }, "Kein Ort nötig"));
      buttons.push(h("button", { class: "btn small", type: "button", onclick: () => openPlaceSearch({ ids: [...S.loc.sel], count: cnt, label: "Auswahl" }) }, "Ort wählen …"));
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !chosen.some(selectable), onclick: (e) => applyLocation(e.currentTarget) }, "Vormerken"));
    } else {
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !sure, onclick: (e) => applyAllSure(e.currentTarget) }, `Alle sicheren prüfen (${sure})`));
    }
  } else if (S.tab === "ovw") {
    info.textContent = "Stand der Bibliothek";
  } else if (S.tab === "cln" && S.cln.bereich === "alben") {
    info.textContent = S.cln.ignored ? "Ausgeblendete Einträge" : "Pro Eintrag zusammenführen oder löschen";
  } else if (S.tab === "cln" && S.cln.bereich === "stapel") {
    const c = S.cln;
    const chosen = c.items.filter((p) => c.sel.has(p.id));
    const list = chosen.length ? chosen : c.items;
    info.textContent = chosen.length ? `${chosen.length} gewählt` : (c.items.length ? "Alle Vorschläge:" : "");
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !list.length,
      onclick: (e) => stageStacks(list, e.currentTarget) }, `Stapeln (${list.length})`));
  } else if (S.tab === "cln" && S.cln.bereich === "papierkorb") {
    const sel = [...S.cln.sel];
    info.textContent = sel.length ? `${sel.length} gewählt` : "Antippen zum Auswählen";
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !(S.cln.info && S.cln.info.anzahl),
      onclick: (e) => restoreTrash(sel.length ? sel : null, e.currentTarget) }, sel.length ? "Wiederherstellen" : "Alle wiederherstellen"));
  } else if (S.tab === "cln" && S.cln.bereich === "zeit") {
    const c = S.cln;
    const chosen = c.items.filter((it) => c.sel.has(it.id));
    const list = (chosen.length ? chosen : c.items).filter((it) => timeChoice(it));
    info.textContent = c.ignored ? "Ausgeblendete Einträge" : chosen.length ? `${chosen.length} gewählt` : "Alle mit Vorschlag:";
    if (!c.ignored) buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !list.length,
      onclick: (e) => stageTimeFixes(list, e.currentTarget) }, `Vormerken (${list.length})`));
  } else if (S.tab === "cln") {
    const c = S.cln;
    const chosen = c.items.filter((it) => c.sel.has(it.id));
    const list = chosen.length ? chosen : c.items;
    info.textContent = c.ignored ? "Behaltene Einträge" : chosen.length ? `${chosen.length} gewählt` : (c.items.length ? "Alle angezeigten:" : "Nichts offen");
    if (!c.ignored && c.bereich === "serien") {
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !list.length, onclick: (e) => stageBurstStacks(list, e.currentTarget) }, "Stapeln"));
    }
    if (!c.ignored && !chosen.length && c.bereich !== "serien") {
      // ohne Auswahl: alle Treffer des Bereichs in der Prüf-Ansicht (auch die noch nicht geladenen)
      info.textContent = c.total ? "Alle Treffer:" : "Nichts offen";
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !c.total, onclick: (e) => openCleanupReview(e.currentTarget) }, `Alle ${c.total} prüfen`));
    } else if (!c.ignored) {
      buttons.push(h("button", { class: "btn small" + (c.bereich === "serien" ? "" : " primary"), type: "button", disabled: !list.length, onclick: (e) => stageCleanup("album", list, e.currentTarget) }, "Ins Prüf-Album"));
      buttons.push(h("button", { class: "btn small danger", type: "button", disabled: !list.length, onclick: (e) => stageCleanup("papierkorb", list, e.currentTarget) }, "Papierkorb"));
    }
  } else if (S.tab === "alb" && S.alb.quelle === "ordner") {
    const open = S.fol.ignored ? [] : S.fol.items.filter((p) => p.status === "neu" || p.status === "ergaenzen");
    info.textContent = open.length ? "Alle offenen Ordner:" : "";
    buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !open.length,
      onclick: (e) => stageFolders(open, e.currentTarget) }, `Vormerken (${open.length})`));
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
    const g = S.sug;
    if (cnt) {
      info.textContent = `${n(cnt, "Regel", "Regeln")} · ${n(total, "Medium", "Medien")}`;
      buttons.push(h("button", { class: "btn small primary", type: "button", onclick: (e) => applyTags(e.currentTarget) }, "Tags vormerken"));
    } else {
      const open = g.hidden ? [] : g.items.filter((s) => s.neu);
      info.textContent = open.length ? "Alle Vorschläge:" : "";
      buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !open.length, onclick: (e) => stageSuggestions(open, e.currentTarget) }, `Alle taggen (${open.length})`));
    }
  }
  $("#ab-buttons").replaceChildren(...buttons);
  const show = buttons.some((b) => !b.disabled);
  $("#actionbar").hidden = !show;
  document.body.classList.toggle("has-ab", show);
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

const TAB_TARGET = { ovw: "#ovw-body", dup: "#dup-list", loc: "#loc-list", cln: "#cln-list", alb: "#alb-list", tags: "#tags-list", stage: "#stage-list", set: "#set-welcome" };

async function doLoadTab(tab, force) {
  try {
    if (tab === "dup" && (force || !S.dup.loaded)) await loadDuplicates(true);
    if (tab === "loc" && (force || !S.loc.loaded)) await loadLocation(true);
    if (tab === "ovw" && (force || !S.ovw.loaded)) await loadOverview();
    if (tab === "cln" && (force || !S.cln.loaded)) await loadCleanup(true);
    if (tab === "alb" && (force || !S.alb.loaded)) await loadAlbums(true);
    if (tab === "tags" && (force || !S.tags.loaded)) await Promise.all([loadTags(), loadSuggestions()]);
    if (tab === "stage" && (force || !S.stage.loaded)) await loadStaged();
    if (tab === "set" && (force || !S.set.loaded)) { await loadSettings(); loadVersion(); }
    if (tab !== "set" && S.status && !S.status.bibliothek) loadStatus(false);
  } catch (e) {
    const box = e.setup
      ? h("div", { class: "banner warn" }, "Noch nicht eingerichtet. ",
        h("button", { type: "button", class: "btn small", onclick: () => go("set") }, "Zu den Einstellungen"))
      : h("div", { class: "banner err" }, "Laden fehlgeschlagen: " + e.message);
    $(TAB_TARGET[tab]).replaceChildren(box);
  }
  updateActionbar();
}

function showTab(tab, force = false) {
  S.tab = tab;
  document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== "tab-" + tab; });
  updateActionbar();
  return loadTab(tab, force);
}

/* -------------------------------------------------------------- Menü */
const ICON = {
  home: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H10v6H4a1 1 0 0 1-1-1z"/>',
  spark: '<path d="M12 3l1.8 4.7 4.7 1.8-4.7 1.8L12 16l-1.8-4.7-4.7-1.8 4.7-1.8z"/><path d="M19 14.5l.8 2.2 2.2.8-2.2.8L19 20.5l-.8-2.2-2.2-.8 2.2-.8z"/>',
  tag: '<path d="M3 12V4a1 1 0 0 1 1-1h8l9 9-9 9z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  album: '<rect x="3" y="7" width="14" height="14" rx="2"/><path d="M7 3h12a2 2 0 0 1 2 2v12"/><path d="M3 17l4-4 3 3 2-2 5 5"/>',
  list: '<path d="M10 6h11M10 12h11M10 18h11"/><path d="M3 6l1.5 1.5L7 5M3 12l1.5 1.5L7 11M3 18l1.5 1.5L7 17"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  scan: '<path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/>',
};

function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", "ico");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICON[name];
  return s;
}

// Bereiche des Menüs; jeder Unterpunkt zeigt ein Panel (tab) mit Voreinstellung
const NAV = [
  { id: "start", label: "Start", icon: "home", views: [["start", "Übersicht", { tab: "ovw" }]] },
  { id: "fotos", label: "Aufräumen", icon: "spark", views: [
    ["dup", "Duplikate", { tab: "dup" }],
    ["serien", "Serienbilder", { tab: "cln", bereich: "serien" }],
    ["speicher", "Speicherfresser", { tab: "cln", bereich: "speicher" }],
    ["qualitaet", "Unscharf & dunkel", { tab: "cln", bereich: "qualitaet" }],
    ["verwaist", "Verwaiste Dateien", { tab: "cln", bereich: "verwaist" }],
    ["papierkorb", "Papierkorb", { tab: "cln", bereich: "papierkorb" }]] },
  { id: "ordnen", label: "Ordnen", icon: "tag", views: [
    ["ort", "Ohne Ort", { tab: "loc" }],
    ["zeit", "Falsche Zeit", { tab: "cln", bereich: "zeit" }],
    ["tags", "Tags", { tab: "tags" }],
    ["stapel", "Stapeln", { tab: "cln", bereich: "stapel" }]] },
  { id: "alben", label: "Alben", icon: "album", views: [
    ["reisen", "Reisen", { tab: "alb", quelle: "reisen" }],
    ["ordner", "Ordner", { tab: "alb", quelle: "ordner" }],
    ["albenpflege", "Alben aufräumen", { tab: "cln", bereich: "alben" }]] },
  { id: "stage", label: "Vorgemerkt", icon: "list", views: [["stage", "Vorgemerkt", { tab: "stage" }]] },
];
const VIEWS = {};
for (const sec of NAV) for (const [id, label, preset] of sec.views) VIEWS[id] = { id, label, preset, sec };
VIEWS.set = { id: "set", label: "Einstellungen", preset: { tab: "set" }, sec: null };
S.view = "dup";
S.counts = {};
S.lastView = {};

function setCount(view, value) {
  if (S.counts[view] === value) return;
  S.counts[view] = value;
  renderNav();
}

const badge = (value) => (value ? h("span", { class: "badge-n" }, value > 999 ? "999+" : String(value)) : null);
const secCount = (sec) => sec.views.reduce((s, [id]) => s + (S.counts[id] || 0), 0);

function renderNav() {
  const cur = VIEWS[S.view] || VIEWS.dup;
  const items = NAV.map((sec) => {
    const active = cur.sec === sec;
    const main = h("button", { type: "button", class: "nav-main", "aria-current": active ? "page" : null,
      onclick: () => go(S.lastView[sec.id] || sec.views[0][0]) },
    icon(sec.icon), h("span", { class: "nav-l" }, sec.label), badge(sec.id === "start" ? 0 : secCount(sec)));
    const subs = sec.views.length > 1 ? h("div", { class: "nav-subs" }, ...sec.views.map(([id, label]) =>
      h("button", { type: "button", class: "nav-sub", "aria-current": S.view === id ? "page" : null, onclick: () => go(id) },
        h("span", {}, label), badge(S.counts[id])))) : null;
    return h("div", { class: "nav-sec" + (active ? " active" : "") }, main, subs);
  });
  const set = h("button", { type: "button", class: "nav-main nav-set", "aria-current": S.view === "set" ? "page" : null, onclick: () => go("set") },
    icon("gear"), h("span", { class: "nav-l" }, "Einstellungen"));
  const brand = h("div", { class: "nav-brand" }, $(".brand .logo").cloneNode(true), "Immich-Pflege");
  $("#mainnav").replaceChildren(brand, ...items, set);
  const sub = $("#subnav");
  if (cur.sec && cur.sec.views.length > 1) {
    sub.hidden = false;
    sub.replaceChildren(...cur.sec.views.map(([id, label]) =>
      h("button", { type: "button", class: "sub-chip", "aria-current": S.view === id ? "page" : null, onclick: () => go(id) },
        label, badge(S.counts[id]))));
    const on = sub.querySelector('[aria-current="page"]');
    if (on && on.scrollIntoView) on.scrollIntoView({ block: "nearest", inline: "nearest" });
  } else {
    sub.hidden = true;
    sub.replaceChildren();
  }
  $("#page-title").textContent = !cur.sec ? cur.label : cur.sec.id === "start" ? "Immich-Pflege" : cur.sec.label;
  $("#set-btn").setAttribute("aria-current", S.view === "set" ? "page" : "false");
}

function go(view, push = true) {
  const v = VIEWS[view] || VIEWS.dup;
  const p = v.preset;
  let force = false;
  if (p.bereich && S.cln.bereich !== p.bereich) { S.cln.bereich = p.bereich; S.cln.kategorie = null; S.cln.loaded = false; force = p.tab === S.tab; }
  if (p.quelle && S.alb.quelle !== p.quelle) { S.alb.quelle = p.quelle; S.alb.loaded = false; force = p.tab === S.tab; }
  const changed = S.view !== v.id;
  S.view = v.id;
  if (v.sec) S.lastView[v.sec.id] = v.id;
  if (push && location.hash !== "#" + v.id) history.pushState(null, "", "#" + v.id);
  try { localStorage.setItem("pflege-view", v.id); } catch (_) { /* egal */ }
  renderNav();
  if (changed) window.scrollTo(0, 0);
  return showTab(p.tab, force);
}

let countsTimer = null;
function loadCounts() {
  if (S.status && !S.status.eingerichtet) return;
  clearTimeout(countsTimer);
  countsTimer = setTimeout(async () => {
    try {
      const r = await api("api/nav-counts");
      for (const [k, value] of Object.entries(r)) if (value !== null) S.counts[k] = value;
      renderNav();
      if (r.reisen === null) setTimeout(loadCounts, 10000); // Alben werden noch gelesen
    } catch (_) { /* Zähler sind nur Beiwerk */ }
  }, 300);
}

/* ------------------------------------------------------------- Start */
$("#scan-btn").append(icon("scan"), h("span", { class: "btn-l" }, "Einlesen"));
$("#set-btn").append(icon("gear"));
$("#scan-btn").addEventListener("click", () => rescan());
$("#v-close").addEventListener("click", () => $("#viewer").close());
$("#rv-close").addEventListener("click", () => $("#review").close());
$("#rv-all").addEventListener("click", () => setAllReview(true));
$("#rv-jump").addEventListener("change", (e) => {
  const sec = $("#rv-body").querySelectorAll(".rv-month")[+e.target.value];  // Gruppe
  if (sec) $("#rv-body").scrollTop = sec.offsetTop - $("#rv-body").offsetTop;
  e.target.value = "";
});
$("#rv-none").addEventListener("click", () => setAllReview(false));
document.querySelectorAll("[data-rv-mode]").forEach((b) => b.addEventListener("click", () => {
  RV.mode = b.dataset.rvMode;
  document.querySelectorAll("[data-rv-mode]").forEach((x) => x.classList.toggle("on", x === b));
}));
document.querySelectorAll("[data-rv-size]").forEach((b) => b.addEventListener("click", () => {
  RV.size = b.dataset.rvSize;
  try { localStorage.setItem("pflege-rv-size", RV.size); } catch (_) { /* egal */ }
  renderReview();
}));
$("#v-prev").addEventListener("click", () => viewerStep(-1));
$("#v-next").addEventListener("click", () => viewerStep(1));
$("#viewer").addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") viewerStep(-1);
  if (e.key === "ArrowRight") viewerStep(1);
});
(() => {  // wischen
  let x0 = null;
  const st = $("#v-stage");
  st.addEventListener("touchstart", (e) => { x0 = e.touches.length === 1 ? e.touches[0].clientX : null; }, { passive: true });
  st.addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0;
    if (Math.abs(dx) > 50) viewerStep(dx < 0 ? 1 : -1);
    x0 = null;
  });
  st.addEventListener("click", (e) => { if (e.target === st) $("#viewer").close(); });
})();
$("#set-btn").addEventListener("click", () => go("set"));
window.addEventListener("popstate", () => go(location.hash.slice(1), false));
$("#scan-full").addEventListener("click", (e) => rescan(true, e.currentTarget));
$("#dup-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadDuplicates(false).finally(() => busy(e.currentTarget, false)); });
$("#loc-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadLocation(false).finally(() => busy(e.currentTarget, false)); });
$("#dup-done").addEventListener("change", (e) => { S.dup.includeDone = e.target.checked; loadTab("dup", true); });
$("#loc-only").addEventListener("change", (e) => { S.loc.only = e.target.checked; loadTab("loc", true); });
$("#loc-conf").addEventListener("change", (e) => { S.loc.minConf = e.target.value || null; loadTab("loc", true); });
$("#place-q").addEventListener("input", () => { clearTimeout(placeTimer); placeTimer = setTimeout(searchPlaces, 300); });
$("#set-home-q").addEventListener("input", () => { clearTimeout(homeTimer); homeTimer = setTimeout(searchHome, 300); });
$("#loc-hours").addEventListener("change", (e) => {
  const v = parseFloat(String(e.target.value).replace(",", "."));
  if (v > 0 && v <= 48) { S.loc.hours = v; loadTab("loc", true); } else { e.target.value = S.loc.hours; }
});
$("#cln-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadCleanup(false).finally(() => busy(e.currentTarget, false)); });
$("#alb-more").addEventListener("click", (e) => { busy(e.currentTarget, true); loadAlbums(false).finally(() => busy(e.currentTarget, false)); });
$("#tags-reload").addEventListener("click", () => loadTab("tags", true));
$("#smart-go").addEventListener("click", () => { const q = $("#smart-q").value.trim(); if (q) loadSmart({ suche: q }); });
$("#smart-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("#smart-go").click(); } });
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
$("#set-rep-channel").addEventListener("change", updateReportFields);
$("#set-rep-test").addEventListener("click", (e) => sendTestReport(e.currentTarget));
$("#set-mem-test").addEventListener("click", (e) => sendTestMemories(e.currentTarget));
$("#set-logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" }).catch(() => null);
  location.href = "/login";
});
$("#version-check").addEventListener("click", async (e) => { busy(e.currentTarget, true); await loadVersion(true); busy(e.currentTarget, false); });
$("#version-update").addEventListener("click", (e) => startUpdate(e.currentTarget));

if ("serviceWorker" in navigator) {
  try { navigator.serviceWorker.register("sw.js").catch(() => {}); } catch (_) { /* ohne geht es auch */ }
}

(async function init() {
  let view = location.hash.slice(1);
  if (!VIEWS[view]) {
    try { view = localStorage.getItem("pflege-view") || "start"; } catch (_) { view = "start"; }
  }
  renderNav();
  await loadStatus(true);
  loadVersion();
  setTimeout(loadVersion, 6000); // Ergebnis der Hintergrundprüfung abholen
  setInterval(loadVersion, 3600 * 1000);
  if (S.status && !S.status.eingerichtet) {
    await go("set", false);
    return;
  }
  history.replaceState(null, "", "#" + (VIEWS[view] ? view : "start"));
  await go(view, false);
  // Nach dem ersten Laden (ggf. Einlesen) Status und Zähler fürs Menü holen
  loadStatus(false);
  loadCounts();
})();
