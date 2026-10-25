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

## So arbeitest du am schnellsten

1. Die **Übersicht nach Ort** zeigt pro vorgeschlagenem Ort, wie viele Medien und Serien betroffen sind.
2. **Alle vormerken** auf einer Ortskarte merkt den Ort für alle Medien mit Vorschlag vor. Steht oben „nur sichere“, werden nur die sicheren vorgemerkt.
3. **Alle sicheren** unten merkt alle sicheren Vorschläge auf einmal vor.

Vorgemerktes verschwindet aus der Liste. An Immich geht es erst, wenn du es unter **Vorgemerkt** überträgst.
4. Für **Ohne Vorschlag**: Mit dem **Monat** eingrenzen und **Ort für alle suchen …** wählen, z. B. „Hamburg“ für die Scans eines Urlaubs. Oder pro Serie über **Ort suchen …** einzeln.

Die Ortssuche nutzt Immichs eigene Ortsdatenbank, ohne Internetdienst.

Mit **App ↗** und **Web ↗** unter jedem Bild öffnest du das Original in Immich, um es dir genauer anzusehen.

## Was ausgeblendet wird

- **Screenshots und Bildschirmaufnahmen:** Erkannt am Dateinamen (Screenshot, Bildschirmfoto, Bildschirmaufnahme, RPReplay …) oder als PNG ohne Kameradaten, so speichert das iPhone Screenshots. Abschaltbar unter ⚙ Einstellungen.
- **Externe Bibliotheken** werden standardmäßig nicht geändert. Das lässt sich ebenfalls in den Einstellungen freigeben.

## Wo es danebenliegen kann

- **Falsch gestellte Kamera-Uhr:** Geht die Kamera z. B. eine Stunde falsch, stimmen alle Abstände nicht. Das ist die häufigste Fehlerquelle.
- **Unterwegs:** Auf Autofahrten oder Wanderungen sind ±2 Stunden grob. Diese Vorschläge sind dann nur „wahrscheinlich“.
- **Getrennt unterwegs:** Wart ihr an verschiedenen Orten, kann das Handy des einen einen falschen Ort für die Kamera des anderen liefern. Die Begründung zeigt immer, von wem der Ort stammt.
