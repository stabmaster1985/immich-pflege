# Massen-Tagging

Regeln vergeben Tags an viele Fotos auf einmal. **Tags werden nur ergänzt, nie entfernt.**

## Regeln anlegen

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

Alle Bedingungen einer Regel müssen zutreffen. Eine Regel ohne Bedingung ist nicht erlaubt, sonst würde die ganze Bibliothek getaggt.

## Vorschau und Vormerken

Pro Regel siehst du **Treffer**, **schon getaggt** und **neu**, dazu Beispielbilder der neuen Treffer. Regeln anhaken und **Tags vormerken**. Übertragen wird unter **✓ Vorgemerkt**. Fehlende Tags legt das Tool in Immich an, getrennt pro Benutzer.

## Für Fortgeschrittene

- **YAML** zeigt alle Regeln als Text. Beim Speichern wird geprüft, und fehlerhafte Regeln werden mit verständlicher Meldung abgelehnt. Die alte Fassung bleibt dann erhalten.
- **Beispiele** fügt Beispielregeln ausgeschaltet hinzu.
- Gespeichert wird in `data/regeln.yaml`, auch die Kommandozeile `pflege tags` nutzt diese Datei.
