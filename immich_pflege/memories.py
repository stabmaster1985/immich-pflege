"""„An diesem Tag“: Fotos vom selben Kalendertag aus früheren Jahren."""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

from .library import Library
from .location import is_screenshot
from .models import Asset

MAX_YEARS = 6  # so viele Jahre stehen höchstens in der Nachricht


def _best(assets: list[Asset]) -> Asset:
    return max(assets, key=lambda a: (a.favorite, a.in_album, a.type == "IMAGE", a.has_gps, a.pixels))


def on_this_day(lib: Library, today: date) -> list[dict[str, Any]]:
    """Je früherem Jahr: Anzahl, Orte, bestes Foto – neuestes Jahr zuerst."""
    by_year: dict[int, list[Asset]] = {}
    for a in lib.assets.values():
        d = a.local_day
        if (d and d.month == today.month and d.day == today.day and d.year < today.year
                and a.visibility == "timeline" and not a.in_review_album and not is_screenshot(a)):
            by_year.setdefault(d.year, []).append(a)
    out = []
    for year in sorted(by_year, reverse=True):
        assets = by_year[year]
        places = [c for c, _ in Counter(a.city for a in assets if a.city).most_common(2)]
        out.append({"jahr": year, "vor": today.year - year, "anzahl": len(assets), "orte": places,
                    "foto": _best(assets).summary()})
    return out


def build_text(days: list[dict[str, Any]]) -> str:
    lines = []
    for d in days[:MAX_YEARS]:
        ago = "vor 1 Jahr" if d["vor"] == 1 else f"vor {d['vor']} Jahren"
        where = f" – {', '.join(d['orte'])}" if d["orte"] else ""
        lines.append(f"• {ago} ({d['jahr']}): {d['anzahl']} {'Foto' if d['anzahl'] == 1 else 'Fotos'}{where}")
    if len(days) > MAX_YEARS:
        lines.append(f"• und {len(days) - MAX_YEARS} weitere Jahre")
    return "\n".join(lines)
