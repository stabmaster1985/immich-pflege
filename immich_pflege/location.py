"""Medien ohne GPS finden, Orte vorschlagen und zu Serien zusammenfassen.

Vorschläge (mit Sicherheit):
- **hoch**: ein Foto mit GPS liegt höchstens 30 min entfernt, oder die GPS-Fotos davor und
  danach (beide im Zeitfenster) liegen am selben Ort.
- **mittel**: ein Foto mit GPS liegt im Zeitfenster, aber weiter weg oder die Nachbarn
  widersprechen sich.
- **niedrig**: kein GPS-Foto im Zeitfenster, aber das letzte davor und das erste danach
  (je höchstens 12 h) liegen am selben Ort – oder der Ort stammt aus derselben Serie.

Serien: Medien ohne Ort, zwischen denen höchstens 2 h liegen. Sind sich alle Vorschläge einer
Serie über den Ort einig, bekommen auch die Medien ohne eigenen Vorschlag den Ort der Serie.
"""

from __future__ import annotations

import bisect
import hashlib
import logging
import math
import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Iterable

from .client import ImmichClient
from .library import Library
from .models import Asset

log = logging.getLogger(__name__)

SAME_PLACE_KM = 1.5
SURE_DELTA_S = 30 * 60
BRACKET_MAX_S = 12 * 3600
SERIES_GAP_S = 2 * 3600
LEVELS = ("niedrig", "mittel", "hoch")
SCREENSHOT_RE = re.compile(
    r"^(screenshot|screen shot|bildschirmfoto|bildschirmaufnahme|simulator screen shot|"
    r"rpreplay|screenrecording|screen recording)", re.IGNORECASE)


def is_screenshot(a: Asset) -> bool:
    if SCREENSHOT_RE.match(a.file_name or ""):
        return True
    # iPhone-Screenshots heißen auch IMG_1234.PNG – erkennbar an fehlenden Kameradaten
    return (a.file_name or "").lower().endswith(".png") and not a.make and not a.model


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def level_at_least(value: str, minimum: str) -> bool:
    return LEVELS.index(value) >= LEVELS.index(minimum)


def format_delta(seconds: float) -> str:
    seconds = abs(seconds)
    if seconds < 60:
        return f"{int(seconds)} s"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if m else f"{h} h"


@dataclass
class Suggestion:
    latitude: float
    longitude: float
    place: str | None
    confidence: str  # niedrig | mittel | hoch
    reason: str
    delta_s: float | None = None
    source: Asset | None = None
    method: str = "naechstes"  # naechstes | zwischen | serie | manuell

    def same_place(self, other: "Suggestion") -> bool:
        return km(self.latitude, self.longitude, other.latitude, other.longitude) <= SAME_PLACE_KM

    def to_dict(self) -> dict[str, Any]:
        out = {
            "breite": self.latitude,
            "laenge": self.longitude,
            "ort": self.place,
            "sicherheit": self.confidence,
            "grund": self.reason,
            "methode": self.method,
            "abstand_min": round(self.delta_s / 60, 1) if self.delta_s is not None else None,
            "abstand_text": format_delta(self.delta_s) if self.delta_s is not None else None,
        }
        if self.source:
            out.update({"quelle_id": self.source.id, "quelle_benutzer": self.source.owner,
                        "quelle_datei": self.source.file_name})
        return out


def _from(src: Asset, delta: float, confidence: str, reason: str, method: str = "naechstes") -> Suggestion:
    return Suggestion(float(src.latitude), float(src.longitude), src.place, confidence, reason, delta, src, method)


@dataclass
class Candidate:
    asset: Asset
    suggestion: Suggestion | None
    editable: bool
    series_id: str | None = None

    @property
    def applicable(self) -> bool:
        return self.editable and self.suggestion is not None

    def to_dict(self) -> dict[str, Any]:
        return {**self.asset.summary(), "aenderbar": self.editable, "serie": self.series_id,
                "vorschlag": self.suggestion.to_dict() if self.suggestion else None}


class GpsIndex:
    """Sortierter Zeitindex aller Medien mit GPS (über alle Benutzer)."""

    def __init__(self, assets: Iterable[Asset]):
        located = sorted((a for a in assets if a.has_gps and a.taken_utc), key=lambda a: a.taken_utc)
        self.assets = located
        self.times = [a.taken_utc.timestamp() for a in located]

    def neighbors(self, asset: Asset) -> tuple[tuple[Asset, float] | None, tuple[Asset, float] | None]:
        t = asset.taken_utc.timestamp()
        i = bisect.bisect_left(self.times, t)
        prev = (self.assets[i - 1], t - self.times[i - 1]) if i > 0 else None
        nxt = (self.assets[i], self.times[i] - t) if i < len(self.times) else None
        return prev, nxt

    def suggest(self, asset: Asset, max_hours: float) -> Suggestion | None:
        if not asset.taken_utc or not self.times:
            return None
        prev, nxt = self.neighbors(asset)
        window = max_hours * 3600
        sides = [(s, label) for s, label in ((prev, "vorher"), (nxt, "nachher")) if s]
        within = [(s, label) for s, label in sides if s[1] <= window]
        if within:
            (best, delta), label = min(within, key=lambda x: x[0][1])
            text = f"{format_delta(delta)} {label} bei {best.owner}"
            others = [s for s, _ in within if s[0] is not best]
            if others:
                other = others[0][0]
                same = km(best.latitude, best.longitude, other.latitude, other.longitude) <= SAME_PLACE_KM
                if same:
                    return _from(best, delta, "hoch", f"{text}; davor und danach derselbe Ort")
                if delta > SURE_DELTA_S:
                    return _from(best, delta, "mittel", f"{text}; davor und danach verschiedene Orte")
            if delta <= SURE_DELTA_S:
                return _from(best, delta, "hoch", text)
            return _from(best, delta, "mittel", text)
        if prev and nxt and prev[1] <= BRACKET_MAX_S and nxt[1] <= BRACKET_MAX_S:
            a, b = prev[0], nxt[0]
            if km(a.latitude, a.longitude, b.latitude, b.longitude) <= SAME_PLACE_KM:
                best, delta = min((prev, nxt), key=lambda x: x[1])
                return _from(best, delta, "niedrig",
                             f"zwischen zwei Fotos am selben Ort ({format_delta(prev[1])} vorher, "
                             f"{format_delta(nxt[1])} nachher)", method="zwischen")
        return None

    # Kompatibilität
    def nearest(self, asset: Asset, max_hours: float) -> Suggestion | None:
        s = self.suggest(asset, max_hours)
        return s if s and s.method == "naechstes" else None


@dataclass
class Series:
    id: str
    members: list[Candidate]
    suggestion: Suggestion | None = None
    several_places: bool = False

    def to_dict(self, with_members: bool = True) -> dict[str, Any]:
        times = [c.asset.local_dt for c in self.members if c.asset.local_dt]
        start, end = (min(times), max(times)) if times else (None, None)
        levels = [c.suggestion.confidence for c in self.members if c.applicable]
        out: dict[str, Any] = {
            "id": self.id,
            "datum": start.date().isoformat() if start else None,
            "start": start.isoformat(sep=" ") if start else None,
            "ende": end.isoformat(sep=" ") if end else None,
            "anzahl": len(self.members),
            "benutzer": sorted({c.asset.owner for c in self.members}),
            "mit_vorschlag": sum(1 for c in self.members if c.applicable),
            "aenderbar": sum(1 for c in self.members if c.editable),
            "mehrere_orte": self.several_places,
            "vorschlag": self.suggestion.to_dict() if self.suggestion else None,
            "sicherheit": min(levels, key=LEVELS.index) if levels else None,
        }
        if with_members:
            out["medien"] = [c.to_dict() for c in self.members]
        return out


@dataclass
class Analysis:
    candidates: list[Candidate]
    series: list[Series]
    screenshots: int = 0
    by_id: dict[str, Candidate] = field(default_factory=dict)


def _series_id(ids: Iterable[str]) -> str:
    return hashlib.sha1(",".join(sorted(ids)).encode()).hexdigest()[:12]


def _build_series(cands: list[Candidate]) -> list[Series]:
    timed = sorted((c for c in cands if c.asset.taken_utc), key=lambda c: c.asset.taken_utc)
    groups: list[list[Candidate]] = []
    for c in timed:
        if groups and (c.asset.taken_utc - groups[-1][-1].asset.taken_utc).total_seconds() <= SERIES_GAP_S:
            groups[-1].append(c)
        else:
            groups.append([c])
    groups += [[c] for c in cands if not c.asset.taken_utc]

    series = []
    for members in groups:
        s = Series(_series_id(c.asset.id for c in members), members)
        own = [c.suggestion for c in members if c.suggestion]
        if own:
            best = max(own, key=lambda x: (LEVELS.index(x.confidence), -(x.delta_s or 0)))
            if all(best.same_place(o) for o in own):
                s.suggestion = best
                inherited_level = "mittel" if best.confidence == "hoch" else "niedrig"
                n = len(own)
                for c in members:
                    if c.suggestion is None:
                        c.suggestion = replace(best, confidence=inherited_level, method="serie",
                                               reason=f"aus derselben Serie ({n} von {len(members)} "
                                                      f"mit eigenem Vorschlag)")
            else:
                s.several_places = True
        for c in members:
            c.series_id = s.id
        series.append(s)
    series.sort(key=lambda s: max((c.asset.local_date_time or "") for c in s.members), reverse=True)
    return series


def analyze(lib: Library, max_hours: float, include_external: bool,
            skip_screenshots: bool = True) -> Analysis:
    index = GpsIndex(lib.assets.values())
    cands: list[Candidate] = []
    screenshots = 0
    for a in lib.assets.values():
        if a.has_gps:
            continue
        if skip_screenshots and is_screenshot(a):
            screenshots += 1
            continue
        cands.append(Candidate(a, index.suggest(a, max_hours), include_external or not a.is_external))
    series = _build_series(cands)
    cands.sort(key=lambda c: (c.asset.local_date_time or "", c.asset.id), reverse=True)
    return Analysis(cands, series, screenshots, {c.asset.id: c for c in cands})


def find_candidates(lib: Library, max_hours: float, include_external: bool,
                    skip_screenshots: bool = True) -> list[Candidate]:
    return analyze(lib, max_hours, include_external, skip_screenshots).candidates


def group_by_day(candidates: list[Candidate]) -> list[dict[str, Any]]:
    days: dict[date | None, list[Candidate]] = {}
    for c in candidates:
        days.setdefault(c.asset.local_day, []).append(c)
    return [{
        "datum": day.isoformat() if day else None,
        "anzahl": len(items),
        "mit_vorschlag": sum(1 for c in items if c.suggestion),
        "medien": [c.to_dict() for c in items],
    } for day, items in days.items()]


def apply_locations(lib: Library, clients: dict[str, ImmichClient], ids: Iterable[str] | None,
                    max_hours: float, include_external: bool, *, skip_screenshots: bool = True,
                    min_confidence: str | None = None, manual: tuple[float, float, str | None] | None = None
                    ) -> dict[str, Any]:
    """Ort setzen: vorgeschlagenen Ort (ids), alle ab einer Sicherheit (min_confidence)
    oder einen von Hand gewählten Ort (manual = (breite, länge, name)) für ids."""
    analysis = analyze(lib, max_hours, include_external, skip_screenshots)
    if ids is None:
        if not min_confidence:
            raise ValueError("ids oder min_confidence angeben")
        ids = [c.asset.id for c in analysis.candidates
               if c.applicable and level_at_least(c.suggestion.confidence, min_confidence)]
    wanted = list(dict.fromkeys(ids))
    skipped: list[dict[str, str]] = []
    buckets: dict[tuple[str, float, float], list[tuple[Candidate, Suggestion]]] = {}
    for aid in wanted:
        c = analysis.by_id.get(aid)
        if c is None:
            reason = "unbekannt" if aid not in lib.assets else (
                "hat schon einen Ort" if lib.assets[aid].has_gps else "Screenshot")
            skipped.append({"id": aid, "grund": reason})
            continue
        if not c.editable:
            skipped.append({"id": aid, "grund": "externe Bibliothek (in den Einstellungen gesperrt)"})
            continue
        if manual:
            lat, lon, name = manual
            sugg = Suggestion(lat, lon, name, "hoch", "von Hand gewählt", method="manuell")
        elif c.suggestion is None:
            skipped.append({"id": aid, "grund": "kein Vorschlag"})
            continue
        else:
            sugg = c.suggestion
        buckets.setdefault((c.asset.owner, sugg.latitude, sugg.longitude), []).append((c, sugg))

    updated = 0
    for (owner, lat, lon), items in buckets.items():
        updated += clients[owner].set_location([c.asset.id for c, _ in items], lat, lon)
        for c, sugg in items:
            a = c.asset
            a.latitude, a.longitude = lat, lon
            if sugg.source:
                a.city, a.state, a.country = sugg.source.city, sugg.source.state, sugg.source.country
            else:
                a.city, a.state, a.country = sugg.place, None, None  # Immich ermittelt den Ort neu
    if updated:
        log.info("Ort für %d Medien übernommen%s", updated, " (von Hand gewählt)" if manual else "")
    return {"aktualisiert": updated, "uebersprungen": skipped}
