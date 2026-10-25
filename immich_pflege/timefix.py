"""Falsche Aufnahmezeiten finden und korrigieren.

- **Kamera-Zeitversatz:** Die Uhr einer Kamera geht falsch (z. B. Sommerzeit vergessen). Pro Kamera
  ohne GPS und Monat werden ihre Fotos gegen die Handyfotos (Geräte mit GPS, beide Benutzer) gelegt: Bei
  welcher Verschiebung (in 30-Minuten-Schritten, bis ±12 h) liegen die meisten Kamerafotos
  innerhalb von 10 Minuten neben einem anderen Foto? Ist das deutlich besser als ohne
  Verschiebung, gibt es einen Vorschlag.
- **Datum aus dem Dateinamen:** IMG_20190714_…, IMG-20240718-WA…, PXL_…, „2019-07-14 12.34.56“ –
  weicht die Aufnahmezeit um mehr als einen Tag davon ab, wird der Dateiname vorgeschlagen.
- **Unplausibel:** in der Zukunft oder ein typisches Standarddatum (1970, 1980, 2000-01-01) bzw.
  vor 1995 von einem Digitalgerät – hier gibt es nur einen Vorschlag, wenn der Dateiname hilft.

Korrigiert wird mit Immichs relativer Verschiebung (``dateTimeRelative``, Minuten); Rückgängig
verschiebt um denselben Betrag zurück.
"""

from __future__ import annotations

import bisect
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .library import Library
from .location import MONTHS
from .models import Asset

STEP_MIN = 30
MAX_OFFSET_MIN = 12 * 60
MATCH_MIN = 10  # Kamerafoto zählt als „passend“, wenn ein anderes Foto höchstens 10 min daneben liegt
MIN_PHOTOS = 12  # so viele Kamerafotos an Tagen mit anderen Fotos braucht ein Monat
MIN_SHARE = 0.5  # mindestens die Hälfte muss mit der Verschiebung passen
SAMPLE = 300  # große Monate: gleichmäßige Stichprobe
NAME_TOLERANCE = timedelta(days=1)
FUTURE_SLACK = timedelta(days=1)
DEFAULT_DATES = {(1970, 1, 1), (1980, 1, 1), (2000, 1, 1), (2001, 1, 1)}
DIGITAL_MAKES = re.compile(r"apple|samsung|google|xiaomi|huawei|oneplus|oppo|motorola|nokia|sony|canon|nikon|"
                           r"fujifilm|olympus|panasonic|gopro|dji|leica|ricoh|pentax", re.I)
NAME_PATTERNS = [
    # IMG_20190714_123456, PXL_20230101_101112345, VID_…, Screenshot_20240720-…
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d\d)(?P<m>[01]\d)(?P<d>[0-3]\d)[_-](?P<H>[0-2]\d)(?P<M>[0-5]\d)(?P<S>[0-5]\d)"),
    # 2019-07-14 12.34.56 / 2019-07-14_12-34-56
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d\d)-(?P<m>[01]\d)-(?P<d>[0-3]\d)[ _T](?P<H>[0-2]\d)[.:-](?P<M>[0-5]\d)[.:-](?P<S>[0-5]\d)"),
    # IMG-20240718-WA0003 (nur Datum)
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d\d)(?P<m>[01]\d)(?P<d>[0-3]\d)-WA\d", re.I),
]
ARTEN = {"zeitversatz": "Kamera-Zeitversatz", "dateiname": "Datum laut Dateiname",
         "zukunft": "In der Zukunft", "standard": "Standarddatum"}


@dataclass
class TimeFix:
    art: str
    assets: list[Asset]
    minutes: int | None  # None = kein Vorschlag, Zeit von Hand wählen
    grund: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return "z" + hashlib.sha1((self.art + ",".join(sorted(a.id for a in self.assets))).encode()).hexdigest()[:11]

    def media(self, assets: list[Asset] | None = None) -> list[dict[str, Any]]:
        return [{**a.summary(), "neue_zeit": shifted(a, self.minutes)} for a in (self.assets if assets is None else assets)]

    def to_dict(self) -> dict[str, Any]:
        step = max(1, len(self.assets) // 6)
        return {
            "id": self.id, "art": self.art, "art_text": ARTEN[self.art], "grund": self.grund,
            "minuten": self.minutes, "anzahl": len(self.assets), **self.extra,
            "medien": self.media(self.assets[::step][:6]),
        }


def shifted(a: Asset, minutes: int | None) -> str | None:
    if minutes is None or not a.local_dt:
        return None
    return (a.local_dt + timedelta(minutes=minutes)).isoformat(sep=" ")


def fmt_offset(minutes: int) -> str:
    sign = "+" if minutes > 0 else "−"
    if abs(minutes) >= 48 * 60:
        return f"{sign}{round(abs(minutes) / 1440)} Tage"
    h, m = divmod(abs(minutes), 60)
    return f"{sign}{h} h" + (f" {m} min" if m else "")


def name_date(file_name: str) -> datetime | None:
    for pat in NAME_PATTERNS:
        m = pat.search(file_name or "")
        if not m:
            continue
        g = m.groupdict()
        try:
            return datetime(int(g["y"]), int(g["m"]), int(g["d"]), int(g.get("H") or 0),
                            int(g.get("M") or 0), int(g.get("S") or 0))
        except ValueError:
            continue
    return None


# ------------------------------------------------------- einzelne Medien
def single_fixes(lib: Library, now: datetime) -> list[TimeFix]:
    fixes: list[TimeFix] = []
    for a in lib.assets.values():
        t = a.local_dt
        if t is None:
            continue
        from_name = name_date(a.file_name)
        if from_name and not (from_name.hour or from_name.minute or from_name.second):
            from_name = from_name.replace(hour=t.hour, minute=t.minute, second=t.second)  # nur Datum
        future = t > now + FUTURE_SLACK
        default = (t.year, t.month, t.day) in DEFAULT_DATES and t.hour == 0 or \
            (t.year < 1995 and bool(DIGITAL_MAKES.search(a.make or "")))
        if from_name and abs(from_name - t) > NAME_TOLERANCE and from_name <= now + FUTURE_SLACK:
            minutes = round((from_name - t).total_seconds() / 60)
            fixes.append(TimeFix("dateiname", [a], minutes,
                                 f"Dateiname sagt {from_name:%d.%m.%Y %H:%M}, Immich {t:%d.%m.%Y %H:%M}"))
        elif future:
            fixes.append(TimeFix("zukunft", [a], None, f"Aufnahme am {t:%d.%m.%Y} liegt in der Zukunft"))
        elif default:
            fixes.append(TimeFix("standard", [a], None,
                                 f"{t:%d.%m.%Y %H:%M} – vermutlich nicht gestellte Kamera-Uhr"))
    return fixes


# ------------------------------------------------------ Kamera-Versatz
def camera_offsets(lib: Library) -> list[TimeFix]:
    """Nur Kameras ohne GPS werden geprüft; Bezug sind Geräte mit GPS (Handys stellen ihre Uhr selbst)."""
    by_cam: dict[tuple[str, str], list[Asset]] = {}
    for a in lib.assets.values():
        if a.local_dt and (a.make or a.model):
            by_cam.setdefault((a.make or "", a.model or ""), []).append(a)
    gps_share = {c: sum(1 for a in ps if a.has_gps) / len(ps) for c, ps in by_cam.items()}
    phones = sorted(a.local_dt for c, ps in by_cam.items() if gps_share[c] >= 0.5 for a in ps)
    if not phones:
        return []
    fixes: list[TimeFix] = []
    for cam, photos in by_cam.items():
        if gps_share[cam] >= 0.5:
            continue
        others = phones
        months: dict[str, list[Asset]] = {}
        for a in photos:
            months.setdefault(a.local_dt.strftime("%Y-%m"), []).append(a)
        found: list[tuple[str, int, list[Asset], int, int]] = []
        for month, ps in sorted(months.items()):
            res = _best_offset(ps, others)
            if res:
                found.append((month, *res))
        # aufeinanderfolgende Monate mit gleichem Versatz zusammenfassen
        for group in _runs(found):
            minutes = group[0][1]
            assets = sorted((a for g in group for a in g[2]), key=lambda a: a.local_dt)
            hits = sum(g[3] for g in group)
            base = sum(g[4] for g in group)
            first, last = group[0][0], group[-1][0]
            span = _month_label(first) + ("" if first == last else " – " + _month_label(last))
            name = " ".join(x for x in cam if x)
            fixes.append(TimeFix("zeitversatz", assets, minutes,
                                 f"{name}: Uhr ging {span} um {fmt_offset(-minutes).lstrip('+−')} "
                                 f"{'vor' if minutes < 0 else 'nach'} – mit {fmt_offset(minutes)} liegen "
                                 f"{hits} statt {base} Fotos neben Fotos anderer Geräte",
                                 {"kamera": name, "zeitraum": span, "treffer": hits, "vorher": base}))
    return fixes


def _best_offset(photos: list[Asset], others: list[datetime]) -> tuple[int, list[Asset], int, int] | None:
    # nur Fotos von Tagen, an denen auch andere Geräte fotografiert haben (±1 Tag Spielraum)
    usable = [a for a in photos if _near(others, a.local_dt, timedelta(hours=13))]
    if len(usable) < MIN_PHOTOS:
        return None
    if len(usable) > SAMPLE:
        usable = usable[:: len(usable) // SAMPLE + 1]
    window = timedelta(minutes=MATCH_MIN)
    scores = {}
    for off in range(-MAX_OFFSET_MIN, MAX_OFFSET_MIN + 1, STEP_MIN):
        delta = timedelta(minutes=off)
        scores[off] = sum(1 for a in usable if _near(others, a.local_dt + delta, window))
    base = scores[0]
    best = max(scores, key=lambda o: (scores[o], -abs(o)))
    if best == 0 or scores[best] < MIN_SHARE * len(usable) or scores[best] < 2 * base + 3:
        return None
    return best, photos, scores[best], base


def _near(sorted_times: list[datetime], t: datetime, window: timedelta) -> bool:
    i = bisect.bisect_left(sorted_times, t - window)
    return i < len(sorted_times) and sorted_times[i] <= t + window


def _runs(found):
    runs: list[list] = []
    for item in found:
        month, minutes = item[0], item[1]
        if runs and runs[-1][-1][1] == minutes and _next_month(runs[-1][-1][0]) == month:
            runs[-1].append(item)
        else:
            runs.append([item])
    return runs


def _next_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:])
    return f"{y + mo // 12}-{mo % 12 + 1:02d}"


def _month_label(m: str) -> str:
    return f"{MONTHS[int(m[5:]) - 1]} {m[:4]}"


def find_fixes(lib: Library, now: datetime | None = None) -> list[TimeFix]:
    now = now or datetime.now()
    offsets = camera_offsets(lib)
    in_offset = {a.id for f in offsets for a in f.assets}
    singles = [f for f in single_fixes(lib, now) if f.assets[0].id not in in_offset]
    order = {"zeitversatz": 0, "dateiname": 1, "zukunft": 2, "standard": 3}
    return sorted(offsets + singles, key=lambda f: (order[f.art], f.assets[0].local_dt), reverse=False)


def summary(fixes: list[TimeFix]) -> dict[str, int]:
    c = Counter(f.art for f in fixes)
    return {k: c.get(k, 0) for k in ARTEN}


def plan_shifts(fix: TimeFix, minutes: int) -> list[dict[str, Any]]:
    by_user: dict[str, list[str]] = {}
    for a in fix.assets:
        by_user.setdefault(a.owner, []).append(a.id)
    return [{"user": u, "ids": ids, "minuten": minutes} for u, ids in sorted(by_user.items())]


def execute_shifts(lib: Library, clients, changes: list[dict[str, Any]]) -> dict[str, Any]:
    from .history import shift_local

    moved, undo = 0, []
    for ch in changes:
        ids = [i for i in ch["ids"] if i in lib.assets]
        if not ids or not ch["minuten"]:
            continue
        clients[ch["user"]].shift_time(ids, ch["minuten"])
        shift_local(lib, ids, ch["minuten"])
        moved += len(ids)
        undo.append({"op": "zeit", "user": ch["user"], "ids": ids, "minuten": -ch["minuten"]})
    return {"verschoben": moved, "rueck": undo}
