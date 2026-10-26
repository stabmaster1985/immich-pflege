# Fotos ohne Ort

Das Tool sucht Fotos und Videos ohne GPS und schlägt einen Ort vor. **Immich selbst errät keine Orte.** Es übersetzt nur vorhandene Koordinaten in Ortsnamen (Stadt, Land) und liefert die Ortssuche. Die Vorschläge berechnet dieses Tool.

## Grundidee

Wer zur gleichen Zeit fotografiert, ist am gleichen Ort. Als Anhaltspunkte dienen die Fotos **mit** GPS, und zwar von **beiden Benutzern**. Verglichen wird die echte Aufnahmezeit (UTC), deshalb stören Zeitzonen und Sommerzeit nicht.

## Sicherheit der Vorschläge

| Sicherheit | Wann |
|---|---|
| **sicher** | Ein GPS-Foto liegt höchstens **30 Minuten** entfernt, **oder** das GPS-Foto davor und das danach liegen beide im Zeitfenster und höchstens **1,5 km** auseinander. |
| **wahrscheinlich** | Ein GPS-Foto liegt im Zeitfenster (Standard **±2 Stunden**), aber weiter als 30 Minuten weg, oder die Fotos davor und danach sind an verschiedenen Orten (dann gewinnt das nähere). Oder der Ort kommt aus derselben Serie, deren Vorschlag sicher ist. |
| **unsicher** | Kein GPS-Foto im Zeitfenster, aber das letzte davor und das erste danach (je höchstens **12 Stunden**) liegen höchstens 1,5 km auseinander. Oder der Ort kommt aus einer Serie, deren Vorschlag wahrscheinlich oder unsicher ist. |
| kein Vorschlag | Nichts davon trifft zu – dann hilft **Ort suchen …** |

Übernommen werden die **genauen Koordinaten** des Nachbarfotos, kein Mittelwert. Stadt und Land ermittelt Immich danach neu. Bei jedem Vorschlag steht, woher er kommt, z. B. „5 min vorher bei julia“.

## Serien

Medien ohne Ort mit höchstens **2 Stunden** Abstand bilden eine **Serie**.

- Sind sich alle Vorschläge einer Serie über den Ort einig, bekommen auch die Medien ohne eigenen Vorschlag diesen Ort, eine Stufe vorsichtiger bewertet. So reicht ein Handyfoto, um eine ganze Kamera-Serie zu verorten.
- Widersprechen sich die Vorschläge, steht „Mehrere Orte“ dran, und es wird nichts automatisch übertragen.
- Serien ganz ohne Vorschlag werden zusätzlich **pro Tag** zusammengefasst.

## Herkunft: Screenshots, Messenger & Co.

Nicht jedes Bild braucht einen Ort. Das Tool teilt alle Medien ohne Ort nach Herkunft ein, oben unter **Herkunft** mit Anzahl zum Filtern:

| Herkunft | Woran erkannt |
|---|---|
| 📷 **Kamerafotos** | Kameradaten (Hersteller/Modell) vorhanden – die lohnen sich zu verorten |
| 📄 **Dokumente & Text** | viel erkannter Text im Bild: ab **10 %** Textfläche oder **300** Zeichen – Dokumente, Quittungen, Speisekarten, abfotografierte Bildschirme, Screenshots in ungewöhnlicher Größe. Gilt auch mit Kameradaten |
| 💬 **Messenger** | Dateiname von WhatsApp (`IMG-20240718-WA0003`, `-WA0001`), Signal, Threema, Telegram |
| 🖼 **Ohne Kameradaten** | weder Hersteller noch Modell: gespeichert, heruntergeladen, bearbeitet, Scans |
| 📱 **Screenshots** | Dateiname (Screenshot, Bildschirmfoto, RPReplay …), PNG ohne Kameradaten **oder** ein Bild ohne Kameradaten in genau der Bildschirmgröße eines Handys oder Tablets (z. B. 1179×2556 – so werden auch markierte und als JPG gespeicherte Screenshots erkannt) |

Der Filter wirkt **im gewählten Ort**: In der Übersicht steht er oben und zählt über alle Orte. Öffnest du einen Ort, steht er im Kopf des Orts und zählt nur dessen Bilder, z. B. „Ohne Vorschlag: 💬 Messenger (5)“. Dann zeigen die Serien nur die Bilder dieser Herkunft, und **Vormerken**, **Alle vormerken** und **Ort für alle suchen** gelten nur für sie.

**Texterkennung:** Dafür nutzt das Tool Immichs Texterkennung (OCR). In Immich unter *Administration → Einstellungen → Maschinelles Lernen → Texterkennung* muss sie eingeschaltet sein, und der Auftrag „Texterkennung“ muss einmal gelaufen sein. Das Tool fragt das Ergebnis nur für Bilder **ohne Ort** ab, im Hintergrund, und merkt es sich (`data/texterkennung.json`). Neue Bilder kommen nach jedem Einlesen dazu. Solange es läuft, steht in der Zusammenfassung „⟳ Texterkennung: … von … Bildern geprüft“. Ein einzelnes Schild im Urlaubsfoto zählt nicht, nur Bilder, die zu einem großen Teil aus Text bestehen. Auf den Kacheln steht der Anfang des erkannten Texts.

Screenshots sind ausgeblendet (abschaltbar unter ⚙ Einstellungen). Bei **Messenger** und **Ohne Kameradaten** erscheint **Alle … prüfen & ausblenden**. Die Prüf-Ansicht zeigt alle, du wählst ab, was doch einen Ort bekommen soll. Dann:

- **ausblenden – kein Ort nötig:** verschwinden dauerhaft aus „Ohne Ort“, aus den Zahlen und aus „Alle sicheren“.
- **archivieren:** zusätzlich aus der Immich-Zeitleiste nehmen (wird vorgemerkt).

**Einzelne Bilder:** In der Liste Bilder antippen, dann unten **Archivieren** oder **Kein Ort nötig**. Das geht ohne Prüf-Ansicht, gut für ein paar Bilder. Archivieren wird wie alles erst **vorgemerkt** und geht beim **Übertragen** unter Vorgemerkt an Immich. Bis dahin ist das Bild hier schon ausgeblendet.

Oben in der Zusammenfassung steht **„… ausgeblendet – ansehen“**. Dort siehst du die erkannten Screenshots und alles, was du ausgeblendet hast. Antippen und **wieder einblenden**, auch für ein Bild, das fälschlich als Screenshot erkannt wurde.

## So arbeitest du am schnellsten

1. Die **Übersicht nach Ort** zeigt pro vorgeschlagenem Ort, wie viele Medien und Serien betroffen sind.
2. **Alle vormerken** auf einer Ortskarte merkt den Ort für alle Medien mit Vorschlag vor. Steht oben „nur sichere“, werden nur die sicheren vorgemerkt.
3. **Alle sicheren prüfen** unten öffnet alle sicheren Vorschläge in der Prüf-Ansicht, nach neuem Ort gruppiert. Einzelne Bilder oder ganze Orte abwählen, dann **… verorten**.

Vorgemerktes verschwindet aus der Liste. An Immich geht es erst, wenn du es unter **Vorgemerkt** überträgst.
4. Für **Ohne Vorschlag**: Mit dem **Monat** eingrenzen und **Ort für alle suchen …** wählen, z. B. „Hamburg“ für die Scans eines Urlaubs. Oder pro Serie über **Ort suchen …** einzeln.

Die Ortssuche nutzt Immichs eigene Ortsdatenbank, ohne Internetdienst.

Mit **App ↗** und **Web ↗** unter jedem Bild öffnest du das Original in Immich, um es dir genauer anzusehen.

## Was ausgeblendet wird

- **Screenshots und Bildschirmaufnahmen:** Erkannt am Dateinamen (Screenshot, Bildschirmfoto, Bildschirmaufnahme, RPReplay …), als PNG ohne Kameradaten (so speichert das iPhone Screenshots) oder an der Bildschirmgröße (siehe Herkunft). Ausblenden abschaltbar unter ⚙ Einstellungen.
- **Externe Bibliotheken** werden standardmäßig nicht geändert. Das lässt sich ebenfalls in den Einstellungen freigeben.

## Wo es danebenliegen kann

- **Falsch gestellte Kamera-Uhr:** Geht die Kamera z. B. eine Stunde falsch, stimmen alle Abstände nicht. Das ist die häufigste Fehlerquelle.
- **Unterwegs:** Auf Autofahrten oder Wanderungen sind ±2 Stunden grob. Diese Vorschläge sind dann nur „wahrscheinlich“.
- **Getrennt unterwegs:** Wart ihr an verschiedenen Orten, kann das Handy des einen einen falschen Ort für die Kamera des anderen liefern. Die Begründung zeigt immer, von wem der Ort stammt.
