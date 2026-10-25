# Vorgemerkt

In der Oberfläche geht keine Änderung sofort an Immich. Was du in den Tabs **Duplikate**, **Ohne Ort**, **Aufräumen**, **Alben** oder **Tags** bestätigst, wird erst **vorgemerkt**. Gesammelt wird es im Tab **✓**.

## Ablauf

1. **Vormerken:** In den Tabs wie gewohnt auswählen und bestätigen. Das Vorgemerkte verschwindet sofort aus der Übersicht, damit du mit dem Rest weitermachen kannst. In Immich ändert sich noch nichts.
2. **Prüfen:** Unter **✓** steht jeder Eintrag mit Vorschaubildern:
   - Duplikate: grün umrandet ist das Bild, das bleibt. Darunter steht, wohin die Kopien gehen (Prüf-Album oder Papierkorb).
   - Orte: unter jedem Bild steht der neue Ort.
   - Alben: neues Album oder welches ergänzt wird, mit wem es geteilt wird, Beispielbilder.
   - Tags: Regel, Tags und Beispielbilder.
3. **Zurücknehmen** legt einen Eintrag wieder in die Übersicht zurück. Er wird dort neu bewertet.
4. **Übertragen** führt einen einzelnen Eintrag in Immich aus, **Alle übertragen** in der Aktionsleiste alle auf einmal. Geht etwas in den Papierkorb, musst du das vorher ausdrücklich bestätigen.

Erfolgreich Übertragenes verschwindet aus der Liste. Schlägt ein Eintrag fehl, z. B. weil Immich nicht erreichbar war, bleibt er mit der Fehlermeldung stehen und kann später erneut übertragen werden.

## Gut zu wissen

- Die Liste liegt in `data/vorgemerkt.json`. Sie übersteht Neustarts und Updates.
- Beim Übertragen gelten dieselben Schutzregeln wie sonst: externe Medien und Kopien des anderen Benutzers kommen nie in den Papierkorb.
- Wurde ein Medium inzwischen in Immich gelöscht, wird es übersprungen. Ein Foto, das zwischenzeitlich schon einen Ort bekommen hat, wird nicht überschrieben.
- Ein Tag-Eintrag merkt sich die **Regel**, nicht die einzelnen Medien. Beim Übertragen gilt der dann aktuelle Stand der Regel.
- Gruppen, die erneut vorgemerkt werden, ersetzen den älteren Eintrag derselben Gruppe bzw. Regel.
- **Kommandozeile und API für n8n** führen weiterhin **direkt** aus (z. B. `/api/no-location/apply`). Zum Vormerken per API gibt es `/api/staged/…`.

## Verlauf und Rückgängig

Unter der Vormerkliste steht der **Verlauf**: jede Übertragung mit Zeitpunkt und Anzahl, auch die per API oder Kommandozeile. Gespeichert werden die letzten 500 in `data/verlauf.json`.

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
