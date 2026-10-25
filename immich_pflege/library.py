"""Einlesen der gesamten Bibliothek aller Benutzer und Zwischenspeichern."""

from __future__ import annotations

import itertools
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .client import ImmichClient, ImmichError
from .models import Asset

log = logging.getLogger(__name__)

CACHE_VERSION = 2  # 2: mit Alben
_UIDS = itertools.count(1)
IGNORED_VISIBILITY = {"hidden", "locked"}  # Live-Photo-Videos bzw. gesperrter Ordner


@dataclass
class ImmichDuplicate:
    user: str
    duplicate_id: str
    asset_ids: list[str]
    suggested_keep: list[str]


@dataclass
class Library:
    scanned_at: str
    duration_s: float
    server_version: str | None
    users: dict[str, dict[str, Any]]  # name -> {id, email}
    assets: dict[str, Asset]
    immich_duplicates: list[ImmichDuplicate] = field(default_factory=list)
    review_albums: dict[str, str | None] = field(default_factory=dict)  # name -> album id
    albums: dict[str, dict[str, Any]] = field(default_factory=dict)  # alle anderen Alben, siehe read_albums
    warnings: list[str] = field(default_factory=list)
    immich_url: str = ""
    rev: int = 0  # Änderungszähler (nicht gespeichert): ungültig machen von Zwischenergebnissen
    albums_ready: bool = True  # False, solange die Album-Inhalte im Hintergrund gelesen werden
    full_scan_at: str = ""  # letztes vollständiges Einlesen (sonst nur Änderungen)
    incremental: bool = False  # dieses Einlesen holte nur Änderungen (nicht gespeichert)
    uid: int = field(default_factory=lambda: next(_UIDS))  # eindeutig je Einlesen (id() kann wiederkehren)

    def assets_of(self, user: str) -> list[Asset]:
        return [a for a in self.assets.values() if a.owner == user]

    def counts(self) -> dict[str, Any]:
        per_user: dict[str, dict[str, int]] = {}
        for a in self.assets.values():
            c = per_user.setdefault(a.owner, {"gesamt": 0, "extern": 0, "upload": 0})
            c["gesamt"] += 1
            c["extern" if a.is_external else "upload"] += 1
        return {"gesamt": len(self.assets), "benutzer": per_user}

    # ------------------------------------------------------------ Persistenz
    def to_json(self) -> dict[str, Any]:
        return {
            "version": CACHE_VERSION,
            "scanned_at": self.scanned_at,
            "duration_s": self.duration_s,
            "server_version": self.server_version,
            "users": self.users,
            "assets": [a.to_dict() for a in self.assets.values()],
            "immich_duplicates": [d.__dict__ for d in self.immich_duplicates],
            "review_albums": self.review_albums,
            "albums": self.albums,
            "warnings": self.warnings,
            "immich_url": self.immich_url,
            "full_scan_at": self.full_scan_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Library":
        if data.get("version") != CACHE_VERSION:
            raise ValueError("Cache-Version passt nicht")
        return cls(
            scanned_at=data["scanned_at"],
            duration_s=data.get("duration_s", 0.0),
            server_version=data.get("server_version"),
            users=data["users"],
            assets={a["id"]: Asset.from_dict(a) for a in data["assets"]},
            immich_duplicates=[ImmichDuplicate(**d) for d in data.get("immich_duplicates", [])],
            review_albums=data.get("review_albums", {}),
            albums=data.get("albums", {}),
            warnings=data.get("warnings", []),
            immich_url=data.get("immich_url", ""),
            full_scan_at=data.get("full_scan_at") or data["scanned_at"],
        )

    def save(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            log.warning("Zwischenspeicher %s nicht schreibbar: %s", path, exc)

    @classmethod
    def load(cls, path: Path) -> "Library | None":
        if not path.exists():
            return None
        try:
            return cls.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            log.warning("Zwischenspeicher %s unbrauchbar (%s) – wird neu eingelesen", path, exc)
            return None


def version_string(v: dict[str, Any]) -> str:
    return f"{v.get('major')}.{v.get('minor')}.{v.get('patch')}"


def find_review_album(client: ImmichClient, name: str) -> str | None:
    for album in client.albums(owned_only=True):
        if album.get("albumName") == name:
            return album["id"]
    return None


ALBUM_WORKERS = 6  # parallele Abfragen der Album-Inhalte


def _album_signature(al: dict[str, Any]) -> str:
    """Ändert sich, sobald Medien hinzukommen oder entfernt werden. „v2“: seit Medien anderer Besitzer
    über die Zeitleiste mitgelesen werden – ältere Zwischenstände werden einmal neu gelesen."""
    return f"v2|{al.get('assetCount')}|{al.get('updatedAt')}|{al.get('lastModifiedAssetTimestamp')}"


def read_albums(clients: dict[str, ImmichClient], users: dict[str, dict[str, Any]],
                skip: set[str], previous: dict[str, dict[str, Any]] | None = None,
                progress: Callable[[str], None] | None = None) -> dict[str, dict[str, Any]]:
    """Alle Alben, die einer der Benutzer sieht (eigene und geteilte), mit Besitzer, Rollen
    und Mitgliedern. ``skip``: Prüf-Alben. Unveränderte Alben aus ``previous`` werden nicht
    erneut abgefragt."""
    names = {u["id"]: n for n, u in users.items()}
    previous = previous or {}
    started = time.monotonic()
    albums: dict[str, dict[str, Any]] = {}
    jobs: list[tuple[str, str]] = []  # (Album, Benutzer), deren Inhalt abgefragt werden muss
    viewers: dict[str, list[str]] = {}  # Album -> Benutzer, die es sehen (Besitzer zuerst)
    for name, client in clients.items():
        for al in client.albums():
            if al["id"] in skip:
                continue
            seen = viewers.setdefault(al["id"], [])
            if users.get(name, {}).get("id") == al.get("ownerId"):
                seen.insert(0, name)
            else:
                seen.append(name)
            entry = albums.get(al["id"])
            if entry is None:
                roles: dict[str, str] = {}
                owner_id = al.get("ownerId")
                for au in al.get("albumUsers") or []:
                    uid = (au.get("user") or {}).get("id")
                    if au.get("role") == "owner":
                        owner_id = uid
                    elif uid in names:
                        roles[names[uid]] = au.get("role") or "viewer"
                owner = names.get(owner_id)
                if owner:
                    roles[owner] = "owner"
                sig = _album_signature(al)
                old = previous.get(al["id"])
                entry = albums[al["id"]] = {
                    "id": al["id"], "name": al.get("albumName") or "", "besitzer": owner,
                    "rollen": roles, "anzahl": al.get("assetCount") or 0, "titelbild": al.get("albumThumbnailAssetId"),
                    "start": al.get("startDate"), "ende": al.get("endDate"), "stand": sig,
                    "medien": set(old["medien"]) if old and old.get("stand") == sig else None,
                }
            if entry["medien"] is None or entry.get("_neu"):
                entry["_neu"] = True
                if entry["anzahl"]:
                    jobs.append((al["id"], name))
    for entry in albums.values():
        if entry.pop("_neu", False):
            entry["medien"] = set()

    def fetch(job: tuple[str, str]) -> tuple[str, set[str]]:
        # Jeder Benutzer liefert zumindest seine eigenen Medien im Album
        return job[0], clients[job[1]].album_asset_ids(job[0])

    report = progress or (lambda text: None)
    total = len({j[0] for j in jobs})
    with ThreadPoolExecutor(max_workers=ALBUM_WORKERS) as pool:
        done: set[str] = set()
        for album_id, ids in pool.map(fetch, jobs):
            albums[album_id]["medien"] |= ids
            done.add(album_id)
            if len(done) % 10 == 0:
                report(f"Alben lesen: {len(done)} von {total}")
        # Fehlt noch etwas (z. B. Julias Fotos in Franks nicht geteiltem Album, über die Partnerfreigabe
        # hineingelegt), über die Zeitleiste des Albums nachlesen – die zeigt alle Medien jedes Besitzers.
        fetched = {j[0] for j in jobs}
        gaps = [(aid, viewers[aid][0]) for aid in fetched
                if len(albums[aid]["medien"]) < albums[aid]["anzahl"] and viewers.get(aid)]

        def fetch_all(job: tuple[str, str]) -> tuple[str, set[str]]:
            try:
                return job[0], clients[job[1]].album_timeline_ids(job[0])
            except ImmichError as exc:
                log.warning("Album %s: Inhalt anderer Besitzer nicht lesbar (%s)", job[0], exc)
                return job[0], set()

        if gaps:
            report(f"Alben mit Fotos anderer Besitzer: {len(gaps)}")
        for album_id, ids in pool.map(fetch_all, gaps):
            albums[album_id]["medien"] |= ids
            if len(albums[album_id]["medien"]) < albums[album_id]["anzahl"]:
                log.info("Album „%s“: %d von %d Medien gefunden (Rest im Papierkorb oder nicht lesbar)",
                         albums[album_id]["name"], len(albums[album_id]["medien"]), albums[album_id]["anzahl"])
    log.info("Alben gelesen: %d, davon %d neu abgefragt, in %.1f s", len(albums), len({j[0] for j in jobs}),
             time.monotonic() - started)
    for entry in albums.values():
        entry["medien"] = sorted(entry["medien"])
    return albums


def apply_album_membership(lib: Library, recompute: bool = False) -> None:
    """Medien im Prüf-Album zählen nur als „im Album“, wenn sie noch in einem anderen Album liegen.
    ``recompute``: „im Album“ für alle Medien aus den gelesenen Alben bestimmen (beim Einlesen nur
    der Änderungen, wo die Abfrage „in keinem Album“ entfällt)."""
    members: set[str] = set()
    for al in lib.albums.values():
        members.update(al["medien"])
    for a in lib.assets.values():
        if recompute or (a.in_review_album and a.in_album):
            a.in_album = a.id in members


INCREMENTAL_MARGIN = timedelta(hours=1)  # Überlappung, damit nichts zwischen zwei Läufen verloren geht


def scan_library(clients: dict[str, ImmichClient], review_album: str, previous: Library | None = None,
                 read_album_contents: bool = True, incremental: bool = False,
                 progress: Callable[[str], None] | None = None) -> Library:
    """Liest alle Assets, Album-Zugehörigkeit und Immich-Duplikate aller Benutzer ein.

    ``read_album_contents=False``: Album-Inhalte später lesen (siehe ``read_albums``); bis dahin
    gelten die vom letzten Einlesen.
    ``incremental``: nur Medien holen, die sich seit ``previous`` geändert haben oder in den
    Papierkorb gegangen sind; endgültig gelöschte findet erst das nächste vollständige Einlesen.
    ``progress``: bekommt laufend einen kurzen Text, was gerade passiert (für die Oberfläche)."""
    report = progress or (lambda text: None)
    started = time.monotonic()
    incremental = bool(incremental and previous and set(previous.users) == set(clients))
    since = ""
    if incremental:
        since = (datetime.fromisoformat(previous.scanned_at) - INCREMENTAL_MARGIN).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    warnings: list[str] = []
    assets: dict[str, Asset] = {}
    users: dict[str, dict[str, Any]] = {}
    duplicates: list[ImmichDuplicate] = []
    review_albums: dict[str, str | None] = {}

    server_version = None
    first = next(iter(clients.values()))
    v = first.server_version()
    server_version = version_string(v)
    if v.get("major") != 3:
        msg = f"Immich-Version {server_version} erkannt – getestet ist das Tool mit 3.x"
        log.warning(msg)
        warnings.append(msg)

    for name, client in clients.items():
        me = client.me()
        users[name] = {"id": me["id"], "email": me.get("email"), "name": me.get("name")}
        uid = me["id"]
        log.info("Lese Bibliothek von %s ein …", name)
        report(f"Medien von {name}")

        own: dict[str, Asset] = {}
        skipped = 0
        t0 = time.monotonic()
        filters: dict[str, Any] = {"withExif": True}
        if incremental:
            own = {i: a for i, a in previous.assets.items() if a.owner == name}
            filters["updatedAfter"] = since
        changed = 0
        for raw in client.search_metadata(**filters):
            # Partner-Freigaben liefern ggf. fremde Assets – nur eigene übernehmen.
            if raw.get("ownerId") and raw["ownerId"] != uid:
                continue
            if raw.get("isTrashed") or raw.get("visibility") in IGNORED_VISIBILITY:
                skipped += 1
                own.pop(raw["id"], None)
                continue
            old = own.get(raw["id"])
            own[raw["id"]] = Asset.from_api(raw, name)
            if old is not None:
                own[raw["id"]].in_album = old.in_album
            changed += 1
            if changed % 1000 == 0:
                report(f"Medien von {name}: {changed:,}".replace(",", "."))
        if incremental:
            for raw in client.search_metadata(withDeleted=True, trashedAfter=since):
                if raw.get("isTrashed") and own.pop(raw["id"], None) is not None:
                    skipped += 1
        t_media = time.monotonic() - t0

        t0 = time.monotonic()
        report(f"Album-Zugehörigkeit von {name}")
        # Beim Einlesen nur der Änderungen ergibt sich „im Album“ aus den gelesenen Alben
        not_in_album = None if incremental else client.search_ids(isNotInAlbum=True)
        album_id = find_review_album(client, review_album)
        review_albums[name] = album_id
        review_members: set[str] = set()
        if album_id:
            review_members = client.search_ids(albumIds=[album_id]) & own.keys()

        for aid, asset in own.items():
            if not_in_album is not None:
                asset.in_album = aid not in not_in_album
            asset.in_review_album = aid in review_members
        t_album = time.monotonic() - t0

        try:
            for st in client.stacks():
                for raw in st.get("assets") or []:
                    if raw.get("id") in own:
                        own[raw["id"]].stack_id = st["id"]
        except ImmichError as exc:  # Stapel sind nur eine Zusatzinfo
            log.warning("Stapel von %s nicht lesbar: %s", name, exc)

        for d in client.duplicates():
            ids = [a["id"] for a in d.get("assets") or [] if a.get("id")]
            duplicates.append(ImmichDuplicate(
                user=name,
                duplicate_id=d.get("duplicateId") or "",
                asset_ids=ids,
                suggested_keep=list(d.get("suggestedKeepAssetIds") or []),
            ))

        log.info("%s: %d Medien (%s, %d ignoriert: Papierkorb/versteckt) – Medien %.1f s, Album-Zugehörigkeit %.1f s",
                 name, len(own), f"{changed} geändert" if incremental else "vollständig", skipped, t_media, t_album)
        assets.update(own)

    skip = {a for a in review_albums.values() if a}
    if read_album_contents:
        # vollständiges Einlesen: auch Albuminhalte frisch, nicht aus dem Zwischenspeicher
        albums = read_albums(clients, users, skip, previous.albums if previous and incremental else None)
    else:
        albums = {k: v for k, v in (previous.albums if previous else {}).items() if k not in skip}

    duration = round(time.monotonic() - started, 2)
    log.info("Einlesen fertig (%s): %d Medien in %.1f s", "nur Änderungen" if incremental else "vollständig",
             len(assets), duration)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lib = Library(
        scanned_at=now,
        full_scan_at=previous.full_scan_at if incremental else now,
        duration_s=duration,
        server_version=server_version,
        users=users,
        assets=assets,
        immich_duplicates=duplicates,
        review_albums=review_albums,
        albums=albums,
        warnings=warnings,
        albums_ready=read_album_contents,
        incremental=incremental,
    )
    apply_album_membership(lib, recompute=incremental)
    return lib
