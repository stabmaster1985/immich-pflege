# Duplikate

Das Tool sucht doppelte Fotos und Videos über **beide Benutzer** und über **Uploads und externe Bibliotheken** hinweg. Zu jeder Gruppe gibt es einen Vorschlag, welches Medium bleibt. Ohne deine Bestätigung wird nichts verändert.

## Woher die Treffer kommen

| Quelle | Was geprüft wird |
|---|---|
| **Prüfsumme** | Die Dateien sind Byte für Byte gleich, z. B. dasselbe Foto bei beiden Benutzern oder im Upload und in der externen Bibliothek. |
| **Name + Zeit** | Gleicher Dateiname (Groß/klein egal) und gleiche Aufnahmezeit auf die Sekunde, z. B. dieselbe Kameradatei einmal hochgeladen und einmal in der externen Bibliothek. |
| **Bild-Fingerabdruck** | Das Bild sieht fast gleich aus, obwohl die Datei anders ist, z. B. eine per WhatsApp verschickte, verkleinerte Kopie ohne Kameradaten. |
| **Immich-KI** | Immichs eigene Duplikaterkennung (Bildähnlichkeit per Machine Learning), jeweils innerhalb eines Benutzers. |

Überschneiden sich Treffer, werden sie zu **einer Gruppe** zusammengeführt. Sind A und B gleich und B und C ähnlich, landen alle drei in einer Gruppe.

## Art der Gruppe

| Art | Bedeutung | Empfehlung |
|---|---|---|
| **identisch** | Alle Dateien haben dieselbe Prüfsumme. | Gefahrlos, kann gesammelt erledigt werden. |
| **sehr wahrscheinlich** | Name + Zeit gleich oder Bild-Fingerabdruck fast gleich. | Kurz ansehen, meist eindeutig. |
| **ähnlich** | Nur Immich-KI: ähnliches Motiv. Das können auch Serienbilder sein, die du behalten willst. | Einzeln prüfen. |

## Welches Medium bleibt

Jede Stufe schlägt alle niedrigeren zusammen:

| Kriterium | Punkte |
|---|---|
| Favorit | 32 |
| in einem Album (das Prüf-Album zählt nicht) | 16 |
| hat GPS | 8 |
| Immich schlägt es vor | 4 |
| liegt in einer externen Bibliothek | 2 |
| höchste Auflösung der Gruppe | 1 |

Bei Gleichstand gewinnt die größere Auflösung, dann die größere Datei. **Tippe auf ein Bild**, um selbst zu wählen, welches bleibt.

## Aktionen

- **Ins Prüf-Album:** Die nicht behaltenen Kopien kommen in das Album „Duplikat-Prüfung“ ihres Besitzers. Das Album wird bei Bedarf angelegt. Gelöscht wird dabei nichts.
- **Papierkorb:** Die nicht behaltenen Kopien kommen in den Immich-Papierkorb und sind dort noch wiederherstellbar. Vorher musst du ausdrücklich bestätigen. Es gelten Schutzregeln:
  - Medien aus **externen Bibliotheken** kommen **nie** in den Papierkorb, sondern ins Prüf-Album.
  - Gehört eine Kopie dem **anderen Benutzer** als dem der behaltenen Datei, kommt sie nur in dessen Prüf-Album.
- **Alle …** unten in der Leiste gilt für **alle offenen Gruppen der aktuellen Auswahl** (Art, Monat, benutzerübergreifend), jeweils mit dem Behalten-Vorschlag. Vorher siehst du, wie viele Medien betroffen sind.
- **Kein Duplikat:** Die Gruppe wird dauerhaft ausgeblendet. Bei Immich-Treffern wird die Markierung auch in Immich entfernt. Kommt später eine weitere Kopie dazu, taucht die Gruppe wieder auf. Unter „ausgeblendete“ kannst du sie wieder aufnehmen.

## Bild-Fingerabdruck

- **Wie er entsteht:** Aus Immichs kleinem Vorschaubild wird ein 64-Bit-Fingerabdruck des Helligkeitsverlaufs berechnet (dHash). Zwei Bilder gelten als fast gleich, wenn sich höchstens 6 der 64 Bits unterscheiden.
- **Wann er rechnet:** Die Berechnung läuft nach jedem Einlesen im Hintergrund, aber nur für neue oder geänderte Bilder. Der Fortschritt steht oben im Tab.
- **Gegen Fehlalarme durch Serienbilder** zählen Treffer nur zwischen verschiedenen Benutzern, zwischen Upload und externer Bibliothek oder wenn einer Kopie die Kameradaten fehlen (typisch für Messenger-Kopien).
- **Abschalten:** unter ⚙ Einstellungen → Duplikate.

## Tipps

- Unter *Immich → Administration → Machine Learning → Duplikaterkennung* lässt sich einstellen, wie ähnlich Bilder für die Immich-KI sein müssen. Ein höherer Wert findet mehr, aber auch mehr Falsche.
- Prüf-Album statt Papierkorb ist der sichere Weg: Im Album siehst du in Ruhe nach und löschst in Immich selbst.
