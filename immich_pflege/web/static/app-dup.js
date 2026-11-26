"use strict";
// Duplikate. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
/* --------------------------------------------------------- Duplikate */
// Seiten nachladen ohne Doppelte: Beim Neuladen zählt nur die jüngste Anfrage, und solange sie läuft,
// bleibt „Weitere anzeigen“ weg (sonst lädt das automatische Nachladen dieselbe Seite ein zweites Mal).
// Sortierung (bleibt gespeichert) und „erledigt“-Zeile für Duplikate, Ohne Ort und Aufräumen
function sortSel(st, key, options, tab) {
  const sel = h("select", { onchange: (e) => {
    st.sort = e.target.value;
    try { localStorage.setItem("pflege-sort-" + key, st.sort); } catch (_) { /* egal */ }
    loadTab(tab, true);
  } }, ...options.map(([v, label]) => h("option", { value: v }, label)));
  sel.value = st.sort || options[0][0];
  return h("label", { class: "field grow" }, "Sortierung", sel);
}
function initSort(st, key, fallback) {
  if (st.sort === undefined) { try { st.sort = localStorage.getItem("pflege-sort-" + key) || fallback; } catch (_) { st.sort = fallback; } }
  return st.sort;
}
function progressText(p) {
  return p && p.woche ? ` · ✓ erledigt: heute ${p.heute.toLocaleString("de-DE")}, 7 Tage ${p.woche.toLocaleString("de-DE")}` : "";
}

function pageGen(st, reset, moreSel) {
  if (reset) { st.gen = (st.gen || 0) + 1; st.resetting = true; $(moreSel).hidden = true; return st.gen; }
  return st.resetting ? -1 : (st.gen || 0);  // -1: Neuladen läuft noch, nichts nachladen
}

async function loadDuplicates(reset) {
  const d = S.dup;
  if (reset) { d.groups = []; d.sel.clear(); d.keep = {}; $("#dup-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const gen = pageGen(d, reset, "#dup-more");
  if (gen < 0) return;
  const params = new URLSearchParams({ offset: d.groups.length, limit: PAGE_DUP, include_done: d.includeDone,
    benutzeruebergreifend: d.crossUser, ignoriert: d.ignored, sortierung: initSort(d, "dup", "datum") });
  if (d.art) params.set("art", d.art);
  if (d.monat) params.set("monat", d.monat);
  const r = await api("api/duplicates?" + params);
  if (gen !== d.gen) return;  // inzwischen neu geladen
  if (reset) { d.resetting = false; d.groups = []; }
  if (d.monat && !r.monate.some((m) => m.key === d.monat)) { d.monat = null; return loadDuplicates(true); }
  if (reset) $("#dup-list").replaceChildren();
  d.total = r.gesamt; d.open = r.offen; d.loaded = true; d.info = r;
  renderDupFilters(r);
  for (const g of r.gruppen) {
    if (d.groups.some((x) => x.id === g.id)) continue;  // schon da (Liste hat sich zwischen den Seiten verschoben)
    d.groups.push(g);
    $("#dup-list").append(renderGroup(g));
  }
  if (!d.groups.length) {
    $("#dup-list").replaceChildren(h("p", { class: "empty" },
      d.ignored ? "Keine ausgeblendeten Gruppen." : (d.art || d.monat || d.crossUser ? "Nichts mit diesem Filter." : "Keine Duplikate gefunden 🎉")));
  }
  $("#dup-summary").textContent = d.ignored
    ? `${n(r.gesamt, "ausgeblendete Gruppe", "ausgeblendete Gruppen")} („kein Duplikat“)`
    : `${r.offen} offen · ${n(r.gesamt, "Gruppe", "Gruppen")} · ${r.benutzeruebergreifend} benutzerübergreifend` + progressText(r.fortschritt);
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
    sortSel(d, "dup", [["datum", "Neueste zuerst"], ["speicher", "Meiste Ersparnis zuerst"]], "dup"),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: d.crossUser,
      onchange: (e) => { d.crossUser = e.target.checked; loadTab("dup", true); } }), "nur benutzerübergreifend"),
    h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: d.ignored,
      onchange: (e) => { d.ignored = e.target.checked; loadTab("dup", true); } }), `ausgeblendete (${r.ignoriert})`));
}

const SOURCE_LABEL = { immich: "Immich-KI", pruefsumme: "Prüfsumme", name_zeit: "Name + Zeit", bildhash: "Bild-Fingerabdruck",
  format: "Format", bearbeitung: "Bearbeitung", raw_paar: "RAW + JPG" };
const KIND_CLASS = { identisch: "conf-hoch", sehr_wahrscheinlich: "conf-mittel", format: "conf-mittel",
  bearbeitung: "conf-mittel", raw_paar: "conf-niedrig", serie: "accent", aehnlich: "conf-niedrig" };

// Serienbilder (fortlaufende Dateinamen, nur ähnlich): stapeln statt wegräumen – alle bleiben
async function stackDuplicates(groups, btn, all = false) {
  const ok = await confirmDialog({ title: all ? "Alle Serienbilder stapeln?" : `${n(groups.length, "Serie", "Serien")} stapeln?`,
    body: [h("p", {}, "Alle Fotos bleiben erhalten und werden in Immich zu einem Stapel zusammengefasst. Oben liegt das mit ★ markierte, die anderen erscheinen nur noch beim Aufklappen."),
      h("p", { class: "muted" }, "Noch geht nichts an Immich – übertragen wird erst unter Vorgemerkt.")],
    okLabel: "Stapeln vormerken" });
  if (!ok) return;
  busy(btn, true);
  try {
    const r = await api("api/staged/duplicate-stacks", { method: "POST", body: all ? { all: true } : { groups } });
    toast(`${n(r.vorgemerkt, "Stapel", "Stapel")} aus ${n(r.medien, "Medium", "Medien")} vorgemerkt`);
    S.dup.sel.clear();
    await afterStage("dup");
  } catch (e) { toast(e.message, true); } finally { busy(btn, false); }
}

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
    }), `${g.medien.length} ${g.art === "serie" ? "Fotos" : "Kopien"}`),
    h("span", { class: "chip " + (KIND_CLASS[g.art] || ""), title: "Art der Übereinstimmung" }, g.art_text),
    ...g.quellen.map((q) => h("span", { class: "chip" }, SOURCE_LABEL[q] || q)),
    g.benutzeruebergreifend ? h("span", { class: "chip accent" }, g.benutzer.join(" + ")) : null,
    g.erledigt ? h("span", { class: "chip ok" }, "erledigt") : null,
    h("button", { type: "button", class: "btn small edit", onclick: () => ignoreGroup(g, S.dup.ignored) },
      S.dup.ignored ? "Wieder aufnehmen" : "Kein Duplikat"),
    h("button", { type: "button", class: "btn small", title: "Zwei Bilder groß vergleichen", onclick: () => openCompare(g) }, "Vergleichen"),
    S.dup.ignored ? null : h("button", { type: "button", class: "btn small" + (keep === ALL_GONE ? " danger" : ""),
      title: keep === ALL_GONE ? "Doch eins behalten (Vorschlag)" : "Keins behalten – alle weg",
      onclick: () => {
        if (keep === ALL_GONE) delete d.keep[g.id]; else { d.keep[g.id] = ALL_GONE; d.sel.add(g.id); }
        card.replaceWith(renderGroup(g));
        updateActionbar();
      } }, keep === ALL_GONE ? "✓ Alle weg" : "Alle weg"),
  );
  const grid = h("div", { class: "grid" });
  for (const m of g.medien) {
    const isKeep = m.id === keep;
    const serie = g.art === "serie";
    const badge = serie ? (isKeep ? "★ oben" : "im Stapel") : isKeep ? "★ bleibt" : (m.im_pruef_album ? "im Prüf-Album" : "weg");
    grid.append(tile({
      class: "tile " + (isKeep || serie ? "keep" : "drop"),
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
  card.append(head);
  if (keep === ALL_GONE) {
    card.append(h("div", { class: "banner warn" }, "Keins wird behalten – alle gehen weg (Papierkorb oder Prüf-Album, je nach Knopf unten). "
      + "Externe Medien und Medien des anderen Benutzers kommen trotzdem nur ins Prüf-Album. Bild antippen behält doch eins."));
  }
  if (g.art === "serie" && keep !== ALL_GONE) {
    card.append(h("div", { class: "banner serie-hint" },
      h("div", {}, h("b", {}, "Eher ein Serienbild: "), "fortlaufende Dateinamen, kurz hintereinander, nur ähnlich – also verschiedene Fotos, keine Kopien. Stapeln behält alle; oben liegt das mit ★ (antippen zum Ändern)."),
      g.benutzer.length === 1 ? h("button", { type: "button", class: "btn small primary",
        onclick: (e) => stackDuplicates([{ id: g.id, keep }], e.currentTarget) }, "Stapeln") : null));
  }
  card.append(grid);
  return card;
}

// S.dup.keep[id] === ALL_GONE: keins behalten, alle weg
const ALL_GONE = "*";
function selectedGroups() {
  return [...S.dup.sel].map((id) => (S.dup.keep[id] === ALL_GONE ? { id, alle: true }
    : { id, keep: S.dup.keep[id] || (S.dup.groups.find((g) => g.id === id) || {}).behalten }));
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

/* ------------------------------------------------- Duplikate vergleichen */
// Zwei Bilder einer Gruppe groß: nebeneinander oder übereinander mit Schieber; darunter die Unterschiede.
const CMP = { g: null, a: null, b: null, mode: "schieber", pos: 50 };

function openCompare(g) {
  const keep = S.dup.keep[g.id] && S.dup.keep[g.id] !== ALL_GONE ? S.dup.keep[g.id] : g.behalten;
  Object.assign(CMP, { g, a: keep, b: g.medien.find((m) => m.id !== keep).id, pos: 50 });
  try { CMP.mode = localStorage.getItem("pflege-cmp") || "schieber"; } catch (_) { /* egal */ }
  renderCompare();
  if (!$("#cmp-dlg").open) $("#cmp-dlg").showModal();
}

function cmpRows(a, b) {
  const ext = (m) => (m.dateiname || "").split(".").pop().toUpperCase();
  const px = (m) => (m.breite && m.hoehe ? `${m.breite}×${m.hoehe} (${((m.breite * m.hoehe) / 1e6).toFixed(1).replace(".", ",")} MP)` : "–");
  const yes = (v) => (v ? "ja" : "nein");
  return [
    ["Datei", (m) => m.dateiname], ["Format", ext], ["Benutzer", (m) => m.benutzer], ["Bibliothek", (m) => (m.extern ? "extern" : "Upload")],
    ["Aufnahme", (m) => fmtTaken(m.aufnahme)], ["Auflösung", px], ["Dateigröße", (m) => fmtSize(m.groesse) || "–"],
    ["Kamera", (m) => m.kamera || "keine Kameradaten"], ["Ort", (m) => m.ort || (m.gps ? "GPS" : "–")],
    ["In Album", (m) => yes(m.im_album)], ["Favorit", (m) => yes(m.favorit)], ["Punkte", (m) => String(m.punkte ?? "")],
  ].map(([label, fn]) => {
    const va = fn(a), vb = fn(b);
    return h("tr", { class: va !== vb ? "diff" : "" }, h("th", {}, label), h("td", {}, va), h("td", {}, vb));
  });
}

function renderCompare() {
  const { g } = CMP;
  const a = g.medien.find((m) => m.id === CMP.a), b = g.medien.find((m) => m.id === CMP.b);
  $("#cmp-title").textContent = `Vergleichen · ${g.art_text}`;
  $("#cmp-sub").textContent = g.medien.length > 2 ? `${g.medien.length} Medien in der Gruppe – oben zwei auswählen` : "";
  const pick = (side) => {
    const sel = h("select", { "aria-label": side === "a" ? "Links" : "Rechts", onchange: (e) => { CMP[side] = e.target.value; renderCompare(); } },
      ...g.medien.map((m, i) => h("option", { value: m.id, disabled: m.id === (side === "a" ? CMP.b : CMP.a) },
        `${String.fromCharCode(65 + i)}: ${m.dateiname}${m.id === g.behalten ? " (Vorschlag)" : ""}`)));
    sel.value = CMP[side];
    return sel;
  };
  const modes = h("div", { class: "row-gap" }, ...[["schieber", "Schieber"], ["neben", "Nebeneinander"]].map(([k, l]) =>
    h("button", { type: "button", class: "chip-btn" + (CMP.mode === k ? " on" : ""), onclick: () => {
      CMP.mode = k; try { localStorage.setItem("pflege-cmp", k); } catch (_) { /* egal */ } renderCompare();
    } }, l)));
  const src = (m) => `thumb/${m.id}?size=preview`;
  let view;
  if (CMP.mode === "neben") {
    view = h("div", { class: "cmp-side" }, ...[a, b].map((m, i) => h("figure", {}, h("img", { src: src(m), alt: m.dateiname }),
      h("figcaption", { class: "small" }, i ? "rechts" : "links"))));
  } else {
    const top = h("img", { src: src(b), alt: b.dateiname, class: "cmp-top", style: `clip-path: inset(0 0 0 ${CMP.pos}%)` });
    const line = h("div", { class: "cmp-line", style: `left:${CMP.pos}%` });
    const range = h("input", { type: "range", min: 0, max: 100, value: CMP.pos, "aria-label": "Schieber links/rechts",
      oninput: (e) => { CMP.pos = +e.target.value; top.style.clipPath = `inset(0 0 0 ${CMP.pos}%)`; line.style.left = CMP.pos + "%"; } });
    view = h("div", {}, h("div", { class: "cmp-stack" }, h("img", { src: src(a), alt: a.dateiname }), top, line,
      h("span", { class: "cmp-lab l" }, "links"), h("span", { class: "cmp-lab r" }, "rechts")), range);
  }
  const choose = (m) => {
    S.dup.keep[g.id] = m.id;
    S.dup.sel.add(g.id);
    const card = document.querySelector(`[data-group="${g.id}"]`);
    if (card) card.replaceWith(renderGroup(g));
    updateActionbar();
    $("#cmp-dlg").close();
    toast(`„${m.dateiname}“ bleibt – unten vormerken`);
  };
  $("#cmp-body").replaceChildren(
    h("div", { class: "cmp-tools" }, h("label", { class: "field" }, "Links", pick("a")), h("label", { class: "field" }, "Rechts", pick("b")), modes),
    view,
    h("table", { class: "tbl cmp-tbl" }, h("thead", {}, h("tr", {}, h("th", {}, ""), h("th", {}, "links"), h("th", {}, "rechts"))),
      h("tbody", {}, ...cmpRows(a, b))),
    h("p", { class: "muted small" }, "Gelb markiert: hier unterscheiden sich die beiden."),
    h("div", { class: "row-gap cmp-actions" },
      h("button", { type: "button", class: "btn primary", onclick: () => choose(a) }, "Links behalten"),
      h("button", { type: "button", class: "btn primary", onclick: () => choose(b) }, "Rechts behalten")));
}
