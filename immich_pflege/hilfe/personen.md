# Personen

Immich erkennt Gesichter und fasst sie zu Personen zusammen. Viele bleiben aber ohne Namen, und manchmal legt Immich dieselbe Person mehrfach an. Unter **Ordnen → Personen** siehst du beides.

## Ohne Namen

Die unbenannten Personen mit den meisten Fotos, je Benutzer bis zu 30, die häufigsten zuerst. Darunter steht, **mit wem** sie meist zusammen auf Fotos sind, z. B. „meist mit Julia (12)“ – das hilft beim Erkennen.

**Benennen geht in Immich:** „In Immich benennen ↗“ öffnet die Person dort (dafür unter ⚙ Einstellungen die „Adresse für Links im Browser“ eintragen). Danach hier **↻** tippen.

## Doppelt angelegt

Personen mit **gleichem Namen** beim selben Benutzer (Groß-/Kleinschreibung und Leerzeichen egal), z. B. zweimal „Oma Ilse“. Tippe auf das Gesicht, das bleiben soll (Vorschlag: das mit den meisten Fotos), dann **Zusammenführen vormerken**. Übertragen wird wie immer unter **Vorgemerkt**.

**Achtung:** Zusammengeführte Personen kann Immich **nicht wieder trennen** – deshalb musst du das ausdrücklich bestätigen, und im Verlauf gibt es dafür kein Rückgängig.

Personen sind in Immich je Benutzer getrennt: Franks „Julia“ und Julias „Julia“ sind zwei verschiedene Personen und werden nicht zusammengeführt.

## Voraussetzungen

Gesichtserkennung in Immich eingeschaltet; der API-Key braucht `person.read`, `person.statistics` und zum Zusammenführen `person.merge` (⚙ Einstellungen → Verbindung testen zeigt fehlende Rechte). Die Liste wird bis zum nächsten Einlesen zwischengespeichert.
