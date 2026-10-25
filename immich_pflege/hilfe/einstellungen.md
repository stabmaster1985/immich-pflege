# Einstellungen

Alle Einstellungen werden hier gemacht und in `data/einstellungen.json` gespeichert. Werte aus einer optionalen `.env` haben Vorrang und erscheinen ausgegraut.

## Immich

- **Adresse:** IP oder Name des Immich-Servers mit Port, z. B. `http://192.168.1.20:2283`.
- **Adresse für Links im Browser** (optional): Die Links „Web ↗“ an den Bildern führen hierhin, z. B. zu deiner externen Immich-Adresse. Leer heißt: die Adresse oben.
- **API-Keys:** Pro Benutzer einer. In Immich als dieser Benutzer anmelden, dann *Kontoeinstellungen → API-Schlüssel → Neuer API-Schlüssel*. Ein leeres Feld beim Speichern behält den bisherigen Key. Keys werden nie an den Browser zurückgegeben.
- **Verbindung testen** zeigt die Immich-Version und zu jedem Key das zugehörige Konto, ohne zu speichern.

## Automatisch einlesen

**Nur Änderungen:** Einlesen holt normalerweise nur, was sich seit dem letzten Mal geändert hat: neue und bearbeitete Fotos und solche, die in den Papierkorb gewandert sind. Das ist bei großen Bibliotheken viel schneller. Einmal pro Woche liest das Tool alles vollständig, dabei verschwinden auch endgültig gelöschte Fotos. Unter ⚙ → Automatisch einlesen gibt es **Jetzt komplett neu einlesen**. Kommandozeile: `pflege einlesen --komplett`.

Neue Fotos erscheinen im Tool erst nach dem Einlesen. Das geht **täglich** zu einer Uhrzeit oder **alle X Stunden**, in der gewählten Zeitzone und mit Sommer- und Winterzeit. Ein verpasster Termin, z. B. weil der Container aus war, wird nachgeholt. Schlägt das Einlesen fehl, versucht es das Tool nach 15 Minuten erneut.

**Danach sichere Ortsvorschläge vormerken:** Nach jedem automatischen Einlesen landen die sicheren Ortsvorschläge unter **Vorgemerkt**, als Eintrag „Automatisch …: sichere Orte“. Übertragen wird erst, wenn du es dort bestätigst. Dafür braucht es keinen n8n-Workflow mehr.

## Albumvorschläge

- **Reise ab km von zu Hause:** Ab dieser Entfernung zählen Fotos als „unterwegs“ (Standard 50 km).
- **Mindestens Medien:** Kleinere Ausflüge werden nicht vorgeschlagen (Standard 20).
- **Zuhause:** leer = automatisch erkennen. Sonst per Ortssuche festlegen, z. B. nach einem Umzug oder für einen zweiten Wohnort.

## Wochenbericht

Einmal pro Woche eine kurze Nachricht aufs Handy: offene Duplikate, verortbare Fotos (davon sicher), Reisen ohne Album, was zum Aufräumen ansteht, falsche Zeiten und was vorgemerkt ist. Dafür braucht es kein n8n.

- **ntfy:** In der ntfy-App ein Thema abonnieren (z. B. `https://ntfy.sh/ein-langer-zufaelliger-name`) und genau diese Adresse eintragen. Mit eigenem ntfy-Server oder geschütztem Thema zusätzlich ein Zugangstoken.
- **Telegram:** Bei @BotFather einen Bot anlegen, dessen Token eintragen, dem Bot einmal schreiben und die eigene Chat-ID eintragen (z. B. über @userinfobot).
- **Testnachricht senden** speichert die Einstellungen und schickt sofort eine Nachricht.

Verpasst der Container den Termin, holt er ihn beim nächsten Start nach, solange es dieselbe Woche ist.

**An diesem Tag:** Über denselben Kanal kommt auf Wunsch jeden Morgen eine Nachricht mit den Fotos vom selben Kalendertag aus früheren Jahren, z. B. „vor 2 Jahren (2024): 23 Fotos – Siena“. Antippen öffnet bei ntfy das schönste Foto direkt in der Immich-App (Favorit, sonst ein Foto aus einem Album). Bei Telegram steht ein Link zur Weboberfläche darunter. An Tagen ohne frühere Fotos kommt nichts. Screenshots, archivierte Fotos und das Prüf-Album zählen nicht. **Heute testen** schickt die heutige Nachricht sofort.

## Duplikate

- **Prüf-Album:** Name des Albums für nicht behaltene Kopien.
- **Bei Original + Bearbeitung behalten:** die bearbeitete Fassung (`IMG_E…`, Standard) oder das Original.
- **Bild-Fingerabdruck:** Findet ähnliche Kopien, etwa per WhatsApp verschickte Fotos. Lädt dafür einmalig das kleine Vorschaubild jedes Fotos.

## Fotos ohne Ort

- **Zeitfenster:** Wie weit ein Foto mit GPS zeitlich entfernt sein darf (Standard ±2 Stunden).
- **Externe Bibliotheken:** Standardmäßig werden sie nicht geändert.
- **Screenshots ausblenden:** Screenshots und Bildschirmaufnahmen tauchen nicht auf.

## Zugang

- **Benutzername + Passwort** aktivieren die Anmeldeseite. Mit „Angemeldet bleiben“ gilt die Anmeldung 90 Tage und verlängert sich bei Benutzung.
- **Neues Passwort** meldet alle anderen Geräte ab.
- **Login abschalten:** Benutzername leeren und speichern.
- **n8n und curl** melden sich per Basic Auth mit denselben Daten an.

## Als App installieren

Die Oberfläche lässt sich wie eine App auf den Startbildschirm legen – mit eigenem Symbol und ohne Adressleiste:

- **iPhone/iPad (Safari):** Teilen-Knopf → **„Zum Home-Bildschirm“**.
- **Android (Chrome):** Menü ⋮ → **„App installieren“** bzw. **„Zum Startbildschirm hinzufügen“**.

Als richtige App (eigenes Fenster) bietet Chrome das nur über **HTTPS** an, also z. B. hinter einem Reverse Proxy. Über `http://IP:2222` legt Chrome nur eine Verknüpfung an; Safari öffnet die Seite auch dann ohne Adressleiste. Die App speichert nichts zwischen – die Daten kommen immer frisch vom Server.

## Updates

Die Karte **Version** zeigt den laufenden Stand. Es gibt zwei Wege für Updates:

### Update-Dienst auf dem Server (empfohlen)

Ein kleiner Dienst auf dem Docker-Server (systemd) übernimmt die Updates. Die App selbst bekommt **keine** Rechte am Server, sie legt nur einen Auftrag in `data/updater/` ab.

1. **Vorbereiten:** Stündlich, oder per „Jetzt auf Updates prüfen“, holt der Dienst neue Versionen von GitHub und baut sie **komplett fertig**. Die laufende Version bleibt dabei unberührt.
2. **Letzter Blick:** Die Karte zeigt „Version … ist vorbereitet“ mit allen Änderungen, am Zahnrad erscheint ein roter Punkt.
3. **Umschalten per Klick:** Der Wechsel dauert nur Sekunden. Startet die neue Version nicht sauber, schaltet der Dienst **automatisch auf die alte zurück** und zeigt den Fehler an.

Eingerichtet wird der Dienst einmalig mit `sudo ./installieren.sh` (oder nur der Dienst: `sudo ./updater/install.sh`) im Projektordner auf dem Server. Danach hält er sich selbst aktuell: Bringt ein Update eine neue Fassung des Dienstes mit, übernimmt er sie beim Umschalten. Entfernen: `sudo ./updater/install.sh --entfernen`.

### n8n-Workflow (optional)

Nur nötig, wenn auf dem Server kein systemd läuft. Ohne Update-Dienst startet **Jetzt aktualisieren** den n8n-Workflow `n8n/immich-pflege-update.json`, dafür die Webhook-Adresse eintragen. Header-Name leer lassen bedeutet: Webhook ohne Authentifizierung. Hier wird erst nach dem Klick geholt und gebaut, das dauert 1–3 Minuten.
