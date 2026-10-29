"""Duplikate finden, gruppieren (Union-Find), Behalten-Vorschlag und Aktionen."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .client import ImmichClient, ImmichError
from .library import Library
from .models import Asset

log = logging.getLogger(__name__)

# Punktwertung in der gewünschten Rangfolge; jede Stufe schlägt alle folgenden zusammen.
WEIGHTS = [
    ("favorit", "Favorit", 128),
    ("original", "Original mit Kameradaten", 64),
    ("im_album", "im Album", 32),
    ("gps", "hat GPS", 16),
    ("immich", "Immich-Vorschlag", 8),
    ("extern", "externe Bibliothek", 4),
    ("fassung", "bevorzugte Fassung", 2),
    ("aufloesung", "höchste Auflösung", 1),
]

# Dateiformate und Fassungen
RAW_EXT = {"arw", "cr2", "cr3", "crw", "nef", "nrw", "orf", "raf", "rw2", "dng", "pef", "srw", "raw", "3fr",
           "erf", "kdc", "mrw", "x3f", "iiq"}
ORIGINAL_EXT = RAW_EXT | {"heic", "heif", "hif", "avif"}  # Original statt daraus erzeugter Kopie (JPG/PNG)
EDITED_RE = re.compile(r"^img_e(\d)", re.IGNORECASE)  # iPhone: IMG_E1234 = bearbeitete Fassung von IMG_1234
EDIT_KEEP = ("bearbeitung", "original")


def split_name(file_name: str) -> tuple[str, str, bool]:
    """(Basisname ohne Endung und ohne Bearbeitungs-Kennung, Endung, ist bearbeitete Fassung)."""
    stem, _, ext = file_name.lower().rpartition(".")
    if not stem:
        stem, ext = ext, ""
    edited = bool(EDITED_RE.match(stem))
    return EDITED_RE.sub(r"img_\1", stem), ext, edited


def pair_kind(a: Asset, b: Asset) -> str | None:
    """Art eines Paars mit gleichem Basisnamen und gleicher Aufnahmezeit, aber anderem Namen."""
    _, ext_a, ed_a = split_name(a.file_name)
    _, ext_b, ed_b = split_name(b.file_name)
    if (ext_a in RAW_EXT) != (ext_b in RAW_EXT):
        return "raw_paar"
    if ed_a != ed_b:
        return "bearbeitung"
    if ext_a != ext_b:
        return "format"
    return None

QUELLEN = {
    "immich": "Immich-Duplikaterkennung",
    "pruefsumme": "identische Prüfsumme",
    "name_zeit": "gleicher Dateiname + Aufnahmezeit",
    "bildhash": "fast gleicher Bild-Fingerabdruck",
    "format": "gleiche Aufnahme in anderem Format",
    "bearbeitung": "Original und bearbeitete Fassung",
    "raw_paar": "RAW und JPG derselben Aufnahme",
}

AKTIONEN = ("album", "papierkorb")

# Art einer Gruppe – wie sicher es wirklich dieselbe Aufnahme ist
ARTEN = {
    "identisch": "identisch",  # alle Dateien Byte für Byte gleich (gleiche Prüfsumme)
    "sehr_wahrscheinlich": "sehr wahrscheinlich",  # Name + Zeit gleich oder Bild-Fingerabdruck fast gleich
    "format": "anderes Format",  # z. B. IMG_1234.HEIC + IMG_1234.JPG
    "bearbeitung": "Original + Bearbeitung",  # z. B. IMG_1234.HEIC + IMG_E1234.HEIC
    "raw_paar": "RAW + JPG",  # Kamera-RAW und JPG derselben Aufnahme – oft gewollt
    "messenger": "Messenger-Kopie",  # Original mit Kameradaten + verschickte/empfangene Kopie ohne
    "serie": "Serienbild – eher stapeln",  # nur ähnlich, aber fortlaufende Dateinamen kurz hintereinander
    "aehnlich": "ähnlich",  # nur Immich-KI: ähnliches Motiv, z. B. auch Serienbilder
}
STRONG_SOURCES = {"pruefsumme", "name_zeit", "bildhash", "format", "bearbeitung", "raw_paar"}
# Arten, die nicht als „offen“ zählen und nur bei ausdrücklicher Auswahl unter „Alle …“ fallen
OPTIONAL_KINDS = {"raw_paar", "serie"}
SIMILAR_SOURCES = {"immich", "bildhash"}  # nur „sieht ähnlich aus“, keine gemeinsame Datei
NUMBER_RE = re.compile(r"^(.*?)(\d+)$")
SERIES_NUMBER_GAP = 3  # Lücken in der Nummerierung erlaubt (gelöschte Fehlversuche)
SERIES_SPAN_S = 10 * 60  # alle Aufnahmen innerhalb von 10 Minuten


def camera_original(a: Asset) -> bool:
    """Original aus der Kamera: mit Kameradaten und kein Messenger-Dateiname."""
    from .location import MESSENGER_RE
    return bool(a.make or a.model) and not MESSENGER_RE.search(a.file_name or "")


def messenger_copies(assets: list[Asset]) -> bool:
    """Ein Original mit Kameradaten und Kopien ohne (per WhatsApp, Signal & Co. verschickt oder in einer
    Gruppe empfangen) – die Kopien sind höchstens so groß wie das Original."""
    originals = [a for a in assets if camera_original(a)]
    copies = [a for a in assets if not camera_original(a)]
    if not originals or not copies or any(a.type != "IMAGE" for a in assets):
        return False
    best = max(o.pixels for o in originals)
    return all(c.pixels <= best for c in copies)


def same_moment(assets: list[Asset], seconds: float = 2) -> bool:
    """Alle zur selben Zeit aufgenommen (Original und bearbeitete Fassung, z. B. aus einer Foto-App)."""
    times = [a.taken_utc for a in assets]
    return all(times) and len({a.owner for a in assets}) == 1 and \
        (max(times) - min(times)).total_seconds() <= seconds


def numbered_series(assets: list[Asset]) -> bool:
    """Fortlaufend nummerierte Aufnahmen derselben Kamera kurz hintereinander, z. B. IMG_1234, IMG_1235,
    IMG_1237: verschiedene Fotos einer Serie, keine Kopien."""
    if len({a.owner for a in assets}) != 1 or len({(a.make, a.model) for a in assets}) != 1:
        return False
    prefixes, numbers = set(), []
    for a in assets:
        m = NUMBER_RE.match(split_name(a.file_name)[0])
        if not m:
            return False
        prefixes.add(m.group(1))
        numbers.append(int(m.group(2)))
    numbers.sort()
    if len(prefixes) != 1 or len(set(numbers)) != len(numbers):
        return False
    if any(b - a > SERIES_NUMBER_GAP for a, b in zip(numbers, numbers[1:])):
        return False
    times = [a.taken_utc for a in assets if a.taken_utc]
    return len(times) == len(assets) and (max(times) - min(times)).total_seconds() <= SERIES_SPAN_S


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
        for kind in ("raw_paar", "bearbeitung", "format"):
            if kind in self.sources:
                return kind
        if self.sources <= SIMILAR_SOURCES:  # nur „sieht ähnlich aus“: genauer hinsehen
            if messenger_copies(self.assets):
                return "messenger"
            if numbered_series(self.assets):
                return "serie"
            if same_moment(self.assets):
                return "bearbeitung"
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


def _preferred_version(group: DuplicateGroup, a: Asset, edit_keep: str) -> bool:
    _, ext, edited = split_name(a.file_name)
    if any(split_name(x.file_name)[2] for x in group.assets) and not all(
            split_name(x.file_name)[2] for x in group.assets):
        return edited if edit_keep == "bearbeitung" else not edited
    exts = {split_name(x.file_name)[1] for x in group.assets}
    if exts & ORIGINAL_EXT and exts - ORIGINAL_EXT:
        return ext in ORIGINAL_EXT  # HEIC/RAW statt daraus erzeugtem JPG
    return False


def _score_group(group: DuplicateGroup, edit_keep: str = "bearbeitung") -> None:
    max_px = max(a.pixels for a in group.assets)
    mixed = len({camera_original(a) for a in group.assets}) > 1  # nur dann ein Unterschied
    for a in group.assets:
        flags = {
            "favorit": a.favorite,
            "original": mixed and camera_original(a),
            "im_album": a.in_album,
            "gps": a.has_gps,
            "immich": a.id in group.immich_suggested,
            "extern": a.is_external,
            "fassung": _preferred_version(group, a, edit_keep),
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


def find_groups(lib: Library, image_pairs: Iterable[tuple[str, str]] = (),
                edit_keep: str = "bearbeitung") -> list[DuplicateGroup]:
    uf = UnionFind()
    pair_sources: list[tuple[list[str], str]] = [
        ([a, b], "bildhash") for a, b in image_pairs if a in lib.assets and b in lib.assets]
    immich_suggested: set[str] = set()

    for d in lib.immich_duplicates:
        ids = [i for i in d.asset_ids if i in lib.assets]
        if len(ids) >= 2:
            pair_sources.append((ids, "immich"))
            immich_suggested.update(i for i in d.suggested_keep if i in lib.assets)

    by_checksum: dict[str, list[str]] = {}
    by_name_time: dict[tuple[str, str], list[str]] = {}
    by_base_time: dict[tuple[str, str, str], list[Asset]] = {}
    for a in lib.assets.values():
        if a.checksum:
            by_checksum.setdefault(a.checksum, []).append(a.id)
        if a.file_name and a.local_dt:
            when = a.local_dt.replace(microsecond=0).isoformat()
            by_name_time.setdefault((a.file_name.lower(), when), []).append(a.id)
            by_base_time.setdefault((split_name(a.file_name)[0], when, a.type), []).append(a)
    pair_sources += [(ids, "pruefsumme") for ids in by_checksum.values() if len(ids) > 1]
    pair_sources += [(ids, "name_zeit") for ids in by_name_time.values() if len(ids) > 1]
    # Paare: gleicher Basisname + gleiche Aufnahmezeit, aber anderes Format oder andere Fassung
    for members in by_base_time.values():
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                kind = pair_kind(members[i], members[j])
                if kind:
                    pair_sources.append(([members[i].id, members[j].id], kind))

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
        _score_group(g, edit_keep)
        groups.append(g)
    groups.sort(key=lambda g: (g.assets[0].local_date_time or "", g.id), reverse=True)  # stabil fürs Blättern
    return groups


# ------------------------------------------------------------------ Aktionen
@dataclass
class PlannedStep:
    asset: Asset
    action: str  # "papierkorb" | "album" | "keine"
    reason: str
    keeper: Asset | None = None  # bleibt – übernimmt die Alben der Kopie

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.asset.id, "benutzer": self.asset.owner, "dateiname": self.asset.file_name,
                "aktion": self.action, "grund": self.reason, "behalten": self.keeper.id if self.keeper else None}


def plan_group(group: DuplicateGroup, keep_id: str | None, action: str) -> list[PlannedStep]:
    """``keep_id=None``: keins behalten, alle weg. Die Schutzregeln bleiben: externe Medien und die des
    anderen Benutzers (gemessen am vorgeschlagenen Behalten) kommen nur ins Prüf-Album."""
    if action not in AKTIONEN:
        raise ValueError(f"Unbekannte Aktion {action!r} (erlaubt: {', '.join(AKTIONEN)})")
    keeper = group.asset(keep_id or group.suggested_keep)
    own = keeper if keep_id else None
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
                steps.append(PlannedStep(a, "papierkorb", "Kopie" if keep_id else "alle weg", own))
                continue
        else:
            target, reason = "album", "Kopie"
        if a.in_review_album:
            steps.append(PlannedStep(a, "keine", "liegt schon im Prüf-Album", own))
        else:
            steps.append(PlannedStep(a, target, reason, own))
    return steps


def ensure_review_album(lib: Library, client: ImmichClient, name: str) -> str:
    from .library import find_review_album

    album_id = lib.review_albums.get(client.user) or find_review_album(client, name)
    if not album_id:
        album_id = client.create_album(name)["id"]
        log.info("Album '%s' für %s angelegt", name, client.user)
    lib.review_albums[client.user] = album_id
    return album_id


def take_over_albums(lib: Library, clients: dict[str, ImmichClient], steps: list[PlannedStep],
                     result: dict[str, Any]) -> None:
    """Was bleibt, kommt in die Alben der Kopien, die weggehen – z. B. das Original in das geteilte
    Album, in dem nur die WhatsApp-Kopie lag. Nur wo der Besitzer des Originals hineinschreiben darf."""
    review = {i for i in lib.review_albums.values() if i}
    todo: dict[tuple[str, str], list[str]] = {}  # (Benutzer, Album) -> Medien
    for s in steps:
        k = s.keeper
        if k is None or k.id not in lib.assets:
            continue
        for al in lib.albums.values():
            if al["id"] in review or s.asset.id not in al["medien"] or k.id in al["medien"]:
                continue
            if al["rollen"].get(k.owner) in ("owner", "editor") and k.owner in clients:
                ids = todo.setdefault((k.owner, al["id"]), [])
                if k.id not in ids:
                    ids.append(k.id)
    for (user, album_id), ids in todo.items():
        try:
            res = clients[user].add_to_album(album_id, ids)
        except ImmichError as exc:
            result["fehler"].append({"id": album_id, "fehler": f"Album übernehmen: {exc}"})
            continue
        new = [r["id"] for r in res if r.get("success")]
        if new:
            lib.albums[album_id]["medien"] = sorted(set(lib.albums[album_id]["medien"]) | set(new))
            for i in new:
                lib.assets[i].in_album = True
            result["alben_uebernommen"] += len(new)
            result["rueck"].append({"op": "album_entfernen", "user": user, "album": album_id, "ids": new})
            log.info("%d behaltene Medien von %s ins Album „%s“ übernommen", len(new), user, lib.albums[album_id]["name"])


def execute_steps(lib: Library, clients: dict[str, ImmichClient], steps: list[PlannedStep],
                  review_album: str) -> dict[str, Any]:
    trash: dict[str, list[str]] = {}
    album: dict[str, list[str]] = {}
    for s in steps:
        if s.action == "papierkorb":
            trash.setdefault(s.asset.owner, []).append(s.asset.id)
        elif s.action == "album":
            album.setdefault(s.asset.owner, []).append(s.asset.id)

    # "rueck": Schritte für „Rückgängig“ im Verlauf (siehe history.py)
    result: dict[str, Any] = {"papierkorb": 0, "album": 0, "fehler": [], "rueck": [], "alben_uebernommen": 0}
    take_over_albums(lib, clients, [s for s in steps if s.action in ("papierkorb", "album")], result)
    for user, ids in album.items():
        client = clients[user]
        album_id = ensure_review_album(lib, client, review_album)
        added = []
        for r in client.add_to_album(album_id, ids):
            if r.get("success") or r.get("error") == "duplicate":
                result["album"] += 1
                if r.get("success"):
                    added.append(r["id"])
                if r["id"] in lib.assets:
                    lib.assets[r["id"]].in_review_album = True
            else:
                result["fehler"].append({"id": r.get("id"), "fehler": r.get("error")})
        if added:
            result["rueck"].append({"op": "album_entfernen", "user": user, "album": album_id, "ids": added})
        log.info("%d Medien von %s ins Album '%s' gelegt", len(ids), user, review_album)
    for user, ids in trash.items():
        # Doppelte Absicherung: externe Medien niemals in den Papierkorb – außer ihre Datei fehlt
        # ohnehin (offline), dann entfernt der Papierkorb nur den Eintrag in Immich
        ids = [i for i in ids if i in lib.assets and (not lib.assets[i].is_external or lib.assets[i].offline)]
        result["papierkorb"] += clients[user].trash(ids)
        result["rueck"].append({"op": "wiederherstellen", "user": user, "ids": ids,
                                "medien": [lib.assets[i].to_dict() for i in ids]})
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
