"""Vereinfachtes, serialisierbares Abbild eines Immich-Assets."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import date, datetime, timezone
from functools import cached_property
from typing import Any


def parse_duration(value: Any) -> int | None:
    """Videolänge in ms – v3 liefert eine Zahl, ältere Versionen „0:00:03.000000“."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    try:
        h, m, s = str(value).split(":")
        ms = int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)
    except ValueError:
        return None
    return ms or None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Asset:
    id: str
    owner: str  # Benutzername aus der Konfiguration
    checksum: str
    file_name: str
    path: str
    local_date_time: str | None  # Immich liefert Ortszeit mit "Z"-Suffix
    file_created_at: str | None  # echte UTC-Zeit
    library_id: str | None
    type: str  # IMAGE | VIDEO | ...
    favorite: bool = False
    visibility: str = "timeline"
    width: int | None = None
    height: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    make: str | None = None
    model: str | None = None
    file_size: int | None = None
    duration_ms: int | None = None  # Videos
    in_album: bool = False
    in_review_album: bool = False
    stack_id: str | None = None  # Immich-Stapel, in dem das Medium liegt
    offline: bool = False  # externe Bibliothek: Datei fehlt auf der Platte
    extra: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ abgeleitet
    @property
    def is_external(self) -> bool:
        return self.library_id is not None

    @property
    def has_gps(self) -> bool:
        if self.latitude is None or self.longitude is None:
            return False
        return not (self.latitude == 0 and self.longitude == 0)

    @property
    def pixels(self) -> int:
        return (self.width or 0) * (self.height or 0)

    @cached_property
    def local_dt(self) -> datetime | None:
        dt = parse_dt(self.local_date_time)
        return dt.replace(tzinfo=None) if dt else None

    @cached_property
    def taken_utc(self) -> datetime | None:
        dt = parse_dt(self.file_created_at) or parse_dt(self.local_date_time)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @property
    def local_day(self) -> date | None:
        return self.local_dt.date() if self.local_dt else None

    @property
    def place(self) -> str | None:
        parts = [p for p in (self.city, self.country) if p]
        return ", ".join(parts) or None

    def to_dict(self) -> dict[str, Any]:
        # schneller als dataclasses.asdict (kopiert nicht rekursiv); ohne zwischengespeicherte Werte
        return {f: getattr(self, f) for f in _FIELDS}

    def summary(self) -> dict[str, Any]:
        """Kompakte Darstellung für API und Oberfläche."""
        return {
            "id": self.id,
            "benutzer": self.owner,
            "dateiname": self.file_name,
            "pfad": self.path,
            "aufnahme": self.local_dt.isoformat(sep=" ") if self.local_dt else None,
            "typ": "video" if self.type == "VIDEO" else "foto",
            "extern": self.is_external,
            "favorit": self.favorite,
            "im_album": self.in_album,
            "im_pruef_album": self.in_review_album,
            "gps": self.has_gps,
            "ort": self.place,
            "breite": self.width,
            "hoehe": self.height,
            "groesse": self.file_size,
            "dauer_s": round(self.duration_ms / 1000, 1) if self.duration_ms else None,
            "thumb": f"thumb/{self.id}",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Asset":
        return cls(**data)

    @classmethod
    def from_api(cls, raw: dict[str, Any], owner: str) -> "Asset":
        exif = raw.get("exifInfo") or {}
        width = exif.get("exifImageWidth") or raw.get("width")
        height = exif.get("exifImageHeight") or raw.get("height")
        return cls(
            id=raw["id"],
            owner=owner,
            checksum=raw.get("checksum") or "",
            file_name=raw.get("originalFileName") or "",
            path=raw.get("originalPath") or "",
            local_date_time=raw.get("localDateTime"),
            file_created_at=raw.get("fileCreatedAt"),
            library_id=raw.get("libraryId"),
            type=raw.get("type") or "IMAGE",
            favorite=bool(raw.get("isFavorite")),
            visibility=raw.get("visibility") or "timeline",
            width=width,
            height=height,
            latitude=exif.get("latitude"),
            longitude=exif.get("longitude"),
            city=exif.get("city"),
            state=exif.get("state"),
            country=exif.get("country"),
            make=exif.get("make"),
            model=exif.get("model"),
            file_size=exif.get("fileSizeInByte"),
            duration_ms=parse_duration(raw.get("duration")),
            offline=bool(raw.get("isOffline")),
        )


_FIELDS = tuple(f.name for f in fields(Asset))
