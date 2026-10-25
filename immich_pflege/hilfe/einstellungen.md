# Einstellungen

Alle Einstellungen werden hier gemacht und in `data/einstellungen.json` gespeichert. Werte aus einer optionalen `.env` haben Vorrang und erscheinen ausgegraut.

## Immich

- **Adresse:** IP oder Name des Immich-Servers mit Port, z. B. `http://192.168.1.20:2283`.
- **API-Keys:** Pro Benutzer einer. In Immich als dieser Benutzer anmelden, dann *Kontoeinstellungen → API-Schlüssel → Neuer API-Schlüssel*. Ein leeres Feld beim Speichern behält den bisherigen Key. Keys werden nie an den Browser zurückgegeben.
- **Verbindung testen** zeigt die Immich-Version und zu jedem Key das zugehörige Konto, ohne zu speichern.

## Automatisch einlesen

Neue Fotos erscheinen im Tool erst nach dem Einlesen. Das geht **täglich** zu einer Uhrzeit oder **alle X Stunden**, in der gewählten Zeitzone und mit Sommer- und Winterzeit. Ein verpasster Termin, z. B. weil der Container aus war, wird nachgeholt. Schlägt das Einlesen fehl, versucht es das Tool nach 15 Minuten erneut.

## Duplikate

- **Prüf-Album:** Name des Albums für nicht behaltene Kopien.
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

Die Karte **Version** zeigt den laufenden Stand. Gibt es Neues auf GitHub, erscheint am Zahnrad ein roter Punkt. **Jetzt aktualisieren** startet den n8n-Workflow `n8n/immich-pflege-update.json`, dafür die Webhook-Adresse eintragen. Header-Name leer lassen bedeutet: Webhook ohne Authentifizierung.
