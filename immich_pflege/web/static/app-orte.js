"use strict";
// Ohne Ort und Karte. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
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
  const gen = pageGen(l, reset, "#loc-more");
  if (gen < 0) return;
  const params = new URLSearchParams({ offset: l.series.length, limit: PAGE_SERIES, only_suggestions: l.only, overview,
    sortierung: initSort(l, "loc", "datum") });
  if (l.hours) params.set("max_hours", l.hours);
  if (l.minConf) params.set("min_confidence", l.minConf);
  if (l.level) params.set("sicherheit", l.level);
  if (l.ort && l.ort !== "*") params.set("ort", l.ort);
  if (l.monat) params.set("monat", l.monat);
  if (l.herkunft) params.set("herkunft", l.herkunft);
  if (l.benutzer) params.set("benutzer", l.benutzer);
  const r = await api("api/no-location?" + params);
  if (gen !== l.gen) return;  // inzwischen neu geladen
  if (reset) { l.resetting = false; l.series = []; }
  l.loaded = true; l.info = r;
  // gewählter Ort/Monat existiert nicht mehr (z. B. nach Übernehmen) -> zurück zur Übersicht
  if (l.ort && l.ort !== "*" && !r.orte.some((o) => o.key === l.ort)) { l.ort = null; l.monat = null; return loadLocation(true); }
  if (l.monat && !r.monate.some((m) => m.key === l.monat)) { l.monat = null; return loadLocation(true); }
  renderLocFilters(r);
  if (reset) $("#loc-list").replaceChildren();
  if (overview) {
    l.total = 0;
    if (r.orte.some((o) => o.breite !== undefined)) {
      $("#loc-list").append(h("div", { class: "row-gap map-all" },
        h("button", { type: "button", class: "btn small", onclick: () => placesMap(r.orte) }, "🗺 Alle Orte auf der Karte")));
    }
    $("#loc-list").append(...r.orte.map(renderPlaceCard));
  } else {
    l.total = r.serien_gesamt;
    if (reset && l.ort !== "*") $("#loc-list").append(renderPlaceHeader(r));
    for (const ser of r.serien) {
      if (l.series.some((x) => x.id === ser.id)) continue;
      l.series.push(ser);
      $("#loc-list").append(renderSeries(ser));
    }
  }
  if (!r.orte.length) $("#loc-list").replaceChildren(h("p", { class: "empty" }, r.medien ? "Nichts mit diesem Filter." : "Alle Medien haben einen Ort 🎉"));
  const by = r.nach_sicherheit;
  $("#loc-summary").textContent = `${n(r.medien, "Medium", "Medien")} ohne Ort · ` +
    `Vorschläge: ${by.hoch} sicher, ${by.mittel} wahrscheinlich, ${by.niedrig} unsicher` +
    progressText(r.fortschritt) + (r.extern_erlaubt ? "" : " · ");
  if (!r.extern_erlaubt) $("#loc-summary").append(h("button", { type: "button", class: "linklike", onclick: unlockExternal }, "externe Bibliotheken gesperrt – freigeben?"));
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

// Externe Bibliotheken sind anfangs gesperrt: Immich schreibt den Ort zusätzlich in eine .xmp-Datei neben
// dem Original – dafür muss der Ordner in Immich beschreibbar eingebunden sein.
async function unlockExternal() {
  const ok = await confirmDialog({
    title: "Externe Bibliotheken freigeben?",
    body: [h("p", {}, "Dann bekommen auch Medien aus externen Bibliotheken (z. B. Kamera-Ordner auf der Festplatte) einen Ort."),
      h("p", {}, "Immich speichert den Ort in seiner Datenbank und schreibt ihn zusätzlich in eine ", h("b", {}, ".xmp-Datei"),
        " neben dem Original. Dafür muss der Ordner im Immich-Container ", h("b", {}, "beschreibbar"), " eingebunden sein (in der docker-compose.yml ohne ",
        h("code", {}, ":ro"), "). Ist er nur lesbar, kann Immich die .xmp-Datei nicht anlegen und der Ort beim erneuten Einlesen der Datei verloren gehen."),
      h("p", { class: "muted" }, "Die Originaldateien selbst ändert Immich nicht. Zurück geht es jederzeit unter Einstellungen → Fotos ohne Ort.")],
    okLabel: "Freigeben", checkLabel: "Der Ordner ist in Immich beschreibbar eingebunden",
  });
  if (!ok) return;
  try {
    await api("api/settings", { method: "PUT", body: { location_include_external: true } });
    S.set.loaded = false;
    await loadTab("loc", true);
    if (S.loc.info && !S.loc.info.extern_erlaubt) toast("Per .env festgelegt (LOCATION_INCLUDE_EXTERNAL=false) – bitte dort ändern", true);
    else toast("Externe Bibliotheken freigegeben");
    loadCounts();
  } catch (e) { toast(e.message, true); }
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
    l.ort !== null ? sortSel(l, "loc", [["datum", "Neueste zuerst"], ["menge", "Größte Serien zuerst"]], "loc") : null,
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
  // Benutzer: nur die eigenen oder nur Julias Bilder (Zahlen passend zu Ort, Monat und Herkunft)
  const users = Object.entries(r.benutzer || {});
  const people = users.length > 1 ? h("div", { class: "row-gap herkunft" }, h("span", { class: "muted small" }, "Benutzer:"),
    h("button", { type: "button", class: "chip-btn" + (l.benutzer ? "" : " on"), onclick: () => { l.benutzer = null; loadTab("loc", true); } }, "Alle"),
    ...users.filter(([u, c]) => c || l.benutzer === u).map(([u, c]) =>
      h("button", { type: "button", class: "chip-btn" + (l.benutzer === u ? " on" : ""), onclick: () => { l.benutzer = u; loadTab("loc", true); } },
        `👤 ${u.charAt(0).toUpperCase() + u.slice(1)} (${c})`))) : null;
  return [people, chips, hint];
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
    toast(`${n(res.vorgemerkt, "Medium", "Medien")} ausgeblendet und zum Archivieren vorgemerkt – unter Vorgemerkt übertragen`);
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
    if (S.loc.benutzer) scope.set("benutzer", S.loc.benutzer);
    r = await api("api/no-location/origin-media?" + scope);
  } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const after = async () => { S.loc.loaded = false; await loadTab("loc", true); loadCounts(); };
  openReview({
    titel: `Ohne Ort: ${name}`, medien: r.medien, gruppe: "monat",
    hinweis: "Abwählen, was doch einen Ort bekommen soll. „Nur ausblenden“: kein Ort nötig, bleibt in der Zeitleiste. „Ausblenden + archivieren“: zusätzlich aus der Zeitleiste nehmen (wird vorgemerkt, bleibt in Suche und Alben). Zurückholen unter „… ausgeblendet – ansehen“.",
    aktionen: [
      { text: (k) => `${k} ausblenden + archivieren`, run: async (ids) => {
        const res = await api("api/staged/archive", { method: "POST", body: { ids, label: name } });
        await api("api/no-location/no-place", { method: "POST", body: { ids } });
        toast(`${n(res.vorgemerkt, "Medium", "Medien")} zum Archivieren vorgemerkt und hier ausgeblendet`);
        S.stage.loaded = false; await after();
      } },
      { klasse: "primary", text: (k) => `${k} nur ausblenden`, run: async (ids) => {
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
      o.breite !== undefined ? h("button", { type: "button", class: "btn small", onclick: () => openMap({ titel: "🗺 " + o.name,
        sub: n(o.anzahl, "Medium", "Medien"), punkte: [{ breite: o.breite, laenge: o.laenge, art: "vorschlag", text: o.name }] }) }, "🗺 Karte") : null,
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
        + (S.loc.herkunft ? ` · nur ${HERKUNFT_PLURAL[S.loc.herkunft] || r.herkunft[S.loc.herkunft].name}` : "")
        + (S.loc.benutzer ? ` · nur von ${S.loc.benutzer.charAt(0).toUpperCase() + S.loc.benutzer.slice(1)}` : "")))),
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
  if (S.loc.level) body.sicherheit = S.loc.level;
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
    placeLine = h("div", { class: "series-place" },
      h("button", { type: "button", class: "linklike place-link", title: "Auf der Karte zeigen", onclick: () => seriesMap(ser) },
        "📍 " + (v.ort || `${v.breite.toFixed(4)}, ${v.laenge.toFixed(4)}`)), " ", confChip(ser.sicherheit),
      h("div", { class: "muted small" }, v.grund + (v.strecke_km > 1.5 ? ` · davor und danach ${fmtKm(v.strecke_km)} auseinander` : "")));
  } else if (!editable.length) {
    placeLine = h("div", { class: "series-place muted" }, "Nur externe Medien – gesperrt. ",
      h("button", { type: "button", class: "linklike", onclick: unlockExternal }, "Freigeben?"));
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
  if (v || editable.length) buttons.append(h("button", { type: "button", class: "btn small", onclick: () => seriesMap(ser) }, "🗺 Karte"));
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
    if (mv && !m.aenderbar) info = h("div", { class: "nosug" }, `📍 ${mv.ort || "Ort"} · `,
      h("button", { type: "button", class: "linklike", title: "Externe Bibliotheken freigeben",
        onclick: (e) => { e.stopPropagation(); unlockExternal(); } }, "extern gesperrt"));
    else if (mv) info = h("div", {}, h("button", { type: "button", class: "sug linklike", title: "Auf der Karte zeigen",
      onclick: (e) => { e.stopPropagation(); mediumMap(m); } }, `📍 ${mv.ort || mv.breite.toFixed(3) + ", " + mv.laenge.toFixed(3)}`), " ", confChip(mv.sicherheit));
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
      body: { ...body, label, max_hours: S.loc.hours, ...(S.loc.herkunft ? { herkunft: S.loc.herkunft } : {}),
        ...(S.loc.benutzer ? { benutzer: S.loc.benutzer } : {}), ...(S.loc.level && !body.ids && !body.place ? { sicherheit: S.loc.level } : {}) } });
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
  const q = new URLSearchParams({ min_confidence: "hoch", max_hours: S.loc.hours });
  if (S.loc.benutzer) q.set("benutzer", S.loc.benutzer);
  if (S.loc.herkunft) q.set("herkunft", S.loc.herkunft);
  const filtered = !!(S.loc.benutzer || S.loc.herkunft);
  try { r = await api("api/no-location/media?" + q); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  if (!r.medien.length) { toast("Keine sicheren Vorschläge offen"); return; }
  for (const m of r.medien) m.info = "📍 " + m.ort_neu;
  openReview({
    titel: "Alle sicheren Ortsvorschläge", medien: r.medien,
    gruppe: (m) => [m.ort_neu, "📍 " + m.ort_neu],
    hinweis: "Jedes Bild bekommt den Ort eines GPS-Fotos, das höchstens 30 Minuten entfernt ist oder bei dem die Fotos davor und danach am selben Ort entstanden.",
    aktionen: [{ klasse: "primary", text: (k) => `${k.toLocaleString("de-DE")} verorten`, run: async (ids, ohne) =>
      doApplyLocation(ohne.length || filtered ? { ids } : { min_confidence: "hoch" }, null, "Alle sicheren Vorschläge") }],
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

/* -------------------------------------------------------------- Karte */
// Leaflet liegt im Tool (static/vendor), die Kartenkacheln kommen von OpenStreetMap
let leafletLoad = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve();
  if (!leafletLoad) {
    leafletLoad = new Promise((ok, fail) => {
      const css = document.createElement("link");
      css.rel = "stylesheet"; css.href = "static/vendor/leaflet/leaflet.css";
      const js = document.createElement("script");
      js.src = "static/vendor/leaflet/leaflet.js";
      js.onload = ok;
      js.onerror = () => { leafletLoad = null; fail(new Error("Karte konnte nicht geladen werden")); };
      document.head.append(css, js);
    });
  }
  return leafletLoad;
}

const MAP_COLOR = { vorschlag: "#2563eb", vorher: "#16a34a", nachher: "#ea580c", unterwegs: "#9333ea", wahl: "#dc2626", ort: "#2563eb" };
const MAP = { map: null, layer: null, cfg: null, pick: null };

function kmBetween(a, b) {
  const r = Math.PI / 180, dp = (b.breite - a.breite) * r, dl = (b.laenge - a.laenge) * r;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(a.breite * r) * Math.cos(b.breite * r) * Math.sin(dl / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(x));
}
function fmtKm(v) { return v < 1 ? `${Math.round(v * 1000)} m` : `${v.toFixed(v < 10 ? 1 : 0).replace(".", ",")} km`; }
function fmtCoord(p) { return `${p.breite.toFixed(5)}, ${p.laenge.toFixed(5)}`; }

// Punkte eines Ortsvorschlags: Vorschlag, GPS-Fotos davor/danach und die geschätzte Stelle unterwegs
function suggestionPoints(v) {
  const pts = [];
  if (v.vorher) pts.push({ ...v.vorher, art: "vorher", text: `Davor (${v.vorher.abstand_text}): ${v.vorher.ort || v.vorher.datei}`, foto: v.vorher.id });
  if (v.nachher) pts.push({ ...v.nachher, art: "nachher", text: `Danach (${v.nachher.abstand_text}): ${v.nachher.ort || v.nachher.datei}`, foto: v.nachher.id });
  if (v.unterwegs) pts.push({ ...v.unterwegs, art: "unterwegs", text: "Geschätzt unterwegs (nach Zeit auf der Strecke)" });
  const dup = pts.some((p) => (p.art === "vorher" || p.art === "nachher") && Math.abs(p.breite - v.breite) < 1e-6 && Math.abs(p.laenge - v.laenge) < 1e-6);
  if (!dup) pts.unshift({ breite: v.breite, laenge: v.laenge, art: "vorschlag", text: `Vorschlag: ${v.ort || fmtCoord(v)}`, vorschlag: true });
  else pts.forEach((p) => { if (p.breite === v.breite && p.laenge === v.laenge) { p.text += " – Vorschlag"; p.vorschlag = true; } });
  return pts;
}

// cfg: { titel, sub, punkte: [{breite, laenge, art, text, foto?, onclick?}], strecke: [A, B]?, target? }
// Mit target lässt sich per Tipp auf die Karte ein Ort wählen und vormerken.
async function openMap(cfg) {
  try { await loadLeaflet(); } catch (e) { toast(e.message, true); return; }
  MAP.cfg = cfg; MAP.pick = null;
  $("#map-title").textContent = cfg.titel;
  $("#map-sub").textContent = cfg.sub || (cfg.target ? "Tippe auf die Karte, um einen Ort zu wählen." : "");
  const dlg = $("#map-dlg");
  if (!dlg.open) dlg.showModal();
  if (!MAP.map) {
    MAP.map = L.map("map", { zoomControl: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19,
      attribution: "© OpenStreetMap-Mitwirkende" }).addTo(MAP.map);
    MAP.map.on("click", (e) => { if (MAP.cfg.target) pickPoint({ breite: e.latlng.lat, laenge: e.latlng.lng }); });
  }
  MAP.map.invalidateSize();
  if (MAP.layer) MAP.layer.remove();
  MAP.layer = L.layerGroup().addTo(MAP.map);
  const pts = cfg.punkte || [];
  if (cfg.strecke) L.polyline(cfg.strecke.map((p) => [p.breite, p.laenge]), { color: "#9333ea", weight: 3, dashArray: "6 6" }).addTo(MAP.layer);
  for (const p of pts) {
    const mk = L.circleMarker([p.breite, p.laenge], { radius: p.vorschlag ? 11 : p.art === "ort" ? 9 : 8, color: p.vorschlag && p.art !== "vorschlag" ? MAP_COLOR.vorschlag : "#fff", weight: p.vorschlag && p.art !== "vorschlag" ? 4 : 2,
      fillColor: MAP_COLOR[p.art] || MAP_COLOR.ort, fillOpacity: .95 }).addTo(MAP.layer);
    if (p.text) mk.bindTooltip(p.text, { direction: "top", offset: [0, -6] });
    mk.on("click", (ev) => {
      L.DomEvent.stopPropagation(ev);
      if (p.onclick) { p.onclick(); return; }
      if (MAP.cfg.target) pickPoint({ breite: p.breite, laenge: p.laenge, name: p.ort || null });
    });
  }
  if (pts.length > 1) MAP.map.fitBounds(L.latLngBounds(pts.map((p) => [p.breite, p.laenge])).pad(0.25), { maxZoom: 15 });
  else if (pts.length) MAP.map.setView([pts[0].breite, pts[0].laenge], 13);
  else MAP.map.setView([51.2, 10.4], 6);
  renderMapInfo();
}

function routeLink(a, b) {
  return `https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route=${a.breite},${a.laenge};${b.breite},${b.laenge}`;
}

// Route über die Straße: fragt den freien OSRM-Dienst (nur auf Knopfdruck), sonst bleibt die Luftlinie
async function showRoute(a, b, btn, out) {
  busy(btn, true);
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${a.laenge},${a.breite};${b.laenge},${b.breite}?overview=full&geometries=geojson`;
    const res = await fetch(url);
    const r = await res.json();
    if (!res.ok || !r.routes || !r.routes.length) throw new Error("Keine Route gefunden");
    const rt = r.routes[0];
    L.geoJSON(rt.geometry, { style: { color: "#2563eb", weight: 4, opacity: .8 } }).addTo(MAP.layer);
    out.textContent = `Route mit dem Auto: ${fmtKm(rt.distance / 1000)} · etwa ${fmtDur(rt.duration)}`;
    btn.hidden = true;
  } catch (e) {
    out.textContent = "Route nicht berechenbar (" + e.message + ") – der Link öffnet sie bei OpenStreetMap.";
    busy(btn, false);
  }
}

function renderMapInfo() {
  const cfg = MAP.cfg;
  const box = $("#map-info");
  const parts = [];
  const legend = [...new Set((cfg.punkte || []).map((p) => p.art))].filter((a) => a !== "ort");
  if (legend.length) {
    const label = { vorschlag: "Vorschlag", vorher: "GPS-Foto davor", nachher: "GPS-Foto danach", unterwegs: "geschätzt unterwegs" };
    const sugg = (cfg.punkte || []).find((p) => p.vorschlag);
    parts.push(h("div", { class: "map-legend" }, ...legend.map((a) => h("span", {}, h("i", { style: `background:${MAP_COLOR[a]}` }),
      (label[a] || a) + (sugg && sugg.art === a && a !== "vorschlag" ? " = Vorschlag" : "")))));
  }
  if (cfg.strecke) {
    const [a, b] = cfg.strecke;
    const out = h("span", { class: "muted small" });
    parts.push(h("div", { class: "map-line" },
      h("b", {}, `Luftlinie davor → danach: ${fmtKm(kmBetween(a, b))}`), " ",
      h("button", { type: "button", class: "btn small", onclick: (e) => showRoute(a, b, e.currentTarget, out) }, "Route berechnen"), " ",
      h("a", { href: routeLink(a, b), target: "_blank", rel: "noopener", class: "small" }, "In OpenStreetMap ↗"), " ", out));
  }
  const fotos = (cfg.punkte || []).filter((p) => p.foto);
  if (fotos.length) {
    parts.push(h("div", { class: "strip map-photos" }, fotos.map((p) => {
      const img = thumb({ id: p.foto, dateiname: p.datei });
      return h("figure", { class: "stage-fig" }, img, h("figcaption", {}, p.art === "vorher" ? "davor" : "danach"));
    })));
  }
  if (MAP.pick) {
    const p = MAP.pick;
    const near = (cfg.punkte || []).filter((x) => x.art !== "ort").map((x) => `${{ vorschlag: "Vorschlag", vorher: "davor", nachher: "danach", unterwegs: "unterwegs" }[x.art]} ${fmtKm(kmBetween(p, x))}`);
    parts.push(h("div", { class: "map-pick" },
      h("div", {}, h("b", {}, "📍 " + (p.name || "Gewählter Punkt")), p.region ? h("span", { class: "muted" }, " · " + p.region) : null,
        h("div", { class: "muted small" }, fmtCoord(p) + (near.length ? " · Abstand: " + near.join(", ") : ""))),
      h("button", { type: "button", class: "btn primary", onclick: (e) => stagePicked(e.currentTarget) },
        `Hier vormerken (${n(cfg.target.count, "Medium", "Medien")})`)));
  } else if (cfg.target) {
    parts.push(h("p", { class: "muted small" }, "Tippe auf die Karte oder einen Punkt, um den Ort für " + n(cfg.target.count, "Medium", "Medien") + " zu wählen."));
  }
  box.replaceChildren(...parts);
}

async function pickPoint(p) {
  MAP.pick = { ...p };
  if (MAP.pickMarker) MAP.pickMarker.remove();
  MAP.pickMarker = L.circleMarker([p.breite, p.laenge], { radius: 10, color: "#fff", weight: 3, fillColor: MAP_COLOR.wahl, fillOpacity: 1 }).addTo(MAP.layer);
  renderMapInfo();
  try {
    const r = await api(`api/places/reverse?breite=${p.breite}&laenge=${p.laenge}`);
    if (MAP.pick && MAP.pick.breite === p.breite && MAP.pick.laenge === p.laenge) {
      MAP.pick.name = p.name || r.name; MAP.pick.region = r.region;
      renderMapInfo();
    }
  } catch (_) { /* ohne Namen geht es auch */ }
}

async function stagePicked(btn) {
  const t = MAP.cfg.target, p = MAP.pick;
  const body = { place: { breite: +p.breite.toFixed(6), laenge: +p.laenge.toFixed(6), name: p.name || null } };
  if (t.ort) { body.ort = t.ort; if (t.monat) body.monat = t.monat; }
  else if (t.series) body.series = t.series;
  else body.ids = t.ids;
  if (await doApplyLocation(body, btn, `${p.name || fmtCoord(p)} (Karte) · ${t.label}`)) $("#map-dlg").close();
}

function seriesMap(ser) {
  const v = ser.vorschlag;
  const editable = ser.medien.filter((m) => m.aenderbar).length;
  openMap({ titel: `🗺 ${fmtRange(ser)}`, sub: v ? `Vorschlag: ${v.ort || fmtCoord(v)} · ${v.grund}` : null,
    punkte: v ? suggestionPoints(v) : [], strecke: v && v.vorher && v.nachher && v.strecke_km > 0 ? [v.vorher, v.nachher] : null,
    target: editable ? { series: [ser.id], count: editable, label: fmtRange(ser) } : null });
}

function mediumMap(m) {
  const v = m.vorschlag;
  openMap({ titel: `🗺 ${m.dateiname}`, sub: `${fmtTaken(m.aufnahme)} · ${v.grund}`, punkte: suggestionPoints(v),
    strecke: v.vorher && v.nachher && v.strecke_km > 0 ? [v.vorher, v.nachher] : null,
    target: m.aenderbar ? { ids: [m.id], count: 1, label: m.dateiname } : null });
}

// Alle Orte der Übersicht auf einer Karte; Antippen öffnet den Ort
function placesMap(orte) {
  const pts = orte.filter((o) => o.breite !== undefined).map((o) => ({ breite: o.breite, laenge: o.laenge, art: "ort",
    text: `${o.name}: ${n(o.anzahl, "Medium", "Medien")}`,
    onclick: () => { $("#map-dlg").close(); S.loc.ort = o.key; loadTab("loc", true); window.scrollTo(0, 0); } }));
  openMap({ titel: "🗺 Orte ohne Ort-Angabe", sub: `${n(pts.length, "Ort", "Orte")} mit Vorschlag – antippen öffnet den Ort`, punkte: pts });
}
