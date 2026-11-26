"use strict";
// Vorgemerkt und Verlauf. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
/* -------------------------------------------------------- Vorgemerkt */
const STAGE_TYPES = [["duplikat", "Duplikate"], ["aufraeumen", "Aufräumen"], ["archiv", "Archivieren"], ["stapel", "Stapel"], ["albenpflege", "Alben aufräumen"], ["zeit", "Aufnahmezeit"], ["ort", "Orte"], ["album", "Alben"], ["tag", "Tags"], ["personen", "Personen"]];
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

// Verlauf nach Tagen, einklappbar (heute offen); Farbe je Art wie bei den vorgemerkten Gruppen
function renderHistory(entries) {
  const list = $("#history-list");
  if (!entries.length) { list.replaceChildren(h("p", { class: "muted" }, "Noch nichts übertragen.")); return; }
  const localDay = (d) => d.toLocaleDateString("sv-SE");  // JJJJ-MM-TT in Ortszeit
  const days = new Map();
  for (const x of entries) {
    const key = x.zeit ? localDay(new Date(x.zeit)) : "";
    if (!days.has(key)) days.set(key, []);
    days.get(key).push(x);
  }
  const today = localDay(new Date());
  const yesterday = localDay(new Date(Date.now() - 864e5));
  list.replaceChildren(...[...days].map(([day, xs], i) => {
    const det = h("details", { class: "hist-day" });
    det.open = stageOpen("hist-" + day, i === 0);
    det.addEventListener("toggle", () => rememberOpen("hist-" + day, det.open));
    const label = day === today ? "Heute" : day === yesterday ? "Gestern" : fmtTaken(day + " 00:00").slice(0, 10);
    const media = xs.reduce((a, x) => a + (x.rueckgaengig ? 0 : x.anzahl), 0);
    det.append(h("summary", {}, h("b", {}, label), h("span", { class: "muted small" }, ` ${n(xs.length, "Übertragung", "Übertragungen")} · ${n(media, "Medium", "Medien")}`)),
      ...xs.map((x) => {
        let status;
        if (x.rueckgaengig) status = h("span", { class: "chip" }, "↩ rückgängig " + fmtDateTime(x.rueckgaengig).slice(-5));
        else if (x.rueckgaengig_moeglich) status = h("button", { type: "button", class: "btn small", onclick: (ev) => undoHistory(x, ev.currentTarget) }, "Rückgängig");
        else status = h("span", { class: "muted small" }, x.nicht_rueckgaengig || "");
        return h("div", { class: "hist-row" + (x.rueckgaengig ? " undone" : ""), "data-typ": x.typ },
          h("span", { class: "sg-icon small", "aria-hidden": "true" }, STAGE_ICON[x.typ] || (x.typ === "papierkorb" ? "♻" : "•")),
          h("div", { class: "grow" }, h("div", {}, x.titel),
            h("div", { class: "muted small" }, `${fmtDateTime(x.zeit).slice(-5)} · ${n(x.anzahl, "Medium", "Medien")} · ${HIST_SOURCE[x.quelle] || x.quelle}`),
            x.rueck_fehler && x.rueck_fehler.length ? h("div", { class: "banner err" }, x.rueck_fehler.join(" · ")) : null),
          status);
      }));
    return det;
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

// Je Art eine einklappbare Gruppe mit eigener Farbe; der Klappzustand bleibt gespeichert
const STAGE_ICON = { duplikat: "⧉", aufraeumen: "🧹", archiv: "🗄", stapel: "📚", albenpflege: "🗂", zeit: "🕑", ort: "📍", album: "🖼", tag: "🏷", personen: "👤" };

function stageOpen(key, fallback) {
  try {
    const v = JSON.parse(localStorage.getItem("pflege-offen") || "{}")[key];
    return v === undefined ? fallback : v;
  } catch (_) { return fallback; }
}

function rememberOpen(key, open) {
  try {
    const all = JSON.parse(localStorage.getItem("pflege-offen") || "{}");
    all[key] = open;
    localStorage.setItem("pflege-offen", JSON.stringify(all));
  } catch (_) { /* egal */ }
}

// Knopf im Kopf einer <details>-Gruppe: ohne dabei auf- oder zuzuklappen
const headBtn = (attrs, label) => h("button", { ...attrs, type: "button", onclick: (ev) => { ev.preventDefault(); ev.stopPropagation(); attrs.onclick(ev); } }, label);

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
      h("p", {}, "Was du unter Aufräumen, Ordnen oder Alben vormerkst, landet hier – noch ohne Änderung in Immich.")));
    updateActionbar();
    return;
  }
  const groups = STAGE_TYPES.map(([typ, label]) => ({ typ, label, entries: st.entries.filter((x) => x.typ === typ) })).filter((g) => g.entries.length);
  const many = st.entries.length > 6;  // viele Einträge: anfangs eingeklappt
  const sections = groups.map((g) => {
    const media = g.entries.reduce((a, x) => a + x.anzahl, 0);
    const trash = g.entries.reduce((a, x) => a + (x.daten.schritte ? x.daten.schritte.filter((s) => s.aktion === "papierkorb").length : 0), 0);
    const errors = g.entries.filter((x) => x.fehler).length;
    const det = h("details", { class: "stage-group", "data-typ": g.typ, id: "stage-" + g.typ });
    det.open = stageOpen("stage-" + g.typ, !many);
    det.addEventListener("toggle", () => rememberOpen("stage-" + g.typ, det.open));
    det.append(
      h("summary", {},
        h("span", { class: "sg-icon", "aria-hidden": "true" }, STAGE_ICON[g.typ] || "•"),
        h("span", { class: "sg-title" }, h("b", {}, g.label),
          h("span", { class: "muted small" }, `${n(g.entries.length, "Eintrag", "Einträge")} · ${n(media, "Medium", "Medien")}`)),
        trash ? h("span", { class: "chip sg-trash" }, `🗑 ${trash}`) : null,
        errors ? h("span", { class: "chip sg-err" }, `⚠ ${errors}`) : null,
        h("span", { class: "sg-actions" },
          headBtn({ class: "btn small", title: "Alle Einträge dieser Gruppe zurücknehmen", onclick: (ev) => unstageGroup(g, ev.currentTarget) }, "Zurücknehmen"),
          headBtn({ class: "btn small primary", onclick: (ev) => applyStaged(g.entries.map((x) => x.id), ev.currentTarget) }, `Übertragen (${g.entries.length})`))),
      h("div", { class: "sg-body" }, ...g.entries.map(stageEntry)));
    return det;
  });
  // Übersicht: jede Gruppe antippbar (öffnet und springt hin), dazu alle auf-/zuklappen
  const allOpen = sections.every((d) => d.open);
  const overview = h("div", { class: "stage-overview" },
    ...groups.map((g) => h("button", { type: "button", class: "chip-btn sg-chip", "data-typ": g.typ,
      onclick: () => { const d = $("#stage-" + g.typ); d.open = true; d.scrollIntoView({ behavior: "smooth", block: "start" }); } },
    `${STAGE_ICON[g.typ]} ${g.label} ${g.entries.length}`)),
    h("button", { type: "button", class: "chip-btn", onclick: () => { groups.forEach((g) => rememberOpen("stage-" + g.typ, !allOpen)); renderStaged(); } },
      allOpen ? "Alle zuklappen" : "Alle aufklappen"));
  list.append(overview, ...sections);
  updateActionbar();
}

function stageEntry(x) {
  const trash = x.daten.schritte ? x.daten.schritte.filter((s) => s.aktion === "papierkorb").length : 0;
  return h("div", { class: "stage-entry" + (x.fehler ? " err" : "") },
    h("div", { class: "se-head" },
      h("div", { class: "grow" }, h("div", { class: "se-title" }, x.titel),
        h("div", { class: "muted small" }, `${n(x.anzahl, "Medium", "Medien")} · vorgemerkt ${fmtDateTime(x.erstellt)}` + (trash ? ` · 🗑 ${trash}` : ""))),
      h("div", { class: "se-actions" },
        !["albenpflege", "personen"].includes(x.typ) ? h("button", { type: "button", class: "btn small", title: "Alle Medien ansehen, einzelne abwählen",
          onclick: (ev) => openStagedReview(x, ev.currentTarget) }, "Ansehen") : null,
        h("button", { type: "button", class: "btn small", title: "Zurücknehmen", onclick: (ev) => unstage(x, ev.currentTarget) }, "↩"),
        h("button", { type: "button", class: "btn small primary", onclick: (ev) => applyStaged([x.id], ev.currentTarget) }, "Übertragen"))),
    x.fehler ? h("div", { class: "banner err" }, "Letzte Übertragung fehlgeschlagen: " + x.fehler) : null,
    x.typ === "album" && x.daten.hinweise && x.daten.hinweise.length ? h("div", { class: "banner warn" }, x.daten.hinweise.join(" · ")) : null,
    x.typ === "album" && x.daten.album_id ? h("div", { class: "small" }, "Album ansehen: ", albumLinks({ id: x.daten.album_id, name: x.daten.name })) : null,
    x.medien.length ? stageMedia(x) : null);
}

// Vorgemerkten Eintrag ansehen: alle Medien, einzelne abwählen (fallen aus dem Eintrag)
async function openStagedReview(x, btn) {
  busy(btn, true);
  let r;
  try { r = await api(`api/staged/${encodeURIComponent(x.id)}/media`); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  openReview({
    titel: x.titel, medien: r.medien, gruppe: "monat",
    hinweis: "Antippen nimmt ein Medium aus dem Eintrag. Unter „ansehen“ öffnet es groß.",
    aktionen: [{ klasse: "primary", leer: true, text: (k) => (k === r.medien.length ? "Schließen" : k ? `${k.toLocaleString("de-DE")} behalten, Rest herausnehmen` : "Ganzen Eintrag zurücknehmen"),
      run: async (ids, ohne) => {
        if (!ohne.length) return;
        const res = await api(`api/staged/${encodeURIComponent(x.id)}/ohne`, { method: "POST", body: { ohne } });
        toast(res.uebrig ? `${n(res.entfernt, "Medium", "Medien")} herausgenommen` : "Alles abgewählt – Eintrag zurückgenommen");
        const src = STAGE_SOURCE[x.typ];
        await Promise.all([loadTab("stage", true), S[src] && S[src].loaded ? loadTab(src, true) : null]);
        loadCounts();
      } }],
  });
}

async function unstageGroup(g, btn) {
  const ok = await confirmDialog({ title: `${g.label}: alles zurücknehmen?`,
    body: h("p", {}, `${n(g.entries.length, "Eintrag kommt", "Einträge kommen")} zurück in die Übersicht. In Immich ändert sich nichts.`),
    okLabel: "Zurücknehmen" });
  if (!ok) return;
  busy(btn, true);
  try {
    for (const x of g.entries) await api("api/staged/" + encodeURIComponent(x.id), { method: "DELETE" });
    toast(`${n(g.entries.length, "Eintrag", "Einträge")} zurückgenommen`);
    const src = STAGE_SOURCE[g.typ];
    await Promise.all([loadTab("stage", true), S[src] && S[src].loaded ? loadTab(src, true) : null]);
    loadCounts();
  } catch (err) { toast(err.message, true); busy(btn, false); }
}

const STAGE_SOURCE = { duplikat: "dup", aufraeumen: "cln", archiv: "tags", stapel: "cln", albenpflege: "cln", zeit: "cln", ort: "loc", album: "alb", tag: "tags", personen: "per" };

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
