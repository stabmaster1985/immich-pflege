# Tags

Tags an viele Fotos auf einmal vergeben – meist reicht ein Haken bei einem Vorschlag. **Tags werden nur ergänzt, nie entfernt**, und jede Übertragung lässt sich im Verlauf (Menü **Vorgemerkt**) **rückgängig** machen.

## Vorschläge

Das Tool schlägt aus euren Daten Tags vor und zählt genau, wie viele Medien noch keinen haben:

| Vorschlag | Tag | Wann |
|---|---|---|
| 🌍 Reisen nach … | `Reisen/<Land>` | Fotos mit Ort in einem Land, ab 10 Fotos – euer Heimatland (das häufigste) nicht |
| 📷 Kamera … | `Kamera/<Modell>` | ab 30 Medien mit dieser Kamera |
| 📥 Screenshots | `Quelle/Screenshot` | Bildschirmfotos |
| 📥 WhatsApp-Bilder | `Quelle/WhatsApp` | Dateinamen wie `IMG-20240718-WA0003` |

**Vormerken** übernimmt einen Vorschlag, **Vormerken (n)** unten alle. **Kein Interesse** blendet ihn dauerhaft aus (unter „ausgeblendete“ zurückholbar). Kommen später neue passende Fotos dazu, erscheint der Vorschlag wieder mit der neuen Anzahl.

## Archivieren statt löschen

Screenshots, WhatsApp-Bilder, Quittungen oder Dokumente stören beim Durchblättern, sollen aber nicht weg. Dafür gibt es **Archivieren**: Die Medien verschwinden aus der Zeitleiste, bleiben aber in der Suche, in Alben und im Archiv von Immich. Den Knopf gibt es bei den Vorschlägen **Screenshots** und **WhatsApp-Bilder** und bei der **KI-Suche**, z. B. für alle Treffer zu „Quittung“. **Rückgängig** holt sie zurück in die Zeitleiste.

## Mit der KI-Suche finden

Immich versteht Bildinhalte (maschinelles Lernen, „Smart Search“). Das Tool nutzt diese Suche für Begriffe wie **Hund, Katze, Strand, Berge, Schnee, Sonnenuntergang, Feuerwerk, Geburtstag, Weihnachten, Essen, Auto, Quittung, Dokument** – oder einen eigenen Begriff (Englisch funktioniert mit Immichs Standardmodell am besten, z. B. „dog on the beach“).

Die KI-Suche liefert **keine feste Trefferzahl**, sondern alles nach Passgenauigkeit sortiert: oben die besten, weiter unten immer unpassender. Deshalb:

1. Begriff antippen. Es erscheinen die passendsten Treffer von euch beiden (je Benutzer bis zu 120), schon getaggte und vorgemerkte nicht.
2. Auf das **erste Bild tippen, das nicht mehr passt**. Alles davor wird grün, der Rest grau.
3. Tag prüfen (Vorschlag z. B. `Tiere/Hund`) und unten **als „…“ vormerken**.
4. Danach erscheinen die nächsten Treffer – so lässt sich Seite für Seite weitermachen.

Voraussetzung: In Immich ist das maschinelle Lernen (Smart Search) aktiv.

## Erweitert: eigene Regeln

Für Sonderfälle gibt es weiterhin eigene Regeln (ganz unten aufklappen).

### Regeln anlegen

**+ Neue Regel** öffnet ein Formular:

| Feld | Bedeutung |
|---|---|
| Tags | ein oder mehrere Tags, mit Komma getrennt, Ebenen mit „/“ (z. B. `Reisen/Italien/2024`) |
| Aufnahme von / bis | Aufnahmedatum (Ortszeit), jeweils einschließlich |
| Bibliothek | nur Uploads oder nur extern |
| Typ | Foto oder Video |
| Album, Person | exakter Name (Groß/klein egal); mehrere mit Komma = alle müssen passen |
| Kamerahersteller | exakt, Groß/klein egal (z. B. `SONY`, `Apple`) |
| Kameramodell, Dateiname, Pfad | Muster (reguläre Ausdrücke), Groß/klein egal |
| Für Benutzer | keiner angehakt = alle |
| aktiv | ausgeschaltete Regeln werden nicht angewendet |

**Land, Region, Ort** prüfen Immichs Ortsdaten (z. B. Land „Italien“, Region „Toskana“, Ort „Siena“). Mehrere mit Komma heißt: eines davon. Nur Fotos mit GPS haben einen Ort, deshalb lohnt es sich, erst unter „Ohne Ort“ zu verorten.

Alle Bedingungen einer Regel müssen zutreffen. Eine Regel ohne Bedingung ist nicht erlaubt, sonst würde die ganze Bibliothek getaggt.

### Vorschau und Vormerken

Pro Regel siehst du **Treffer**, **schon getaggt** und **neu**, dazu Beispielbilder der neuen Treffer. Regeln anhaken und **Tags vormerken**. Übertragen wird unter **Vorgemerkt**. Fehlende Tags legt das Tool in Immich an, getrennt pro Benutzer.

### Für Fortgeschrittene

- **YAML** zeigt alle Regeln als Text. Beim Speichern wird geprüft, und fehlerhafte Regeln werden mit verständlicher Meldung abgelehnt. Die alte Fassung bleibt dann erhalten.
- **Beispiele** fügt Beispielregeln ausgeschaltet hinzu.
- Gespeichert wird in `data/regeln.yaml`, auch die Kommandozeile `pflege tags` nutzt diese Datei.
