"use strict";
// Einstellungen, Version, Hilfe. Alle Dateien teilen sich einen Namensraum; Reihenfolge siehe index.html.
/* ------------------------------------------------------ Einstellungen */
async function loadSettings() {
  const d = await api("api/settings");
  S.set.data = d; S.set.loaded = true;
  const lock = (id, key) => {
    const el = $(id);
    el.disabled = d.gesperrt.includes(key);
    el.title = el.disabled ? "In der .env festgelegt" : "";
  };
  $("#set-url").value = d.immich_url; lock("#set-url", "immich_url");
  $("#set-mqtt-on").checked = d.mqtt_enabled; lock("#set-mqtt-on", "mqtt_enabled");
  $("#set-mqtt-host").value = d.mqtt_host; lock("#set-mqtt-host", "mqtt_host");
  $("#set-mqtt-port").value = d.mqtt_port; lock("#set-mqtt-port", "mqtt_port");
  $("#set-mqtt-user").value = d.mqtt_user; lock("#set-mqtt-user", "mqtt_user");
  $("#set-mqtt-pass").value = ""; lock("#set-mqtt-pass", "mqtt_password");
  $("#set-mqtt-pass").placeholder = d.mqtt_password_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-mqtt-base").value = d.mqtt_base_topic; lock("#set-mqtt-base", "mqtt_base_topic");
  $("#set-mqtt-prefix").value = d.mqtt_discovery_prefix; lock("#set-mqtt-prefix", "mqtt_discovery_prefix");
  $("#set-mqtt-interval").value = d.mqtt_publish_interval; lock("#set-mqtt-interval", "mqtt_publish_interval");
  $("#set-public-url").value = d.public_url; lock("#set-public-url", "public_url");
  updateMqttFields();
  loadMqttInfo();
  $("#set-album").value = d.review_album; lock("#set-album", "review_album");
  $("#set-link-url").value = d.link_url; lock("#set-link-url", "link_url");
  $("#set-hours").value = d.location_max_hours; lock("#set-hours", "location_max_hours");
  $("#set-ext").checked = d.location_include_external; lock("#set-ext", "location_include_external");
  $("#set-shots").checked = d.location_skip_screenshots; lock("#set-shots", "location_skip_screenshots");
  $("#set-fp").checked = d.dup_image_hash; lock("#set-fp", "dup_image_hash");
  $("#set-edit").value = d.dup_edit_keep; lock("#set-edit", "dup_edit_keep");
  $("#set-alb-km").value = d.album_min_km; lock("#set-alb-km", "album_min_km");
  $("#set-alb-min").value = d.album_min_media; lock("#set-alb-min", "album_min_media");
  S.set.homes = (d.album_home || []).slice();
  renderHomes();
  $("#set-web-user").value = d.web_user; lock("#set-web-user", "web_user");
  $("#set-web-pw").value = ""; lock("#set-web-pw", "web_password");
  $("#set-logout").hidden = !d.login_aktiv;
  $("#set-login-hint").textContent = d.login_aktiv
    ? "Login ist aktiv. Benutzername leeren und speichern schaltet ihn ab."
    : "Ohne Login kann jeder im Heimnetz das Tool bedienen. Für Zugriff von außen unbedingt setzen.";
  $("#set-auto").value = d.auto_scan; lock("#set-auto", "auto_scan");
  $("#set-auto-time").value = d.auto_scan_time; lock("#set-auto-time", "auto_scan_time");
  $("#set-auto-hours").value = d.auto_scan_hours; lock("#set-auto-hours", "auto_scan_hours");
  $("#set-auto-stage").checked = d.auto_stage_locations; lock("#set-auto-stage", "auto_stage_locations");
  for (const k of AUTO_MORE) { $("#set-auto-" + k).checked = d.auto_stage_more.includes(k); lock("#set-auto-" + k, "auto_stage_more"); }
  $("#set-auto-action").value = d.auto_stage_action; lock("#set-auto-action", "auto_stage_action");
  $("#set-tz").value = d.timezone; lock("#set-tz", "timezone");
  updateAutoFields();
  $("#set-upd-check").checked = d.update_check; lock("#set-upd-check", "update_check");
  $("#set-upd-repo").value = d.update_repo; lock("#set-upd-repo", "update_repo");
  $("#set-rep-channel").value = d.report_channel; lock("#set-rep-channel", "report_channel");
  $("#set-rep-day").value = String(d.report_day); lock("#set-rep-day", "report_day");
  $("#set-rep-time").value = d.report_time; lock("#set-rep-time", "report_time");
  $("#set-rep-ntfy-url").value = d.report_ntfy_url; lock("#set-rep-ntfy-url", "report_ntfy_url");
  $("#set-rep-ntfy-token").value = ""; lock("#set-rep-ntfy-token", "report_ntfy_token");
  $("#set-rep-ntfy-token").placeholder = d.report_ntfy_token_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-rep-tg-token").value = ""; lock("#set-rep-tg-token", "report_telegram_token");
  $("#set-rep-tg-token").placeholder = d.report_telegram_token_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-rep-tg-chat").value = d.report_telegram_chat; lock("#set-rep-tg-chat", "report_telegram_chat");
  $("#set-mem").checked = d.memories; lock("#set-mem", "memories");
  $("#set-mem-time").value = d.memories_time; lock("#set-mem-time", "memories_time");
  updateReportFields();
  $("#set-upd-token").value = ""; lock("#set-upd-token", "update_github_token");
  $("#set-upd-token").placeholder = d.update_github_token_gesetzt ? "gespeichert" : "nicht gesetzt";
  $("#set-upd-url").value = d.update_webhook_url; lock("#set-upd-url", "update_webhook_url");
  $("#set-n8n").open = !!d.update_webhook_url;
  $("#set-upd-header").value = d.update_webhook_header; lock("#set-upd-header", "update_webhook_header");
  $("#set-upd-secret").value = ""; lock("#set-upd-secret", "update_webhook_secret");
  $("#set-upd-secret").placeholder = !d.update_webhook_header ? "ohne Auth" : (d.update_webhook_secret_gesetzt ? "gespeichert" : "nicht gesetzt");
  $("#set-users").replaceChildren(...(d.benutzer.length ? d.benutzer : [{ name: "", key_gesetzt: false }]).map(userRow));
  $("#set-add-user").disabled = d.gesperrt.includes("users");
  $("#set-test-result").replaceChildren();
  $("#set-env-hint").textContent = d.gesperrt.length
    ? "Ausgegraute Felder sind in der .env festgelegt und haben Vorrang. Gespeichert wird in " + d.datenordner + "/einstellungen.json."
    : "Gespeichert wird in " + d.datenordner + "/einstellungen.json.";
  $("#set-welcome").replaceChildren(...(d.eingerichtet ? [] : [h("div", { class: "banner warn" },
    h("b", {}, "Willkommen! "), "Trage die Immich-Adresse und für jeden Benutzer einen API-Key ein, teste die Verbindung und speichere.")]));
}

function updateAutoFields() {
  const mode = $("#set-auto").value;
  $("#set-auto-time-wrap").hidden = mode !== "taeglich";
  $("#set-auto-hours-wrap").hidden = mode !== "intervall";
  $("#set-tz").closest("label").hidden = mode === "aus";
  const a = S.status && S.status.auto_einlesen;
  const parts = [];
  if (a && a.modus !== "aus" && a.naechstes) parts.push("Nächstes Einlesen: " + fmtDateTime(a.naechstes));
  if (a && a.letztes) parts.push("zuletzt automatisch: " + fmtDateTime(a.letztes));
  if (a && a.fehler) parts.push("Fehler: " + a.fehler);
  $("#set-auto-info").textContent = parts.join(" · ");
}

function userRow(u) {
  const locked = S.set.data && S.set.data.gesperrt.includes("users");
  const row = h("div", { class: "user-row", "data-alt": u.name || "" },
    h("input", { type: "text", class: "u-name", value: u.name || "", placeholder: "Name, z. B. frank", autocapitalize: "off", disabled: locked, "aria-label": "Benutzername" }),
    h("input", { type: "password", class: "u-key", autocomplete: "off", disabled: locked, "aria-label": "API-Key",
      placeholder: u.key_gesetzt ? "gespeichert" + (u.key_ende ? " …" + u.key_ende : "") : "API-Key einfügen" }),
    h("button", { type: "button", class: "btn small", disabled: locked, "aria-label": "Entfernen", title: "Entfernen", onclick: () => row.remove() }, "✕"));
  return row;
}

function readUsers() {
  return [...document.querySelectorAll("#set-users .user-row")].map((r) => ({
    name: r.querySelector(".u-name").value.trim().toLowerCase(),
    key: r.querySelector(".u-key").value.trim(),
    alt: r.dataset.alt,
  })).filter((u) => u.name || u.key);
}

function readSettingsForm() {
  const d = S.set.data;
  const body = {};
  const put = (key, val) => { if (!d.gesperrt.includes(key)) body[key] = val; };
  put("immich_url", $("#set-url").value.trim());
  put("review_album", $("#set-album").value.trim());
  put("link_url", $("#set-link-url").value.trim());
  put("location_max_hours", $("#set-hours").value);
  put("location_include_external", $("#set-ext").checked);
  put("location_skip_screenshots", $("#set-shots").checked);
  put("dup_image_hash", $("#set-fp").checked);
  put("dup_edit_keep", $("#set-edit").value);
  put("album_min_km", $("#set-alb-km").value);
  put("album_min_media", $("#set-alb-min").value);
  put("album_home", S.set.homes || []);
  if (!d.gesperrt.includes("users")) body.benutzer = readUsers();
  put("auto_scan", $("#set-auto").value);
  put("auto_scan_time", $("#set-auto-time").value);
  put("auto_scan_hours", $("#set-auto-hours").value);
  put("auto_stage_locations", $("#set-auto-stage").checked);
  put("auto_stage_more", AUTO_MORE.filter((k) => $("#set-auto-" + k).checked));
  put("auto_stage_action", $("#set-auto-action").value);
  put("timezone", $("#set-tz").value.trim());
  put("update_check", $("#set-upd-check").checked);
  put("update_repo", $("#set-upd-repo").value.trim());
  put("update_webhook_url", $("#set-upd-url").value.trim());
  put("update_webhook_header", $("#set-upd-header").value.trim());
  put("mqtt_enabled", $("#set-mqtt-on").checked);
  put("mqtt_host", $("#set-mqtt-host").value.trim());
  put("mqtt_port", Number($("#set-mqtt-port").value) || 1883);
  put("mqtt_user", $("#set-mqtt-user").value.trim());
  if ($("#set-mqtt-pass").value) put("mqtt_password", $("#set-mqtt-pass").value);
  put("mqtt_base_topic", $("#set-mqtt-base").value.trim());
  put("mqtt_discovery_prefix", $("#set-mqtt-prefix").value.trim());
  put("mqtt_publish_interval", Number($("#set-mqtt-interval").value) || 900);
  put("public_url", $("#set-public-url").value.trim());
  put("report_channel", $("#set-rep-channel").value);
  put("report_day", Number($("#set-rep-day").value));
  put("report_time", $("#set-rep-time").value);
  put("report_ntfy_url", $("#set-rep-ntfy-url").value.trim());
  put("report_telegram_chat", $("#set-rep-tg-chat").value.trim());
  put("memories", $("#set-mem").checked);
  put("memories_time", $("#set-mem-time").value);
  if ($("#set-rep-ntfy-token").value.trim()) put("report_ntfy_token", $("#set-rep-ntfy-token").value.trim());
  if ($("#set-rep-tg-token").value.trim()) put("report_telegram_token", $("#set-rep-tg-token").value.trim());
  if ($("#set-upd-token").value.trim()) put("update_github_token", $("#set-upd-token").value.trim());
  if ($("#set-upd-secret").value.trim()) put("update_webhook_secret", $("#set-upd-secret").value.trim());
  if (!d.gesperrt.includes("web_user")) {
    body.web_user = $("#set-web-user").value.trim();
    if ($("#set-web-pw").value) body.web_password = $("#set-web-pw").value;
  }
  return body;
}

// Selbsttest: jede genutzte Immich-Schnittstelle einmal nur lesend; schreibende nur anhand der Key-Rechte
async function runSelfTest(btn) {
  const box = $("#set-test-result");
  busy(btn, true);
  box.replaceChildren(h("p", { class: "muted small" }, "Prüfe alle Immich-Funktionen (nur lesend) …"));
  try {
    const r = await api("api/selftest", { method: "POST" });
    const mark = (ok) => (ok === true ? "✓" : ok === false ? "✗" : "–");
    const cls = (ok) => (ok === true ? "test-ok" : ok === false ? "test-bad" : "muted");
    const users = Object.entries(r.benutzer).map(([u, t]) => h("details", { class: "selftest", open: t.fehler > 0 },
      h("summary", {}, `${cap(u)}: ` + (t.fehler ? `${n(t.fehler, "Problem", "Probleme")}` : "alles in Ordnung ✓")),
      h("table", { class: "tbl selftest-tbl" }, h("tbody", {},
        ...t.lesen.map((c) => h("tr", { class: cls(c.ok) }, h("td", {}, mark(c.ok)), h("td", {}, h("b", {}, c.name), h("div", { class: "muted small" }, c.zweck)),
          h("td", { class: "small" }, c.detail + (c.ok ? ` · ${c.ms} ms` : "")))))),
      h("p", { class: "small" }, h("b", {}, "Schreiben"), t.rechte_bekannt ? " (geprüft anhand der Rechte des API-Keys, nicht ausprobiert):" : " – Immich verrät die Rechte dieses Keys nicht; nicht prüfbar."),
      t.rechte_bekannt ? h("ul", { class: "small" }, ...t.schreiben.map((w) => h("li", { class: cls(w.ok) }, `${mark(w.ok)} ${w.zweck} `, h("code", {}, w.recht)))) : null));
    const m = r.mqtt;
    box.replaceChildren(h("div", { class: "banner " + (r.fehler ? "warn" : "ok") }, r.fehler
      ? `${n(r.fehler, "Problem", "Probleme")} gefunden – Details unten. ✗ = Immich lehnt ab oder antwortet anders als erwartet, – = nicht prüfbar.`
      : "Alle genutzten Immich-Funktionen antworten wie erwartet ✓"), ...users,
    h("p", { class: "small muted" }, "Home Assistant (MQTT): " + (!m.aktiv ? "aus" : m.verbunden ? `verbunden mit ${m.broker}` : `nicht verbunden (${m.fehler || "verbinde …"})`)));
  } catch (e) {
    box.replaceChildren(h("div", { class: "banner err" }, e.message));
  } finally { busy(btn, false); }
}

async function testConnection(btn) {
  const box = $("#set-test-result");
  const body = {};
  if (!$("#set-url").disabled) body.immich_url = $("#set-url").value.trim();
  if (!S.set.data.gesperrt.includes("users")) body.benutzer = readUsers();
  busy(btn, true);
  try {
    const r = await api("api/settings/test", { method: "POST", body });
    const lines = [h("li", { class: r.erreichbar ? "test-ok" : "test-bad" },
      r.erreichbar ? `✓ Immich erreichbar${r.version ? " – Version " + r.version : ""}` : `✗ ${r.immich_url} nicht erreichbar`)];
    for (const [name, k] of Object.entries(r.schluessel)) {
      lines.push(h("li", { class: k.ok ? "test-ok" : "test-bad" }, k.ok ? `✓ ${name}: ${k.konto}` + (k.rechte_alle ? " · Key mit allen Rechten" : "") : `✗ ${name}: ${k.fehler}`));
      if (k.rechte_fehlend && k.rechte_fehlend.length) {
        lines.push(h("li", { class: "test-bad" }, `⚠ ${name}: dem API-Key${k.key_name ? ` „${k.key_name}“` : ""} fehlen Rechte:`,
          h("ul", {}, k.rechte_fehlend.map((p) => h("li", {}, h("code", {}, p.recht), " – " + p.wofuer))),
          h("div", { class: "small" }, "In Immich unter Konto-Einstellungen → API-Schlüssel den Key bearbeiten und die Rechte ergänzen (oder „Alle“ wählen). Danach hier nichts ändern – der Key bleibt derselbe.")));
      }
    }
    for (const w of r.warnungen) lines.push(h("li", { class: "test-bad" }, "⚠ " + w));
    box.replaceChildren(h("ul", {}, lines));
  } catch (e) {
    box.replaceChildren(h("div", { class: "banner err" }, (e.details.length ? e.details.join(" · ") : e.message)));
  } finally {
    busy(btn, false);
  }
}

function updateMqttFields() {
  $("#set-mqtt-fields").hidden = !$("#set-mqtt-on").checked;
}

async function loadMqttInfo() {
  try {
    const m = await api("api/mqtt");
    $("#set-mqtt-info").textContent = !m.aktiv ? "aus"
      : m.verbunden ? `✓ verbunden mit ${m.broker}` + (m.zuletzt_gesendet ? ` · zuletzt gesendet ${fmtDateTime(m.zuletzt_gesendet)}` : "")
        : `✗ nicht verbunden (${m.broker})` + (m.fehler ? `: ${m.fehler}` : " – verbinde …");
  } catch (_) { /* egal */ }
}

function updateReportFields() {
  const ch = $("#set-rep-channel").value;
  $("#set-rep-fields").hidden = ch === "aus";
  $("#set-rep-ntfy").hidden = ch !== "ntfy";
  $("#set-rep-tg").hidden = ch !== "telegram";
}

async function sendTestMemories(btn) {
  busy(btn, true);
  try {
    await api("api/settings", { method: "PUT", body: readSettingsForm() });
    await api("api/memories/test", { method: "POST" });
    toast("„An diesem Tag“ gesendet – schau aufs Handy");
  } catch (e) {
    toast(e.message, true);
  } finally { busy(btn, false); }
}

async function sendTestReport(btn) {
  busy(btn, true);
  try {
    await api("api/settings", { method: "PUT", body: readSettingsForm() });  // erst speichern, dann testen
    await api("api/report/test", { method: "POST" });
    toast("Testnachricht gesendet – schau aufs Handy");
    await loadSettings();
  } catch (e) {
    toast(e.details && e.details.length ? e.details.join(" · ") : e.message, true);
  } finally { busy(btn, false); }
}

async function saveSettings(btn) {
  busy(btn, true);
  try {
    const before = S.set.data;
    const r = await api("api/settings", { method: "PUT", body: readSettingsForm() });
    toast(r.login_geaendert ? "Gespeichert – Login ist aktiv, du bleibst angemeldet" : "Einstellungen gespeichert");
    const accessChanged = before.immich_url !== r.immich_url ||
      JSON.stringify(before.benutzer) !== JSON.stringify(r.benutzer) || before.review_album !== r.review_album;
    S.loc.hours = null;
    await loadStatus(true);
    await loadSettings();
    loadVersion();
    S.dup.loaded = S.loc.loaded = S.alb.loaded = S.tags.loaded = false;
    if (accessChanged && r.eingerichtet) toast("Gespeichert – Bibliothek wird beim nächsten Öffnen neu eingelesen");
  } catch (e) {
    toast(e.details.length ? e.details.join(" · ") : e.message, true);
  } finally {
    busy(btn, false);
  }
}

/* ------------------------------------------------------------ Version */
const short = (c) => (c ? c.slice(0, 7) : "?");

async function loadVersion(force = false) {
  let v;
  try {
    v = await api(force ? "api/version/check" : "api/version", force ? { method: "POST" } : {});
  } catch (e) {
    $("#version-info").textContent = "Version nicht ermittelbar: " + e.message;
    return null;
  }
  S.version = v;
  $("#set-btn").classList.toggle("dot", !!v.update_available);
  $("#set-btn").title = v.update_available ? "Einstellungen – Update verfügbar" : "Einstellungen";
  if (S.tab !== "set" && !force) return v;
  const cur = v.current || {};
  const parts = [`Läuft: ${short(cur.commit)}${cur.branch ? " (" + cur.branch + ")" : ""}`];
  if (cur.updated_at) parts.push("Stand " + fmtDateTime(cur.updated_at));
  if (v.dienst && v.dienst.verfuegbar) { /* Stand kommt vom Update-Dienst (siehe unten) */ }
  else if (!v.enabled) parts.push("Update-Prüfung aus");
  else if (v.error) parts.push("Prüfung fehlgeschlagen: " + v.error);
  else if (v.status === "update") parts.push(`${v.behind} neue ${v.behind === 1 ? "Änderung" : "Änderungen"} auf GitHub`);
  else if (v.status === "current") parts.push("aktuell ✓");
  else if (v.status === "unknown") parts.push("lokaler Stand ist GitHub unbekannt");
  $("#version-info").textContent = parts.join(" · ");
  $("#version-commits").replaceChildren(...(v.commits && v.commits.length
    ? [h("ul", { class: "commits" }, v.commits.map((c) => h("li", {}, h("code", {}, short(c.commit)), " ", c.message)))] : []));
  $("#version-check").hidden = !v.enabled;
  if (v.dienst && v.dienst.verfuegbar) { renderUpdater(v); return v; }
  $("#version-host").replaceChildren();
  const btn = $("#version-update");
  btn.hidden = !v.update_moeglich;
  btn.className = "btn small" + (v.update_available ? " primary" : "");
  if (!v.update_moeglich) {
    $("#version-out").textContent = "Für Updates per Klick einmalig auf dem Server im Projektordner ausführen: sudo ./installieren.sh – danach erscheint hier der Update-Dienst.";
  } else if (!btn.disabled) {
    $("#version-out").textContent = "";
  }
  return v;
}

async function startUpdate(btn) {
  const ok = await confirmDialog({ title: "Jetzt aktualisieren?",
    body: h("p", {}, "n8n holt den neuen Stand von GitHub, baut den Container neu und startet ihn. Das Tool ist dabei 1–3 Minuten nicht erreichbar."),
    okLabel: "Aktualisieren" });
  if (!ok) return;
  const from = ((S.version || {}).current || {}).commit;
  const out = $("#version-out");
  btn.disabled = true;
  out.textContent = "Starte Update …";
  try {
    await api("api/version/update", { method: "POST" });
  } catch (e) {
    out.textContent = "Update konnte nicht gestartet werden: " + e.message;
    btn.disabled = false;
    return;
  }
  out.textContent = "Update gestartet – der Container wird neu gebaut und startet neu. Die Seite lädt danach von selbst neu (meist 1–3 Minuten).";
  const started = Date.now();
  const poll = async () => {
    const now = await fetch("api/version", { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (now && now.current && now.current.commit && now.current.commit !== from) return location.reload();
    if (Date.now() - started > 10 * 60 * 1000) {
      out.textContent = "Noch keine neue Version – bitte in n8n die Ausführung des Workflows prüfen.";
      btn.disabled = false;
      return;
    }
    setTimeout(poll, 10000);
  };
  setTimeout(poll, 15000);
}

/* Update-Dienst auf dem Docker-Server: vorbereiten, ansehen, umschalten */
let updaterTimer = null;
function renderUpdater(v) {
  const d = v.dienst;
  const box = $("#version-host");
  clearTimeout(updaterTimer);
  $("#version-update").hidden = true;
  $("#version-check").hidden = true;
  $("#version-commits").replaceChildren();  // die Liste kommt hier vom Dienst
  const seen = d.zeit ? "zuletzt " + fmtDateTime(d.zeit) : "";
  const parts = [h("div", { class: "muted small" }, `Update-Dienst auf dem Server: verbunden · ${seen}`)];
  const busy = d.phase === "vorbereiten" || d.phase === "umschalten" || d.auftrag_offen;
  if (busy) {
    parts.push(h("div", { class: "banner warn" }, d.auftrag_offen && !["vorbereiten", "umschalten"].includes(d.phase)
      ? "Auftrag übergeben – der Dienst startet gleich …" : d.meldung));
    updaterTimer = setTimeout(() => loadVersion(), 4000);
  } else if (d.phase === "bereit") {
    parts.push(h("div", {}, h("b", {}, `Version ${short(d.bereit)} ist vorbereitet`), " – das Umschalten dauert nur Sekunden."),
      h("ul", { class: "commits" }, (d.commits || []).map((c) => h("li", {}, h("code", {}, short(c.commit)), " ", c.message))),
      h("div", { class: "row-gap" },
        h("button", { type: "button", class: "btn small primary", onclick: (e) => switchVersion(d, e.currentTarget) }, "Jetzt umschalten"),
        h("button", { type: "button", class: "btn small", onclick: (e) => prepareVersion(e.currentTarget) }, "Erneut prüfen")));
  } else {
    if (d.phase === "fehler") {
      parts.push(h("div", { class: "banner err" }, d.meldung, d.log ? h("pre", { class: "log" }, d.log) : null));
    } else {
      parts.push(h("div", {}, d.meldung || "Aktuell."));
    }
    parts.push(h("div", { class: "row-gap" },
      h("button", { type: "button", class: "btn small", onclick: (e) => prepareVersion(e.currentTarget) }, "Jetzt auf Updates prüfen")));
  }
  parts.push(h("p", { class: "muted small" }, "Neue Versionen werden stündlich im Hintergrund vorbereitet. Umgeschaltet wird nur per Klick."));
  box.replaceChildren(...parts);
  $("#version-out").textContent = "";
}

async function prepareVersion(btn) {
  busy(btn, true);
  try {
    await api("api/updater/prepare", { method: "POST" });
    await loadVersion();
  } catch (e) {
    toast(e.message, true);
  } finally {
    busy(btn, false);
  }
}

async function switchVersion(d, btn) {
  const ok = await confirmDialog({
    title: `Auf Version ${short(d.bereit)} umschalten?`,
    body: [h("p", {}, "Diese Änderungen werden aktiv:"),
      h("ul", { class: "commits" }, (d.commits || []).map((c) => h("li", {}, h("code", {}, short(c.commit)), " ", c.message))),
      h("p", { class: "muted" }, "Das Tool ist nur wenige Sekunden weg. Startet die neue Version nicht sauber, schaltet der Dienst automatisch auf die alte zurück.")],
    okLabel: "Umschalten",
  });
  if (!ok) return;
  const from = ((S.version || {}).current || {}).commit;
  busy(btn, true);
  try {
    await api("api/updater/apply", { method: "POST", body: { bereit: d.bereit } });
  } catch (e) {
    toast(e.message, true); busy(btn, false); return;
  }
  $("#version-host").replaceChildren(h("div", { class: "banner warn" }, "Schalte um … die Seite lädt gleich von selbst neu."));
  const started = Date.now();
  const poll = async () => {
    const now = await fetch("api/version", { cache: "no-store", headers: { "X-Requested-With": "pflege" } })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (now && now.current && now.current.commit && now.current.commit !== from) return location.reload();
    if (now && now.dienst && now.dienst.phase === "fehler") { S.version = now; return loadVersion(); }
    if (Date.now() - started > 5 * 60 * 1000) { toast("Umschalten dauert ungewöhnlich lange – Status prüfen", true); return loadVersion(); }
    setTimeout(poll, 3000);
  };
  setTimeout(poll, 3000);
}

/* --------------------------------------------------------------- Hilfe */
// Kleiner Markdown-Renderer für die Hilfetexte (Überschriften, Absätze, Listen, Tabellen,
// **fett**, *kursiv*, `Code`). Der Text wird vorher escaped – kein HTML aus den Dateien.
function mdInline(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>");
}

function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const head = line.match(/^(#{1,3})\s+(.*)$/);
    if (head) { out.push(`<h${head[1].length}>${mdInline(head[2])}</h${head[1].length}>`); i++; continue; }
    if (line.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].startsWith("|")) { rows.push(lines[i]); i++; }
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => mdInline(c.trim()));
      const body = rows.filter((r, idx) => !(idx === 1 && /^\|[\s:|-]+\|$/.test(r.trim())));
      const [first, ...rest] = body;
      out.push(`<div class="table-wrap"><table><thead><tr>${cells(first).map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>` +
        rest.map((r) => `<tr>${cells(r).map((c) => `<td>${c}</td>`).join("")}</tr>`).join("") + "</tbody></table></div>");
      continue;
    }
    const list = line.match(/^(\s*)([-*]|\d+\.)\s+/);
    if (list) {
      const ordered = /\d/.test(list[2]);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) {
        const indent = lines[i].match(/^\s*/)[0].length;
        const text = mdInline(lines[i].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        items.push(indent ? `<ul><li>${text}</li></ul>` : `<li>${text}</li>`);
        i++;
      }
      const tag = ordered ? "ol" : "ul";
      out.push(`<${tag}>${items.join("").replace(/<\/ul><ul>/g, "")}</${tag}>`);
      continue;
    }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#|\||\s*([-*]|\d+\.)\s)/.test(lines[i])) { para.push(lines[i]); i++; }
    out.push(`<p>${mdInline(para.join(" "))}</p>`);
  }
  return out.join("\n");
}

async function openHelp(topic) {
  const body = $("#help-body");
  body.innerHTML = "<p>Lade …</p>";
  $("#help-dlg").showModal();
  try {
    const resp = await fetch("api/help/" + topic, { headers: { "X-Requested-With": "pflege" } });
    if (!resp.ok) throw new Error("Hilfe nicht verfügbar");
    body.innerHTML = renderMarkdown(await resp.text());
  } catch (e) {
    body.replaceChildren(h("div", { class: "banner err" }, e.message));
  }
  $("#help-dlg").scrollTop = 0;
}
