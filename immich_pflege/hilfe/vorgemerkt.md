# Vorgemerkt

In der Oberfläche geht keine Änderung sofort an Immich. Was du unter **Aufräumen**, **Ordnen** oder **Alben** bestätigst, wird erst **vorgemerkt**. Gesammelt wird es im Menüpunkt **Vorgemerkt**, die Zahl daran zeigt, wie viel wartet.

## Ablauf

1. **Vormerken:** Wie gewohnt auswählen und bestätigen. Das Vorgemerkte verschwindet sofort aus der Übersicht, damit du mit dem Rest weitermachen kannst. In Immich ändert sich noch nichts.
2. **Prüfen:** Die Einträge sind **nach Art gruppiert** (Duplikate, Aufräumen, Archivieren, Orte, Alben, Tags …), jede Gruppe mit eigener Farbe und **einklappbar**. Im Kopf einer Gruppe stehen Anzahl, Medien und ggf. 🗑 Papierkorb, dazu **Übertragen (n)** und **Zurücknehmen** nur für diese Gruppe. Oben führt jeder Chip direkt zu seiner Gruppe, **Alle auf-/zuklappen** schaltet alle um. Der Klappzustand bleibt gespeichert, bei vielen Einträgen sind die Gruppen anfangs zu. Jeder Eintrag zeigt Vorschaubilder:
   - Duplikate: grün umrandet ist das Bild, das bleibt. Darunter steht, wohin die Kopien gehen (Prüf-Album oder Papierkorb).
   - Orte: unter jedem Bild steht der neue Ort.
   - Alben: neues Album oder welches ergänzt wird, mit wem es geteilt wird, Beispielbilder.
   - Tags: Regel, Tags und Beispielbilder.
3. **Ansehen** am Eintrag öffnet **alle** betroffenen Medien in der Prüf-Ansicht (nicht nur die Beispielbilder). Bilder antippen nimmt sie aus dem Eintrag, unter „groß ansehen“ öffnest du sie in voller Größe. **… behalten, Rest herausnehmen** speichert das. Die herausgenommenen Medien kommen zurück in ihre Übersicht (bei Reisen gelten sie wie dort abgewählte als „gehört nicht zur Reise“). Ist alles abgewählt, fällt der ganze Eintrag weg. Bei Tag-Regeln wird aus der Regel dabei eine feste Auswahl.
4. **Zurücknehmen** (↩ am Eintrag) legt einen Eintrag wieder in die Übersicht zurück. Er wird dort neu bewertet.
5. **Übertragen** führt einen einzelnen Eintrag in Immich aus, **Alle übertragen** in der Aktionsleiste alle auf einmal. Geht etwas in den Papierkorb, musst du das vorher ausdrücklich bestätigen.

Erfolgreich Übertragenes verschwindet aus der Liste. Schlägt ein Eintrag fehl, z. B. weil Immich nicht erreichbar war, bleibt er mit der Fehlermeldung stehen und kann später erneut übertragen werden.

## Gut zu wissen

- Die Liste liegt in `data/vorgemerkt.json`. Sie übersteht Neustarts und Updates.
- Beim Übertragen gelten dieselben Schutzregeln wie sonst: externe Medien und Kopien des anderen Benutzers kommen nie in den Papierkorb.
- Wurde ein Medium inzwischen in Immich gelöscht, wird es übersprungen. Ein Foto, das zwischenzeitlich schon einen Ort bekommen hat, wird nicht überschrieben.
- Ein Tag-Eintrag merkt sich die **Regel**, nicht die einzelnen Medien. Beim Übertragen gilt der dann aktuelle Stand der Regel.
- Gruppen, die erneut vorgemerkt werden, ersetzen den älteren Eintrag derselben Gruppe bzw. Regel.
- **Kommandozeile und API für n8n** führen weiterhin **direkt** aus (z. B. `/api/no-location/apply`). Zum Vormerken per API gibt es `/api/staged/…`.

## Verlauf und Rückgängig

Unter der Vormerkliste steht der **Verlauf**: jede Übertragung mit Zeitpunkt und Anzahl, auch die per API oder Kommandozeile. Er ist **nach Tagen gruppiert** und einklappbar (heute aufgeklappt), mit derselben Farbe je Art. Gespeichert werden die letzten 500 in `data/verlauf.json`.

**Rückgängig** macht eine Übertragung wieder rückgängig:

| Was übertragen wurde | Rückgängig |
|---|---|
| Papierkorb (Duplikate, Aufräumen) | aus dem Papierkorb zurückholen – solange Immich ihn noch nicht geleert hat |
| Prüf-Album | wieder aus dem Prüf-Album nehmen |
| Neues Album | Album löschen (die Fotos bleiben erhalten) |
| Album ergänzt / geteilt | ergänzte Fotos wieder herausnehmen, Freigabe zurücknehmen |
| Tags | die gesetzten Tags wieder entfernen |
| Aufnahmezeit | um denselben Betrag zurückverschieben |
| **Orte** | **nicht möglich:** Immich kann Koordinaten nur ändern, nicht entfernen. Bei einem falschen Ort einfach einen anderen setzen. |

Jede Übertragung lässt sich einmal zurücknehmen. Danach steht „rückgängig gemacht“ am Eintrag.

## Prüf-Ansicht: viele Bilder auf einmal kontrollieren

Überall, wo viele Bilder auf einmal vorgemerkt werden, gibt es **Prüfen**. Das betrifft Tag-Vorschläge, eigene Regeln, KI-Suche, Archivieren, alle sicheren Orte, Aufräumen, Falsche Zeit, Reisen und Ordner-Alben. Es öffnet sich ein dichtes Raster aller betroffenen Bilder, auch bei Tausenden:

- Die Bilder sind **in Gruppen** sortiert: Monat, Tag, Ort, Art oder bei der KI-Suche nach Passgenauigkeit. **Springe zu …** führt direkt zu einer Gruppe.
- **Antippen** wählt ein Bild ab (grau mit ✕) und wieder an. Das **Häkchen an der Gruppe** wählt die ganze Gruppe ab oder an. **Alle / Keine** gelten für alles.
- **Antippen: groß ansehen** öffnet stattdessen die Großansicht, dort wischst du durch die Gruppe. Bei der KI-Suche gibt es zusätzlich **ab hier abwählen**.
- **Größe S/M/L** ändert die Kachelgröße. Bei S passen auf dem Handy etwa 7 Bilder in eine Reihe. Die Wahl bleibt gespeichert.
- Vorschaubilder lädt das Tool erst, wenn ihre Gruppe in die Nähe kommt. Darum öffnet sich die Ansicht auch bei 4.000 Bildern sofort.
- Unten steht, wie viele gewählt sind. Der Knopf merkt **genau diese** vor. Wie immer geht erst beim Übertragen etwas an Immich.
