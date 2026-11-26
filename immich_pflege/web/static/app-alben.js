"use strict";
// Albumvorschläge (Reisen). Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
/* -------------------------------------------------------------- Alben */
const PAGE_ALB = 20;
const ALB_STATUS = { neu: "Neues Album", ergaenzen: "Album ergänzen", vorhanden: "Schon in Alben" };

async function loadAlbums(reset) {
  const a = S.alb;
  if (a.quelle === "ordner") return loadFolders();
  if (reset) { a.trips = []; a.sel.clear(); a.choice = {}; a.ohne = {}; a.open = {}; $("#alb-list").replaceChildren(h("p", { class: "empty" }, "Lade …")); }
  const gen = pageGen(a, reset, "#alb-more");
  if (gen < 0) return;
  const params = new URLSearchParams({ offset: a.trips.length, limit: PAGE_ALB, ignoriert: a.ignored });
  if (a.status) params.set("status", a.status);
  if (a.jahr) params.set("jahr", a.jahr);
  const r = await api("api/album-suggestions?" + params);
  if (gen !== a.gen) return;  // inzwischen neu geladen
  if (reset) { a.resetting = false; a.trips = []; }
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
    if (a.trips.some((x) => x.id === t.id)) continue;
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
  }
  if (t.album) found.append(" ", h("button", { type: "button", class: "btn small", onclick: (e) => openAlbumView(t.album, t, e.currentTarget) }, "Album ansehen")); else {
    found.append(`Kein passendes Album – geprüft: ${n(S.alb.info.alben, "Album", "Alben")} beider Benutzer.`);
  }
  const others = t.kandidaten.filter((k) => !t.album || k.id !== t.album.id);
  if (others.length) found.append(h("div", { class: "muted small" }, (t.status === "vorhanden" && !t.album ? "" : "Auch Fotos in: "),
    ...others.map((k, i) => h("span", { class: "alb-other" }, (i ? " · " : "") + `„${k.name}“ (${k.in_reise}) `,
      h("button", { type: "button", class: "linklike small", onclick: (e) => openAlbumView(k, t, e.currentTarget) }, "ansehen"), " ", albumLinks(k)))));
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

// Album im Tool ansehen: was schon drin ist, und vorn die Medien der Reise, die noch fehlen
async function openAlbumView(al, t, btn) {
  busy(btn, true);
  let r;
  try { r = await api(`api/albums/${encodeURIComponent(al.id)}/media` + (t ? "?reise=" + encodeURIComponent(t.id) : "")); }
  catch (e) { toast(e.message, true); return; } finally { busy(btn, false); }
  const month = rvGrouper({});
  const canAdd = t && r.fehlend && al.besitzer !== "anderer Benutzer" && !S.alb.ignored;
  openReview({
    titel: `🖼 „${r.name}“`, medien: r.medien, nurAnsehen: true,
    gruppe: (m) => (m.fehlt ? ["fehlt", `Fehlt noch im Album (aus „${t.name}“)`] : month(m)),
    hinweis: `${n(r.anzahl, "Medium", "Medien")} im Album` + (r.fehlend ? ` · ${n(r.fehlend, "Medium", "Medien")} der Reise fehlen noch (oben, markiert)` : "")
      + ". Antippen öffnet groß.",
    fuss: r.besitzer ? `gehört ${r.besitzer}` : "",
    aktionen: [
      canAdd ? { klasse: "primary", leer: true, text: () => `${n(r.fehlend, "fehlendes", "fehlende")} ergänzen`, run: async () => {
        S.alb.choice[t.id] = { album: al.id, name: "" };
        await stageTrips([t], $("#rv-actions button.primary"));
      } } : null,
      { leer: true, text: () => "Schließen", run: async () => {} },
    ].filter(Boolean),
  });
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
