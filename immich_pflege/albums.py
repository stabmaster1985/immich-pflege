"""Alben vorschlagen: Reisen erkennen und mit den vorhandenen Alben beider Benutzer abgleichen.

Ablauf:
1. Zuhause erkennen: das Gebiet (Raster ~10 km) mit den meisten Aufnahmetagen.
2. Reisen: Fotos mit GPS weiter als ``min_km`` von zu Hause, pro Benutzer zeitlich gereiht.
   Eine Lücke über 36 Stunden oder ein Foto von zu Hause beendet die Reise.
3. Reisen beider Benutzer, die sich zeitlich überschneiden, werden zusammengelegt.
4. Fotos ohne GPS desselben Benutzers im Reisezeitraum (z. B. von der Kamera) zählen mit.
5. Abgleich mit allen Alben (eigene und geteilte, beider Benutzer): Liegt die Reise schon
   fast ganz in Alben, ist sie erledigt; passt ein Album teilweise, wird es ergänzt;
   sonst wird ein neues Album vorgeschlagen.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

from .client import ImmichClient, ImmichError
from .library import Library
from .location import MONTHS, is_screenshot, km
from .models import Asset

log = logging.getLogger(__name__)

HOME_GRID = 0.1  # Grad (~10 km): Raster für die Erkennung von zu Hause
HOME_SHARE = 0.5  # weitere Gebiete gelten als Zuhause ab der Hälfte der Tage des ersten
TRIP_GAP_S = 36 * 3600  # so lange ohne Foto von unterwegs = neue Reise
EDGE_S = 3 * 3600  # Fotos ohne GPS bis 3 h vor/nach der Reise zählen noch dazu
MIN_GPS = 3  # mindestens so viele Fotos mit GPS von unterwegs
COMPLETE = 0.95  # Anteil in Alben, ab dem eine Reise erledigt ist
MATCH = 0.2  # Anteil, ab dem ein Album als passend zum Ergänzen gilt
NAME_SHARE = 0.6  # Ort für den Namen: Stadt, Region oder Land mit mindestens diesem Anteil
DATE_SLACK = timedelta(days=2)
STATUS = {"neu": "Neues Album", "ergaenzen": "Album ergänzen", "vorhanden": "Schon in Alben"}
SAMPLES = 8
WRITE_ROLES = ("owner", "editor")


@dataclass
class Home:
    latitude: float
    longitude: float
    name: str
    days: int
    manual: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "tage": self.days, "von_hand": self.manual,
                "breite": round(self.latitude, 3), "laenge": round(self.longitude, 3)}


@dataclass
class AlbumMatch:
    album: dict[str, Any]
    inside: int  # Medien der Reise, die schon im Album liegen
    coverage: float  # Anteil der Reise im Album
    share: float  # Anteil des Albums, der zur Reise gehört
    by_name: bool  # Name passt zu Ort und Jahr der Reise

    def to_dict(self, lib: Library) -> dict[str, Any]:
        return {**album_info(self.album, lib), "in_reise": self.inside,
                "abdeckung": round(self.coverage, 3), "nach_name": self.by_name}


@dataclass
class Trip:
    assets: list[Asset]  # sortiert nach Aufnahmezeit
    gps: list[Asset]  # davon unterwegs mit GPS
    name: str = ""
    places: list[str] = field(default_factory=list)
    status: str = "neu"
    target: AlbumMatch | None = None
    matches: list[AlbumMatch] = field(default_factory=list)

    @cached_property
    def ids(self) -> set[str]:
        return {a.id for a in self.assets}

    @property
    def id(self) -> str:
        return "r" + hashlib.sha1(",".join(sorted(a.id for a in self.gps)).encode()).hexdigest()[:11]

    @property
    def start(self):
        return self.assets[0].local_dt

    @property
    def end(self):
        return self.assets[-1].local_dt

    @property
    def users(self) -> dict[str, int]:
        return dict(Counter(a.owner for a in self.assets).most_common())

    def missing(self, album: dict[str, Any] | None) -> list[Asset]:
        inside = set(album["medien"]) if album else set()
        return [a for a in self.assets if a.id not in inside]

    def to_dict(self, lib: Library) -> dict[str, Any]:
        days = (self.end.date() - self.start.date()).days + 1
        step = max(1, len(self.assets) // SAMPLES)
        return {
            "id": self.id,
            "name": self.name,
            "start": self.start.isoformat(sep=" "),
            "ende": self.end.isoformat(sep=" "),
            "tage": days,
            "anzahl": len(self.assets),
            "videos": sum(1 for a in self.assets if a.type == "VIDEO"),
            "benutzer": self.users,
            "orte": self.places,
            "status": self.status,
            "status_text": STATUS[self.status],
            "album": self.target.to_dict(lib) if self.target else None,
            "fehlend": len(self.missing(self.target.album if self.target else None)),
            "kandidaten": [m.to_dict(lib) for m in self.matches],
            "beispiele": [a.summary() for a in self.assets[::step][:SAMPLES]],
        }


def album_info(album: dict[str, Any], lib: Library) -> dict[str, Any]:
    return {"id": album["id"], "name": album["name"], "besitzer": album["besitzer"] or "anderer Benutzer",
            "geteilt_mit": sorted(u for u, r in album["rollen"].items() if r != "owner"),
            "anzahl": album.get("anzahl") or len(album["medien"])}


# ------------------------------------------------------------------ Zuhause
def find_homes(assets: Iterable[Asset], min_km: float) -> list[Home]:
    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for a in assets:
        if not a.has_gps or not a.local_day:
            continue
        key = (round(a.latitude / HOME_GRID), round(a.longitude / HOME_GRID))
        c = cells.setdefault(key, {"days": set(), "lat": 0.0, "lon": 0.0, "n": 0, "cities": Counter()})
        c["days"].add(a.local_day)
        c["lat"] += a.latitude
        c["lon"] += a.longitude
        c["n"] += 1
        if a.city:
            c["cities"][a.city] += 1
    ranked = sorted(cells.values(), key=lambda c: (len(c["days"]), c["n"]), reverse=True)
    homes: list[Home] = []
    for c in ranked:
        if homes and len(c["days"]) < max(3, len(ranked[0]["days"]) * HOME_SHARE):
            break
        lat, lon = c["lat"] / c["n"], c["lon"] / c["n"]
        if any(km(lat, lon, h.latitude, h.longitude) <= min_km for h in homes):
            continue  # Nachbarraster derselben Gegend
        name = c["cities"].most_common(1)[0][0] if c["cities"] else f"{lat:.2f}, {lon:.2f}"
        homes.append(Home(lat, lon, name, len(c["days"])))
    return homes


def is_away(a: Asset, homes: list[Home], min_km: float) -> bool:
    return all(km(a.latitude, a.longitude, h.latitude, h.longitude) > min_km for h in homes)


# ------------------------------------------------------------------- Reisen
def _segments(assets: list[Asset], homes: list[Home], min_km: float) -> list[list[Asset]]:
    """Fotos von unterwegs eines Benutzers zu Abschnitten reihen."""
    out: list[list[Asset]] = []
    current: list[Asset] = []
    home_seen = False
    for a in assets:
        if not a.has_gps:
            continue
        if not is_away(a, homes, min_km):
            home_seen = True
            continue
        if current and (home_seen or (a.taken_utc - current[-1].taken_utc).total_seconds() > TRIP_GAP_S):
            out.append(current)
            current = []
        current.append(a)
        home_seen = False
    if current:
        out.append(current)
    return out


def find_trips(lib: Library, min_km: float, min_media: int, exclude: set[str] | None = None,
               homes: list[Home] | None = None) -> tuple[list[Home], list[Trip]]:
    """``homes``: von Hand festgelegtes Zuhause; sonst automatisch erkannt."""
    exclude = exclude or set()
    usable = sorted((a for a in lib.assets.values()
                     if a.taken_utc and a.local_dt and not is_screenshot(a) and not a.in_review_album
                     and a.id not in exclude),
                    key=lambda a: a.taken_utc)
    homes = homes or find_homes(usable, min_km)
    if not homes:
        return [], []

    by_user: dict[str, list[Asset]] = {}
    for a in usable:
        by_user.setdefault(a.owner, []).append(a)
    segs = [s for user_assets in by_user.values() for s in _segments(user_assets, homes, min_km)]

    # Überschneidende Abschnitte (auch verschiedener Benutzer) zusammenlegen
    segs.sort(key=lambda s: s[0].taken_utc)
    merged: list[list[Asset]] = []
    for s in segs:
        if merged and s[0].taken_utc <= merged[-1][-1].taken_utc + timedelta(hours=6):
            merged[-1] = sorted(merged[-1] + s, key=lambda a: a.taken_utc)
        else:
            merged.append(s)

    times = [a.taken_utc for a in usable]
    trips: list[Trip] = []
    for gps in merged:
        lo = bisect.bisect_left(times, gps[0].taken_utc - timedelta(seconds=EDGE_S))
        hi = bisect.bisect_right(times, gps[-1].taken_utc + timedelta(seconds=EDGE_S))
        users = {a.owner for a in gps}
        gps_ids = {a.id for a in gps}
        members = [a for a in usable[lo:hi] if a.owner in users and (a.id in gps_ids or not a.has_gps)]
        if len(gps) < MIN_GPS or len(members) < min_media:
            continue
        trip = Trip(assets=members, gps=gps)
        trip.name, trip.places = trip_name(trip)
        trips.append(trip)
    trips.sort(key=lambda t: t.start, reverse=True)
    return homes, trips


def _period(trip: Trip) -> str:
    s, e = trip.start, trip.end
    if (s.year, s.month) == (e.year, e.month):
        return f"{MONTHS[s.month - 1]} {s.year}"
    if s.year == e.year:
        return f"{MONTHS[s.month - 1]}–{MONTHS[e.month - 1]} {s.year}"
    return f"{MONTHS[s.month - 1]} {s.year} – {MONTHS[e.month - 1]} {e.year}"


def trip_name(trip: Trip) -> tuple[str, list[str]]:
    n = len(trip.gps)
    place = None
    for attr in ("city", "state", "country"):
        counts = Counter(getattr(a, attr) for a in trip.gps if getattr(a, attr))
        if counts:
            top, cnt = counts.most_common(1)[0]
            if cnt / n >= NAME_SHARE:
                place = top
                break
    countries = Counter(a.country for a in trip.gps if a.country)
    if place is None:
        place = " & ".join(c for c, _ in countries.most_common(2)) or "Unterwegs"
    cities = Counter(a.city for a in trip.gps if a.city)
    places = [c for c, _ in cities.most_common(4)]
    return f"{place}, {_period(trip)}", places


# ------------------------------------------------------------- Abgleich
def _norm(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


def _dates_overlap(album: dict[str, Any], trip: Trip) -> bool:
    from .models import parse_dt

    s, e = parse_dt(album.get("start")), parse_dt(album.get("ende"))
    if not s or not e:
        return False
    s, e = s.replace(tzinfo=None), e.replace(tzinfo=None)
    return s - DATE_SLACK <= trip.end and trip.start <= e + DATE_SLACK


class AlbumIndex:
    """Einmal pro Berechnung: Mitglieder als Mengen, Medium -> Alben, normalisierte Namen."""

    def __init__(self, lib: Library):
        self.members = {aid: set(al["medien"]) for aid, al in lib.albums.items()}
        self.names = {aid: _norm(al["name"]) for aid, al in lib.albums.items()}
        self.by_asset: dict[str, list[str]] = {}
        for aid, members in self.members.items():
            for m in members:
                self.by_asset.setdefault(m, []).append(aid)


def match_albums(trip: Trip, lib: Library, index: AlbumIndex | None = None) -> None:
    index = index or AlbumIndex(lib)
    ids = trip.ids
    words = set()
    for a in trip.gps:
        for v in (a.city, a.state, a.country):
            if v:
                words |= _norm(v)
    years = {str(trip.start.year), str(trip.end.year)}
    hits = Counter(al for i in ids for al in index.by_asset.get(i, ()))
    covered = {i for i in ids if i in index.by_asset}
    matches: list[AlbumMatch] = []
    for aid, al in lib.albums.items():
        inside = hits.get(aid, 0)
        name = index.names[aid]
        by_name = bool(name & words) and (bool(name & years) or _dates_overlap(al, trip))
        if not inside and not by_name:
            continue
        members = index.members[aid]
        matches.append(AlbumMatch(al, inside, inside / len(ids), inside / len(members) if members else 0.0, by_name))
    matches.sort(key=lambda m: (m.inside, m.by_name), reverse=True)
    trip.matches = matches
    best = matches[0] if matches else None
    if best and best.coverage >= COMPLETE:
        trip.status, trip.target = "vorhanden", best
    elif len(covered) / len(ids) >= COMPLETE:
        trip.status, trip.target = "vorhanden", None  # verteilt auf mehrere Alben
    else:
        fitting = [m for m in matches if m.coverage >= MATCH or m.share >= 0.5 or m.by_name]
        if fitting:
            trip.status, trip.target = "ergaenzen", fitting[0]
        else:
            trip.status, trip.target = "neu", None


def suggest(lib: Library, min_km: float, min_media: int, exclude: set[str] | None = None,
            homes: list[Home] | None = None) -> tuple[list[Home], list[Trip]]:
    homes, trips = find_trips(lib, min_km, min_media, exclude, homes)
    index = AlbumIndex(lib)
    for t in trips:
        match_albums(t, lib, index)
    return homes, trips


# ------------------------------------------------------------------- Plan
class AlbumError(ValueError):
    pass


def plan_trip(trip: Trip, lib: Library, album_id: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Was beim Übertragen passiert: Album anlegen oder ergänzen, ggf. teilen, Medien je Benutzer."""
    notes: list[str] = []
    if album_id:
        album = lib.albums.get(album_id)
        if album is None:
            raise AlbumError("Album nicht gefunden – bitte neu einlesen")
        owner = album["besitzer"]
        missing = trip.missing(album)
        share: list[str] = []
        media: dict[str, list[str]] = {}
        for user, cnt in Counter(a.owner for a in missing).items():
            role = album["rollen"].get(user)
            if role not in WRITE_ROLES:
                if role is None and owner:
                    share.append(user)  # Besitzer teilt das Album mit diesem Benutzer
                else:
                    notes.append(f"{cnt} Medien von {user} passen nicht hinein: "
                                 + ("nur Betrachter des Albums" if role else "Album gehört keinem eingerichteten Benutzer"))
                    continue
            media[user] = [a.id for a in missing if a.owner == user]
        plan = {"aktion": "ergaenzen", "album_id": album_id, "name": album["name"], "besitzer": owner,
                "teilen": sorted(share), "medien": media}
    else:
        name = (name or trip.name).strip()
        if not name:
            raise AlbumError("Albumname fehlt")
        users = trip.users
        owner = next(iter(users))
        plan = {"aktion": "neu", "album_id": None, "name": name, "besitzer": owner,
                "teilen": sorted(u for u in users if u != owner),
                "medien": {u: [a.id for a in trip.assets if a.owner == u] for u in users}}
    plan["anzahl"] = sum(len(v) for v in plan["medien"].values())
    plan["hinweise"] = notes
    plan["reise"] = trip.id
    plan["alle_medien"] = sorted(trip.ids)
    return plan


def plan_title(plan: dict[str, Any]) -> str:
    n = plan["anzahl"]
    if plan["aktion"] == "neu":
        text = f"📁 Neues Album „{plan['name']}“ mit {n} Medien"
    else:
        text = f"📁 „{plan['name']}“ um {n} Medien ergänzen"
    if plan["teilen"]:
        text += f", geteilt mit {', '.join(plan['teilen'])}"
    return text


def execute_plan(lib: Library, clients: dict[str, ImmichClient], plan: dict[str, Any]) -> dict[str, Any]:
    owner = plan["besitzer"]
    if owner not in clients:
        raise AlbumError(f"Kein API-Key für den Besitzer {owner!r}")
    editors = [{"userId": lib.users[u]["id"], "role": "editor"} for u in plan["teilen"] if u in lib.users]
    album_id = plan["album_id"]
    undo: list[dict[str, Any]] = []
    if plan["aktion"] == "neu":
        created = clients[owner].create_album(plan["name"], editors)
        album_id = created["id"]
        lib.albums[album_id] = {"id": album_id, "name": plan["name"], "besitzer": owner,
                                "rollen": {owner: "owner", **{u: "editor" for u in plan["teilen"]}},
                                "anzahl": 0, "start": None, "ende": None, "medien": []}
        undo.append({"op": "album_loeschen", "user": owner, "album": album_id})
        log.info("Album „%s“ angelegt (%s)", plan["name"], owner)
    else:
        if album_id not in lib.albums:
            raise AlbumError("Album gibt es nicht mehr – bitte neu einlesen")
        if editors:
            clients[owner].share_album(album_id, editors)
            for u in plan["teilen"]:
                lib.albums[album_id]["rollen"][u] = "editor"
            undo += [{"op": "teilen_aufheben", "user": owner, "album": album_id, "nutzer": e["userId"]}
                     for e in editors]
    album = lib.albums[album_id]
    members = set(album["medien"])
    added, skipped, errors = 0, 0, []
    for user, ids in plan["medien"].items():
        ids = [i for i in ids if i in lib.assets and i not in members]
        if not ids:
            continue
        try:
            results = clients[user].add_to_album(album_id, ids)
        except ImmichError as exc:
            errors.append(f"{user}: {exc}")
            continue
        new = [r["id"] for r in results if r.get("success")]
        if new and plan["aktion"] != "neu":  # ein neues Album wird beim Rückgängig ganz gelöscht
            undo.append({"op": "album_entfernen", "user": user, "album": album_id, "ids": new})
        for r in results:
            if r.get("success") or r.get("error") == "duplicate":
                members.add(r["id"])
                lib.assets[r["id"]].in_album = True
                added += 1 if r.get("success") else 0
            else:
                skipped += 1
    album["medien"] = sorted(members)
    album["anzahl"] = len(members)
    if errors:
        raise AlbumError("; ".join(errors))
    return {"album_id": album_id, "name": album["name"], "hinzugefuegt": added, "uebersprungen": skipped,
            "rueck": undo}


# ------------------------------------------------------- „Kein Album“
class TripIgnoreList:
    """Reisen, für die kein Album gewünscht ist. Gemerkt als Mengen von Medien-IDs, damit
    eine Reise auch nach neuen Fotos wiedererkannt wird (Überschneidung ab 50 %)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.sets: list[set[str]] = []
        try:
            if path.exists():
                self.sets = [set(s) for s in json.loads(path.read_text(encoding="utf-8")).get("reisen", [])]
        except (OSError, ValueError) as exc:
            log.warning("%s unlesbar: %s", path, exc)

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"reisen": [sorted(s) for s in self.sets]}), encoding="utf-8")
        tmp.replace(self.path)

    def contains(self, ids: set[str]) -> bool:
        return overlaps(ids, self.sets)

    def add(self, ids: set[str]) -> None:
        with self._lock:
            self.sets.append(set(ids))
            self._save()

    def remove(self, ids: set[str]) -> None:
        with self._lock:
            self.sets = [s for s in self.sets if not overlaps(ids, [s])]
            self._save()


def overlaps(ids: set[str], sets: Iterable[set[str]]) -> bool:
    return any(len(ids & s) >= 0.5 * min(len(ids), len(s)) for s in sets if s)
