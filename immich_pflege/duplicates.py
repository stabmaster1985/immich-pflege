"""Duplikate finden, gruppieren (Union-Find), Behalten-Vorschlag und Aktionen."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from .client import ImmichClient
from .library import Library
from .models import Asset

log = logging.getLogger(__name__)

# Punktwertung in der gewünschten Rangfolge; jede Stufe schlägt alle folgenden zusammen.
WEIGHTS = [
    ("favorit", "Favorit", 32),
    ("im_album", "im Album", 16),
    ("gps", "hat GPS", 8),
    ("immich", "Immich-Vorschlag", 4),
    ("extern", "externe Bibliothek", 2),
    ("aufloesung", "höchste Auflösung", 1),
]

QUELLEN = {
    "immich": "Immich-Duplikaterkennung",
    "pruefsumme": "identische Prüfsumme",
    "name_zeit": "gleicher Dateiname + Aufnahmezeit",
    "bildhash": "fast gleicher Bild-Fingerabdruck",
}

AKTIONEN = ("album", "papierkorb")

# Art einer Gruppe – wie sicher es wirklich dieselbe Aufnahme ist
ARTEN = {
    "identisch": "identisch",  # alle Dateien Byte für Byte gleich (gleiche Prüfsumme)
    "sehr_wahrscheinlich": "sehr wahrscheinlich",  # Name + Zeit gleich oder Bild-Fingerabdruck fast gleich
    "aehnlich": "ähnlich",  # nur Immich-KI: ähnliches Motiv, z. B. auch Serienbilder
}
STRONG_SOURCES = {"pruefsumme", "name_zeit", "bildhash"}


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:  # Pfadkompression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def union_all(self, items: Iterable[str]) -> None:
        items = list(items)
        for other in items[1:]:
            self.union(items[0], other)

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for x in self.parent:
            out.setdefault(self.find(x), []).append(x)
        return out


@dataclass
class Score:
    points: int
    reasons: list[str]
    key: tuple


@dataclass
class DuplicateGroup:
    id: str
    assets: list[Asset]
    sources: set[str]
    immich_suggested: set[str]
    scores: dict[str, Score] = field(default_factory=dict)
    suggested_keep: str = ""

    @property
    def users(self) -> set[str]:
        return {a.owner for a in self.assets}

    def asset(self, asset_id: str) -> Asset:
        for a in self.assets:
            if a.id == asset_id:
                return a
        raise KeyError(asset_id)

    @property
    def kind(self) -> str:
        checksums = {a.checksum for a in self.assets}
        if len(checksums) == 1 and "" not in checksums:
            return "identisch"
        if self.sources & STRONG_SOURCES:
            return "sehr_wahrscheinlich"
        return "aehnlich"

    @property
    def month(self) -> str:
        days = [a.local_day for a in self.assets if a.local_day]
        return min(days).strftime("%Y-%m") if days else "ohne-datum"

    @property
    def asset_ids(self) -> frozenset[str]:
        return frozenset(a.id for a in self.assets)

    def done(self, keep_id: str | None = None) -> bool:
        keep_id = keep_id or self.suggested_keep
        return all(a.in_review_album for a in self.assets if a.id != keep_id)

    def to_dict(self, keep_id: str | None = None) -> dict[str, Any]:
        keep_id = keep_id or self.suggested_keep
        return {
            "id": self.id,
            "quellen": sorted(self.sources),
            "benutzer": sorted(self.users),
            "benutzeruebergreifend": len(self.users) > 1,
            "art": self.kind,
            "art_text": ARTEN[self.kind],
            "monat": self.month,
            "behalten": keep_id,
            "vorschlag": self.suggested_keep,
            "erledigt": self.done(keep_id),
            "medien": [
                {**a.summary(), "punkte": self.scores[a.id].points,
                 "gruende": self.scores[a.id].reasons, "immich_vorschlag": a.id in self.immich_suggested}
                for a in self.assets
            ],
        }


def _score_group(group: DuplicateGroup) -> None:
    max_px = max(a.pixels for a in group.assets)
    for a in group.assets:
        flags = {
            "favorit": a.favorite,
            "im_album": a.in_album,
            "gps": a.has_gps,
            "immich": a.id in group.immich_suggested,
            "extern": a.is_external,
            "aufloesung": a.pixels == max_px and max_px > 0,
        }
        points = sum(w for k, _, w in WEIGHTS if flags[k])
        reasons = [label for k, label, _ in WEIGHTS if flags[k]]
        # Gleichstand: größere Auflösung, größere Datei, nicht im Prüf-Album, dann stabil per ID
        key = (points, a.pixels, a.file_size or 0, not a.in_review_album, a.id)
        group.scores[a.id] = Score(points, reasons, key)
    group.suggested_keep = max(group.assets, key=lambda a: group.scores[a.id].key).id


def group_id(asset_ids: Iterable[str]) -> str:
    return hashlib.sha1(",".join(sorted(asset_ids)).encode()).hexdigest()[:12]


def find_groups(lib: Library) -> list[DuplicateGroup]:
    uf = UnionFind()
    pair_sources: list[tuple[list[str], str]] = []
    immich_suggested: set[str] = set()

    for d in lib.immich_duplicates:
        ids = [i for i in d.asset_ids if i in lib.assets]
        if len(ids) >= 2:
            pair_sources.append((ids, "immich"))
            immich_suggested.update(i for i in d.suggested_keep if i in lib.assets)

    by_checksum: dict[str, list[str]] = {}
    by_name_time: dict[tuple[str, str], list[str]] = {}
    for a in lib.assets.values():
        if a.checksum:
            by_checksum.setdefault(a.checksum, []).append(a.id)
        if a.file_name and a.local_dt:
            key = (a.file_name.lower(), a.local_dt.replace(microsecond=0).isoformat())
            by_name_time.setdefault(key, []).append(a.id)
    pair_sources += [(ids, "pruefsumme") for ids in by_checksum.values() if len(ids) > 1]
    pair_sources += [(ids, "name_zeit") for ids in by_name_time.values() if len(ids) > 1]

    for ids, _ in pair_sources:
        uf.union_all(ids)
    group_sources: dict[str, set[str]] = {}
    for ids, src in pair_sources:
        group_sources.setdefault(uf.find(ids[0]), set()).add(src)

    groups: list[DuplicateGroup] = []
    for root, ids in uf.groups().items():
        if len(ids) < 2:
            continue
        assets = sorted((lib.assets[i] for i in ids),
                        key=lambda a: (a.local_date_time or "", a.owner, a.is_external, a.id))
        g = DuplicateGroup(
            id=group_id(ids),
            assets=assets,
            sources=group_sources.get(root, set()),
            immich_suggested={i for i in immich_suggested if i in ids},
        )
        _score_group(g)
        groups.append(g)
    groups.sort(key=lambda g: (g.assets[0].local_date_time or ""), reverse=True)
    return groups


# ------------------------------------------------------------------ Aktionen
@dataclass
class PlannedStep:
    asset: Asset
    action: str  # "papierkorb" | "album" | "keine"
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.asset.id, "benutzer": self.asset.owner, "dateiname": self.asset.file_name,
                "aktion": self.action, "grund": self.reason}


def plan_group(group: DuplicateGroup, keep_id: str, action: str) -> list[PlannedStep]:
    if action not in AKTIONEN:
        raise ValueError(f"Unbekannte Aktion {action!r} (erlaubt: {', '.join(AKTIONEN)})")
    keeper = group.asset(keep_id)
    steps: list[PlannedStep] = []
    for a in group.assets:
        if a.id == keep_id:
            continue
        if action == "papierkorb":
            if a.is_external:
                target, reason = "album", "externe Bibliothek – nie in den Papierkorb"
            elif a.owner != keeper.owner:
                target, reason = "album", f"gehört {a.owner}, behalten wird bei {keeper.owner}"
            else:
                steps.append(PlannedStep(a, "papierkorb", "Kopie"))
                continue
        else:
            target, reason = "album", "Kopie"
        if a.in_review_album:
            steps.append(PlannedStep(a, "keine", "liegt schon im Prüf-Album"))
        else:
            steps.append(PlannedStep(a, target, reason))
    return steps


def ensure_review_album(lib: Library, client: ImmichClient, name: str) -> str:
    from .library import find_review_album

    album_id = lib.review_albums.get(client.user) or find_review_album(client, name)
    if not album_id:
        album_id = client.create_album(name)["id"]
        log.info("Album '%s' für %s angelegt", name, client.user)
    lib.review_albums[client.user] = album_id
    return album_id


def execute_steps(lib: Library, clients: dict[str, ImmichClient], steps: list[PlannedStep],
                  review_album: str) -> dict[str, Any]:
    trash: dict[str, list[str]] = {}
    album: dict[str, list[str]] = {}
    for s in steps:
        if s.action == "papierkorb":
            trash.setdefault(s.asset.owner, []).append(s.asset.id)
        elif s.action == "album":
            album.setdefault(s.asset.owner, []).append(s.asset.id)

    result: dict[str, Any] = {"papierkorb": 0, "album": 0, "fehler": []}
    for user, ids in album.items():
        client = clients[user]
        album_id = ensure_review_album(lib, client, review_album)
        for r in client.add_to_album(album_id, ids):
            if r.get("success") or r.get("error") == "duplicate":
                result["album"] += 1
                if r["id"] in lib.assets:
                    lib.assets[r["id"]].in_review_album = True
            else:
                result["fehler"].append({"id": r.get("id"), "fehler": r.get("error")})
        log.info("%d Medien von %s ins Album '%s' gelegt", len(ids), user, review_album)
    for user, ids in trash.items():
        # Doppelte Absicherung: externe Medien niemals in den Papierkorb
        ids = [i for i in ids if i in lib.assets and not lib.assets[i].is_external]
        result["papierkorb"] += clients[user].trash(ids)
        for i in ids:
            lib.assets.pop(i, None)
        log.info("%d Medien von %s in den Papierkorb verschoben", len(ids), user)
    return result


# ------------------------------------------------------------ „Kein Duplikat“
class IgnoreList:
    """Gruppen, die als „kein Duplikat“ markiert wurden (DATA_DIR/duplikate_ignoriert.json).

    Eine Gruppe bleibt ausgeblendet, solange sie nur aus markierten Medien besteht. Kommt eine
    neue Kopie hinzu, taucht sie wieder auf.
    """

    def __init__(self, path):
        self.path = path
        self.sets: list[frozenset[str]] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            self.sets = [frozenset(ids) for ids in data.get("gruppen", [])]
        except (OSError, ValueError) as exc:
            log.warning("Liste „kein Duplikat“ unlesbar (%s) – starte leer", exc)

    def contains(self, group: DuplicateGroup) -> bool:
        ids = group.asset_ids
        return any(ids <= s for s in self.sets)

    def add(self, ids: Iterable[str]) -> None:
        new = frozenset(ids)
        self.sets = [s for s in self.sets if not s <= new] + [new]
        self._save()

    def remove(self, ids: Iterable[str]) -> None:
        ids = frozenset(ids)
        self.sets = [s for s in self.sets if not ids <= s]
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"gruppen": [sorted(s) for s in self.sets]}
            self.path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("Liste „kein Duplikat“ nicht speicherbar: %s", exc)


def clear_immich_duplicates(lib: Library, clients: dict[str, ImmichClient], group: DuplicateGroup) -> int:
    """Nimmt Immich-erkannte Duplikate auch in Immich aus der Duplikatliste."""
    if "immich" not in group.sources:
        return 0
    ids = group.asset_ids
    by_owner: dict[str, list[str]] = {}
    for d in lib.immich_duplicates:
        hit = [i for i in d.asset_ids if i in ids]
        if hit:
            by_owner.setdefault(d.user, []).extend(hit)
    n = 0
    for owner, owner_ids in by_owner.items():
        n += clients[owner].clear_duplicate(sorted(set(owner_ids)))
    lib.immich_duplicates = [d for d in lib.immich_duplicates
                             if not (set(d.asset_ids) & ids)]
    return n
