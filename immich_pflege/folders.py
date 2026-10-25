"""Alben aus Ordnern der externen Bibliothek.

Jeder Ordner (z. B. ``/mnt/fotos/2019 Toskana``) mit mindestens ``MIN_MEDIA`` Medien wird als Album
vorgeschlagen – außer seine Medien liegen schon fast alle (95 %) in Alben. Gibt es ein Album mit dem
Ordnernamen, wird es ergänzt. Auf Wunsch hält das Tool das Album aktuell: Nach jedem Einlesen kommen
neue Dateien aus dem Ordner automatisch hinzu (nur hinzufügen, nie entfernen; im Verlauf rückgängig).
"""

from __future__ import annotations

import hashlib
import json
import logging
import posixpath
import re
import threading
from pathlib import Path
from typing import Any, Iterable

from .library import Library
from .models import Asset

log = logging.getLogger(__name__)

MIN_MEDIA = 5
COMPLETE = 0.95
# Ordnernamen ohne Aussage (Kamera-Ordner, nur Jahreszahl) bekommen den übergeordneten Ordner dazu
GENERIC_RE = re.compile(r"^(\d+|\d{3}[A-Z_]{3,}\w*|dcim|camera|kamera|fotos?|bilder|images?|import\w*)$", re.I)
SYSTEM_DIRS = {"", "mnt", "media", "volume1", "volume2", "srv", "data", "home", "share", "shares", "usr", "photos", "library"}


def folder_name(folder: str) -> str:
    base = posixpath.basename(folder.rstrip("/")) or folder
    parent = posixpath.basename(posixpath.dirname(folder.rstrip("/")))
    if GENERIC_RE.match(base) and parent.lower() not in SYSTEM_DIRS and not GENERIC_RE.match(parent):
        return f"{parent} {base}"
    return base


def folder_key(owner: str, folder: str) -> str:
    return "o" + hashlib.sha1(f"{owner}:{folder}".encode()).hexdigest()[:11]


def folder_groups(lib: Library) -> dict[tuple[str, str], list[Asset]]:
    groups: dict[tuple[str, str], list[Asset]] = {}
    for a in lib.assets.values():
        if a.is_external and a.path:
            groups.setdefault((a.owner, posixpath.dirname(a.path)), []).append(a)
    return groups


def _with_twins(ids: Iterable[str], twins: dict[str, set[str]] | None) -> set[str]:
    """Albuminhalt samt Kopien und Stapel-Geschwistern: liegt eins drin, gilt das andere als enthalten."""
    ids = set(ids)
    return ids.union(*(twins.get(i, ()) for i in ids)) if twins else ids


def proposals(lib: Library, synced: dict[str, Any], twins: dict[str, set[str]] | None = None) -> list[dict[str, Any]]:
    members: dict[str, set[str]] = {aid: _with_twins(al["medien"], twins) for aid, al in lib.albums.items()}
    in_any = set().union(*members.values()) if members else set()
    by_name = {al["name"].strip().lower(): al for al in lib.albums.values() if al["besitzer"]}
    out = []
    for (owner, folder), assets in folder_groups(lib).items():
        if len(assets) < MIN_MEDIA:
            continue
        key = folder_key(owner, folder)
        ids = {a.id for a in assets}
        name = folder_name(folder)
        same = by_name.get(name.lower())
        if key in synced and synced[key]["album"] in lib.albums:
            status, album = "abgeglichen", lib.albums[synced[key]["album"]]
        elif len(ids & in_any) >= COMPLETE * len(ids):
            status, album = "vorhanden", None
        elif same and (same["besitzer"] == owner or same["rollen"].get(owner) in ("owner", "editor")):
            status, album = "ergaenzen", same
        else:
            status, album = "neu", None
        missing = sorted(ids - members[album["id"]]) if album else sorted(ids)
        assets.sort(key=lambda a: (a.local_dt is None, a.local_dt))
        step = max(1, len(assets) // 8)
        out.append({"id": key, "ordner": folder, "benutzer": owner, "name": name, "status": status,
                    "anzahl": len(ids), "fehlend": len(missing),
                    "album": {"id": album["id"], "name": album["name"]} if album else None,
                    "beispiele": [a.summary() for a in assets[::step][:8]]})
    order = {"neu": 0, "ergaenzen": 1, "abgeglichen": 2, "vorhanden": 3}
    out.sort(key=lambda p: (order[p["status"]], p["ordner"].lower()))
    return out


def folder_missing(lib: Library, owner: str, folder: str, album_id: str | None,
                   twins: dict[str, set[str]] | None = None) -> list[str]:
    """Medien des Ordners, die noch nicht im Ziel-Album liegen (alle bei neuem Album)."""
    inside = _with_twins(lib.albums[album_id]["medien"], twins) if album_id in lib.albums else set()
    return sorted(a.id for a in folder_groups(lib).get((owner, folder), []) if a.id not in inside)


def plan_folder(lib: Library, owner: str, folder: str, name: str | None, album_id: str | None,
                sync: bool, without: set[str] | None = None, twins: dict[str, set[str]] | None = None) -> dict[str, Any]:
    """``without``: abgewählte Medien – kommen nicht ins Album, auch später beim Abgleich nicht."""
    without = without or set()
    ids = sorted(a.id for a in folder_groups(lib).get((owner, folder), []))
    if not ids:
        raise ValueError("Ordner nicht gefunden – bitte neu einlesen")
    if album_id:
        inside = _with_twins(lib.albums[album_id]["medien"], twins)
        media = [i for i in ids if i not in inside and i not in without]
        plan = {"aktion": "ergaenzen", "album_id": album_id, "name": lib.albums[album_id]["name"]}
    else:
        media = [i for i in ids if i not in without]
        plan = {"aktion": "neu", "album_id": None, "name": (name or folder_name(folder)).strip()}
    plan.update(besitzer=owner, teilen=[], medien={owner: media} if media else {}, anzahl=len(media),
                hinweise=[], reise=None, alle_medien=ids, ordner_ohne=sorted(without & set(ids)), ordner=folder,
                sync=sync, ordner_key=folder_key(owner, folder))
    return plan


class SyncedFolders:
    """Ordner, deren Album nach jedem Einlesen aktuell gehalten wird (DATA_DIR/ordner_alben.json)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {}
        try:
            if path.exists():
                self.data = json.loads(path.read_text(encoding="utf-8")).get("ordner", {})
        except (OSError, ValueError) as exc:
            log.warning("%s unlesbar: %s", path, exc)

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ordner": self.data}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def set(self, key: str, owner: str, folder: str, album_id: str, without: list[str] | None = None) -> None:
        with self._lock:
            self.data[key] = {"benutzer": owner, "ordner": folder, "album": album_id, "ohne": sorted(without or [])}
            self._save()

    def remove(self, key: str) -> None:
        with self._lock:
            if self.data.pop(key, None) is not None:
                self._save()


def pending_sync(lib: Library, synced: SyncedFolders, twins: dict[str, set[str]] | None = None) -> list[dict[str, Any]]:
    """Neue Dateien in abgeglichenen Ordnern, die noch nicht im Album liegen."""
    groups = folder_groups(lib)
    out = []
    for key, s in list(synced.data.items()):
        album = lib.albums.get(s["album"])
        if album is None:
            synced.remove(key)  # Album gelöscht -> Abgleich beenden
            continue
        skip = _with_twins(album["medien"], twins) | set(s.get("ohne") or [])  # abgewählte bleiben draußen
        new = sorted(a.id for a in groups.get((s["benutzer"], s["ordner"]), []) if a.id not in skip)
        if new:
            out.append({"aktion": "ergaenzen", "album_id": s["album"], "name": album["name"], "besitzer": s["benutzer"],
                        "teilen": [], "medien": {s["benutzer"]: new}, "anzahl": len(new), "ordner": s["ordner"]})
    return out
