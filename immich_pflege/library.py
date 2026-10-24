"""Einlesen der gesamten Bibliothek aller Benutzer und Zwischenspeichern."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import ImmichClient
from .models import Asset

log = logging.getLogger(__name__)

CACHE_VERSION = 1
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
    warnings: list[str] = field(default_factory=list)

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
            "warnings": self.warnings,
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
            warnings=data.get("warnings", []),
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


def scan_library(clients: dict[str, ImmichClient], review_album: str) -> Library:
    """Liest alle Assets, Album-Zugehörigkeit und Immich-Duplikate aller Benutzer ein."""
    started = time.monotonic()
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

        own: dict[str, Asset] = {}
        skipped = 0
        for raw in client.search_metadata(withExif=True):
            # Partner-Freigaben liefern ggf. fremde Assets – nur eigene übernehmen.
            if raw.get("ownerId") and raw["ownerId"] != uid:
                continue
            if raw.get("isTrashed") or raw.get("visibility") in IGNORED_VISIBILITY:
                skipped += 1
                continue
            own[raw["id"]] = Asset.from_api(raw, name)

        not_in_album = client.search_ids(isNotInAlbum=True)
        album_id = find_review_album(client, review_album)
        review_albums[name] = album_id
        review_members: set[str] = set()
        if album_id:
            review_members = client.search_ids(albumIds=[album_id]) & own.keys()

        for aid, asset in own.items():
            asset.in_album = aid not in not_in_album
            asset.in_review_album = aid in review_members
        # Mitglieder des Prüf-Albums zählen nur als "im Album", wenn sie noch in einem
        # anderen Album liegen.
        for aid in review_members:
            asset = own[aid]
            if asset.in_album:
                others = [a for a in client.albums(asset_id=aid) if a.get("id") != album_id]
                asset.in_album = bool(others)

        for d in client.duplicates():
            ids = [a["id"] for a in d.get("assets") or [] if a.get("id")]
            duplicates.append(ImmichDuplicate(
                user=name,
                duplicate_id=d.get("duplicateId") or "",
                asset_ids=ids,
                suggested_keep=list(d.get("suggestedKeepAssetIds") or []),
            ))

        log.info("%s: %d Medien (%d ignoriert: Papierkorb/versteckt)", name, len(own), skipped)
        assets.update(own)

    duration = round(time.monotonic() - started, 2)
    log.info("Einlesen fertig: %d Medien in %.1f s", len(assets), duration)
    return Library(
        scanned_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration_s=duration,
        server_version=server_version,
        users=users,
        assets=assets,
        immich_duplicates=duplicates,
        review_albums=review_albums,
        warnings=warnings,
    )
