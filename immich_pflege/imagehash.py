"""Bild-Fingerabdruck (dHash) aus Immichs Vorschaubildern – findet ähnliche Kopien, deren
Dateien sich unterscheiden (z. B. per WhatsApp verschickt: verkleinert, umbenannt, ohne EXIF).

- dHash mit 64 Bit: Helligkeitsverlauf eines auf 9×8 Pixel verkleinerten Graustufenbilds.
- Zwischengespeichert in DATA_DIR/bildhash.json (pro Medium, solange sich die Prüfsumme nicht ändert).
- Vergleich über 4 Abschnitte à 16 Bit (LSH), danach Hamming-Abstand ≤ MAX_DISTANCE.
"""

from __future__ import annotations

import io
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image

from .client import ImmichClient, ImmichError
from .library import Library
from .models import Asset

log = logging.getLogger(__name__)

MAX_DISTANCE = 6  # von 64 Bit
BANDS = 4
SAVE_EVERY = 200


def dhash(data: bytes) -> int:
    with Image.open(io.BytesIO(data)) as img:
        small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
        px = small.tobytes()  # 72 Graustufenwerte (L-Modus: 1 Byte pro Pixel)
    value = 0
    for row in range(8):
        for col in range(8):
            left, right = px[row * 9 + col], px[row * 9 + col + 1]
            value = (value << 1) | (1 if left > right else 0)
    return value


def distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def hashable(a: Asset) -> bool:
    return a.type == "IMAGE"


def may_pair(a: Asset, b: Asset) -> bool:
    """Nur Paare, bei denen eine ähnliche Kopie plausibel ist – Serienbilder desselben Handys nicht."""
    if a.checksum and a.checksum == b.checksum:
        return False  # identisch: findet schon die Prüfsumme
    if a.owner != b.owner or a.is_external != b.is_external:
        return True
    return not (a.make or a.model) or not (b.make or b.model)  # z. B. WhatsApp-Kopie ohne EXIF


class HashStore:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()
        try:
            if path.exists():
                self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Bild-Fingerabdrücke unlesbar (%s) – werden neu berechnet", exc)

    def get(self, a: Asset) -> int | None:
        entry = self.data.get(a.id)
        if entry and entry.get("c") == a.checksum:
            return int(entry["h"], 16)
        return None

    def put(self, a: Asset, value: int) -> None:
        with self._lock:
            self.data[a.id] = {"c": a.checksum, "h": f"{value:016x}"}

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data), encoding="utf-8")
                tmp.replace(self.path)
            except OSError as exc:
                log.warning("Bild-Fingerabdrücke nicht speicherbar: %s", exc)

    def missing(self, lib: Library) -> list[Asset]:
        return [a for a in lib.assets.values() if hashable(a) and self.get(a) is None]


@dataclass
class HashProgress:
    running: bool = False
    done: int = 0
    total: int = 0
    errors: int = 0
    last_error: str | None = None
    finished_at: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict:
        return {"laeuft": self.running, "fertig": self.done, "gesamt": self.total, "fehler": self.errors,
                "letzter_fehler": self.last_error, "abgeschlossen": self.finished_at}


def compute_missing(lib: Library, clients: dict[str, ImmichClient], store: HashStore,
                    progress: HashProgress, on_save: Callable[[], None] | None = None) -> None:
    from datetime import datetime, timezone

    todo = store.missing(lib)
    progress.running, progress.done, progress.total, progress.errors = True, 0, len(todo), 0
    log.info("Berechne Bild-Fingerabdrücke für %d Medien …", len(todo))
    try:
        for i, a in enumerate(todo, 1):
            if progress.stop.is_set():
                break
            try:
                data, _ = clients[a.owner].thumbnail(a.id)
                store.put(a, dhash(data))
            except (ImmichError, OSError, ValueError) as exc:  # OSError: Bild nicht lesbar
                progress.errors += 1
                progress.last_error = f"{a.file_name}: {exc}"
            progress.done = i
            if i % SAVE_EVERY == 0:
                store.save()
        store.save()
        if on_save:
            on_save()
    finally:
        progress.running = False
        progress.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log.info("Bild-Fingerabdrücke fertig: %d berechnet, %d Fehler", progress.done, progress.errors)


def similar_pairs(lib: Library, store: HashStore, max_distance: int = MAX_DISTANCE) -> list[tuple[str, str]]:
    hashes: list[tuple[Asset, int]] = []
    for a in lib.assets.values():
        if hashable(a):
            h = store.get(a)
            if h is not None:
                hashes.append((a, h))
    buckets: dict[tuple[int, int], list[int]] = {}
    for idx, (_, h) in enumerate(hashes):
        for band in range(BANDS):
            key = (band, (h >> (band * 16)) & 0xFFFF)
            buckets.setdefault(key, []).append(idx)
    pairs: set[tuple[str, str]] = set()
    for members in buckets.values():
        if len(members) < 2 or len(members) > 500:  # sehr große Buckets: einfarbige Bilder o. Ä.
            continue
        for x in range(len(members)):
            a, ha = hashes[members[x]]
            for y in range(x + 1, len(members)):
                b, hb = hashes[members[y]]
                if distance(ha, hb) <= max_distance and may_pair(a, b):
                    pairs.add(tuple(sorted((a.id, b.id))))
    return sorted(pairs)

