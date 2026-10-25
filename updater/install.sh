#!/usr/bin/env bash
# Richtet den Update-Dienst von immich-pflege auf dem Docker-Server ein (einmalig, als root).
#   sudo ./updater/install.sh            einrichten bzw. aktualisieren
#   sudo ./updater/install.sh --entfernen
#   ./updater/install.sh --units         nur die systemd-Units abgleichen (ruft der Dienst nach Updates selbst auf)
set -euo pipefail
if [ "$(id -u)" != "0" ]; then echo "Bitte als root ausführen: sudo $0" >&2; exit 1; fi
if ! command -v systemctl >/dev/null; then echo "systemd fehlt – Update-Dienst nicht möglich" >&2; exit 1; fi
DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNITS="immich-pflege-updater.service immich-pflege-updater.path immich-pflege-updater.timer"
SYSTEMD="${PFLEGE_SYSTEMD_DIR:-/etc/systemd/system}"

if [ "${1:-}" = "--entfernen" ]; then
  systemctl disable --now immich-pflege-updater.path immich-pflege-updater.timer 2>/dev/null || true
  for u in $UNITS; do rm -f "$SYSTEMD/$u"; done
  systemctl daemon-reload
  rm -f "$DIR/data/updater/status.json"
  echo "Update-Dienst entfernt."
  exit 0
fi

mkdir -p "$DIR/data/updater"
chown 1000:1000 "$DIR/data" "$DIR/data/updater"
changed=0
for u in $UNITS; do
  new="$(sed "s#@DIR@#$DIR#g" "$DIR/updater/$u")"
  if [ ! -f "$SYSTEMD/$u" ] || [ "$new" != "$(cat "$SYSTEMD/$u")" ]; then
    printf '%s\n' "$new" >"$SYSTEMD/$u"
    changed=1
  fi
done
chmod +x "$DIR/updater/pflege-updater.sh"
[ $changed = 1 ] && systemctl daemon-reload
systemctl enable --now immich-pflege-updater.path immich-pflege-updater.timer >/dev/null
if [ "${1:-}" = "--units" ]; then
  [ $changed = 1 ] && echo "Update-Dienst: systemd-Units aktualisiert."
  exit 0  # läuft im Dienst selbst – status würde auf dessen Sperre warten
fi
PFLEGE_DIR="$DIR" bash "$DIR/updater/pflege-updater.sh" status
echo "Update-Dienst eingerichtet ($DIR). Die App zeigt ihn unter ⚙ Einstellungen → Version."
