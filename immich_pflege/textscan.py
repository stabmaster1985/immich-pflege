"""Texterkennung (OCR) aus Immich: Wie viel vom Bild ist Text?

Immich 3.x erkennt Text in Bildern (Einstellung „Texterkennung“ im maschinellen Lernen) und liefert
ihn mit ``GET /assets/{id}/ocr`` als Textfelder samt Ecken (0–1 relativ zum Bild). Daraus berechnet
das Tool die Textfläche und die Zeichenzahl. Viel Text heißt: Dokument, Quittung, Speisekarte,
abfotografierter Bildschirm oder Screenshot – solche Bilder brauchen meist keinen Ort, auch wenn
sie Kameradaten haben.

Abgefragt werden nur Bilder ohne Ort; das Ergebnis liegt in DATA_DIR/texterkennung.json und wird
nur neu geholt, wenn sich die Datei (Prüfsumme) ändert.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .client import ImmichClient, ImmichError
from .models import Asset

log = logging.getLogger(__name__)

DOC_AREA = 0.10  # ab 10 % Textfläche …
DOC_CHARS = 300  # … oder 300 erkannten Zeichen gilt ein Bild als Dokument/Textbild
MIN_SCORE = 0.5  # unsichere Textfelder nicht mitzählen
WORKERS = 4
SAVE_EVERY = 200


def _area(box: dict[str, Any]) -> float:
    """Fläche des Vierecks (Gaußsche Trapezformel, relative Koordinaten)."""
    xs = [box.get(f"x{i}") or 0.0 for i in range(1, 5)]
    ys = [box.get(f"y{i}") or 0.0 for i in range(1, 5)]
    return abs(sum(xs[i] * ys[(i + 1) % 4] - xs[(i + 1) % 4] * ys[i] for i in range(4))) / 2


def text_stats(boxes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """{f: Textfläche 0–1, n: Zeichen, t: Textanfang} aus den OCR-Feldern."""
    good = [b for b in boxes if (b.get("textScore") or 0) >= MIN_SCORE and (b.get("text") or "").strip()]
    text = " ".join(b["text"].strip() for b in good)
    return {"f": round(min(1.0, sum(_area(b) for b in good)), 4), "n": len(text.replace(" ", "")), "t": text[:80]}


def is_document(stats: dict[str, Any] | None) -> bool:
    return bool(stats) and (stats["f"] >= DOC_AREA or stats["n"] >= DOC_CHARS)


class TextStore:
    """Zwischenspeicher der Texterkennung je Medium (gültig, solange die Prüfsumme gleich ist)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, dict[str, Any]] = {}
        self.rev = 0  # zählt hoch, sobald neue Ergebnisse da sind (für Zwischenstände der Ansicht)
        try:
            if path.exists():
                self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("%s unlesbar: %s", path, exc)

    def get(self, a: Asset) -> dict[str, Any] | None:
        entry = self.data.get(a.id)
        return entry if entry and entry.get("c") == a.checksum else None

    def put(self, a: Asset, stats: dict[str, Any]) -> None:
        with self._lock:
            self.data[a.id] = {"c": a.checksum, **stats}

    def save(self) -> None:
        with self._lock:
            self.rev += 1
            try:
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.path)
            except OSError as exc:
                log.warning("Texterkennung nicht speicherbar: %s", exc)


@dataclass
class TextProgress:
    running: bool = False
    done: int = 0
    total: int = 0
    with_text: int = 0
    errors: int = 0
    finished_at: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, Any]:
        return {"laeuft": self.running, "fertig": self.done, "gesamt": self.total, "mit_text": self.with_text,
                "fehler": self.errors, "abgeschlossen": self.finished_at}


def fetch_missing(assets: list[Asset], clients: dict[str, ImmichClient], store: TextStore,
                  progress: TextProgress, on_save: Callable[[], None] | None = None) -> None:
    """Texterkennung für Bilder holen, die noch nicht im Zwischenspeicher liegen (mit dem Key des Besitzers)."""
    todo = [a for a in assets if a.type == "IMAGE" and a.owner in clients and store.get(a) is None]
    progress.running, progress.done, progress.total, progress.with_text = True, 0, len(todo), 0
    if todo:
        log.info("Hole Texterkennung für %d Bilder ohne Ort …", len(todo))

    def one(a: Asset) -> tuple[Asset, dict[str, Any] | None]:
        try:
            return a, text_stats(clients[a.owner].ocr(a.id))
        except ImmichError as exc:
            log.debug("Texterkennung %s: %s", a.file_name, exc)
            return a, None

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for i, (a, stats) in enumerate(pool.map(one, todo), 1):
                if progress.stop.is_set():
                    break
                if stats is None:
                    progress.errors += 1
                else:
                    store.put(a, stats)
                    progress.with_text += is_document(stats)
                progress.done = i
                if i % SAVE_EVERY == 0:
                    store.save()
                    if on_save:
                        on_save()
        if todo:
            store.save()
            if on_save:
                on_save()
    finally:
        progress.running = False
        progress.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
