"use strict";
// Tags und Tag-Vorschläge. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
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
