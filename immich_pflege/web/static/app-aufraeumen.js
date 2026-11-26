"use strict";
// Aufräumen, Alben aufräumen, Ordner-Alben, Stapeln, Papierkorb. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
/* ---------------------------------------------------------- Aufräumen */
const PAGE_CLN = 30;
async function loadCleanup(reset) {
  const c = S.cln;
  if (c.bereich === "papierkorb") return loadTrash();
  if (c.bereich === "stapel") return loadStacks();
  if (c.bereich === "alben") return loadAlbumCare();
  if (reset) { c.items = []; c.sel.clear(); c.keep = {}; c.edit = {}; $("#cln-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const gen = pageGen(c, reset, "#cln-more");
  if (gen < 0) return;
  const isTime = c.bereich === "zeit";
  const params = new URLSearchParams({ offset: c.items.length, limit: PAGE_CLN, ignoriert: c.ignored });
  if (!isTime) params.set("sortierung", initSort(c, "cln", "standard"));
  if (c.kategorie) params.set(isTime ? "art" : "kategorie", c.kategorie);
  if (!isTime) params.set("art", c.bereich);
  const [r, counts] = await Promise.all([
    api((isTime ? "api/timefix?" : "api/cleanup?") + params),
    api(isTime ? "api/cleanup?limit=0" : "api/timefix?limit=0"),
  ]);
  if (gen !== c.gen) return;  // inzwischen neu geladen
  if (reset) { c.resetting = false; c.items = []; }
  const cln = isTime ? counts : r;
  const time = isTime ? r : counts;
  if (reset) $("#cln-list").replaceChildren();
  c.info = r; c.total = r.gesamt; c.loaded = true;
  renderCleanupFilters(cln, time);
  if (isTime) {
    for (const it of r.eintraege) { if (!c.items.some((x) => x.id === it.id)) { c.items.push(it); $("#cln-list").append(renderTimeFix(it)); } }
    if (!c.items.length) $("#cln-list").replaceChildren(h("p", { class: "empty" }, c.ignored ? "Nichts ausgeblendet." : "Keine falschen Zeiten gefunden 🎉"));
    $("#cln-summary").textContent = `${n(r.gesamt, "Eintrag", "Einträge")}`;
    $("#cln-more").hidden = c.items.length >= c.total;
    updateActionbar();
    return;
  }
  for (const it of r.eintraege) { if (!c.items.some((x) => x.id === it.id)) { c.items.push(it); $("#cln-list").append(renderCleanupItem(it)); } }
  if (!c.items.length) {
    const fp = r.fingerabdruck;
    const hint = c.bereich === "qualitaet" && fp.aktiv && (fp.laeuft || fp.fehlend)
      ? "Schärfe und Helligkeit werden mit den Bild-Fingerabdrücken berechnet – das läuft noch."
      : c.bereich === "qualitaet" && !fp.aktiv ? "Dafür bitte unter ⚙ Einstellungen den Bild-Fingerabdruck einschalten."
        : c.ignored ? "Nichts ausgeblendet." : "Nichts gefunden 🎉";
    $("#cln-list").replaceChildren(h("p", { class: "empty" }, hint));
  }
  $("#cln-summary").textContent = c.ignored ? `${n(r.gesamt, "ausgeblendeter Eintrag", "ausgeblendete Einträge")}`
    : `${n(r.gesamt, "Eintrag", "Einträge")} · ${fmtBig(r.groesse)} würden frei` + progressText(r.fortschritt);
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
    ["speicher", "videos", "serien", "qualitaet"].includes(c.bereich)
      ? sortSel(c, "cln", [["standard", "Standard"], ["speicher", "Meiste Ersparnis zuerst"], ["menge", "Meiste Bilder zuerst"]], "cln") : null,
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

// Serie stapeln: Antippen nimmt ein Bild aus dem Stapel (aussortiert) oder wieder hinein, ★ legt es oben
function seriesMode(it) {
  const c = S.cln;
  if (!c.mode) c.mode = {};
  if (!c.mode[it.id]) { try { c.mode[it.id] = localStorage.getItem("pflege-serien-modus") || "eins"; } catch (_) { c.mode[it.id] = "eins"; } }
  return c.mode[it.id];
}

function renderSeriesStack(it, card) {
  const c = S.cln;
  c.ohne = c.ohne || {};
  const out = c.ohne[it.id] || (c.ohne[it.id] = new Set());
  const members = it.medien.filter((m) => !out.has(m.id));
  const top = members.some((m) => m.id === c.keep[it.id]) ? c.keep[it.id]
    : (members.find((m) => m.aktion !== "weg") || members[0] || {}).id;
  const redraw = () => { card.replaceWith(renderCleanupItem(it)); updateActionbar(); };
  const grid = h("div", { class: "grid" });
  for (const m of it.medien) {
    const gone = out.has(m.id), isTop = m.id === top;
    grid.append(tile({
      class: "tile " + (gone ? "drop" : "keep"), title: gone ? "Antippen: doch in den Stapel" : "Antippen: aussortieren",
      onclick: () => { gone ? out.delete(m.id) : out.add(m.id); c.sel.add(it.id); redraw(); },
    }, thumb(m), h("span", { class: "badge" }, gone ? "weg" : isTop ? "★ oben" : "im Stapel"),
    !gone && !isTop ? h("button", { type: "button", class: "star-btn", title: "Dieses Bild oben auf den Stapel", "aria-label": "Nach oben",
      onclick: (e) => { e.stopPropagation(); c.keep[it.id] = m.id; c.sel.add(it.id); redraw(); } }, "★") : null,
    h("div", { class: "meta" }, h("div", { class: "name" }, m.dateiname), h("div", {}, fmtTaken(m.aufnahme)), openLinks(m))));
  }
  const nOut = out.size, nIn = it.medien.length - nOut;
  const go = (weg) => stageBurstStacks([it], null, weg);
  return [grid, h("div", { class: "muted small" }, nIn > 1 ? `${nIn} Bilder werden gestapelt (★ oben)` + (nOut ? `, ${nOut} aussortiert` : "")
    : nIn === 1 ? `Nur ein Bild bleibt – kein Stapel${nOut ? `, ${nOut} aussortiert` : ""}` : "Mindestens ein Bild muss bleiben"),
  h("div", { class: "row-gap" },
    !nOut ? h("button", { type: "button", class: "btn small primary", onclick: () => go("album") }, "Stapel vormerken")
      : nIn ? [h("button", { type: "button", class: "btn small primary", onclick: () => go("album") }, "Vormerken, Rest ins Prüf-Album"),
        h("button", { type: "button", class: "btn small danger", onclick: () => go("papierkorb") }, "Vormerken, Rest in den Papierkorb")] : null)];
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
  if (it.kategorie === "serien" && !c.ignored) {
    const mode = seriesMode(it);
    card.append(h("div", { class: "row-gap series-mode" }, h("span", { class: "muted small" }, "Was tun?"),
      ...[["eins", "Eins behalten"], ["stapel", "Stapeln"]].map(([k, l]) => h("button", { type: "button", class: "chip-btn" + (mode === k ? " on" : ""),
        onclick: () => { c.mode[it.id] = k; try { localStorage.setItem("pflege-serien-modus", k); } catch (_) { /* egal */ }
          card.replaceWith(renderCleanupItem(it)); updateActionbar(); } }, l))));
    if (mode === "stapel") { card.append(...renderSeriesStack(it, card).flat().filter(Boolean)); return card; }
  }
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
async function refreshOrientation(items, btn) {
  const ids = items.flatMap((it) => it.medien.map((m) => m.id));
  busy(btn, true);
  try {
    const r = await api("api/orientation/refresh", { method: "POST", body: { ids } });
    toast(`Immich liest ${n(r.angestossen, "Foto", "Fotos")} neu ein – in ein paar Minuten neu einlesen und prüfen`);
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

async function archiveCleanup(items, btn) {
  const ids = [...new Set(items.flatMap((it) => it.medien.filter((m) => m.aktion === "weg").map((m) => m.id)))];
  busy(btn, true);
  try {
    const res = await api("api/staged/archive", { method: "POST", body: { ids, label: VIEWS[S.view] ? VIEWS[S.view].label : "Aufräumen" } });
    toast(`${n(res.vorgemerkt, "Medium", "Medien")} zum Archivieren vorgemerkt`);
    S.cln.sel.clear();
    await afterStage("cln");
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

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
      c.bereich !== "verwaist" ? { text: (k) => `${k} archivieren`, run: async (ids) => {
        const res = await api("api/staged/archive", { method: "POST", body: { ids, label: VIEWS[S.view] ? VIEWS[S.view].label : "Aufräumen" } });
        toast(`${n(res.vorgemerkt, "Medium", "Medien")} zum Archivieren vorgemerkt – bleiben erhalten, nur aus der Zeitleiste`);
        await afterStage("cln");
      } } : null,
      { text: (k) => `${k} ins Prüf-Album`, klasse: c.bereich === "videos" ? "" : "primary", run: stage("album") },
      { text: (k) => `${k} Papierkorb`, klasse: "danger", run: stage("papierkorb") },
    ].filter(Boolean),
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

async function stageBurstStacks(items, btn, weg = "album") {
  const c = S.cln;
  const ohne = Object.fromEntries(items.filter((it) => c.ohne && c.ohne[it.id] && c.ohne[it.id].size).map((it) => [it.id, [...c.ohne[it.id]]]));
  const out = Object.values(ohne).reduce((a, x) => a + x.length, 0);
  if (out && weg === "papierkorb") {
    const ok = await confirmDialog({ title: "Aussortierte in den Papierkorb?", danger: true, okLabel: "Vormerken",
      body: h("p", {}, `${n(out, "Bild geht", "Bilder gehen")} beim Übertragen in den Papierkorb (externe ins Prüf-Album). Der Rest wird gestapelt.`) });
    if (!ok) return;
  }
  busy(btn, true);
  try {
    const keep = Object.fromEntries(items.filter((it) => c.keep[it.id]).map((it) => [it.id, c.keep[it.id]]));
    const r = await api("api/staged/cleanup", { method: "POST", body: { action: "stapel", ids: items.map((it) => it.id), keep, ohne, weg } });
    toast(`${n(r.vorgemerkt, "Stapel", "Stapel")} vorgemerkt` + (r.aussortiert ? `, ${r.aussortiert} aussortiert` : " – nichts wird gelöscht"));
    for (const it of items) if (c.ohne) delete c.ohne[it.id];
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
