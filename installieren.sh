#!/usr/bin/env bash
# immich-pflege auf dem Docker-Server installieren – ohne n8n. Einmalig als root:
#
#   git clone https://github.com/stabmaster1985/immich-pflege.git && sudo ./immich-pflege/installieren.sh
#
# Danach laufen Updates per Klick in der App (Update-Dienst, siehe updater/). Erneut ausführen
# repariert eine Installation: Container neu bauen und starten, Update-Dienst einrichten.
set -euo pipefail

if [ "$(id -u)" != "0" ]; then echo "Bitte als root ausführen: sudo $0" >&2; exit 1; fi
for cmd in git docker; do
  command -v "$cmd" >/dev/null || { echo "FEHLER: $cmd fehlt auf diesem Server." >&2; exit 1; }
done
if docker compose version >/dev/null 2>&1; then DC="docker compose"
elif command -v docker-compose >/dev/null; then DC="docker-compose"
else echo "FEHLER: docker compose fehlt." >&2; exit 1; fi

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
[ -d .git ] && [ -f docker-compose.yml ] || { echo "FEHLER: $DIR ist kein Klon von immich-pflege." >&2; exit 1; }

echo "== Daten in $DIR/data (Container läuft als Benutzer 1000)"
mkdir -p data
chown 1000:1000 data

echo "== Baue und starte $(git log -1 --format='%h %s')"
$DC up -d --build --remove-orphans

STATUS=""
for _ in $(seq 1 45); do
  STATUS="$(docker inspect -f '{{.State.Health.Status}}' immich-pflege 2>/dev/null || echo fehlt)"
  [ "$STATUS" = "healthy" ] && break
  sleep 2
done
if [ "$STATUS" != "healthy" ]; then
  echo "FEHLER: Container startet nicht (Status: $STATUS)." >&2
  $DC logs --tail 50 >&2
  exit 1
fi

if command -v systemctl >/dev/null; then
  echo "== Update-Dienst einrichten (Updates per Klick in der App)"
  ./updater/install.sh
else
  echo "Hinweis: Ohne systemd kein Update-Dienst – Updates dann mit: git pull && $DC up -d --build"
fi

PORT="$(sed -n 's/^PFLEGE_PORT=//p' .env 2>/dev/null | tail -n 1)"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "Fertig. Oberfläche: http://${IP:-<server>}:${PORT:-2222} – dort unter ⚙ Einstellungen Immich-Adresse und API-Keys eintragen."
