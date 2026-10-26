# immich-pflege

Wartungstool für einen selbst gehosteten **Immich-Server (v3.x, getestet gegen die API von 3.2.4, geprüft mit 3.3.1)**: als Docker-Container mit mobiler Web-Oberfläche, Kommandozeile `pflege` und JSON-API für n8n.

| Funktion | Was passiert |
|---|---|
| **Duplikate** | Findet doppelte Medien über beide Benutzer und über Uploads und externe Bibliotheken hinweg: per Prüfsumme, Dateiname + Aufnahmezeit, Bild-Fingerabdruck (z. B. WhatsApp-Kopien) und Immichs eigener Erkennung. Jede Gruppe hat eine Art (identisch, sehr wahrscheinlich, ähnlich) und einen Behalten-Vorschlag. Nicht behaltene Kopien kommen ins Album „Duplikat-Prüfung“ oder in den Papierkorb. |
| **Ohne Ort** | Medien ohne GPS bekommen einen Ortsvorschlag mit Sicherheit (sicher, wahrscheinlich, unsicher) aus den GPS-Fotos beider Benutzer, zusammengefasst nach Ort und Serie. Für den Rest gibt es die Ortssuche von Immich. Screenshots werden ausgeblendet. |
| **Aufräumen** | Speicherfresser (große Videos, Bildschirmaufnahmen, doppelte Live-Photo-Videos), Serienbilder (das schärfste bleibt oder alles stapeln), **Stapeln aus eigenen Alben**, **Alben aufräumen** (doppelte von beiden Benutzern zusammenführen, leere/Mini-Alben, bessere Titelbilder), unscharfe und dunkle Fotos, falsche Aufnahmezeiten samt Kamera-Zeitversatz, verwaiste Dateien der externen Bibliothek, Papierkorb-Übersicht. |
| **Alben** | Erkennt Reisen (weg von zu Hause, beide Benutzer zusammen) und schlägt Alben vor. Vorher wird gegen alle vorhandenen Alben beider Benutzer abgeglichen: schon vorhanden, ergänzen oder neu. Neue Alben werden mit dem anderen Benutzer geteilt. Außerdem **Alben aus Ordnern** der externen Bibliothek, auf Wunsch automatisch aktuell gehalten. |
| **Tags** | Fertige Vorschläge zum Abhaken (Länder, Kameras, Screenshots, WhatsApp) und Suche mit Immichs KI (Hund, Strand, Quittung …): erstes unpassendes Bild antippen, alles davor wird getaggt. Eigene Regeln für Sonderfälle. Tags werden nur ergänzt, nie entfernt. **Archivieren** nimmt Screenshots, WhatsApp-Bilder, Quittungen u. Ä. aus der Zeitleiste, ohne zu löschen. |
| **Übersicht** | Kennzahlen je Benutzer, offene Aufgaben, Aufnahmen je Jahr, Erledigtes je Monat. Auf Wunsch wöchentlich als Nachricht per ntfy oder Telegram, dazu täglich „An diesem Tag“. |

Alles startet als **Vorschau**. In der Oberfläche wird Bestätigtes zuerst nur **vorgemerkt** und verschwindet aus der Übersicht. Unter **Vorgemerkt** prüfst du alles noch einmal und überträgst es dann per Klick an Immich. Jede Übertragung steht im **Verlauf** und lässt sich dort rückgängig machen (außer Orten, siehe Hilfe).

**Alle Einstellungen und Regeln werden in der Oberfläche gemacht.** Dateien musst du nicht bearbeiten.

---

## Einrichtung

### 1. API-Keys in Immich anlegen

Für **jeden** Benutzer (hier frank und julia) einzeln:

1. In Immich als dieser Benutzer anmelden
2. Avatar oben rechts → **Kontoeinstellungen** → **API-Schlüssel** → **Neuer API-Schlüssel**
3. Name z. B. `immich-pflege`. Berechtigungen: am einfachsten **Alle**. Wer die Rechte einschränken will, braucht mindestens:
   `asset.read`, `asset.view`, `asset.update`, `asset.delete`, `album.read`, `album.create`, `album.update`, `album.delete`, `albumAsset.create`, `albumAsset.delete`, `albumUser.create`, `albumUser.delete`, `duplicate.read`, `person.read`, `stack.read`, `stack.create`, `stack.delete`, `tag.read`, `tag.create`, `tag.asset`, `user.read`
4. Den Schlüssel kopieren, er wird nur einmal angezeigt.

> Jeder Benutzer kann nur seine eigenen Medien ändern. Deshalb braucht das Tool je Benutzer einen Schlüssel und verwendet automatisch den des Besitzers.

### 2. Container starten

Das Tool läuft auf dem Docker-Server, zum Beispiel neben paperless-companion und firefly-dashboard. Immich kann auf einem eigenen LXC oder einer eigenen VM laufen, das Tool spricht es über das Netzwerk an (Port 2283). **n8n ist nicht nötig.** Einmalig als root auf dem Docker-Server:

```bash
git clone https://github.com/stabmaster1985/immich-pflege.git
sudo ./immich-pflege/installieren.sh
```

Das Skript legt `data/` für den Container (Benutzer 1000) an, baut und startet den Container, wartet bis er läuft und richtet den [Update-Dienst](#updates-per-klick-update-dienst) ein. Danach kommen Updates per Klick aus der App. Erneut ausgeführt repariert es eine Installation.

Von Hand geht es so:

```bash
cd immich-pflege
mkdir -p data && sudo chown 1000:1000 data   # Container läuft als Benutzer 1000, nicht als root
docker compose up -d --build
sudo ./updater/install.sh                    # optional: Updates per Klick
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

Beim ersten Öffnen liest das Tool die Bibliothek ein, was bei großen Bibliotheken ein bis zwei Minuten dauert. Danach liegt sie zwischengespeichert in `data/bibliothek.json`. **Neu einlesen** gibt es als Button, per `pflege einlesen` oder über `POST /api/scan`. In der Oberfläche läuft es im Hintergrund (`{"wait": false}`), der Fortschritt steht in `GET /api/status` unter `einlesen_laeuft`, `fortschritt` und `alben_laeuft`. Listen, Vormerken und Übertragen warten nicht darauf.

**Automatisch einlesen:** Neue Fotos erscheinen erst nach dem Einlesen. Unter **⚙ Einstellungen → Automatisch einlesen** stellst du ein, ob das Tool das selbst erledigt: **täglich** zu einer Uhrzeit oder **alle X Stunden**. Die Zeitzone ist Europe/Berlin, wählbar, und berücksichtigt Sommer- und Winterzeit. War der Container zum geplanten Zeitpunkt aus, holt das Tool das Einlesen nach. Das nächste Einlesen steht in den Einstellungen und oben in der Statuszeile („auto 03:00“). Ab Werk ist es aus.

Logs: `docker logs immich-pflege` und `data/pflege.log`.

> Von außerhalb des Heimnetzes nur über einen Reverse-Proxy mit HTTPS und mit gesetztem Login. Die API-Keys verlassen nie den Container: Vorschaubilder reicht das Backend durch.

### Optional: Einstellungen per `.env` festlegen

Wer lieber mit Dateien arbeitet, kann die meisten Werte auch in einer `.env` vorgeben (`IMMICH_URL`, `REVIEW_ALBUM`, `LOCATION_MAX_HOURS`, `LOCATION_INCLUDE_EXTERNAL`, `WEB_USER`/`WEB_PASSWORD`, `UPDATE_*`). API-Keys (`IMMICH_KEY_<NAME>`) gehen per `docker-compose.override.yml`, siehe `.env.example`. Werte aus der `.env` haben Vorrang und erscheinen in der Oberfläche ausgegraut.

### Updates per Klick (Update-Dienst)

Für Updates gibt es einen kleinen Dienst auf dem Docker-Server (systemd, im Ordner `updater/`). Er bereitet neue Versionen stündlich im Hintergrund vor: holen und Image fertig bauen, die laufende Version bleibt unberührt. In der App siehst du unter **⚙ Einstellungen → Version** die Änderungen und schaltest per Klick um. Das dauert Sekunden, und startet die neue Version nicht sauber, geht es automatisch zurück auf die alte.

```bash
cd ~/immich-pflege
sudo ./updater/install.sh            # einmalig; macht installieren.sh mit
sudo ./updater/install.sh --entfernen
```

Bringt ein Update eine neue Fassung des Dienstes mit, übernimmt er sie beim Umschalten selbst. Der Container bekommt dafür **keine** Rechte am Docker-Host. App und Dienst tauschen nur Dateien in `data/updater/` aus (Auftrag `request.json`, Stand `status.json`, Protokoll `update.log`).

### Optional: Aktualisieren per n8n

Nur nötig, wenn auf dem Server kein systemd läuft oder du es wie beim paperless-companion und firefly-dashboard halten willst. `n8n/immich-pflege-update.json` ist ein fertiger n8n-Workflow, der das Tool per SSH auf dem Docker-Server aktualisiert. Ablauf:

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

## Oberfläche und Hilfe

Das Menü ist nach Aufgaben sortiert. Auf dem Handy liegt es unten, am großen Bildschirm links, die Unterpunkte stehen dort direkt darunter bzw. auf dem Handy oben zum Wischen. Jeder Punkt zeigt, wie viel offen ist:

| Menü | Unterpunkte |
|---|---|
| **Start** | Kennzahlen und „Zu tun“ mit allen offenen Punkten zum Antippen |
| **Aufräumen** | Duplikate, Serienbilder, Speicherfresser, Unscharf & dunkel, Verwaiste Dateien, Papierkorb |
| **Ordnen** | Ohne Ort, Falsche Zeit, Tags, Stapeln |
| **Alben** | Reisen, Ordner, Alben aufräumen |
| **Vorgemerkt** | Vormerkliste und Verlauf mit Rückgängig |

Oben rechts: **Einlesen** und **⚙ Einstellungen**. **Prüf-Ansicht:** Überall, wo viele Bilder auf einmal vorgemerkt werden, öffnet **Prüfen** alle betroffenen Bilder als dichtes Raster, auch Tausende. Die Bilder sind nach Monat, Tag, Ort oder Passgenauigkeit gruppiert. Du wählst einzelne Bilder oder ganze Gruppen ab, und vorgemerkt wird genau die Auswahl. Das gilt für Tag-Vorschläge, eigene Regeln, KI-Suche, Archivieren, sichere Orte, Aufräumen, Falsche Zeit, Reisen und Ordner-Alben (abgewählte Dateien bleiben auch beim automatischen Abgleich draußen). **Großansicht:** Kleine Vorschaubilder antippen, bei großen Kacheln auf **Groß**, in der KI-Suche auf ⤢. Dann wischen oder mit den Pfeiltasten durch die ganze Gruppe blättern. Jeder Punkt hat eine eigene Adresse (z. B. `…:2222/#serien`), der Zurück-Knopf funktioniert. Unten erscheint bei Bedarf eine Aktionsleiste mit Bestätigungsdialogen. Die Oberfläche ist fürs Handy gebaut, folgt hellem und dunklem Modus und lädt nichts aus dem Internet. Sie lässt sich **als App auf den Startbildschirm legen** (Safari: „Zum Home-Bildschirm“, Chrome: „App installieren“ – als eigenes Fenster nur über HTTPS).

**Jede Seite hat oben ein „?“** mit einer ausführlichen Erklärung: wie Treffer und Vorschläge entstehen, nach welchen Kriterien bewertet wird und wo die Grenzen liegen. Dieselben Texte liegen im Repository:

| Thema | Datei |
|---|---|
| Duplikate: Quellen, Arten, Behalten-Vorschlag, Schutzregeln, Bild-Fingerabdruck | [`immich_pflege/hilfe/duplikate.md`](immich_pflege/hilfe/duplikate.md) |
| Fotos ohne Ort: Kriterien und Sicherheit, Serien, Ortssuche, Fehlerquellen | [`immich_pflege/hilfe/ohne-ort.md`](immich_pflege/hilfe/ohne-ort.md) |
| Aufräumen: Speicherfresser, Serienbilder, unscharf/dunkel, falsche Zeit, Papierkorb | [`immich_pflege/hilfe/aufraeumen.md`](immich_pflege/hilfe/aufraeumen.md) |
| Albumvorschläge: Reise-Erkennung, Abgleich mit vorhandenen Alben, Teilen | [`immich_pflege/hilfe/alben.md`](immich_pflege/hilfe/alben.md) |
| Tags: Vorschläge, KI-Suche, eigene Regeln | [`immich_pflege/hilfe/tags.md`](immich_pflege/hilfe/tags.md) |
| Vorgemerkt, Verlauf und Rückgängig | [`immich_pflege/hilfe/vorgemerkt.md`](immich_pflege/hilfe/vorgemerkt.md) |
| Einstellungen: Immich, automatisch einlesen, Zugang, als App installieren, Updates | [`immich_pflege/hilfe/einstellungen.md`](immich_pflege/hilfe/einstellungen.md) |

Das YAML-Format der Regeln ist in [`immich_pflege/regeln.example.yaml`](immich_pflege/regeln.example.yaml) beschrieben.

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
docker exec    immich-pflege pflege duplikate --art identisch --papierkorb --ja
docker exec -it immich-pflege pflege duplikate --kein-duplikat 3fa2c1d9e0b4
docker exec -it immich-pflege pflege fingerabdruck                # Bild-Fingerabdrücke berechnen
docker exec -it immich-pflege pflege duplikate --papierkorb       # mit Rückfrage
docker exec    immich-pflege pflege duplikate --papierkorb --ja   # ohne Rückfrage
docker exec -it immich-pflege pflege duplikate -g 3fa2c1d9e0b4 --behalten 3fa2c1d9e0b4=<medien-id> --papierkorb

# Fotos ohne Ort
docker exec -it immich-pflege pflege ohne-ort --stunden 3
docker exec -it immich-pflege pflege ohne-ort --orte                               # Übersicht nach Ort mit Mengen
docker exec -it immich-pflege pflege ohne-ort --ort "Siena, Italien" --ort-uebernehmen
docker exec -it immich-pflege pflege ohne-ort --ort ohne --monat 2023-04
docker exec -it immich-pflege pflege ohne-ort --sicherheit hoch --ort-uebernehmen   # alle sicheren
docker exec -it immich-pflege pflege ohne-ort --serie <serien-id> --ort-uebernehmen
docker exec -it immich-pflege pflege ohne-ort --datum 2024-07-16 --ort-uebernehmen
docker exec -it immich-pflege pflege ohne-ort --id <medien-id> --ort-uebernehmen

# Tags
docker exec -it immich-pflege pflege alben --alle                 # Albumvorschläge (mit erledigten)
docker exec -it immich-pflege pflege alben --anlegen r1a2b3c4d5e6  # Album anlegen bzw. ergänzen
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
| POST | `/api/scan` | Einlesen, normalerweise nur Änderungen. `{"full": true}` liest alles, `{"wait": false}` startet im Hintergrund (202) |
| GET | `/api/duplicates` | Gruppen mit Mengen je Art und Monat. Parameter: `art`, `monat`, `benutzeruebergreifend`, `ignoriert`, `offset`, `limit`, `include_done` |
| POST | `/api/duplicates/apply` | Aktion auf Gruppen (`groups`) oder alle offenen der Auswahl (`all` + `art`/`monat`/`benutzeruebergreifend`) |
| POST | `/api/duplicates/ignore` | „Kein Duplikat“: `{"groups": [...]}`, mit `"undo": true` wieder aufnehmen |
| POST | `/api/fingerprints/start` | Fehlende Bild-Fingerabdrücke im Hintergrund berechnen |
| GET | `/api/no-location` | Medien ohne Ort als Serien mit Mengen je Ort (`orte`) und Monat (`monate`). Parameter: `ort`, `monat`, `overview=true` (nur die Mengen), `max_hours`, `offset`, `limit`, `only_suggestions`, `min_confidence` |
| POST | `/api/no-location/apply` | Ort übernehmen: `ids`, `series`, `ort`/`monat` (alle Serien eines Ortes oder Monats), `min_confidence` (`hoch`/`mittel`/`niedrig`), optional `place` `{breite, laenge, name}` |
| GET | `/api/places?q=Siena` | Ortssuche über Immich |
| GET | `/api/album-suggestions` | Reisen mit Albumvorschlag. Parameter: `status` (`neu`, `ergaenzen`, `vorhanden`; ohne = offene), `jahr`, `ignoriert`, `offset`, `limit` |
| GET | `/api/album-suggestions/{id}/media` | Alle Medien einer Reise, `im_album` bezogen auf `album` (ohne = Vorschlag, leer = neues Album) |
| GET | `/api/folder-albums` | Ordner der externen Bibliothek als Albumvorschlag: `status` (`neu`, `ergaenzen`, `abgeglichen`, `vorhanden`) |
| POST | `/api/staged/folder-albums` | vormerken: `{"ordner": [{"id", "name"?, "album"?, "sync", "ohne"?}]}`; `sync` hält das Album nach jedem Einlesen aktuell, `ohne` bleibt dauerhaft draußen |
| POST | `/api/album-suggestions/apply` | Direkt anlegen/ergänzen: `{"trips": [{"id": "…"}]}`, optional je Reise `album` (Album-ID, `null` = neues Album) `name` und `ohne` (abgewählte Medien) |
| POST | `/api/album-suggestions/ignore` | „Kein Album“: `{"trips": [...]}`, mit `"undo": true` wieder aufnehmen |
| GET | `/api/tags` | Regel-Vorschau (`rules=Name`, mehrfach möglich) |
| GET | `/api/help/{thema}` | Hilfetext als Markdown (`duplikate`, `ohne-ort`, `aufraeumen`, `alben`, `tags`, `vorgemerkt`, `einstellungen`) |
| GET/PUT | `/api/rules` | Regeln lesen/speichern (`{"regeln": [...]}` oder `{"yaml": "..."}`) |
| GET/PUT | `/api/settings` | Einstellungen (Keys nur maskiert) |
| GET | `/api/version` | laufende Version und ob es auf GitHub Neues gibt |
| GET | `/api/updater` | Stand des Update-Dienstes (vorbereitet, Änderungen, Fehler) |
| POST | `/api/updater/prepare` | Update-Dienst: neue Version vorbereiten |
| POST | `/api/updater/apply` | Update-Dienst: vorbereitete Version starten, `{"bereit": "<commit>"}` |
| POST | `/api/version/update` | Update über den n8n-Webhook anstoßen |
| POST | `/api/settings/test` | Verbindung und Keys prüfen, ohne zu speichern |
| POST | `/api/tags/apply` | Tags anwenden |
| GET | `/api/staged` | Vormerkliste mit Einträgen und Summen |
| POST | `/api/staged/duplicates` | Duplikat-Aktion vormerken (Felder wie `/api/duplicates/apply`) |
| POST | `/api/staged/no-location` | Orte vormerken (Felder wie `/api/no-location/apply`, dazu `label`) |
| POST | `/api/staged/albums` | Alben vormerken (Felder wie `/api/album-suggestions/apply`) |
| GET | `/api/cleanup` | Aufräumen: `art` (`speicher`, `serien`, `qualitaet`, `verwaist`), `kategorie`, `ignoriert`, `offset`, `limit` |
| POST | `/api/staged/cleanup` | Aufräumen vormerken: `action` (`album`/`papierkorb`, bei Serien auch `stapel`), `ids` oder `kategorie`, optional `keep` {Eintrag: Medium} |
| POST | `/api/cleanup/keep` | „Behalten“/„Passt so“: `{"ids": [...]}`, mit `"undo": true` zurück |
| GET | `/api/suggestions` | Tag-Vorschläge aus den Daten (`ausgeblendet=true` für ausgeblendete) und Begriffe der KI-Suche |
| GET | `/api/suggestions/smart` | KI-Suche: `begriff` (aus der Liste) oder `suche` (eigener Text), optional `tag`, `anzahl` (Treffer je Benutzer, bis 1000; Standard 120) |
| POST | `/api/staged/suggestions`, `/api/staged/smart` | Vorschläge (`ids`) bzw. KI-Treffer (`tag`, `ids`) vormerken |
| POST | `/api/staged/archive` | Archivieren vormerken: `vorschlag` (ID) oder `ids`, optional `label` |
| GET | `/api/suggestions/{id}/media` | alle Treffer eines Vorschlags zum Prüfen (`aktion`: `tag` oder `archiv`), neueste zuerst |
| POST | `/api/staged/suggestions/{id}/auswahl` | Vorschlag ohne abgewählte Medien vormerken: `ohne` (IDs), `aktion` (`tag`/`archiv`) |
| POST | `/api/suggestions/hide` | „Kein Interesse“: `ids`, mit `undo` zurück |
| GET | `/api/album-care` | Alben aufräumen: doppelt, fast gleich, leer, mini, schlechtes Titelbild |
| POST | `/api/staged/album-care` | vormerken: `id`, `aktion` (`zusammenfuehren`/`loeschen`/`titelbild`), `ziel`, `loeschen`, `titelbild` (eigene Wahl) |
| GET | `/api/stacks` | Stapel-Vorschläge: `album`, `ganz` (ganzes Album je Benutzer) |
| POST | `/api/staged/stacks` | Stapel vormerken: `album`, `ids` (ohne = alle), `ganz`, `oben` {Vorschlag: Medium}, `aus_album` |
| GET | `/api/timefix` | Falsche Aufnahmezeiten: `art` (`zeitversatz`, `dateiname`, `zukunft`, `standard`) |
| GET | `/api/tags/rules/{name}/media` | alle neuen Treffer einer eigenen Regel |
| POST | `/api/staged/tags/{name}/auswahl` | eigene Regel ohne abgewählte Medien vormerken: `ohne` |
| GET | `/api/no-location/origin-media` | alle Medien ohne Ort einer `herkunft` (`kamera`, `messenger`, `ohne_kamera`, `screenshot`) |
| GET | `/api/no-location/hidden` | ausgeblendete Medien ohne Ort mit `grund` (`screenshot` oder `kein_ort`) |
| POST | `/api/no-location/no-place` | „kein Ort nötig“: `ids`; mit `undo` wieder einblenden (auch erkannte Screenshots) |
| GET | `/api/no-location/media` | alle Medien mit Ortsvorschlag ab `min_confidence` (Standard `hoch`), mit `ort_neu` |
| GET | `/api/album-check` | liegt `asset` in `album`? Fragt Immich direkt (`GET /albums?assetId=`), liest das Album bei Abweichung neu |
| GET | `/api/folder-albums/{id}/media` | Dateien eines Ordners, die noch nicht im Album (`album`) liegen |
| GET | `/api/timefix/{id}/media` | alle Medien eines Eintrags (die Liste enthält nur eine Auswahl) |
| POST | `/api/staged/timefix` | Zeitkorrektur vormerken: `{"eintraege": [{"id", "minuten"? , "ziel"?, "ohne"?}]}` – `ohne`: Medien, die nicht verschoben werden |
| GET | `/api/trash` | Papierkorb beider Benutzer |
| POST | `/api/trash/restore` | Wiederherstellen: `{"ids": [...]}`, ohne = alles |
| GET | `/api/dashboard` | Kennzahlen der Übersicht |
| GET/POST | `/api/report`, `/api/report/test` | Wochenbericht-Text bzw. Testnachricht |
| POST | `/api/memories/test` | „An diesem Tag“ für heute sofort senden |
| GET | `/api/history` | Verlauf der Übertragungen |
| POST | `/api/history/{id}/undo` | Übertragung rückgängig machen |
| POST | `/api/staged/tags` | Regeln vormerken: `{"rules": [...]}` |
| DELETE | `/api/staged/{id}` | Eintrag zurücknehmen |
| POST | `/api/staged/apply` | Vorgemerktes übertragen: `ids` (ohne = alle), bei Papierkorb `confirm: "PAPIERKORB"` |

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

# Alle sicheren Ortsvorschläge übernehmen (z. B. nachts per n8n)
curl $AUTH -X POST $B/api/no-location/apply -H 'Content-Type: application/json' -d '{"min_confidence":"hoch"}'

# Eine Serie von Hand verorten
curl $AUTH "$B/api/places?q=Siena"
curl $AUTH -X POST $B/api/no-location/apply -H 'Content-Type: application/json' \
  -d '{"series":["<serien-id>"],"place":{"breite":43.3188,"laenge":11.3308,"name":"Siena"}}'

curl $AUTH -X POST $B/api/tags/apply -H 'Content-Type: application/json' -d '{}'          # alle aktiven Regeln
curl $AUTH -X POST $B/api/tags/apply -H 'Content-Type: application/json' -d '{"rules":["Systemkamera"]}'
```

### Automatisch ohne n8n

Was früher ein nächtlicher n8n-Workflow erledigt hat, kann das Tool selbst: Unter **⚙ Einstellungen → Automatisch einlesen** täglich einlesen lassen und **„Danach sichere Ortsvorschläge vormerken“** anhaken. Morgens liegen die sicheren Orte unter **Vorgemerkt** und warten auf deinen Blick.

Auch der **Wochenbericht** braucht kein n8n: unter ⚙ Einstellungen → Wochenbericht ntfy oder Telegram eintragen.

### Optional: n8n-Workflow (Idee: jede Nacht)

Die API führt direkt aus, ohne Vormerkliste. Beispiel:

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

### Hinweise zur Immich-API (geprüft gegen die OpenAPI-Spezifikation v3.2.4 und v3.3.1)

- `PUT /api/assets` (Koordinaten setzen) ist in v3 als *deprecated* markiert, ist aber in 3.2.4 und 3.3.1 der einzige Weg dafür. Der Aufruf steckt an einer Stelle in `client.py` (`set_location`).
- In `POST /api/search/metadata` sind seit 3.2.0 die einfachen Filter (`isNotInAlbum`, `albumIds`, `personIds`, `tagIds`, `page`) *deprecated* zugunsten von `filter` und `cursor`. Sie funktionieren weiter. Das Tool liest `nextCursor` und fällt auf `nextPage` zurück.
- **Albuminhalte:** `POST /api/search/metadata` mit `albumIds` liefert jedem Benutzer nur seine eigenen Medien, und `GET /api/albums/{id}` enthält seit 3.x keine Medienliste mehr. Findet die Suche weniger, als das Album zählt (`assetCount`), etwa Julias Fotos in Franks nicht geteiltem Album, liest das Tool das Album über `GET /api/timeline/buckets` und `/bucket` mit `albumId` nach. So zeigt auch Immich ein Album an, mit allen Besitzern.
- Titelbilder setzt das Tool mit `PATCH /api/albums/{id}` (`albumThumbnailAssetId`), immer mit dem Key des Album-Besitzers.
- Bulk-Aufrufe gehen in Blöcken zu 500 IDs. Ist Immich nicht 3.x, erscheint eine Warnung.
- Assets mit `visibility` `hidden` (Live-Photo-Videos) oder `locked` sowie Medien im Papierkorb werden ignoriert. Über Partner-Freigaben sichtbare Medien werden nur ihrem Besitzer zugeordnet.
