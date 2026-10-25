# Albumvorschläge

Das Tool erkennt Reisen in euren Fotos und schlägt dafür Alben vor. Vorher prüft es, ob es schon passende Alben gibt, bei beiden Benutzern, eigene und geteilte.

## Wie eine Reise erkannt wird

1. **Zuhause:** Das Gebiet (etwa 10 × 10 km) mit den meisten Aufnahmetagen. Habt ihr zwei Wohnorte mit ähnlich vielen Tagen, zählen beide. Oben im Tab steht, was erkannt wurde. Unter ⚙ Einstellungen → Albumvorschläge kannst du Zuhause auch selbst festlegen (Ortssuche, bis zu 5 Orte, z. B. Wohnort und Ferienhaus).
2. **Unterwegs:** Fotos mit GPS, die weiter als die eingestellte Entfernung (Standard **50 km**) von zu Hause entfernt sind.
3. **Eine Reise** ist eine Folge solcher Fotos eines Benutzers. Sie endet, wenn **36 Stunden** lang kein Foto von unterwegs kommt oder ein Foto von zu Hause dazwischen liegt.
4. **Gemeinsame Reisen:** Überschneiden sich die Reisen von euch beiden zeitlich, werden sie zu einer zusammengelegt.
5. **Fotos ohne GPS** (z. B. von der Kamera) zählen dazu, wenn sie im Reisezeitraum liegen (bis 3 Stunden davor und danach) und vom selben Benutzer stammen, der auch GPS-Fotos von der Reise hat.
6. Vorgeschlagen wird erst ab **20 Medien** (einstellbar) und mindestens 3 Fotos mit GPS. Screenshots und Medien im Prüf-Album zählen nicht.

Der **Name** ergibt sich aus den Orten: die Stadt, wenn mindestens 60 % der Fotos dort entstanden, sonst die Region (z. B. „Toskana“), sonst das Land. Dazu kommt der Zeitraum, z. B. „Toskana, Juli 2024“. Vor dem Vormerken kannst du den Namen ändern.

## Abgleich mit vorhandenen Alben

Beim Einlesen liest das Tool **alle Alben beider Benutzer** mit ihrem Inhalt, eigene und geteilte. Nur das Prüf-Album zählt nicht. Für jede Reise gilt dann:

| Ergebnis | Wann |
|---|---|
| **Schon in Alben** | Mindestens 95 % der Reise liegen in einem Album oder verteilt auf mehrere. |
| **Album ergänzen** | Ein Album enthält schon einen Teil der Reise (ab 20 %), besteht zur Hälfte aus Fotos der Reise, oder sein Name passt: Ort der Reise und Jahr bzw. Zeitraum, z. B. „Italien 2024“. Dann werden nur die fehlenden Medien ergänzt. |
| **Neues Album** | Nichts davon trifft zu. |

Unter **Ziel** kannst du statt des Vorschlags ein anderes passendes Album wählen oder doch ein neues anlegen.

Neben jedem gefundenen Album stehen **App ↗** und **Web ↗**: Sie öffnen das Album in der Immich-App (`immich://album?id=…`) bzw. in der Weboberfläche, um vorher hineinzuschauen. Die App öffnet nur Alben, die das dort angemeldete Konto sehen darf (eigene und geteilte).

## Wem das Album gehört

- **Neues Album:** Es gehört dem Benutzer mit den meisten Medien der Reise und wird mit dem anderen geteilt (als Bearbeiter), wenn auch von ihm Fotos dabei sind. Jeder fügt seine eigenen Fotos hinzu, so liegen am Ende die Fotos von euch beiden darin.
- **Album ergänzen:** Hat der andere Benutzer noch keinen Zugriff, teilt der Besitzer das Album mit ihm als Bearbeiter. Das steht vorher in der Vormerkliste dabei. Ist jemand nur Betrachter, werden seine Fotos nicht hinzugefügt (Hinweis in der Vormerkliste).

## Alle Bilder ansehen und einzelne abwählen

Die Karte zeigt nur ein paar Beispielbilder. **Alle … ansehen** klappt sämtliche Bilder der Reise auf:

- Grün umrandet = kommt ins Album.
- Mit **✓ im Album** = liegt schon im gewählten Album, bleibt dort.
- **Antippen** nimmt ein Bild heraus (grau) oder wieder hinein. Oben steht „28 von 31 ausgewählt“.

Herausgenommene Bilder gehören danach **nicht mehr zu dieser Reise**. Die Reise gilt also als erledigt, auch wenn sie nicht im Album liegen. Nimmst du den Eintrag unter ✓ Vorgemerkt wieder zurück, ist auch die Abwahl aufgehoben.

## Ablauf

1. **Vormerken** pro Reise oder für alle angezeigten. Noch geht nichts an Immich.
2. Unter **✓ Vorgemerkt** prüfen und **Übertragen**. Erst dann legt das Tool Alben an, teilt sie und fügt Medien hinzu. Gelöscht oder verschoben wird nie etwas.
3. **Kein Album** blendet eine Reise dauerhaft aus. Kommen später Fotos dazu, bleibt sie ausgeblendet. Unter „ausgeblendete“ lässt sie sich wieder aufnehmen.

## Grenzen

- Ohne Fotos mit GPS gibt es kein Zuhause und keine Reisen.
- Ausflüge unter der Mindestzahl an Medien erscheinen nicht. Die Schwelle lässt sich unter ⚙ Einstellungen → Albumvorschläge senken.
- Ein Umzug: Der frühere Wohnort gilt nur dann als Zuhause, wenn ihr dort mindestens halb so viele Aufnahmetage habt wie am jetzigen. Sonst erscheinen alte Fotos von dort als „Reise“, die blendest du mit **Kein Album** aus.
- Nach einer Änderung in Immich (z. B. Album von Hand angelegt) erst **Neu einlesen**, dann sieht das Tool sie.
