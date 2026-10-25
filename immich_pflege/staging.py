"""Vormerkliste: Änderungen erst sammeln, prüfen und dann gesammelt an Immich übertragen.

Gespeichert in DATA_DIR/vorgemerkt.json. Vorgemerktes verschwindet aus den Übersichten.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

TYPES = ("duplikat", "ort", "tag")
SAMPLES = 8


class StagingStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.entries: list[dict[str, Any]] = []
        try:
            if path.exists():
                self.entries = json.loads(path.read_text(encoding="utf-8")).get("eintraege", [])
        except (OSError, ValueError) as exc:
            log.warning("Vormerkliste unlesbar (%s) – starte leer", exc)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"eintraege": self.entries}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("Vormerkliste nicht speicherbar: %s", exc)

    def add(self, typ: str, title: str, payload: dict[str, Any], media: list[dict[str, Any]],
            count: int, key: str | None = None) -> dict[str, Any]:
        """Neuer Eintrag. ``key`` verhindert Doppelte (z. B. Gruppen-ID); ein gleicher Key ersetzt."""
        assert typ in TYPES
        entry = {
            "id": uuid.uuid4().hex[:12],
            "typ": typ,
            "key": key,
            "titel": title,
            "anzahl": count,
            "erstellt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "medien": media[:SAMPLES],
            "daten": payload,
            "fehler": None,
        }
        with self._lock:
            if key:
                self.entries = [e for e in self.entries if not (e["typ"] == typ and e.get("key") == key)]
            self.entries.append(entry)
            self._save()
        return entry

    def remove(self, entry_ids: Iterable[str]) -> int:
        ids = set(entry_ids)
        with self._lock:
            before = len(self.entries)
            self.entries = [e for e in self.entries if e["id"] not in ids]
            self._save()
            return before - len(self.entries)

    def set_error(self, entry_id: str, message: str | None) -> None:
        with self._lock:
            for e in self.entries:
                if e["id"] == entry_id:
                    e["fehler"] = message
            self._save()

    def of_type(self, typ: str) -> list[dict[str, Any]]:
        return [e for e in self.entries if e["typ"] == typ]

    def asset_ids(self, typ: str) -> set[str]:
        """Alle Medien, die in Einträgen dieses Typs stecken (für das Ausblenden in den Übersichten)."""
        out: set[str] = set()
        for e in self.of_type(typ):
            d = e["daten"]
            if typ == "duplikat":
                out.update(d.get("alle_medien", []))
            elif typ == "ort":
                out.update(ch["asset_id"] for ch in d.get("aenderungen", []))
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "anzahl": len(self.entries),
            "nach_typ": {t: sum(1 for e in self.entries if e["typ"] == t) for t in TYPES},
            "medien": sum(e["anzahl"] for e in self.entries),
            "papierkorb": sum(sum(1 for s in e["daten"].get("schritte", []) if s["aktion"] == "papierkorb")
                              for e in self.of_type("duplikat")),
        }
