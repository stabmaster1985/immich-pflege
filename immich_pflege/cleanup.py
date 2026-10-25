"""Aufräumen: Speicherfresser, Serienbilder, unscharfe/dunkle Fotos.

Jeder Treffer ist ein Eintrag mit einem oder mehreren Medien; Medien mit ``aktion="weg"`` gehen
beim Übertragen ins Prüf-Album oder in den Papierkorb (dieselben Schutzregeln wie bei Duplikaten).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .duplicates import PlannedStep, split_name
from .imagehash import HashStore, distance
from .library import Library
from .location import is_screenshot
from .models import Asset

log = logging.getLogger(__name__)

MB = 1024 * 1024
BIG_VIDEO_MB = 300  # Videos ab dieser Größe
LIVE_MAX_S = 3.5  # Live-Photo-Videos sind ~3 s lang
LIVE_DELTA_S = 2  # und zur selben Sekunde wie das Foto aufgenommen
BURST_GAP_S = 2  # Serienbild: höchstens 2 s Abstand zum vorigen Foto
BURST_MIN = 3
BURST_MAX_DIST = 12  # Fingerabdruck-Abstand innerhalb einer Serie (von 64 Bit)
DARK_MAX = 25  # Helligkeit 0–255
BLUR_MAX = 3.0  # Schärfe (Streuung nach Laplace-Filter, Vorschaubild 250 px)
SCREEN_RE = re.compile(r"^(screenrecording|rpreplay|bildschirmaufnahme|screen[_ -]?record)", re.I)

ARTEN = {"speicher": "Speicherfresser", "serien": "Serienbilder", "qualitaet": "Unscharf & dunkel", "verwaist": "Verwaiste Dateien"}
KATEGORIEN = {
    "grosse_videos": ("speicher", f"Videos ab {BIG_VIDEO_MB} MB"),
    "bildschirmaufnahmen": ("speicher", "Bildschirmaufnahmen"),
    "live_videos": ("speicher", "Live-Photo-Videos doppelt"),
    "serien": ("serien", "Serienbilder"),
    "versehentlich": ("qualitaet", "Versehentlich (dunkel und unscharf)"),
    "dunkel": ("qualitaet", "Sehr dunkel"),
    "unscharf": ("qualitaet", "Unscharf"),
    "offline": ("verwaist", "Datei fehlt (offline)"),
}


@dataclass
class Item:
    kategorie: str
    assets: list[Asset]
    drop: set[str]  # IDs, die weg sollen
    grund: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return "a" + hashlib.sha1((self.kategorie + ",".join(sorted(a.id for a in self.assets))).encode()).hexdigest()[:11]

    @property
    def ids(self) -> set[str]:
        return {a.id for a in self.assets}

    @property
    def size(self) -> int:
        return sum(a.file_size or 0 for a in self.assets if a.id in self.drop)

    def to_dict(self) -> dict[str, Any]:
        art, label = KATEGORIEN[self.kategorie]
        return {
            "id": self.id, "art": art, "kategorie": self.kategorie, "kategorie_text": label,
            "grund": self.grund, "groesse": self.size, **self.extra,
            "medien": [{**a.summary(), "aktion": "weg" if a.id in self.drop else "bleibt"} for a in self.assets],
        }

    def steps(self, action: str) -> list[PlannedStep]:
        out = []
        for a in self.assets:
            if a.id not in self.drop:
                continue
            act = action
            if action == "papierkorb" and a.is_external and not a.offline:
                act = "album"  # externe Medien nie in den Papierkorb (außer die Datei fehlt ohnehin)
            out.append(PlannedStep(a, act, KATEGORIEN[self.kategorie][1]))
        return out


# ------------------------------------------------------------ Speicher
def storage_hogs(lib: Library) -> list[Item]:
    items: list[Item] = []
    images: dict[tuple[str, str], list[Asset]] = {}
    for a in lib.assets.values():
        if a.type == "IMAGE" and a.taken_utc:
            images.setdefault((a.owner, split_name(a.file_name)[0]), []).append(a)
    for a in lib.assets.values():
        if a.type != "VIDEO" or a.favorite or a.in_review_album:
            continue
        size = a.file_size or 0
        if SCREEN_RE.match(a.file_name or "") or (not a.make and not a.model and is_screenshot(a)):
            items.append(Item("bildschirmaufnahmen", [a], {a.id}, f"{size / MB:.0f} MB"))
        elif a.duration_ms and a.duration_ms <= LIVE_MAX_S * 1000 and a.taken_utc:
            twins = [p for p in images.get((a.owner, split_name(a.file_name)[0]), [])
                     if abs((p.taken_utc - a.taken_utc).total_seconds()) <= LIVE_DELTA_S]
            if twins:
                items.append(Item("live_videos", [twins[0], a], {a.id},
                                  "Kurzes Video zur selben Sekunde wie das Foto – das Live-Photo hat es schon"))
        elif size >= BIG_VIDEO_MB * MB:
            mins = f", {a.duration_ms / 60000:.0f} min" if a.duration_ms else ""
            items.append(Item("grosse_videos", [a], {a.id}, f"{size / MB:.0f} MB{mins}"))
    items.sort(key=lambda i: i.size, reverse=True)
    return items


# ------------------------------------------------------------- Serien
def bursts(lib: Library, store: HashStore) -> list[Item]:
    by_cam: dict[tuple, list[Asset]] = {}
    for a in lib.assets.values():
        if a.type == "IMAGE" and a.taken_utc and not a.in_review_album and not a.stack_id and not is_screenshot(a):
            by_cam.setdefault((a.owner, a.make, a.model, a.is_external), []).append(a)
    items: list[Item] = []
    for photos in by_cam.values():
        photos.sort(key=lambda a: a.taken_utc)
        run: list[Asset] = []
        for a in photos + [None]:  # None schließt die letzte Serie ab
            if a is not None and run and (a.taken_utc - run[-1].taken_utc).total_seconds() <= BURST_GAP_S \
                    and _similar(store, run[-1], a):
                run.append(a)
                continue
            if len(run) >= BURST_MIN:
                items.append(_burst_item(run, store))
            run = [a] if a is not None else []
    items.sort(key=lambda i: i.assets[0].taken_utc, reverse=True)
    return items


def _similar(store: HashStore, a: Asset, b: Asset) -> bool:
    ha, hb = store.get(a), store.get(b)
    return ha is None or hb is None or distance(ha, hb) <= BURST_MAX_DIST


def _burst_item(run: list[Asset], store: HashStore) -> Item:
    def rank(a: Asset):
        q = store.quality(a)
        return (a.favorite, a.in_album, q[0] if q else 0.0, -run.index(a))
    keep = max(run, key=rank)
    q = store.quality(keep)
    why = "Favorit" if keep.favorite else "in einem Album" if keep.in_album else "das schärfste" if q else "das erste"
    secs = (run[-1].taken_utc - run[0].taken_utc).total_seconds()
    return Item("serien", run, {a.id for a in run if a.id != keep.id},
                f"{len(run)} Aufnahmen in {secs:.0f} s – behalten wird {why}",
                {"sekunden": secs})


# ------------------------------------------------------------ Qualität
def poor_quality(lib: Library, store: HashStore, exclude: set[str] | None = None) -> list[Item]:
    """``exclude``: Medien, die schon in einer Serie stecken (dort wird das schärfste behalten)."""
    exclude = exclude or set()
    items: list[Item] = []
    for a in lib.assets.values():
        if a.type != "IMAGE" or a.favorite or a.in_review_album or a.id in exclude or is_screenshot(a):
            continue
        q = store.quality(a)
        if q is None:
            continue
        sharp, bright = q
        dark, blurry = bright <= DARK_MAX, sharp <= BLUR_MAX
        if dark and blurry:
            kind = "versehentlich"
        elif dark:
            kind = "dunkel"
        elif blurry:
            kind = "unscharf"
        else:
            continue
        items.append(Item(kind, [a], {a.id}, f"Schärfe {sharp:.1f} · Helligkeit {bright:.0f}",
                          {"schaerfe": sharp, "helligkeit": bright}))
    order = {"versehentlich": 0, "dunkel": 1, "unscharf": 2}
    items.sort(key=lambda i: (order[i.kategorie], i.extra["schaerfe"]))
    return items


def orphans(lib: Library) -> list[Item]:
    """Externe Medien, deren Datei auf der Platte fehlt (verschoben, umbenannt oder gelöscht)."""
    items = [Item("offline", [a], {a.id}, a.path) for a in lib.assets.values() if a.offline]
    items.sort(key=lambda i: i.assets[0].path)
    return items


def find_items(lib: Library, store: HashStore) -> list[Item]:
    series = bursts(lib, store)
    in_series = {i for item in series for i in item.ids}
    return storage_hogs(lib) + series + poor_quality(lib, store, in_series) + orphans(lib)


# -------------------------------------------------------------- Behalten
class KeepList:
    """„Behalten“: Einträge dauerhaft ausblenden (DATA_DIR/aufraeumen_behalten.json)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.ids: set[str] = set()
        try:
            if path.exists():
                self.ids = set(json.loads(path.read_text(encoding="utf-8")).get("eintraege", []))
        except (OSError, ValueError) as exc:
            log.warning("%s unlesbar: %s", path, exc)

    def update(self, ids: Iterable[str], remove: bool = False) -> None:
        with self._lock:
            self.ids = self.ids - set(ids) if remove else self.ids | set(ids)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"eintraege": sorted(self.ids)}), encoding="utf-8")
            tmp.replace(self.path)
