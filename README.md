# immich-pflege

Wartungstool für einen selbst gehosteten **Immich-Server (v3.x, getestet gegen die API von 3.2.4)**: als Docker-Container mit mobiler Web-Oberfläche, Kommandozeile `pflege` und JSON-API für n8n.

| Funktion | Was passiert |
|---|---|
| **Duplikate** | Immich-Duplikaterkennung pro Benutzer, dazu identische Prüfsumme sowie gleicher Dateiname mit gleicher Aufnahmezeit, auch benutzerübergreifend und zwischen Upload und externer Bibliothek. Überlappende Treffer werden zu Gruppen zusammengeführt. Ein Behalten-Vorschlag kommt aus einer Punktwertung. Nicht behaltene Kopien kommen ins Album „Duplikat-Prüfung“ oder in den Papierkorb. |
| **Ohne Ort** | Alle Medien ohne GPS, nach Tag gruppiert, mit Vorschlag: Ort des zeitlich nächsten Fotos mit GPS (beider Benutzer) innerhalb von ±2 h |
| **Tags** | Massen-Tagging nach Regeln, die du in der Oberfläche anlegst. Tags werden nur ergänzt, nie entfernt. |

Alles startet als **Vorschau**. Änderungen gibt es nur nach ausdrücklicher Aktion.

**Alle Einstellungen und Regeln werden in der Oberfläche gemacht.** Dateien musst du nicht bearbeiten.

---

## Einrichtung

### 1. API-Keys in Immich anlegen

Für **jeden** Benutzer (hier frank und julia) einzeln:

1. In Immich als dieser Benutzer anmelden
2. Avatar oben rechts → **Kontoeinstellungen** → **API-Schlüssel** → **Neuer API-Schlüssel**
3. Name z. B. `immich-pflege`. Berechtigungen: am einfachsten **Alle**. Wer die Rechte einschränken will, braucht mindestens:
   `asset.read`, `asset.view`, `asset.update`, `asset.delete`, `album.read`, `album.create`, `albumAsset.create`, `duplicate.read`, `person.read`, `tag.read`, `tag.create`, `tag.asset`, `user.read`
4. Den Schlüssel kopieren, er wird nur einmal angezeigt.

> Jeder Benutzer kann nur seine eigenen Medien ändern. Deshalb braucht das Tool je Benutzer einen Schlüssel und verwendet automatisch den des Besitzers.

### 2. Container starten

Das Tool läuft auf dem Docker-Server, zum Beispiel neben paperless-companion und firefly-dashboard. Immich kann auf einem eigenen LXC oder einer eigenen VM laufen, das Tool spricht es über das Netzwerk an (Port 2283). Am einfachsten installierst du über den n8n-Workflow (siehe [Aktualisieren per n8n](#aktualisieren-per-n8n)), der beim ersten Lauf alles klont und startet. Von Hand geht es so:

```bash
git clone https://github.com/stabmaster1985/immich-pflege.git
cd immich-pflege
mkdir -p data && sudo chown 1000:1000 data   # Container läuft als Benutzer 1000, nicht als root
docker compose up -d --build
```

Die Oberfläche läuft auf Port 2222. Soll ein anderer Port genutzt werden, lege eine `.env` mit `PFLEGE_PORT=…` an (siehe `.env.example`).

### 3. In der Oberfläche einrichten

`http://<server>:2222` öffnen. Beim ersten Start öffnet sich automatisch **⚙ Einstellungen**:

1. **Adresse** von Immich: IP des Immich-LXC mit Port, z. B. `http://192.168.1.20:2283`. Der Docker-Server muss diesen Port erreichen können.
2. **Benutzer und API-Keys:** Name (z. B. `frank`) und Key einfügen, mit **+ Benutzer** weitere ergänzen
3. **Verbindung testen:** zeigt Immich-Version und für jeden Key das zugehörige Konto
4. Optional Prüf-Album, Zeitfenster, externe Bibliotheken sowie **Benutzername und Passwort** für den Zugang zum Tool
5. **Speichern**

Gespeichert wird in `data/einstellungen.json`. Keys werden nie an den Browser zurückgegeben, angezeigt werden nur die letzten 4 Zeichen. Das Passwort wird nur als Hash gespeichert. Ein leeres Key-Feld beim Speichern heißt „bisherigen Key behalten“.

**Anmeldung:** Ist ein Login gesetzt, erscheint eine Anmeldeseite. Mit „Angemeldet bleiben“ (vorausgewählt) gilt die Anmeldung 90 Tage und verlängert sich bei Benutzung von selbst, ohne Häkchen endet sie mit dem Browser (höchstens 12 h). Wer den Login in den Einstellungen setzt, bleibt dabei angemeldet. Ein neues Passwort meldet alle Geräte ab. Nach 5 Fehlversuchen ist die Anmeldung 5 Minuten gesperrt. **Abmelden** steht unter ⚙ Einstellungen → Zugang.

Beim ersten Öffnen eines Tabs liest das Tool die Bibliothek ein, was bei großen Bibliotheken ein bis zwei Minuten dauert. Danach liegt sie zwischengespeichert in `data/bibliothek.json`. **Neu einlesen** gibt es als Button, per `pflege einlesen` oder über `POST /api/scan`.

**Automatisch einlesen:** Neue Fotos erscheinen erst nach dem Einlesen. Unter **⚙ Einstellungen → Automatisch einlesen** stellst du ein, ob das Tool das selbst erledigt: **täglich** zu einer Uhrzeit oder **alle X Stunden**. Die Zeitzone ist Europe/Berlin, wählbar, und berücksichtigt Sommer- und Winterzeit. War der Container zum geplanten Zeitpunkt aus, holt das Tool das Einlesen nach. Das nächste Einlesen steht in den Einstellungen und oben in der Statuszeile („auto 03:00“). Ab Werk ist es aus.

Logs: `docker logs immich-pflege` und `data/pflege.log`.

> Von außerhalb des Heimnetzes nur über einen Reverse-Proxy mit HTTPS und mit gesetztem Login. Die API-Keys verlassen nie den Container: Vorschaubilder reicht das Backend durch.

### Optional: Einstellungen per `.env` festlegen

Wer lieber mit Dateien arbeitet, kann die meisten Werte auch in einer `.env` vorgeben (`IMMICH_URL`, `REVIEW_ALBUM`, `LOCATION_MAX_HOURS`, `LOCATION_INCLUDE_EXTERNAL`, `WEB_USER`/`WEB_PASSWORD`, `UPDATE_*`). API-Keys (`IMMICH_KEY_<NAME>`) gehen per `docker-compose.override.yml`, siehe `.env.example`. Werte aus der `.env` haben Vorrang und erscheinen in der Oberfläche ausgegraut.

### Aktualisieren per n8n

Das läuft wie beim paperless-companion und firefly-dashboard. `n8n/immich-pflege-update.json` ist ein fertiger n8n-Workflow, der das Tool per SSH auf dem Docker-Server aktualisiert. Ablauf:

1. Das Repository unter `~/immich-pflege` holen: beim ersten Lauf klonen (das ersetzt Schritt 2 oben), danach `git pull --rebase --autostash`.
2. `data/` anlegen und, wenn der SSH-Benutzer root ist, an UID 1000 übergeben.
3. `docker compose up -d --build`, alte Images aufräumen, auf den Healthcheck warten.

`data/` (Einstellungen, Regeln, Zwischenspeicher) und eine eventuelle `.env` sind nicht im Repository und bleiben bei jedem Update erhalten.

**Einrichten:**
1. In n8n **Import from File** → `n8n/immich-pflege-update.json` wählen.
2. Im Knoten **Update auf Docker-Host** SSH-Zugangsdaten anlegen: Host ist der Docker-Server (dieselben Zugangsdaten wie bei den anderen Anwendungen), dazu Benutzer und privater Schlüssel. Der Benutzer braucht Docker-Rechte (root oder Gruppe `docker`) sowie `git` auf dem Host.
3. Im Knoten **Webhook** Header-Auth-Zugangsdaten anlegen (Name `X-Update-Key`, langer Zufallswert) und den Workflow aktivieren.
4. Im Tool unter **⚙ Einstellungen → Updates** die Production-URL des Webhooks und den Zufallswert als Header-Wert eintragen und speichern.

**Update-Knopf:** Unter **⚙ Einstellungen** zeigt die Karte **Version** den laufenden Commit. Gibt es auf GitHub Neues, erscheinen dort die neuen Commits, am Zahnrad ein roter Punkt und der Knopf **▶ Jetzt aktualisieren**. Nach dem Klick ruft das Tool den n8n-Webhook auf (mit `typ`, `von`, `auf`). Die Seite lädt nach dem Neustart von selbst neu. GitHub wird höchstens einmal pro Stunde gefragt, abschalten lässt sich das unter „Updates“. Die Version schreibt der Docker-Build aus dem `.git`-Verzeichnis in `version.json`.

Alternativ startest du den Workflow per **Test workflow** oder, wenn aktiviert, täglich um 4 Uhr. Der Webhook antwortet sofort mit 202, weil sich das Tool beim Neustart beendet. Das Ergebnis steht in den n8n-Ausführungen. Ein Fehler bricht den Workflow mit der Ausgabe ab.

> Der Workflow aktualisiert den Branch `main`. Für ein privates Repository braucht der Host einen Deploy Key für `git pull` und das Tool unter „Updates“ ein GitHub-Token (Fine-grained, nur dieses Repository, *Contents: Read-only*). Das Vorgehen beschreibt die README des paperless-companion.

---

## Oberfläche

Vier Tabs (**Duplikate**, **Ohne Ort**, **Tags**, **⚙ Einstellungen**), unten eine Aktionsleiste mit Bestätigungsdialogen. Die Oberfläche ist fürs Handy gebaut, folgt hellem und dunklem Modus und lädt nichts aus dem Internet.

- **Duplikate:** Tippe auf ein Bild, damit es bleibt. Hake Gruppen an und wähle dann **Ins Prüf-Album** oder **Papierkorb**. Der Dialog zeigt vorher genau, was passiert. Für den Papierkorb muss zusätzlich ein Häkchen gesetzt werden.
- **Ohne Ort:** Das Zeitfenster ist einstellbar. Bilder mit 📍-Vorschlag antippen oder pro Tag **Alle**, dann **Ort übernehmen**.
- **Tags:** **+ Neue Regel** öffnet ein Formular mit allen Bedingungen. Pro Regel siehst du Treffer, schon getaggt und neu, mit Beispielbildern. Abhaken und **Tags anwenden**. **Beispiele** fügt Beispielregeln ausgeschaltet hinzu. **YAML** zeigt die Regeln als Text für Fortgeschrittene. Fehlerhafte Regeln werden beim Speichern mit verständlicher Meldung abgelehnt, und die alte Fassung bleibt erhalten.

## Regeln der Duplikat-Bearbeitung

**Behalten-Vorschlag.** Jede Stufe schlägt alle niedrigeren zusammen:

| Kriterium | Punkte |
|---|---|
| Favorit | 32 |
| in einem Album (das Prüf-Album zählt nicht) | 16 |
| hat GPS | 8 |
| Immich schlägt es vor | 4 |
| liegt in externer Bibliothek | 2 |
| höchste Auflösung der Gruppe | 1 |

Bei Gleichstand gewinnt die größere Auflösung, dann die größere Datei.

**Schutzregeln für den Papierkorb:**
- Medien aus **externen Bibliotheken kommen nie in den Papierkorb**, sondern stattdessen ins Prüf-Album.
- **Kopien eines anderen Benutzers** als dem der behaltenen Datei kommen nur ins Prüf-Album des Besitzers.
- Papierkorb heißt Immich-Papierkorb (`force: false`), also wiederherstellbar.

Das Album „Duplikat-Prüfung“ wird pro Benutzer angelegt, falls es fehlt.

## Regeln fürs Tagging

Regeln legst du in der Oberfläche an. Gespeichert werden sie als `data/regeln.yaml`, damit auch die Kommandozeile sie nutzt. Alle Bedingungen einer Regel müssen zutreffen:

| Feld | Bedeutung |
|---|---|
| Tags | ein oder mehrere Tags, verschachtelt mit „/“ (z. B. `Reisen/Italien/2024`) |
| von / bis | Aufnahmedatum (Ortszeit), jeweils einschließlich |
| Bibliothek | nur Uploads oder nur extern |
| Typ | Foto oder Video |
| Album, Person | exakter Name; mehrere = alle müssen passen |
| Kamerahersteller | exakt, Groß/klein egal (z. B. `SONY`, `Apple`) |
| Kameramodell, Dateiname, Pfad | reguläre Ausdrücke, Groß/klein egal |
| Für Benutzer | keiner angehakt = alle |
| aktiv | ausgeschaltete Regeln werden nicht angewendet |

Das YAML-Format ist in [`immich_pflege/regeln.example.yaml`](immich_pflege/regeln.example.yaml) beschrieben.

---

## Kommandozeile

Im Container heißt die Kommandozeile `pflege`:

```bash
docker exec -it immich-pflege pflege version          # Immich-Version + Schlüssel prüfen
# (die Kommandozeile nutzt dieselben Einstellungen und Regeln wie die Oberfläche)
docker exec -it immich-pflege pflege einlesen         # Bibliothek neu einlesen

# Duplikate
docker exec -it immich-pflege pflege duplikate                    # Vorschau (Tabelle)
docker exec -it immich-pflege pflege duplikate --json > dup.json
docker exec -it immich-pflege pflege duplikate --csv > dup.csv
docker exec -it immich-pflege pflege duplikate --ins-album        # alle offenen Gruppen
docker exec -it immich-pflege pflege duplikate --papierkorb       # mit Rückfrage
docker exec    immich-pflege pflege duplikate --papierkorb --ja   # ohne Rückfrage
docker exec -it immich-pflege pflege duplikate -g 3fa2c1d9e0b4 --behalten 3fa2c1d9e0b4=<medien-id> --papierkorb

# Fotos ohne Ort
docker exec -it immich-pflege pflege ohne-ort --stunden 3
docker exec -it immich-pflege pflege ohne-ort --datum 2024-07-16 --ort-uebernehmen
docker exec -it immich-pflege pflege ohne-ort --id <medien-id> --ort-uebernehmen

# Tags
docker exec -it immich-pflege pflege tags                         # Vorschau
docker exec -it immich-pflege pflege tags --regel "Italien-Urlaub 2024" --anwenden
```

Alle Befehle verstehen `--neu` (vorher neu einlesen) sowie `--json` und `--csv`.

---

## JSON-API (n8n)

Die API-Dokumentation zum Ausprobieren liegt unter `http://<server>:2222/api/docs`. Ist in den Einstellungen ein Login gesetzt, braucht jeder Aufruf Basic Auth mit denselben Zugangsdaten (die Anmeldeseite ist nur für den Browser). In n8n heißt das: *HTTP Request → Authentication: Generic → Basic Auth*.

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/healthz` | Lebenszeichen (ohne Anmeldung) |
| GET | `/api/status` | Version, Stand der Bibliothek, Schlüsselprüfung (`?server=false` ohne Immich-Abfrage) |
| POST | `/api/scan` | Neu einlesen. `{"wait": false}` startet im Hintergrund (202) |
| GET | `/api/duplicates` | Gruppen (`offset`, `limit`, `include_done`) |
| POST | `/api/duplicates/apply` | Aktion auf Gruppen |
| GET | `/api/no-location` | Medien ohne Ort nach Tagen (`max_hours`, `offset`, `limit`, `only_suggestions`) |
| POST | `/api/no-location/apply` | Ort übernehmen |
| GET | `/api/tags` | Regel-Vorschau (`rules=Name`, mehrfach möglich) |
| GET/PUT | `/api/rules` | Regeln lesen/speichern (`{"regeln": [...]}` oder `{"yaml": "..."}`) |
| GET/PUT | `/api/settings` | Einstellungen (Keys nur maskiert) |
| GET | `/api/version` | laufende Version und ob es auf GitHub Neues gibt |
| POST | `/api/version/update` | Update über den n8n-Webhook anstoßen |
| POST | `/api/settings/test` | Verbindung und Keys prüfen, ohne zu speichern |
| POST | `/api/tags/apply` | Tags anwenden |

Fehler kommen als `{"fehler": "…"}` zurück: 400 bei ungültiger Anfrage, 409 solange das Tool noch nicht eingerichtet ist, 422 bei fehlerhaften Regeln oder Einstellungen (mit `details`), 502 wenn Immich nicht erreichbar ist.

### Beispiele

```bash
B=http://immich-pflege:2222        # aus dem Docker-Netz, sonst http://<server>:2222
AUTH="-u frank:geheim"

curl $AUTH -X POST $B/api/scan
curl $AUTH "$B/api/duplicates?include_done=false&limit=0"

# Vorschau: was würde passieren?
curl $AUTH -X POST $B/api/duplicates/apply -H 'Content-Type: application/json' \
  -d '{"action":"papierkorb","all":true,"dry_run":true}'

# Alle offenen Gruppen ins Prüf-Album
curl $AUTH -X POST $B/api/duplicates/apply -H 'Content-Type: application/json' \
  -d '{"action":"album","all":true}'

# Papierkorb für bestimmte Gruppen, eine davon mit eigener Wahl – nur mit confirm
curl $AUTH -X POST $B/api/duplicates/apply -H 'Content-Type: application/json' \
  -d '{"action":"papierkorb","confirm":"PAPIERKORB",
       "groups":[{"id":"3fa2c1d9e0b4"},{"id":"9be04d11aa20","keep":"<medien-id>"}]}'

# Ort für alle Vorschläge eines Tages übernehmen
curl $AUTH "$B/api/no-location?only_suggestions=true&limit=0" \
  | jq '[.tage[] | select(.datum=="2024-07-16") | .medien[].id]' \
  | jq '{ids: .}' \
  | curl $AUTH -X POST $B/api/no-location/apply -H 'Content-Type: application/json' -d @-

curl $AUTH -X POST $B/api/tags/apply -H 'Content-Type: application/json' -d '{}'          # alle aktiven Regeln
curl $AUTH -X POST $B/api/tags/apply -H 'Content-Type: application/json' -d '{"rules":["Systemkamera"]}'
```

### n8n-Workflow (Idee: jede Nacht)

1. **Schedule Trigger**, täglich 03:00
2. **HTTP Request** `POST http://immich-pflege:2222/api/scan`, Body `{"wait": true}`, Timeout 600 s
3. **HTTP Request** `POST …/api/tags/apply`, Body `{}`
4. **HTTP Request** `POST …/api/duplicates/apply`, Body `{"action":"album","all":true}`
5. **IF** `{{$json.ergebnis.album > 0}}` → Benachrichtigung: „{{$json.ergebnis.album}} Duplikate liegen im Prüf-Album“

n8n erreicht das Tool unter `http://immich-pflege:2222`, wenn n8n im selben Docker-Netz hängt. Sonst geht es über `http://<server>:2222`.

---

## Entwicklung

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

Die Tests laufen gegen einen **Mock-Immich** (`tests/mock_immich.py`). Er bildet die genutzten Endpunkte im Antwortformat von v3.2.4 nach (Vorlage: `tests/fixtures/asset_response.json`), einschließlich Paging per `nextCursor` und `nextPage`. Zum Ausprobieren der Oberfläche ohne echtes Immich:

```bash
.venv/bin/uvicorn tests.mock_immich:demo_app --port 2283 &
# in der Oberfläche: Adresse http://127.0.0.1:2283, Keys key-frank / key-julia
DATA_DIR=./data .venv/bin/uvicorn immich_pflege.web.app:create_app --factory --port 2222
```

### Hinweise zur Immich-API (geprüft gegen die OpenAPI-Spezifikation v3.2.4)

- `PUT /api/assets` (Koordinaten setzen) ist in v3 als *deprecated* markiert, ist aber in 3.2.4 der einzige Weg dafür. Der Aufruf steckt an einer Stelle in `client.py` (`set_location`).
- In `POST /api/search/metadata` sind seit 3.2.0 die einfachen Filter (`isNotInAlbum`, `albumIds`, `personIds`, `tagIds`, `page`) *deprecated* zugunsten von `filter` und `cursor`. Sie funktionieren weiter. Das Tool liest `nextCursor` und fällt auf `nextPage` zurück.
- Bulk-Aufrufe gehen in Blöcken zu 500 IDs. Ist Immich nicht 3.x, erscheint eine Warnung.
- Assets mit `visibility` `hidden` (Live-Photo-Videos) oder `locked` sowie Medien im Papierkorb werden ignoriert. Über Partner-Freigaben sichtbare Medien werden nur ihrem Besitzer zugeordnet.
