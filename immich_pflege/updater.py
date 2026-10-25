"""Verbindung zum Update-Dienst auf dem Docker-Server (updater/pflege-updater.sh).

Die App legt Aufträge in DATA_DIR/updater/request.json ab und liest den Stand aus
DATA_DIR/updater/status.json. Der Container braucht dafür keine Rechte am Docker-Host.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import parse_dt

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=3)  # Dienst läuft stündlich – länger still = nicht verbunden
BUSY = ("vorbereiten", "umschalten")


class Updater:
    def __init__(self, data_dir: Path):
        self.dir = data_dir / "updater"

    @property
    def status_file(self) -> Path:
        return self.dir / "status.json"

    @property
    def request_file(self) -> Path:
        return self.dir / "request.json"

    def status(self) -> dict[str, Any]:
        try:
            data = json.loads(self.status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"verfuegbar": False, "phase": None}
        seen = parse_dt(data.get("zeit"))
        stale = not seen or datetime.now(timezone.utc) - seen > STALE_AFTER
        busy = data.get("phase") in BUSY
        return {**data, "verfuegbar": not stale or busy, "veraltet": stale,
                "auftrag_offen": self.request_file.exists()}

    def request(self, action: str) -> None:
        """Auftrag ablegen. Direkt schreiben (kein Umbenennen) – systemd reagiert aufs Schließen."""
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {"aktion": action, "zeit": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        with open(self.request_file, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        log.info("Auftrag an den Update-Dienst: %s", action)
