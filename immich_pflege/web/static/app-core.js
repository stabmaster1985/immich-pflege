"use strict";
// Grundlagen: Zustand, Hilfsfunktionen, Vorschauen, Großansicht, Status. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.

const PAGE_DUP = 20;

const S = {
  tab: "dup",
  status: null,
  dup: { groups: [], total: 0, open: 0, keep: {}, sel: new Set(), includeDone: false, art: null, monat: null, crossUser: false, ignored: false, loaded: false, info: null },
  stats: { jahr: null, metric: "medien" },
  loc: { series: [], total: 0, sel: new Set(), open: new Set(), hours: null, only: false, minConf: null, ort: null, monat: null, herkunft: null, benutzer: null, loaded: false, info: null },
  ovw: { loaded: false },
  cln: { bereich: "speicher", kategorie: null, ignored: false, items: [], total: 0, sel: new Set(), keep: {}, loaded: false, info: null },
  fol: { items: [], status: null, ignored: false, choice: {}, sync: {}, ohne: {} },
  alb: { quelle: "reisen", trips: [], total: 0, status: null, jahr: null, ignored: false, sel: new Set(), choice: {}, ohne: {}, open: {}, loaded: false, info: null },
  sug: { items: [], hidden: false, info: null, smart: null, cut: null, tag: "" },
  per: { loaded: false, data: null, keep: {} },
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
  if (b >= 1099511627776) return (b / 1099511627776).toFixed(2).replace(".", ",") + " TB";
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

/* ------------------------------------------------- Fehlende Vorschauen */
// Vorschaubild lädt nicht: einmal nachladen, sonst Platzhalter mit dem Grund (HTTP-Status von Immich)
document.addEventListener("error", (e) => {
  const img = e.target;
  if (!(img instanceof HTMLImageElement) || !/(^|\/)thumb\//.test(img.getAttribute("src") || "")) return;
  if (!img.dataset.retry) {
    img.dataset.retry = "1";
    const src = img.getAttribute("src");
    setTimeout(() => { img.src = src + (src.includes("?") ? "&" : "?") + "r=1"; }, 2000 + Math.random() * 2000);
    return;
  }
  thumbFailed(img);
}, true);

async function thumbFailed(img) {
  if (img.classList.contains("thumb-err")) return;
  img.classList.add("thumb-err");
  let why = "";
  try {
    const r = await fetch(img.getAttribute("src"), { cache: "no-store" });
    if (r.ok) { img.classList.remove("thumb-err"); const s = img.getAttribute("src"); img.src = s + (s.includes("?") ? "&" : "?") + "ok=1"; return; }  // klappt inzwischen
    const detail = (await r.text()).replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim().slice(0, 160);
    img.dataset.detail = detail;
    why = r.ok ? "" : (r.status === 403 && /permission/i.test(detail) ? "dem API-Key fehlt ein Recht – ⚙ Einstellungen → Verbindung testen"
      : r.status === 403 ? "von Immich abgewiesen" : r.status === 400 ? "kein Zugriff oder unbekannt (gehört es einem anderen Konto?)" : r.status === 404 ? "Immich hat keine Vorschau – wird neu erzeugt, später neu laden" : "Immich-Fehler") + ` (HTTP ${r.status})`;
  } catch (_) { why = "keine Verbindung"; }
  img.alt = "Vorschau fehlt" + (why ? ": " + why : "");
  img.title = img.alt + (img._m && img._m.dateiname ? " – " + img._m.dateiname : "") + (img.dataset.detail ? "\n" + img.dataset.detail : "");
  const code = (why.match(/HTTP \d+/) || [""])[0];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120"><rect width="120" height="120" fill="#8884"/>`
    + `<text x="60" y="56" font-size="13" text-anchor="middle" fill="#666" font-family="sans-serif">Vorschau fehlt</text>`
    + `<text x="60" y="76" font-size="12" text-anchor="middle" fill="#666" font-family="sans-serif">${code}</text></svg>`;
  img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
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
  big.onerror = () => { if (VW.list[VW.i] === m) thumbFailed(img); };
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

// Knopf während einer Aktion sperren. Den Knopf vorher merken: e.currentTarget ist nach dem Klick
// (also nach dem ersten await) leer – sonst bliebe der Knopf für immer gesperrt.
function onBusyClick(sel, action) {
  $(sel).addEventListener("click", (e) => {
    const btn = e.currentTarget;
    busy(btn, true);
    Promise.resolve().then(action).catch((err) => toast(err.message, true)).finally(() => {
      busy(btn, false);
      if (typeof autoMore !== "undefined" && btn.classList.contains("more")) {  // noch sichtbar? dann gleich weiter
        autoMore.unobserve(btn);
        autoMore.observe(btn);
      }
    });
  });
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
