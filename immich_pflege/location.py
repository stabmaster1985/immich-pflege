"""Medien ohne GPS finden und Ort vom zeitlich nächsten Foto mit GPS vorschlagen."""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from .client import ImmichClient
from .library import Library
from .models import Asset

log = logging.getLogger(__name__)


@dataclass
class Suggestion:
    source: Asset
    delta_s: float

    @property
    def latitude(self) -> float:
        return float(self.source.latitude)

    @property
    def longitude(self) -> float:
        return float(self.source.longitude)

    def to_dict(self) -> dict[str, Any]:
        return {
            "breite": self.latitude,
            "laenge": self.longitude,
            "ort": self.source.place,
            "abstand_min": round(self.delta_s / 60, 1),
            "abstand_text": format_delta(self.delta_s),
            "quelle_id": self.source.id,
            "quelle_benutzer": self.source.owner,
            "quelle_datei": self.source.file_name,
        }


@dataclass
class Candidate:
    asset: Asset
    suggestion: Suggestion | None
    editable: bool

    def to_dict(self) -> dict[str, Any]:
        return {**self.asset.summary(), "aenderbar": self.editable,
                "vorschlag": self.suggestion.to_dict() if self.suggestion else None}


def format_delta(seconds: float) -> str:
    seconds = abs(seconds)
    if seconds < 60:
        return f"{int(seconds)} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if m else f"{h} h"


class GpsIndex:
    """Sortierter Zeitindex aller Medien mit GPS (über alle Benutzer)."""

    def __init__(self, assets: Iterable[Asset]):
        located = sorted((a for a in assets if a.has_gps and a.taken_utc), key=lambda a: a.taken_utc)
        self.assets = located
        self.times = [a.taken_utc.timestamp() for a in located]

    def nearest(self, asset: Asset, max_hours: float) -> Suggestion | None:
        if not asset.taken_utc or not self.times:
            return None
        t = asset.taken_utc.timestamp()
        i = bisect.bisect_left(self.times, t)
        best: Suggestion | None = None
        for j in (i - 1, i):
            if 0 <= j < len(self.times):
                delta = abs(self.times[j] - t)
                if delta <= max_hours * 3600 and (best is None or delta < best.delta_s):
                    best = Suggestion(self.assets[j], delta)
        return best


def find_candidates(lib: Library, max_hours: float, include_external: bool) -> list[Candidate]:
    index = GpsIndex(lib.assets.values())
    out = []
    for a in lib.assets.values():
        if a.has_gps:
            continue
        out.append(Candidate(a, index.nearest(a, max_hours), include_external or not a.is_external))
    out.sort(key=lambda c: (c.asset.local_date_time or "", c.asset.id), reverse=True)
    return out


def group_by_day(candidates: list[Candidate]) -> list[dict[str, Any]]:
    days: dict[date | None, list[Candidate]] = {}
    for c in candidates:
        days.setdefault(c.asset.local_day, []).append(c)
    result = []
    for day, items in days.items():
        result.append({
            "datum": day.isoformat() if day else None,
            "anzahl": len(items),
            "mit_vorschlag": sum(1 for c in items if c.suggestion),
            "medien": [c.to_dict() for c in items],
        })
    return result


def apply_locations(lib: Library, clients: dict[str, ImmichClient], ids: Iterable[str],
                    max_hours: float, include_external: bool) -> dict[str, Any]:
    wanted = list(dict.fromkeys(ids))
    candidates = {c.asset.id: c for c in find_candidates(lib, max_hours, include_external)}
    skipped: list[dict[str, str]] = []
    buckets: dict[tuple[str, float, float], list[Candidate]] = {}
    for aid in wanted:
        c = candidates.get(aid)
        if c is None:
            reason = "unbekannt" if aid not in lib.assets else "hat schon einen Ort"
            skipped.append({"id": aid, "grund": reason})
        elif not c.editable:
            skipped.append({"id": aid, "grund": "externe Bibliothek (LOCATION_INCLUDE_EXTERNAL=false)"})
        elif c.suggestion is None:
            skipped.append({"id": aid, "grund": "kein Foto mit GPS im Zeitfenster"})
        else:
            key = (c.asset.owner, c.suggestion.latitude, c.suggestion.longitude)
            buckets.setdefault(key, []).append(c)

    updated = 0
    for (owner, lat, lon), items in buckets.items():
        updated += clients[owner].set_location([c.asset.id for c in items], lat, lon)
        for c in items:
            src = c.suggestion.source
            a = c.asset
            a.latitude, a.longitude = lat, lon
            a.city, a.state, a.country = src.city, src.state, src.country
    if updated:
        log.info("Ort für %d Medien übernommen", updated)
    return {"aktualisiert": updated, "uebersprungen": skipped}
