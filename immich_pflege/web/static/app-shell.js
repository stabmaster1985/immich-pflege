"use strict";
// Aktionsleiste, Tabs, Menü und Start der Oberfläche (zuletzt laden). Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
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
      const series = S.dup.groups.filter((g) => S.dup.sel.has(g.id) && g.art === "serie");
      if (series.length) buttons.push(h("button", { class: "btn small", type: "button",
        onclick: (e) => stackDuplicates(series.map((g) => ({ id: g.id, keep: S.dup.keep[g.id] || g.behalten })), e.currentTarget) }, `Stapeln (${series.length})`));
      buttons.push(h("button", { class: "btn small primary", type: "button", onclick: (e) => applyDuplicates("album", e.currentTarget) }, "Ins Prüf-Album"));
      buttons.push(h("button", { class: "btn small danger", type: "button", onclick: (e) => applyDuplicates("papierkorb", e.currentTarget) }, "Papierkorb"));
    } else {
      const open = S.dup.open || 0;
      info.textContent = open ? "Aktuelle Auswahl:" : "Nichts offen";
      if (S.dup.art === "serie") {
        info.textContent = S.dup.groups.length ? "Serienbilder:" : "Nichts offen";
        buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !S.dup.groups.length,
          onclick: (e) => stackDuplicates([], e.currentTarget, true) }, "Alle stapeln"));
      } else buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !open, onclick: (e) => applyAllDuplicates("album", e.currentTarget) }, `Alle ins Album (${open})`),
        h("button", { class: "btn small danger", type: "button", disabled: !open, onclick: (e) => applyAllDuplicates("papierkorb", e.currentTarget) }, "Papierkorb …"));
    }
  } else if (S.tab === "loc") {
    const cnt = S.loc.sel.size;
    // sichere Vorschläge passend zu Herkunft/Benutzer (aus den Orten gezählt)
    const sure = !S.loc.info ? 0 : (S.loc.herkunft || S.loc.benutzer)
      ? S.loc.info.orte.reduce((a, o) => a + (o.nach_sicherheit ? o.nach_sicherheit.hoch : 0), 0)
      : S.loc.info.nach_sicherheit.hoch;
    info.textContent = cnt ? n(cnt, "Medium", "Medien") + " gewählt" : "Serie vormerken oder Bilder antippen";
    if (cnt) {
      const chosen = S.loc.series.flatMap((s) => s.medien).filter((m) => S.loc.sel.has(m.id));
      // gewählte Bilder ohne Ort-Vorschlag: archivieren (vormerken) oder „kein Ort nötig“
      buttons.push(h("button", { class: "btn small", type: "button", title: "Hier ausblenden (kein Ort nötig) und aus der Zeitleiste nehmen – bleibt in Suche und Alben",
        onclick: (e) => archiveLocSelection(e.currentTarget) }, "Ausblenden + archivieren"));
      buttons.push(h("button", { class: "btn small", type: "button", title: "Nur hier dauerhaft ausblenden, bleibt in der Zeitleiste",
        onclick: (e) => noPlaceLocSelection(e.currentTarget) }, "Nur ausblenden"));
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
  } else if (S.tab === "cln" && S.cln.bereich === "ausrichtung") {
    // nichts soll weg: Immich die Dateien neu einlesen lassen (behebt quer stehende Vorschauen meist)
    const c = S.cln;
    const chosen = c.items.filter((it) => c.sel.has(it.id));
    const list = (chosen.length ? chosen : c.items).filter((it) => it.kategorie === "drehung");
    info.textContent = c.ignored ? "Behaltene Einträge" : chosen.length ? `${chosen.length} gewählt` : "Unstimmige Drehung:";
    if (!c.ignored) buttons.push(h("button", { class: "btn small primary", type: "button", disabled: !list.length,
      title: "Immich liest die Dateien neu ein und erzeugt die Vorschau neu – an den Fotos ändert sich nichts",
      onclick: (e) => refreshOrientation(list, e.currentTarget) }, `In Immich neu einlesen (${list.length})`));
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
      if (c.bereich !== "verwaist") buttons.push(h("button", { class: "btn small", type: "button", disabled: !list.length, title: "Aus der Zeitleiste nehmen – bleibt erhalten",
        onclick: (e) => archiveCleanup(list, e.currentTarget) }, "Archivieren"));
      buttons.push(h("button", { class: "btn small" + (["serien", "videos"].includes(c.bereich) ? "" : " primary"), type: "button", disabled: !list.length, onclick: (e) => stageCleanup("album", list, e.currentTarget) }, "Ins Prüf-Album"));
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

const TAB_TARGET = { per: "#per-list", ovw: "#ovw-body", dup: "#dup-list", loc: "#loc-list", cln: "#cln-list", alb: "#alb-list", tags: "#tags-list", stage: "#stage-list", set: "#set-welcome" };

async function doLoadTab(tab, force) {
  try {
    if (tab === "dup" && (force || !S.dup.loaded)) await loadDuplicates(true);
    if (tab === "loc" && (force || !S.loc.loaded)) await loadLocation(true);
    if (tab === "ovw" && (force || !S.ovw.loaded)) await loadOverview();
    if (tab === "cln" && (force || !S.cln.loaded)) await loadCleanup(true);
    if (tab === "alb" && (force || !S.alb.loaded)) await loadAlbums(true);
    if (tab === "tags" && (force || !S.tags.loaded)) await Promise.all([loadTags(), loadSuggestions()]);
    if (tab === "stage" && (force || !S.stage.loaded)) await loadStaged();
    if (tab === "per" && (force || !S.per.loaded)) await loadPeople();
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
    ["videos", "Videos", { tab: "cln", bereich: "videos" }],
    ["qualitaet", "Unscharf & dunkel", { tab: "cln", bereich: "qualitaet" }],
    ["ausrichtung", "Gedreht & gespiegelt", { tab: "cln", bereich: "ausrichtung" }],
    ["verwaist", "Verwaiste Dateien", { tab: "cln", bereich: "verwaist" }],
    ["papierkorb", "Papierkorb", { tab: "cln", bereich: "papierkorb" }]] },
  { id: "ordnen", label: "Ordnen", icon: "tag", views: [
    ["ort", "Ohne Ort", { tab: "loc" }],
    ["zeit", "Falsche Zeit", { tab: "cln", bereich: "zeit" }],
    ["tags", "Tags", { tab: "tags" }],
    ["personen", "Personen", { tab: "per" }],
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
$("#map-close").addEventListener("click", () => $("#map-dlg").close());
$("#cmp-close").addEventListener("click", () => $("#cmp-dlg").close());
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
onBusyClick("#dup-more", () => loadDuplicates(false));
onBusyClick("#loc-more", () => loadLocation(false));
$("#dup-done").addEventListener("change", (e) => { S.dup.includeDone = e.target.checked; loadTab("dup", true); });
$("#loc-only").addEventListener("change", (e) => { S.loc.only = e.target.checked; loadTab("loc", true); });
// „nur sichere“/„ab wahrscheinlich“: ab dieser Stufe; „=…“: genau diese Stufe (die anderen Medien fallen weg)
$("#loc-conf").addEventListener("change", (e) => {
  const v = e.target.value;
  S.loc.minConf = v && !v.startsWith("=") ? v : null;
  S.loc.level = v.startsWith("=") ? v.slice(1) : null;
  loadTab("loc", true);
});
$("#place-q").addEventListener("input", () => { clearTimeout(placeTimer); placeTimer = setTimeout(searchPlaces, 300); });
$("#set-home-q").addEventListener("input", () => { clearTimeout(homeTimer); homeTimer = setTimeout(searchHome, 300); });
$("#loc-hours").addEventListener("change", (e) => {
  const v = parseFloat(String(e.target.value).replace(",", "."));
  if (v > 0 && v <= 48) { S.loc.hours = v; loadTab("loc", true); } else { e.target.value = S.loc.hours; }
});
onBusyClick("#cln-more", () => loadCleanup(false));
onBusyClick("#alb-more", () => loadAlbums(false));
// Unten angekommen: automatisch nachladen (der Knopf bleibt als Rückfall)
const autoMore = new IntersectionObserver((entries) => {
  for (const en of entries) {
    const btn = en.target;
    if (en.isIntersecting && !btn.hidden && !btn.disabled && !btn.closest("[hidden]")) btn.click();
  }
}, { rootMargin: "0px 0px 400px 0px" });
["#dup-more", "#loc-more", "#cln-more", "#alb-more"].forEach((sel) => autoMore.observe($(sel)));
$("#tags-reload").addEventListener("click", () => loadTab("tags", true));
$("#per-reload").addEventListener("click", () => loadTab("per", true));
$("#smart-size").addEventListener("change", (e) => { try { localStorage.setItem("pflege-ki-anzahl", e.target.value); } catch (_) { /* egal */ } });
try { const v = localStorage.getItem("pflege-ki-anzahl"); if (v) $("#smart-size").value = v; } catch (_) { /* egal */ }
$("#smart-go").addEventListener("click", () => { const q = $("#smart-q").value.trim(); if (q) loadSmart({ suche: q }); });
$("#smart-q").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("#smart-go").click(); } });
document.querySelectorAll(".help-btn").forEach((b) => b.addEventListener("click", () => openHelp(b.dataset.help)));
document.querySelectorAll(".auto-btn").forEach((b) => b.addEventListener("click", (e) => openAutoStage(e.currentTarget)));
$("#rule-new").addEventListener("click", () => openRule(null));
$("#rule-examples").addEventListener("click", () => addExamples().catch((e) => toast(e.message, true)));
$("#rule-yaml").addEventListener("click", openYaml);
$("#rule-save").addEventListener("click", (e) => saveRuleFromDialog(e.currentTarget));
$("#rule-delete").addEventListener("click", deleteRule);
$("#yaml-save").addEventListener("click", (e) => saveYaml(e.currentTarget));
$("#set-add-user").addEventListener("click", () => $("#set-users").append(userRow({ name: "", key_gesetzt: false })));
$("#set-test").addEventListener("click", (e) => testConnection(e.currentTarget));
$("#set-selftest").addEventListener("click", (e) => runSelfTest(e.currentTarget));
$("#set-mqtt-on").addEventListener("change", updateMqttFields);
$("#set-mqtt-send").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  busy(btn, true);
  try { await api("api/mqtt/publish", { method: "POST" }); setTimeout(loadMqttInfo, 3500); toast("Wird gesendet"); }
  catch (err) { toast(err.message, true); } finally { busy(btn, false); }
});
$("#set-auto").addEventListener("change", updateAutoFields);
$("#set-rep-channel").addEventListener("change", updateReportFields);
$("#set-rep-test").addEventListener("click", (e) => sendTestReport(e.currentTarget));
$("#set-mem-test").addEventListener("click", (e) => sendTestMemories(e.currentTarget));
$("#set-logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST" }).catch(() => null);
  location.href = "/login";
});
onBusyClick("#version-check", () => loadVersion(true));
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
