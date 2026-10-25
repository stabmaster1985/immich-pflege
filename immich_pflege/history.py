"""Verlauf: jede Übertragung an Immich mit den Schritten, um sie rückgängig zu machen.

Gespeichert in DATA_DIR/verlauf.json (die letzten ``KEEP`` Einträge). Ein Rückgängig-Schritt ist
ein kleines Wörterbuch ``{"op": …, "user": …, …}``, ausgeführt mit dem Key dieses Benutzers:

- ``album_entfernen``  {album, ids}       Medien wieder aus einem Album nehmen
- ``wiederherstellen`` {ids, medien}      aus dem Papierkorb holen (medien: gespeicherte Assets)
- ``album_loeschen``   {album}            angelegtes Album löschen (die Medien bleiben)
- ``teilen_aufheben``  {album, nutzer}    Freigabe für einen Benutzer zurücknehmen
- ``tag_entfernen``    {tag, ids}         gesetzten Tag wieder abnehmen
- ``zeit``             {ids, minuten}     Aufnahmezeit zurückverschieben
- ``stapel_aufloesen`` {stack, ids}       angelegten Stapel wieder auflösen
- ``album_hinzufuegen`` {album, ids}      wieder ins Album legen
- ``album_wiederherstellen`` {name, rollen, medien}  gelöschtes Album neu anlegen (mit Inhalt und Freigaben)
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .client import ImmichClient, ImmichError
from .library import Library
from .models import Asset

log = logging.getLogger(__name__)

KEEP = 500
NOT_UNDOABLE = {
    "ort": "Immich kann Koordinaten nur ändern, nicht entfernen – bei Bedarf einen anderen Ort setzen.",
    "papierkorb": "Wieder löschen geht über Duplikate oder Aufräumen.",
}


class HistoryStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.entries: list[dict[str, Any]] = []
        try:
            if path.exists():
                self.entries = json.loads(path.read_text(encoding="utf-8")).get("eintraege", [])
        except (OSError, ValueError) as exc:
            log.warning("Verlauf unlesbar (%s) – starte leer", exc)

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"eintraege": self.entries[-KEEP:]}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("Verlauf nicht speicherbar: %s", exc)

    def add(self, typ: str, title: str, count: int, undo: list[dict[str, Any]],
            source: str = "oberflaeche", details: dict[str, Any] | None = None) -> dict[str, Any]:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "zeit": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "typ": typ,
            "titel": title,
            "anzahl": count,
            "quelle": source,
            "rueck": undo,
            "nicht_rueckgaengig": None if undo else NOT_UNDOABLE.get(typ, "Nichts zurückzunehmen"),
            "rueckgaengig": None,
            "details": details or {},
        }
        with self._lock:
            self.entries.append(entry)
            self.entries = self.entries[-KEEP:]
            self._save()
        return entry

    def get(self, entry_id: str) -> dict[str, Any] | None:
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def mark_undone(self, entry_id: str, errors: list[str]) -> None:
        with self._lock:
            e = self.get(entry_id)
            if e:
                e["rueckgaengig"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                e["rueck_fehler"] = errors
                self._save()

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for e in reversed(self.entries[-limit:]):
            item = {k: v for k, v in e.items() if k != "rueck"}
            item["rueckgaengig_moeglich"] = bool(e["rueck"]) and not e["rueckgaengig"]
            out.append(item)
        return out

    def per_month(self) -> dict[str, dict[str, int]]:
        """Übertragene Medien je Monat und Art – für die Übersicht."""
        out: dict[str, dict[str, int]] = {}
        for e in self.entries:
            if e["rueckgaengig"]:
                continue
            m = e["zeit"][:7]
            out.setdefault(m, {})
            out[m][e["typ"]] = out[m].get(e["typ"], 0) + e["anzahl"]
        return out


def undo_ops(lib: Library | None, clients: dict[str, ImmichClient], ops: list[dict[str, Any]]) -> list[str]:
    """Rückgängig-Schritte in umgekehrter Reihenfolge ausführen. Liefert Fehlermeldungen."""
    errors: list[str] = []
    for op in reversed(ops):
        if op["op"] == "album_wiederherstellen":  # braucht die Keys mehrerer Benutzer
            from .albumcare import restore_album
            try:
                restore_album(lib, clients, op)
            except (ImmichError, KeyError) as exc:
                errors.append(f"Album „{op['name']}“ nicht wiederhergestellt: {exc}")
            continue
        client = clients.get(op["user"])
        if client is None:
            errors.append(f"Kein API-Key mehr für {op['user']}")
            continue
        try:
            _undo_one(lib, client, op)
        except ImmichError as exc:
            errors.append(f"{op['op']} ({op['user']}): {exc}")
    return errors


def _undo_one(lib: Library | None, client: ImmichClient, op: dict[str, Any]) -> None:
    kind = op["op"]
    if kind == "album_entfernen":
        client.remove_from_album(op["album"], op["ids"])
        if lib:
            review = op["album"] in lib.review_albums.values()
            album = lib.albums.get(op["album"])
            if album:
                album["medien"] = sorted(set(album["medien"]) - set(op["ids"]))
            for i in op["ids"]:
                if i in lib.assets and review:
                    lib.assets[i].in_review_album = False
    elif kind == "wiederherstellen":
        client.restore_trash(op["ids"])
        if lib:
            for data in op.get("medien", []):
                lib.assets[data["id"]] = Asset.from_dict(data)
    elif kind == "album_loeschen":
        client.delete_album(op["album"])
        if lib:
            lib.albums.pop(op["album"], None)
    elif kind == "teilen_aufheben":
        client.unshare_album(op["album"], op["nutzer"])
        if lib and op["album"] in lib.albums:
            names = {u["id"]: n for n, u in lib.users.items()}
            lib.albums[op["album"]]["rollen"].pop(names.get(op["nutzer"], ""), None)
    elif kind == "tag_entfernen":
        client.untag_assets(op["tag"], op["ids"])
    elif kind == "stapel_aufloesen":
        client.delete_stack(op["stack"])
        if lib:
            for i in op["ids"]:
                if i in lib.assets and lib.assets[i].stack_id == op["stack"]:
                    lib.assets[i].stack_id = None
    elif kind == "album_hinzufuegen":
        client.add_to_album(op["album"], op["ids"])
        if lib and op["album"] in lib.albums:
            album = lib.albums[op["album"]]
            album["medien"] = sorted(set(album["medien"]) | set(op["ids"]))
    elif kind == "zeit":
        client.shift_time(op["ids"], op["minuten"])
        if lib:
            shift_local(lib, op["ids"], op["minuten"])
    else:
        raise ImmichError(f"Unbekannter Rückgängig-Schritt {kind!r}")


def shift_local(lib: Library, ids: list[str], minutes: int) -> None:
    """Zwischenspeicher nachziehen, nachdem die Aufnahmezeit in Immich verschoben wurde."""
    delta = timedelta(minutes=minutes)
    for i in ids:
        a = lib.assets.get(i)
        if a is None:
            continue
        data = a.to_dict()
        for key in ("local_date_time", "file_created_at"):
            if data[key]:
                t = datetime.fromisoformat(data[key].replace("Z", "+00:00")) + delta
                data[key] = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        lib.assets[i] = Asset.from_dict(data)
