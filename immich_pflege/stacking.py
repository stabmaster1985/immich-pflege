"""Stapeln: zusammengehörige Fotos zu Immich-Stapeln zusammenfassen statt zu löschen.

Quelle sind eigene Alben, in denen Zusammengehöriges gesammelt wurde. Innerhalb eines Albums
gehören Fotos zu einem Stapel, wenn sie demselben Benutzer gehören (Immich stapelt nur eigene
Medien) und
- denselben Basisnamen haben und höchstens 2 s auseinander liegen (RAW+JPG, HEIC+JPG, IMG_E…), oder
- höchstens 2 s auseinander liegen (Serienbild), oder
- höchstens 60 s auseinander liegen und sich im Bild-Fingerabdruck ähneln.
Alternativ wird das ganze Album (je Benutzer) zu einem Stapel.

Oben liegt: ein Favorit, sonst kein RAW, sonst die bearbeitete Fassung, sonst das schärfste, sonst
das größte Bild.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .duplicates import RAW_EXT, split_name
from .imagehash import HashStore, distance
from .library import Library
from .models import Asset

PAIR_GAP_S = 2
BURST_GAP_S = 2
SIMILAR_GAP_S = 60
SIMILAR_MAX_DIST = 12


@dataclass
class StackProposal:
    album_id: str
    assets: list[Asset]  # erstes = oben
    grund: str

    @property
    def owner(self) -> str:
        return self.assets[0].owner

    @property
    def id(self) -> str:
        return "s" + hashlib.sha1(",".join(sorted(a.id for a in self.assets)).encode()).hexdigest()[:11]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "album": self.album_id, "benutzer": self.owner, "grund": self.grund,
                "anzahl": len(self.assets), "oben": self.assets[0].id,
                "medien": [a.summary() for a in self.assets]}


def rank(a: Asset, store: HashStore | None) -> tuple:
    q = store.quality(a) if store else None
    _, ext, edited = split_name(a.file_name)
    return (a.favorite, ext not in RAW_EXT, edited, q[0] if q else 0.0, a.pixels)


def order(assets: list[Asset], store: HashStore | None, top: str | None = None) -> list[Asset]:
    """Oben das beste (oder ``top``), danach nach Aufnahmezeit."""
    best = next((a for a in assets if a.id == top), None) or max(assets, key=lambda a: rank(a, store))
    rest = sorted((a for a in assets if a is not best), key=lambda a: (a.taken_utc is None, a.taken_utc))
    return [best, *rest]


def album_assets(lib: Library, album_id: str) -> list[Asset]:
    album = lib.albums.get(album_id)
    if album is None:
        return []
    return [lib.assets[i] for i in album["medien"] if i in lib.assets]


def propose(lib: Library, album_id: str, store: HashStore | None) -> tuple[list[StackProposal], dict[str, int]]:
    """Stapel-Vorschläge in einem Album. Liefert dazu Zahlen (schon gestapelt, ohne Partner)."""
    assets = [a for a in album_assets(lib, album_id) if a.taken_utc]
    stats = {"medien": len(assets), "gestapelt": sum(1 for a in assets if a.stack_id)}
    free = [a for a in assets if not a.stack_id]
    parent = {a.id: a.id for a in free}
    why: dict[str, set[str]] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: Asset, b: Asset, reason: str) -> None:
        ra, rb = find(a.id), find(b.id)
        reasons = why.setdefault(ra, set())
        if ra != rb:
            parent[rb] = ra
            reasons |= why.pop(rb, set())
        reasons.add(reason)

    by_owner: dict[str, list[Asset]] = {}
    for a in free:
        by_owner.setdefault(a.owner, []).append(a)
    for photos in by_owner.values():
        photos.sort(key=lambda a: a.taken_utc)
        for i, a in enumerate(photos):
            for b in photos[i + 1:]:
                gap = (b.taken_utc - a.taken_utc).total_seconds()
                if gap > SIMILAR_GAP_S:
                    break
                if gap <= PAIR_GAP_S and split_name(a.file_name)[0] == split_name(b.file_name)[0]:
                    union(a, b, "gleicher Name (RAW/JPG, HEIC/JPG oder Bearbeitung)")
                elif gap <= BURST_GAP_S:
                    union(a, b, "Serienbild")
                elif store is not None:
                    ha, hb = store.get(a), store.get(b)
                    if ha is not None and hb is not None and distance(ha, hb) <= SIMILAR_MAX_DIST:
                        union(a, b, "ähnliches Motiv kurz nacheinander")
    groups: dict[str, list[Asset]] = {}
    for a in free:
        groups.setdefault(find(a.id), []).append(a)
    proposals = [StackProposal(album_id, order(g, store), ", ".join(sorted(why.get(root, set()))))
                 for root, g in groups.items() if len(g) >= 2]
    proposals.sort(key=lambda p: p.assets[0].taken_utc, reverse=True)
    stats["einzeln"] = sum(1 for g in groups.values() if len(g) == 1)
    return proposals, stats


def whole_album(lib: Library, album_id: str, store: HashStore | None) -> list[StackProposal]:
    """Ganzes Album als Stapel – je Benutzer einer (Immich stapelt nur eigene Medien)."""
    by_owner: dict[str, list[Asset]] = {}
    for a in album_assets(lib, album_id):
        if not a.stack_id:
            by_owner.setdefault(a.owner, []).append(a)
    return [StackProposal(album_id, order(g, store), "ganzes Album") for g in by_owner.values() if len(g) >= 2]


def execute_stacks(lib: Library, clients, plan: dict[str, Any]) -> dict[str, Any]:
    """plan: {stapel: [{user, ids (erstes oben)}], album, aus_album}."""
    made, undo, errors = 0, [], []
    removed: dict[str, list[str]] = {}
    for st in plan["stapel"]:
        ids = [i for i in st["ids"] if i in lib.assets and not lib.assets[i].stack_id]
        if len(ids) < 2:
            continue
        res = clients[st["user"]].create_stack(ids)
        sid = res.get("id")
        made += 1
        for i in ids:
            lib.assets[i].stack_id = sid
        undo.append({"op": "stapel_aufloesen", "user": st["user"], "stack": sid, "ids": ids})
        if plan.get("aus_album") and plan.get("album"):
            removed.setdefault(st["user"], []).extend(ids)
    album_id = plan.get("album")
    for user, ids in removed.items():
        n = clients[user].remove_from_album(album_id, ids)
        if n:
            undo.append({"op": "album_hinzufuegen", "user": user, "album": album_id, "ids": ids})
            if album_id in lib.albums:
                lib.albums[album_id]["medien"] = sorted(set(lib.albums[album_id]["medien"]) - set(ids))
        elif ids:
            errors.append(f"{user}: konnte nicht aus dem Album nehmen")
    return {"gestapelt": made, "medien": sum(len(u["ids"]) for u in undo if u["op"] == "stapel_aufloesen"),
            "fehler": errors, "rueck": undo}
