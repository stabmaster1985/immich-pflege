"use strict";
// Prüf-Ansicht (viele Bilder auf einmal). Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
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
  const only = !!cfg.nurAnsehen;  // nur ansehen: ohne Auswahl, Antippen öffnet groß
  Object.assign(RV, { cfg, medien: cfg.medien, off: new Set(cfg.ohne || []), mode: only ? "ansehen" : "waehlen" });
  $("#review").classList.toggle("rv-view", only);
  $("#rv-all").parentElement.querySelectorAll("button").forEach((b) => { b.hidden = only; });
  $('[data-rv-mode="waehlen"]').parentElement.hidden = only;
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
  const groupsText = `${RV.groups.length} ${RV.groups.length === 1 ? noun[0] : noun[1]}`;
  $("#rv-count").textContent = RV.cfg.nurAnsehen ? `${de(total)} ${total === 1 ? "Medium" : "Medien"} · ${groupsText}`
    : `${de(chosen)} von ${de(total)} ausgewählt · ${groupsText}`;
  $("#rv-foot-info").textContent = RV.cfg.nurAnsehen ? (RV.cfg.fuss || "") : chosen === total ? "alle ausgewählt" : `${de(total - chosen)} abgewählt`;
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

const SMART_REVIEW = 400;  // Treffer je Benutzer für die Prüf-Ansicht (Standard, oben wählbar)

function smartSize() {
  try { return +localStorage.getItem("pflege-ki-anzahl") || SMART_REVIEW; } catch (_) { return SMART_REVIEW; }
}

async function loadSmart(q) {
  const g = S.sug;
  g.lastQuery = q;
  const box = $("#smart-box");
  box.replaceChildren(h("p", { class: "empty" }, "Frage Immichs KI-Suche …"));
  const params = new URLSearchParams({ anzahl: smartSize() });
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
    r.medien.length ? again : null, " ", smartHiddenLink(r)));
  if (r.medien.length) openSmartReview(r);
}

function smartHiddenLink(r) {
  return r.ausgeblendet ? h("button", { type: "button", class: "linklike small", onclick: (e) => openSmartHidden(r.tag, e.currentTarget) },
    `${r.ausgeblendet} für „${r.tag}“ ausgeblendet – ansehen`) : "";
}

// Ausgeblendete KI-Treffer eines Tags: ansehen und einzelne wieder zeigen
async function openSmartHidden(tag, btn) {
  busy(btn, true);
  let r;
  try { r = await api("api/suggestions/smart/hidden?tag=" + encodeURIComponent(tag)); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  openReview({
    titel: `Ausgeblendet für „${tag}“`, medien: r.medien, gruppe: "monat", ohne: r.medien.map((m) => m.id),
    hinweis: "Diese Treffer zeigt die KI-Suche für diesen Tag nicht mehr. Wähle die aus, die wieder erscheinen sollen.",
    aktionen: [{ klasse: "primary", text: (k) => `${k} wieder zeigen`, run: async (ids) => {
      await api("api/suggestions/smart/hide", { method: "POST", body: { tag, ids, undo: true } });
      toast(`${n(ids.length, "Treffer erscheint", "Treffer erscheinen")} wieder`);
      if (S.sug.lastQuery) loadSmart(S.sug.lastQuery);
    } }],
  });
}

// KI-Treffer prüfen: nach Passgenauigkeit sortiert, in Blöcken zu 50. Anfangs ist nichts gewählt –
// das erste Bild antippen, das nicht mehr passt; alles davor wird gewählt. Danach einzeln nachbessern.
function openSmartReview(r, off = null) {
  const g = S.sug;
  const tagIn = h("input", { type: "text", value: g.tag, "aria-label": "Tag", oninput: (e) => { g.tag = e.target.value; rvCount(); } });
  openReview({
    titel: `KI-Suche: ${r.begriff || r.suche}`, medien: r.medien, gruppe: "rang", rang: true,
    ohne: off ? r.medien.map((m) => m.id).filter((id) => off.has(id)) : r.medien.map((m) => m.id),
    hinweis: "Sortiert nach Passgenauigkeit. Tippe auf das erste Bild, das nicht mehr passt – alles davor wird gewählt. Danach unter „abwählen“ einzeln nachbessern."
      + " „Ausblenden“ nimmt die gewählten Bilder für diesen Tag dauerhaft aus der Suche.",
    extra: h("label", { class: "field rv-tag" }, "Tag", tagIn),
    aktionen: [
      { text: (k) => `${k} ausblenden`, run: async (ids) => {
        const tag = g.tag.trim();
        if (!tag) { toast("Bitte einen Tag eintragen", true); return false; }
        const res = await api("api/suggestions/smart/hide", { method: "POST", body: { tag, ids } });
        toast(`${n(ids.length, "Treffer", "Treffer")} ausgeblendet – erscheinen für „${tag}“ nicht mehr`);
        const gone = new Set(ids);
        const keepOff = new Set([...RV.off].filter((id) => !gone.has(id)));
        Object.assign(r, { medien: r.medien.filter((m) => !gone.has(m.id)), ausgeblendet: res.ausgeblendet });
        const mode = RV.mode;
        openSmartReview(r, keepOff);
        RV.mode = mode; renderReview();
        return false;  // Prüf-Ansicht bleibt offen
      } },
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
