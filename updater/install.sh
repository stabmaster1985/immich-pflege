#!/usr/bin/env bash
# Richtet den Update-Dienst von immich-pflege auf dem Docker-Server ein (einmalig, als root).
#   sudo ./updater/install.sh            einrichten bzw. aktualisieren
#   sudo ./updater/install.sh --entfernen
set -euo pipefail
if [ "$(id -u)" != "0" ]; then echo "Bitte als root ausführen: sudo $0" >&2; exit 1; fi
if ! command -v systemctl >/dev/null; then echo "systemd fehlt – Update-Dienst nicht möglich (n8n-Workflow nutzen)" >&2; exit 1; fi
DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNITS="immich-pflege-updater.service immich-pflege-updater.path immich-pflege-updater.timer"

if [ "${1:-}" = "--entfernen" ]; then
  systemctl disable --now immich-pflege-updater.path immich-pflege-updater.timer 2>/dev/null || true
  for u in $UNITS; do rm -f "/etc/systemd/system/$u"; done
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
  if [ ! -f "/etc/systemd/system/$u" ] || [ "$new" != "$(cat "/etc/systemd/system/$u")" ]; then
    printf '%s\n' "$new" >"/etc/systemd/system/$u"
    changed=1
  fi
done
chmod +x "$DIR/updater/pflege-updater.sh"
[ $changed = 1 ] && systemctl daemon-reload
systemctl enable --now immich-pflege-updater.path immich-pflege-updater.timer >/dev/null
PFLEGE_DIR="$DIR" bash "$DIR/updater/pflege-updater.sh" status
echo "Update-Dienst eingerichtet ($DIR). Die App zeigt ihn unter ⚙ Einstellungen → Version."
