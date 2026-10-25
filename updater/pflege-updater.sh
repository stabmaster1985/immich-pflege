#!/usr/bin/env bash
# immich-pflege – Update-Dienst auf dem Docker-Server (nicht im Container).
#
# Die App legt Aufträge in data/updater/request.json ab, dieses Skript schreibt den Stand nach
# data/updater/status.json. Ausgelöst per systemd (siehe install.sh): sofort bei einem Auftrag
# und stündlich zum automatischen Vorbereiten.
#
#   pflege-updater.sh handle    Auftrag abarbeiten – ohne Auftrag: vorbereiten
#   pflege-updater.sh prepare   neue Version holen und fertig bauen (ohne umzuschalten)
#   pflege-updater.sh apply     vorbereitete Version starten (bei Fehler zurück auf die alte)
#   pflege-updater.sh status    nur den Status schreiben
set -euo pipefail

# Das Skript ersetzt sich beim Umschalten selbst (git) – deshalb aus einer Kopie laufen.
if [ -z "${PFLEGE_UPDATER_COPY:-}" ]; then
  PFLEGE_DIR="${PFLEGE_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
  tmp="$(mktemp)"
  cp "$0" "$tmp"
  PFLEGE_UPDATER_COPY=1 PFLEGE_DIR="$PFLEGE_DIR" exec bash "$tmp" "$@"
fi
trap 'rm -f "$0"' EXIT

DIENST_VERSION=1
REPO="$PFLEGE_DIR"
BRANCH="${PFLEGE_BRANCH:-main}"
IMAGE="${PFLEGE_IMAGE:-immich-pflege}"
CONTAINER="${PFLEGE_CONTAINER:-immich-pflege}"
HEALTH_WAIT="${PFLEGE_HEALTH_WAIT:-60}"
DIR="$REPO/data/updater"
STATUS="$DIR/status.json"
REQUEST="$DIR/request.json"
READY="$DIR/bereit"
LOG="$DIR/update.log"

mkdir -p "$DIR"
if [ "$(id -u)" = "0" ]; then chown --reference="$REPO/data" "$DIR" 2>/dev/null || chown 1000:1000 "$DIR"; fi
cd "$REPO"

exec 9>"$DIR/.lock"
if command -v flock >/dev/null; then flock -w 600 9 || { echo "Update-Dienst ist beschäftigt"; exit 1; }; fi

if docker compose version >/dev/null 2>&1; then DC="docker compose"; else DC="docker-compose"; fi

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG" >&2; }
esc() { printf '%s' "$1" | tr -d '\000-\010\013-\037' | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\n\t' '  '; }

commits_json() {  # Commits zwischen $1 und $2 als JSON-Liste (neueste zuerst)
  local out="" first=1 sha msg
  while IFS=$'\t' read -r sha msg; do
    [ -n "$sha" ] || continue
    [ $first = 1 ] || out="$out,"
    out="$out{\"commit\":\"$sha\",\"message\":\"$(esc "$msg")\"}"
    first=0
  done < <(git log --format='%H%x09%s' -n 30 "$1..$2" 2>/dev/null || true)
  printf '[%s]' "$out"
}

write_status() {  # write_status phase meldung [bereit-sha]
  local phase="$1" msg="$2" ready="${3:-}" cur commits="[]"
  cur="$(git rev-parse HEAD 2>/dev/null || echo "")"
  [ -n "$ready" ] && commits="$(commits_json "$cur" "$ready")"
  local tail=""
  [ "$phase" = "fehler" ] && tail="$(tail -n 15 "$LOG" 2>/dev/null || true)"
  cat >"$STATUS.tmp" <<EOF
{"phase":"$phase","meldung":"$(esc "$msg")","aktuell":"$cur","bereit":"$ready","branch":"$BRANCH","commits":$commits,"zeit":"$(date -u +%FT%TZ)","dienst_version":$DIENST_VERSION,"log":"$(esc "$tail")"}
EOF
  chmod 644 "$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
}

prepared() { [ -f "$READY" ] && cat "$READY" || true; }

prepare() {
  local cur new
  write_status "vorbereiten" "Hole neue Version von GitHub …"
  log "== Vorbereiten"
  if ! git fetch -q origin "$BRANCH" >>"$LOG" 2>&1; then
    write_status "fehler" "GitHub nicht erreichbar (git fetch fehlgeschlagen)"; return 1
  fi
  cur="$(git rev-parse HEAD)"
  new="$(git rev-parse "origin/$BRANCH")"
  if [ "$cur" = "$new" ]; then
    rm -f "$READY"
    write_status "aktuell" "Die neueste Version läuft bereits."; return 0
  fi
  if ! git merge-base --is-ancestor "$cur" "$new"; then
    write_status "fehler" "Lokaler Stand weicht von GitHub ab – bitte auf dem Server prüfen (git status)."; return 1
  fi
  if [ "$(prepared)" = "$new" ] && docker image inspect "$IMAGE:bereit" >/dev/null 2>&1; then
    write_status "bereit" "Version ${new:0:7} ist vorbereitet." "$new"; return 0
  fi
  write_status "vorbereiten" "Baue Version ${new:0:7} …"
  log "Baue $new"
  if ! git archive --format=tar "$new" | docker build -q \
      --build-arg GIT_COMMIT="$new" --build-arg GIT_BRANCH="$BRANCH" \
      --build-arg GIT_DATE="$(git show -s --format=%cI "$new")" \
      -t "$IMAGE:bereit" - >>"$LOG" 2>&1; then
    rm -f "$READY"
    write_status "fehler" "Bauen der neuen Version fehlgeschlagen – die laufende Version bleibt."; return 1
  fi
  echo "$new" >"$READY"
  log "Bereit: $new"
  write_status "bereit" "Version ${new:0:7} ist vorbereitet." "$new"
}

healthy() {
  local s=""
  for _ in $(seq 1 "$((HEALTH_WAIT / 2))"); do
    s="$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null || echo fehlt)"
    [ "$s" = "healthy" ] && return 0
    sleep 2
  done
  log "Container-Status: $s"
  return 1
}

apply() {
  local new cur
  new="$(prepared)"
  if [ -z "$new" ] || ! docker image inspect "$IMAGE:bereit" >/dev/null 2>&1; then
    write_status "fehler" "Es ist keine Version vorbereitet."; return 1
  fi
  cur="$(git rev-parse HEAD)"
  write_status "umschalten" "Schalte auf ${new:0:7} um …" "$new"
  log "== Umschalten $cur -> $new"
  docker tag "$IMAGE:latest" "$IMAGE:vorher" 2>/dev/null || true
  if ! git merge -q --ff-only "$new" >>"$LOG" 2>&1; then
    write_status "fehler" "git merge fehlgeschlagen – nichts umgeschaltet."; return 1
  fi
  docker tag "$IMAGE:bereit" "$IMAGE:latest"
  $DC up -d --no-build --remove-orphans >>"$LOG" 2>&1 || true
  if healthy; then
    rm -f "$READY"
    docker image rm "$IMAGE:bereit" >/dev/null 2>&1 || true
    docker image prune -f >/dev/null 2>&1 || true
    log "Fertig: $new läuft"
    write_status "fertig" "Version ${new:0:7} läuft."
    return 0
  fi
  log "Neue Version startet nicht – zurück auf $cur"
  $DC logs --tail 30 >>"$LOG" 2>&1 || true
  git reset -q --hard "$cur" >>"$LOG" 2>&1
  docker tag "$IMAGE:vorher" "$IMAGE:latest" 2>/dev/null || true
  $DC up -d --no-build --remove-orphans >>"$LOG" 2>&1 || true
  write_status "fehler" "Die neue Version startete nicht – die alte Version läuft wieder."
  return 1
}

handle() {
  local action=""
  if [ -f "$REQUEST" ]; then
    action="$(sed -n 's/.*"aktion"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$REQUEST" | head -n 1)"
    rm -f "$REQUEST"
  fi
  case "$action" in
    umschalten) apply ;;
    *) prepare ;;  # „vorbereiten“ oder stündlicher Lauf ohne Auftrag
  esac
}

case "${1:-handle}" in
  handle) handle ;;
  prepare) prepare ;;
  apply) apply ;;
  status)
    r="$(prepared)"
    if [ -n "$r" ]; then write_status "bereit" "Version ${r:0:7} ist vorbereitet." "$r"
    else write_status "eingerichtet" "Update-Dienst eingerichtet."; fi ;;
  *) echo "Aufruf: $0 handle|prepare|apply|status" >&2; exit 2 ;;
esac
