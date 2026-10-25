# Einstellungen

Alle Einstellungen werden hier gemacht und in `data/einstellungen.json` gespeichert. Werte aus einer optionalen `.env` haben Vorrang und erscheinen ausgegraut.

## Immich

- **Adresse:** IP oder Name des Immich-Servers mit Port, z. B. `http://192.168.1.20:2283`.
- **Adresse für Links im Browser** (optional): Die Links „Web ↗“ an den Bildern führen hierhin, z. B. zu deiner externen Immich-Adresse. Leer heißt: die Adresse oben.
- **API-Keys:** Pro Benutzer einer. In Immich als dieser Benutzer anmelden, dann *Kontoeinstellungen → API-Schlüssel → Neuer API-Schlüssel*. Ein leeres Feld beim Speichern behält den bisherigen Key. Keys werden nie an den Browser zurückgegeben.
- **Verbindung testen** zeigt die Immich-Version und zu jedem Key das zugehörige Konto, ohne zu speichern.

## Automatisch einlesen

Neue Fotos erscheinen im Tool erst nach dem Einlesen. Das geht **täglich** zu einer Uhrzeit oder **alle X Stunden**, in der gewählten Zeitzone und mit Sommer- und Winterzeit. Ein verpasster Termin, z. B. weil der Container aus war, wird nachgeholt. Schlägt das Einlesen fehl, versucht es das Tool nach 15 Minuten erneut.

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

## Updates

Die Karte **Version** zeigt den laufenden Stand. Es gibt zwei Wege für Updates:

### Update-Dienst auf dem Server (empfohlen)

Ein kleiner Dienst auf dem Docker-Server (systemd) übernimmt die Updates. Die App selbst bekommt **keine** Rechte am Server, sie legt nur einen Auftrag in `data/updater/` ab.

1. **Vorbereiten:** Stündlich, oder per „Jetzt auf Updates prüfen“, holt der Dienst neue Versionen von GitHub und baut sie **komplett fertig**. Die laufende Version bleibt dabei unberührt.
2. **Letzter Blick:** Die Karte zeigt „Version … ist vorbereitet“ mit allen Änderungen, am Zahnrad erscheint ein roter Punkt.
3. **Umschalten per Klick:** Der Wechsel dauert nur Sekunden. Startet die neue Version nicht sauber, schaltet der Dienst **automatisch auf die alte zurück** und zeigt den Fehler an.

Eingerichtet wird der Dienst einmalig mit `sudo ./updater/install.sh` im Projektordner auf dem Server. Der n8n-Workflow erledigt das bei seinem nächsten Lauf automatisch, wenn er als root arbeitet. Entfernen: `sudo ./updater/install.sh --entfernen`.

### n8n-Workflow

Ohne Update-Dienst startet **Jetzt aktualisieren** den n8n-Workflow `n8n/immich-pflege-update.json`, dafür die Webhook-Adresse eintragen. Header-Name leer lassen bedeutet: Webhook ohne Authentifizierung. Hier wird erst nach dem Klick geholt und gebaut, das dauert 1–3 Minuten.
