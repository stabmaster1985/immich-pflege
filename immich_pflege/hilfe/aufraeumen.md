# Aufräumen

Der Tab sammelt alles, was Platz kostet oder offensichtlich daneben ist. Oben wählst du den **Bereich**. Wie überall gilt: erst **vormerken**, unter **✓ Vorgemerkt** prüfen, dann übertragen. Im Verlauf lässt sich jede Übertragung **rückgängig** machen.

**Behalten** bzw. **Passt so** blendet einen Eintrag dauerhaft aus. Unter „behaltene“ holst du ihn zurück.

## Speicherfresser

| Art | Erkannt an |
|---|---|
| **Große Videos** | ab **300 MB**, das größte zuerst |
| **Bildschirmaufnahmen** | Dateiname wie `ScreenRecording…`, `RPReplay…`, „Bildschirmaufnahme“ |
| **Live-Photo-Videos doppelt** | ein kurzes Video (bis 3,5 s) mit demselben Namen wie ein Foto, höchstens 2 s daneben aufgenommen. Das Live-Photo enthält das Video schon. Das passiert, wenn Fotos einmal als HEIC und einmal getrennt als MOV hochgeladen wurden. |

Favoriten und Medien im Prüf-Album bleiben außen vor.

## Serienbilder

Fotos **derselben Kamera** desselben Benutzers mit höchstens **2 Sekunden** Abstand, mindestens 3 hintereinander. Ist der Bild-Fingerabdruck schon berechnet, müssen sie sich auch ähneln (höchstens 12 von 64 Bit verschieden), sonst reicht die Zeit.

**Behalten wird:** ein Favorit, sonst ein Foto, das in einem Album liegt, sonst das **schärfste**, sonst das erste. Tippe auf ein anderes Bild, um es stattdessen zu behalten.

## Unscharf & dunkel

Aus demselben kleinen Vorschaubild wie der Fingerabdruck berechnet das Tool zwei Werte:

- **Helligkeit** 0–255. Bis **25** gilt als „sehr dunkel“.
- **Schärfe** (wie stark sich benachbarte Bildpunkte unterscheiden). Bis **3** gilt als „unscharf“.
- Beides zusammen ist **versehentlich**, typisch für ein Foto aus der Hosentasche.

Fotos in einer Serie, Favoriten und Screenshots zählen hier nicht. Gewollt dunkle Fotos (Sternenhimmel, Feuerwerk) und bewusst weiche Bilder (Nebel, Porträt mit Unschärfe) erscheinen ebenfalls. Dafür gibt es **Behalten**.

Nach dem Update werden Schärfe und Helligkeit für alle Fotos einmalig im Hintergrund nachberechnet. Das dauert bei großen Bibliotheken ein paar Stunden.

## Verwaiste Dateien

Medien der **externen Bibliothek**, deren Datei auf der Platte fehlt, weil sie verschoben, umbenannt oder gelöscht wurde. Immich nennt sie „offline“. Unter dem Eintrag steht der alte Pfad. Liegt die Datei nur woanders, bringt Immich sie nach dem nächsten Scannen der Bibliothek von selbst wieder in Ordnung. Sonst räumt **Papierkorb** den toten Eintrag weg. Das ist die einzige Ausnahme von der Regel „externe Medien nie in den Papierkorb“, denn die Datei ist ohnehin nicht mehr da.

## Falsche Zeit

- **Kamera-Zeitversatz:** Geprüft werden nur Kameras ohne GPS. Pro Monat legt das Tool ihre Fotos neben die Handyfotos von euch beiden und probiert Verschiebungen in 30-Minuten-Schritten bis ±12 Stunden. Passt eine Verschiebung bei mindestens der Hälfte der Fotos (ein anderes Foto höchstens 10 Minuten daneben) und deutlich besser als ohne, gibt es einen Vorschlag. Ein typischer Fall: die Sommerzeit an der Kamera vergessen, also eine Stunde Versatz. Gleiche Verschiebung in aufeinanderfolgenden Monaten wird zusammengefasst. Die Stunden lassen sich vor dem Vormerken anpassen.
- **Datum laut Dateiname:** `IMG_20190714_123456`, `PXL_…`, `IMG-20240718-WA0003` (WhatsApp, nur Datum) oder `2019-07-14 12.34.56`. Weicht Immichs Aufnahmezeit mehr als einen Tag davon ab, schlägt das Tool den Dateinamen vor.
- **In der Zukunft** und **Standarddatum** (1970, 1980, 2000-01-01 um Mitternacht, oder vor 1995 von einem Digitalgerät): Hier gibt es keinen Vorschlag. Trage die richtige Zeit selbst ein.

Korrigiert wird mit Immichs relativer Zeitverschiebung. **Rückgängig** verschiebt um denselben Betrag zurück. Orte, Serien und Albumvorschläge rechnen danach mit der richtigen Zeit.

## Stapeln aus Alben

Statt Zusammengehöriges zu löschen, kann es in Immich **gestapelt** werden. In der Zeitleiste liegt dann nur das obere Bild, die anderen dahinter (in Immich über das Stapel-Symbol aufklappbar). Gelöscht wird nichts.

1. Unter **Album** eines deiner Alben wählen, in dem du Zusammengehöriges gesammelt hast.
2. Das Tool schlägt Stapel vor. Zusammen kommen Fotos **desselben Benutzers** (Immich stapelt nur eigene Medien), die
   - denselben Namen haben und höchstens 2 Sekunden auseinanderliegen (RAW+JPG, HEIC+JPG, Original + Bearbeitung),
   - höchstens 2 Sekunden auseinanderliegen (Serienbild) oder
   - höchstens 60 Sekunden auseinanderliegen und sich im Bild-Fingerabdruck ähneln.
   Mit **ganzes Album als einen Stapel** wird stattdessen alles (je Benutzer) zu einem Stapel.
3. **Oben** liegt ein Favorit, sonst kein RAW, sonst die bearbeitete Fassung, sonst das schärfste, sonst das größte Bild. Antippen wählt ein anderes.
4. Optional **danach aus dem Album nehmen**, damit das Album leer wird, sobald alles gestapelt ist.

Schon gestapelte Fotos bleiben außen vor. Serienbilder lassen sich auch unter **Serienbilder** mit **Stapeln** zusammenfassen. **Rückgängig** löst die Stapel wieder auf und legt herausgenommene Fotos zurück ins Album.

Seit Immich 3.3 werden Bearbeitungen vom Handy automatisch gestapelt. Liegen Original und Bearbeitung schon in einem Stapel, zeigt sie die Duplikat-Suche nicht mehr an.

## Alben aufräumen

Findet unter euren Alben (beide Benutzer, eigene und geteilte):

| Art | Wann |
|---|---|
| **Gleicher Name** | z. B. bei dir und Julia je ein „Toskana 2024“ (Groß-/Kleinschreibung und Leerzeichen egal) |
| **Fast gleicher Inhalt** | das kleinere Album liegt zu mindestens **90 %** im größeren |
| **Leer** | Album ohne Medien |
| **Nur 1–2 Medien** | Mini-Alben, oft aus Versehen angelegt |

**Zusammenführen:** Das markierte **Ziel**-Album (antippen zum Ändern) bekommt alle Fotos der anderen. Hat der andere Benutzer noch keinen Zugriff, teilt der Besitzer es mit ihm. Jeder legt seine eigenen Fotos hinein. Mit **die anderen danach löschen** verschwinden die übrigen Alben, die Fotos selbst bleiben natürlich erhalten.

**Album löschen** entfernt nur das Album, nie die Fotos. **Passt so** blendet einen Eintrag aus. **Rückgängig** im Verlauf legt gelöschte Alben mit Inhalt und Freigaben neu an. Das neue Album bekommt eine neue Adresse, geteilte Links auf das alte funktionieren danach nicht mehr.

## Papierkorb

Zeigt, was bei euch beiden im Immich-Papierkorb liegt, mit Größe. Bei Medien, die das Tool selbst verschoben hat, steht auch, ab wann Immich sie **endgültig löscht** (Einstellung „Papierkorb“ in Immich, meist 30 Tage). Antippen und **Wiederherstellen**, oder alles auf einmal. Wiederhergestellte Medien erscheinen nach dem nächsten **Neu einlesen** wieder in den Listen.

Den Papierkorb leeren kann das Tool bewusst nicht, das bleibt Immich überlassen.
