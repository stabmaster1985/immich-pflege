"use strict";
// Startseite, Statistik, Personen. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
/* ----------------------------------------------------------- Übersicht */

// Eindeutiges auf einen Schlag vormerken: je Art ein Eintrag unter Vorgemerkt, Kontrolle dort
const AUTO_MORE = ["identisch", "messenger", "bearbeitung", "serien"];
const AUTO_HINT = { orte: "nur „sicher“: GPS-Foto höchstens 30 min entfernt oder davor und danach derselbe Ort",
  identisch: "Byte für Byte gleiche Dateien", messenger: "per Messenger verschickte/empfangene Kopie – das Original mit Kameradaten bleibt und übernimmt ihre Alben",
  bearbeitung: "gleiche Aufnahme als Original und bearbeitete Fassung", serien: "Serien werden gestapelt, alle Fotos bleiben" };

async function openAutoStage(btn) {
  busy(btn, true);
  let r;
  try { r = await api("api/auto-stage"); } catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const boxes = {};
  const rows = Object.entries(r.arten).map(([k, a]) => {
    boxes[k] = h("input", { type: "checkbox", checked: a.anzahl > 0 && k !== "bearbeitung", disabled: !a.anzahl });
    return h("label", { class: "auto-row" + (a.anzahl ? "" : " muted") }, boxes[k],
      h("span", {}, h("b", {}, a.name), ` – ${a.anzahl ? (k === "orte" ? n(a.medien, "Medium", "Medien") : `${n(a.anzahl, k === "serien" ? "Serie" : "Gruppe", k === "serien" ? "Serien" : "Gruppen")}, ${n(a.medien, "Medium", "Medien")}`) : "nichts offen"}`,
        h("div", { class: "muted small" }, AUTO_HINT[k])));
  });
  const action = h("select", {}, h("option", { value: "album" }, "ins Prüf-Album"), h("option", { value: "papierkorb" }, "in den Papierkorb"));
  const ok = await confirmDialog({
    title: "⚡ Eindeutiges vormerken",
    body: [h("p", {}, "Merkt die sicheren Fälle auf einmal vor – je Art ein Eintrag. Unter ", h("b", {}, "Vorgemerkt"), " siehst du mit „Ansehen“ alles und nimmst einzelne heraus, bevor etwas an Immich geht."),
      ...rows, h("label", { class: "f" }, "Duplikat-Kopien", action),
      h("p", { class: "muted small" }, "Schutzregeln gelten wie immer: externe Medien und die des anderen Benutzers nur ins Prüf-Album; der Papierkorb wird beim Übertragen noch einmal bestätigt. Automatisch nach jedem Einlesen: ⚙ Einstellungen → Automatisch einlesen.")],
    okLabel: "Vormerken",
  });
  if (!ok) return;
  const arten = Object.keys(boxes).filter((k) => boxes[k].checked);
  if (!arten.length) return;
  try {
    const res = await api("api/auto-stage", { method: "POST", body: { arten, aktion: action.value } });
    toast(res.gesamt ? `Vorgemerkt: ${Object.entries(res.vorgemerkt).filter(([, v]) => v).map(([k, v]) => `${r.arten[k].name} ${v}`).join(", ")}` : "Nichts Neues vorzumerken");
    S.dup.loaded = S.loc.loaded = S.cln.loaded = false;
    await Promise.all([loadTab("stage", true), S.tab !== "stage" && S.tab !== "set" ? loadTab(S.tab, true) : null]);
    loadCounts();
  } catch (e) { toast(e.message, true); }
}

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
  const keyWarn = (d.key_warnungen || []).map((w) => h("div", { class: "banner warn" },
    h("b", {}, `API-Key von ${w.benutzer}: es fehlen Rechte. `),
    w.fehlend.map((p) => `${p.recht} (${p.wofuer})`).join(", "),
    ". In Immich unter Konto-Einstellungen → API-Schlüssel ergänzen oder „Alle“ wählen."));
  const statsBox = h("div", { class: "stat-box" });
  renderStats(statsBox);
  box.replaceChildren(...[
    ...keyWarn,
    tiles,
    h("h2", { class: "stage-head" }, "Zu tun"),
    todo.childElementCount ? todo : h("p", { class: "muted" }, "Alles aufgeräumt 🎉"),
    todo.childElementCount ? h("div", { class: "row-gap auto-cta" },
      h("button", { type: "button", class: "btn primary", onclick: (e) => openAutoStage(e.currentTarget) }, "⚡ Eindeutiges vormerken"),
      h("span", { class: "muted small" }, "sichere Orte, identische Duplikate, Messenger-Kopien, Serien – auf einen Schlag")) : null,
    h("h2", { class: "stage-head" }, "Benutzer"), users,
    h("h2", { class: "stage-head" }, "Statistik"), statsBox,
    d.erledigt.length ? h("h2", { class: "stage-head" }, "Erledigt je Monat") : null,
    d.erledigt.length ? doneTable(d.erledigt) : null,
    h("p", { class: "muted small" }, rep.kanal === "aus" ? "Wochenbericht: aus (⚙ Einstellungen)"
      : `Wochenbericht per ${rep.kanal}: ${rep.tag}s ${rep.uhrzeit}` + (rep.letzter ? ` · zuletzt ${fmtDateTime(rep.letzter)}` : "") + (rep.fehler ? ` · Fehler: ${rep.fehler}` : "")),
  ].filter(Boolean));
}

/* ------------------------------------------------------------ Statistik */
// Jahre (je Benutzer gestapelt) → Tipp auf ein Jahr zeigt dessen Monate → Tipp auf einen Monat öffnet seine Fotos.
// Farben je Benutzer fest (Reihenfolge der Benutzer), nicht nach Rang.
const MONTH_SHORT = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];
const WEEKDAY_LONG = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"];
const userColor = (i) => (i < 2 ? `var(--series-${i + 1})` : "var(--muted)");
const cap = (u) => u.charAt(0).toUpperCase() + u.slice(1);
const de = (x) => x.toLocaleString("de-DE");

// Säulen: items = [{label, parts: [{val, color}], tip, active, onclick}]; ein Hinweistext unter dem Diagramm
function barChart(items, { aria, labelEvery = 1, height = 140, max = null } = {}) {
  max = max || Math.max(1, ...items.map((it) => it.parts.reduce((a, p) => a + p.val, 0)));
  const tip = h("div", { class: "ychart-tip muted small" }, "\u00a0");
  const wrap = h("div", { class: "ychart", role: "img", "aria-label": aria, style: `height:${height}px` });
  items.forEach((it, k) => {
    const total = it.parts.reduce((a, p) => a + p.val, 0);
    const fill = h("div", { class: "ybar-fill", style: `height:${total ? Math.max(2, (total / max) * 100) : 0}%` },
      ...it.parts.filter((p) => p.val).map((p) => h("div", { class: "ybar-seg", style: `flex-grow:${p.val};background:${p.color}` })));
    const bar = h("div", { class: "ybar" + (it.active ? " on" : "") + (it.onclick ? " click" : ""), tabindex: "0",
      role: it.onclick ? "button" : null, "aria-label": it.tip }, fill,
    k % labelEvery === 0 ? h("div", { class: "ybar-x" }, it.label) : null);
    const show = () => { tip.textContent = it.tip; };
    bar.addEventListener("mouseenter", show);
    bar.addEventListener("focus", show);
    bar.addEventListener("click", () => { show(); if (it.onclick) it.onclick(); });
    bar.addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && it.onclick) { e.preventDefault(); it.onclick(); } });
    wrap.append(bar);
  });
  return h("div", { class: "chart" }, wrap, tip);
}

// Rangliste als waagerechte Balken (eine Reihe)
function rankList(title, list, total) {
  if (!list.length) return null;
  const max = list[0].anzahl;
  return h("div", { class: "rank card" }, h("h3", {}, title),
    ...list.map((x) => h("div", { class: "rank-row", title: `${x.name}: ${de(x.anzahl)} (${Math.round((x.anzahl / total) * 100)} %)` },
      h("span", { class: "rank-name" }, x.name),
      h("span", { class: "rank-bar" }, h("i", { style: `width:${Math.max(2, (x.anzahl / max) * 100)}%` })),
      h("span", { class: "rank-n" }, de(x.anzahl)))));
}

function userTip(prefix, b, users) {
  const per = users.length > 1 ? " · " + users.map((u) => `${cap(u)} ${de(b.je_benutzer[u] || 0)} (${fmtBig((b.groesse_je_benutzer || {})[u] || 0)})`).join(", ") : "";
  return `${prefix}: ${de(b.medien)} Medien${per} · ${fmtBig(b.groesse)}` + (b.videos ? ` · ${de(b.videos)} Videos` : "")
    + (b.medien ? ` · ${Math.round((b.ohne_gps / b.medien) * 100)} % ohne Ort` : "");
}

async function renderStats(box) {
  const year = S.stats.jahr;
  if (!box.childElementCount) box.append(h("p", { class: "muted small" }, "Lade Statistik …"));
  let r;
  try { r = await api("api/stats" + (year ? "?jahr=" + year : "")); }
  catch (e) { if (year) { S.stats.jahr = null; return renderStats(box); } box.replaceChildren(h("div", { class: "banner err" }, e.message)); return; }
  const users = r.benutzer;
  const metric = S.stats.metric;
  // Anzahl oder Speicher je Benutzer gestapelt; „mit Ort“ als Anteil (eine Reihe, Skala bis 100 %)
  const parts = (b) => (metric === "ort" ? [{ val: b.medien ? Math.round(((b.medien - b.ohne_gps) / b.medien) * 100) : 0, color: "var(--series-1)" }]
    : users.map((u, i) => ({ val: (metric === "groesse" ? b.groesse_je_benutzer : b.je_benutzer)[u] || 0, color: userColor(i) })));
  const scaleMax = metric === "ort" ? 100 : null;
  const metricBar = h("div", { class: "row-gap metric-bar" }, ...[["medien", "Anzahl"], ["groesse", "Speicher"], ["ort", "mit Ort"]].map(([k, l]) =>
    h("button", { type: "button", class: "chip-btn" + (metric === k ? " on" : ""), onclick: () => { S.stats.metric = k; renderStats(box); } }, l)));
  const legend = metric !== "ort" && users.length > 1 ? h("div", { class: "legend" }, ...users.map((u, i) =>
    h("span", {}, h("i", { style: `background:${userColor(i)}` }), cap(u)))) : null;
  const peak = r.jahre.reduce((a, y) => (y.medien > (a ? a.medien : -1) ? y : a), null);
  const years = barChart(r.jahre.map((y) => ({
    label: r.jahre.length > 12 ? "’" + y.jahr.slice(2) : y.jahr, parts: parts(y), active: y.jahr === year,
    tip: userTip(y.jahr, y, users) + (y.jahr === year ? " – noch einmal tippen: alle Jahre" : " – tippen: Monate"),
    onclick: () => { S.stats.jahr = y.jahr === year ? null : y.jahr; renderStats(box); },
  })), { aria: "Aufnahmen je Jahr", labelEvery: r.jahre.length > 24 ? 2 : 1, max: scaleMax });
  const g = r.gesamt;
  const kpi = (v, l) => h("div", { class: "kpi" }, h("b", {}, v), h("span", { class: "muted small" }, l));
  const head = h("div", { class: "stats-head" },
    h("div", {}, h("b", {}, year ? `Jahr ${year}` : "Alle Jahre"),
      h("div", { class: "muted small" }, year ? "Tippe auf einen Monat, um seine Fotos zu sehen."
        : (peak ? `Tippe auf ein Jahr für seine Monate · meiste Aufnahmen ${peak.jahr} (${de(peak.medien)})` : ""))),
    year ? h("button", { type: "button", class: "btn small", onclick: () => { S.stats.jahr = null; renderStats(box); } }, "← Alle Jahre") : null);
  const kpis = h("div", { class: "kpis" }, kpi(de(g.medien), "Medien"), kpi(fmtBig(g.groesse), "Speicher"),
    kpi(de(g.videos), "Videos"), kpi(g.medien ? Math.round((g.ohne_gps / g.medien) * 100) + " %" : "–", "ohne Ort"),
    g.extern ? kpi(de(g.extern), "extern") : null, g.ohne_datum ? kpi(de(g.ohne_datum), "ohne Datum") : null);
  let months = null;
  if (year) {
    months = h("div", {}, h("h3", {}, `Monate ${year}`), barChart(r.monate.map((m, k) => ({
      label: MONTH_SHORT[k], parts: parts(m),
      tip: userTip(`${MONTHS[k]} ${year}`, m, users) + (m.medien ? " – tippen: Fotos ansehen" : ""),
      onclick: m.medien ? () => openMonthMedia(m.monat, `${MONTHS[k]} ${year}`) : null,
    })), { aria: `Aufnahmen je Monat ${year}`, max: scaleMax }));
  }
  box.replaceChildren(...[head, kpis, metricBar, legend, years, months,
    h("div", { class: "rank-grid" }, ...[rankList("Kameras", r.kameras, g.medien), rankList("Länder", r.laender, g.medien),
      rankList("Orte", r.orte, g.medien), r.personen && r.personen.length ? rankList("Personen", r.personen, g.medien) : null,
      rankList("Formate", r.formate, g.medien)].filter(Boolean)),
    h("div", { class: "card" }, h("h3", {}, "Wann wird fotografiert?"), heatmap(r.heatmap)),
    year ? null : storageCard(r.speicher)].filter(Boolean));
}

// Wochentag × Uhrzeit: je dunkler, desto mehr Aufnahmen (eine Farbe, hell → dunkel)
function heatmap(m) {
  const max = Math.max(1, ...m.flat());
  const tip = h("div", { class: "ychart-tip muted small" }, "\u00a0");
  let best = [0, 0];
  m.forEach((row, d) => row.forEach((c, hh) => { if (c > m[best[0]][best[1]]) best = [d, hh]; }));
  const grid = h("div", { class: "heat", role: "img", "aria-label": "Aufnahmen nach Wochentag und Uhrzeit" },
    h("span", {}), ...Array.from({ length: 24 }, (_, hh) => h("span", { class: "heat-x" }, hh % 6 === 0 ? String(hh) : "")),
    ...m.flatMap((row, d) => [h("span", { class: "heat-y" }, WEEKDAYS[(d + 1) % 7]), ...row.map((c, hh) => {
      const cell = h("span", { class: "heat-c", tabindex: "-1",
        style: `background: color-mix(in srgb, var(--series-1) ${c ? Math.round(12 + 88 * (c / max)) : 0}%, var(--chip))` });
      const show = () => { tip.textContent = `${WEEKDAY_LONG[d]}, ${hh}–${hh + 1} Uhr: ${de(c)} Medien`; };
      cell.addEventListener("mouseenter", show); cell.addEventListener("click", show);
      return cell;
    })]));
  return h("div", {}, h("div", { class: "muted small" }, `Am meisten: ${WEEKDAY_LONG[best[0]]}s ${best[1]}–${best[1] + 1} Uhr · tippe auf ein Feld`), grid, tip);
}

// Speicher: Platte laut Immich, Zuwachs je Monat (letzte 12 Monate) und wann sie voll ist
function storageCard(sp) {
  if (!sp) return null;
  const parts = [h("h3", {}, "Speicher & Prognose")];
  if (sp.gesamt) {
    const pct = sp.prozent ?? (sp.belegt / sp.gesamt) * 100;
    parts.push(h("div", { class: "disk" }, h("i", { style: `width:${Math.min(100, pct)}%` })),
      h("div", { class: "kpis" }, h("div", { class: "kpi" }, h("b", {}, fmtBig(sp.belegt)), h("span", { class: "muted small" }, `belegt (${Math.round(pct)} %)`)),
        h("div", { class: "kpi" }, h("b", {}, fmtBig(sp.frei)), h("span", { class: "muted small" }, "frei")),
        h("div", { class: "kpi" }, h("b", {}, fmtBig(sp.zuwachs_monat)), h("span", { class: "muted small" }, "Zuwachs je Monat")),
        h("div", { class: "kpi" }, h("b", {}, !sp.monate_bis_voll ? "–" : sp.monate_bis_voll > 120 ? "> 10 Jahre"
          : new Date(sp.voll_am).toLocaleDateString("de-DE", { month: "short", year: "numeric" })),
          h("span", { class: "muted small" }, !sp.monate_bis_voll ? "kein Zuwachs" : sp.monate_bis_voll > 120 ? "bis die Platte voll ist"
            : `voll in ~${de(Math.round(sp.monate_bis_voll))} Monaten`))));
  } else {
    parts.push(h("p", { class: "muted small" }, "Freien Platz liefert Immich nicht – fehlt dem API-Key das Recht server.storage? Zuwachs trotzdem:"),
      h("div", { class: "kpi" }, h("b", {}, fmtBig(sp.zuwachs_monat)), h("span", { class: "muted small" }, "Zuwachs je Monat")));
  }
  parts.push(barChart(sp.monate.map((m) => ({ label: MONTH_SHORT[+m.monat.slice(5) - 1], parts: [{ val: m.groesse, color: "var(--series-1)" }],
    tip: `${MONTHS[+m.monat.slice(5) - 1]} ${m.monat.slice(0, 4)}: +${fmtBig(m.groesse)}` })), { aria: "Speicherzuwachs je Monat", height: 80 }),
  h("p", { class: "muted small" }, "Prognose: Mittel der letzten 12 Monate (nach dem Datum, an dem die Medien in Immich kamen). Gezählt sind nur Originale – Vorschauen und Videos in Immich brauchen zusätzlich Platz."));
  return h("div", { class: "card" }, ...parts);
}

async function openMonthMedia(month, label) {
  let r;
  try { r = await api("api/stats/media?monat=" + month); } catch (e) { toast(e.message, true); return; }
  openReview({ titel: `📅 ${label}`, medien: r.medien, gruppe: "tag", nurAnsehen: true,
    hinweis: "Nach Tagen gruppiert. Antippen öffnet groß.", aktionen: [{ leer: true, text: () => "Schließen", run: async () => {} }] });
}

const DONE_LABEL = { duplikat: "Duplikate", aufraeumen: "Aufgeräumt", archiv: "Archiviert", stapel: "Gestapelt", albenpflege: "Alben", zeit: "Zeit", ort: "Verortet", album: "In Alben", tag: "Getaggt", papierkorb: "Wiederhergestellt", personen: "Personen zusammengeführt" };
function doneTable(rows) {
  const keys = Object.keys(DONE_LABEL).filter((k) => rows.some((r) => r[k]));
  return h("table", { class: "tbl" },
    h("thead", {}, h("tr", {}, h("th", {}, "Monat"), ...keys.map((k) => h("th", {}, DONE_LABEL[k])))),
    h("tbody", {}, ...rows.slice().reverse().map((r) => h("tr", {}, h("td", {}, month(r.monat)),
      ...keys.map((k) => h("td", {}, r[k] ? r[k].toLocaleString("de-DE") : "–"))))));
}
function month(m) { return new Date(m + "-15").toLocaleDateString("de-DE", { month: "short", year: "numeric" }); }

/* ------------------------------------------------------------- Personen */
// Unbenannte Personen (mit wem sie meist zusammen auf Fotos sind) – benennen in Immich;
// doppelt angelegte Personen hier zusammenführen (vormerken, in Immich nicht rückgängig zu machen).
async function loadPeople() {
  $("#per-list").replaceChildren(h("p", { class: "empty" }, "Frage Immichs Gesichtserkennung …"));
  S.per.data = await api("api/people");
  S.per.loaded = true;
  renderPeople();
}

function renderPeople() {
  const box = $("#per-list");
  const r = S.per.data;
  const web = S.status && S.status.link_url;
  $("#per-summary").textContent = `${de(r.anzahl_benannt)} mit Namen · ${de(r.anzahl_unbenannt)} ohne Namen`
    + (r.doppelt.length ? ` · ${n(r.doppelt.length, "Person doppelt", "Personen doppelt")}` : "");
  const face = (user, id) => h("img", { class: "face", src: `person-thumb/${encodeURIComponent(user)}/${id}`, alt: "", loading: "lazy" });
  const doubles = r.doppelt.map((d) => {
    const key = d.benutzer + "|" + d.name;
    const keep = S.per.keep[key] || d.behalten;
    return h("article", { class: "card" },
      h("div", { class: "card-head" }, h("div", {}, h("h2", {}, `👤 ${d.name}`),
        h("span", { class: "muted" }, `${n(d.personen.length, "Eintrag", "Einträge")} bei ${cap(d.benutzer)} – Immich hat die Person mehrfach angelegt`))),
      h("div", { class: "faces" }, ...d.personen.map((p) => h("label", { class: "face-pick" + (p.id === keep ? " on" : "") },
        h("input", { type: "radio", name: "keep-" + key, checked: p.id === keep, onchange: () => { S.per.keep[key] = p.id; renderPeople(); } }),
        face(d.benutzer, p.id), h("span", { class: "small" }, `${p.name} · ${n(p.anzahl, "Foto", "Fotos")}`),
        h("span", { class: "muted small" }, p.id === keep ? "bleibt" : "geht darin auf")))),
      h("div", { class: "row-gap" }, h("button", { type: "button", class: "btn small primary", onclick: (e) => mergePeople(d, keep, e.currentTarget) },
        "Zusammenführen vormerken")));
  });
  const unnamed = r.unbenannt.map((u) => h("div", { class: "face-card" }, face(u.benutzer, u.id),
    h("b", {}, n(u.anzahl, "Foto", "Fotos")),
    h("span", { class: "muted small" }, u.mit ? `meist mit ${u.mit.name} (${u.mit.anzahl})` : "mit niemand Bekanntem"),
    h("span", { class: "muted small" }, cap(u.benutzer)),
    web ? h("a", { href: `${web}/people/${encodeURIComponent(u.id)}`, target: "_blank", rel: "noopener", class: "small" }, "In Immich benennen ↗") : null));
  box.replaceChildren(...[
    r.fehler.length ? h("div", { class: "banner warn" }, "Nicht alles abrufbar: " + r.fehler.join(" · ") + " – Recht person.read am API-Key?") : null,
    r.doppelt.length ? h("h2", { class: "stage-head" }, "Doppelt angelegt") : null, ...doubles,
    h("h2", { class: "stage-head" }, "Ohne Namen – die mit den meisten Fotos"),
    unnamed.length ? h("div", { class: "face-grid" }, ...unnamed) : h("p", { class: "empty" }, "Alle häufigen Personen haben einen Namen 🎉"),
    h("p", { class: "muted small" }, web ? "Benennen geht in Immich: „In Immich benennen“ öffnet die Person. Danach hier ↻."
      : "Benennen geht in Immich unter Personen. Für direkte Links unter ⚙ Einstellungen die „Adresse für Links im Browser“ eintragen."),
  ].filter(Boolean));
}

async function mergePeople(d, keep, btn) {
  const keepP = d.personen.find((p) => p.id === keep);
  const others = d.personen.filter((p) => p.id !== keep);
  const ok = await confirmDialog({ title: `„${d.name}“ zusammenführen?`, danger: true, okLabel: "Vormerken",
    checkLabel: "Mir ist klar: Immich kann das nicht rückgängig machen",
    body: [h("p", {}, `${n(others.length, "Eintrag geht", "Einträge gehen")} in „${keepP.name}“ (${n(keepP.anzahl, "Foto", "Fotos")}) auf.`),
      h("p", { class: "muted" }, "Die Gesichter aller Fotos gehören danach zu einer Person. Übertragen wird erst unter Vorgemerkt – Trennen geht danach nicht mehr.")] });
  if (!ok) return;
  busy(btn, true);
  try {
    await api("api/staged/people-merge", { method: "POST", body: { eintraege: [{ benutzer: d.benutzer, behalten: keep, ids: others.map((p) => p.id) }] } });
    toast("Zusammenführen vorgemerkt – unter Vorgemerkt übertragen");
    S.stage.loaded = false;
    await loadTab("per", true);
    loadCounts();
  } catch (e) { toast(e.message, true); busy(btn, false); }
}
