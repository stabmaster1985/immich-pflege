"""Tag-Vorschläge statt selbst geschriebener Regeln.

1. **Aus den Daten** (exakt gezählt, intern als Regel ausgedrückt): Länder außer dem Heimatland,
   Kameras, Screenshots, WhatsApp-Bilder.
2. **KI-Suche** (Immichs Smart Search): Begriffe wie Hund, Strand, Quittung. Die Treffer kommen nach
   Passgenauigkeit sortiert, aber ohne feste Grenze – deshalb wählt man in der Oberfläche das erste
   Bild, das nicht mehr passt; alles davor wird getaggt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from .client import ImmichClient
from .library import Library
from .location import is_screenshot

log = logging.getLogger(__name__)

MIN_COUNTRY = 10  # so viele Fotos braucht ein Land für einen Vorschlag
MIN_CAMERA = 30
MIN_SOURCE = 10
SMART_SIZE = 120  # Treffer je Benutzer, die die KI-Suche holt (Standard)
SMART_MAX = 5000  # höchstens so viele neue Treffer je Benutzer
SMART_PAGE = 1000  # mehr gibt Immich pro Abfrage nicht her
SMART_SCAN = 20000  # so weit wird in der Rangliste höchstens geblättert (schon getaggte übersprungen)
WHATSAPP_RE = r"-WA\d{4}"

# Begriffe für die KI-Suche: Anzeige, Suchtext (englisch – Immichs Standardmodell versteht Englisch am
# besten), vorgeschlagener Tag
BEGRIFFE = [
    ("Hund", "a photo of a dog", "Tiere/Hund"),
    ("Katze", "a photo of a cat", "Tiere/Katze"),
    ("Strand", "a beach with sand and sea", "Natur/Strand"),
    ("Berge", "mountains landscape", "Natur/Berge"),
    ("Schnee", "snow in winter", "Natur/Schnee"),
    ("Sonnenuntergang", "a sunset", "Natur/Sonnenuntergang"),
    ("Feuerwerk", "fireworks at night", "Anlässe/Feuerwerk"),
    ("Geburtstag", "a birthday cake with candles", "Anlässe/Geburtstag"),
    ("Weihnachten", "a christmas tree", "Anlässe/Weihnachten"),
    ("Essen", "a plate of food", "Essen"),
    ("Auto", "a car", "Fahrzeuge/Auto"),
    ("Quittung", "a receipt from a shop", "Dokumente/Quittung"),
    ("Dokument", "a scanned paper document with text", "Dokumente/Dokument"),
]


def _sid(kind: str, key: str) -> str:
    return "v" + hashlib.sha1(f"{kind}:{key}".encode()).hexdigest()[:11]


def home_country(lib: Library) -> str | None:
    counts = Counter(a.country for a in lib.assets.values() if a.country)
    return counts.most_common(1)[0][0] if counts else None


def _nice_spelling(variants: Counter) -> tuple[str, str]:
    """Schönste Schreibweise: Hersteller nicht nur in Großbuchstaben (Sony statt SONY), sonst die häufigste."""
    def pretty(word: str, options: list[str]) -> str:
        mixed = [o for o in options if not o.isupper()]
        if mixed:
            return mixed[0]
        return word.title() if len(word) > 3 else word  # SONY -> Sony, aber HTC/LG bleiben
    ordered = [v for v, _ in variants.most_common()]
    make = pretty(ordered[0][0], [m for m, _ in ordered])
    return make, ordered[0][1]


def data_suggestions(lib: Library) -> list[dict[str, Any]]:
    """Vorschläge als Regel-Definitionen: {id, art, titel, grund, regel}."""
    out: list[dict[str, Any]] = []
    home = home_country(lib)
    for country, n in Counter(a.country for a in lib.assets.values() if a.country).most_common():
        if country == home or n < MIN_COUNTRY:
            continue
        out.append({"id": _sid("land", country), "art": "land", "titel": f"Reisen nach {country}",
                    "grund": f"{n} Fotos mit Ort in {country}",
                    "regel": {"name": f"Vorschlag: {country}", "tag": f"Reisen/{country}", "land": country}})
    # Kameras unabhängig von der Schreibweise: „SONY“ und „Sony“ sind dieselbe Kamera
    spellings: dict[tuple[str, str], Counter] = {}
    for a in lib.assets.values():
        if a.make and a.model and a.make.strip() and a.model.strip():
            make, model = a.make.strip(), a.model.strip()
            spellings.setdefault((make.lower(), model.lower()), Counter())[(make, model)] += 1
    cams = sorted(spellings.items(), key=lambda kv: -sum(kv[1].values()))
    for (make_l, model_l), variants in cams:
        n = sum(variants.values())
        if n < MIN_CAMERA:
            continue
        make, model = _nice_spelling(variants)
        label = model if model_l.startswith(make_l) else f"{make} {model}"
        out.append({"id": _sid("kamera", f"{make_l}|{model_l}"), "art": "kamera", "titel": f"Kamera {label}",
                    "grund": f"{n} Medien mit dieser Kamera",
                    "regel": {"name": f"Vorschlag: {label}", "tag": f"Kamera/{label}", "hersteller": make,
                              "modell": f"^{re.escape(model)}$"}})  # Regeln: Groß/klein egal
    shots = sum(1 for a in lib.assets.values() if is_screenshot(a))
    if shots >= MIN_SOURCE:
        out.append({"id": _sid("quelle", "screenshot"), "art": "quelle", "titel": "Screenshots",
                    "grund": f"{shots} Bildschirmfotos",
                    "regel": {"name": "Vorschlag: Screenshots", "tag": "Quelle/Screenshot",
                              "dateiname": r"^(Screenshot|IMG_\d+\.PNG$)", "typ": "foto"}})
    wa = sum(1 for a in lib.assets.values() if re.search(WHATSAPP_RE, a.file_name or ""))
    if wa >= MIN_SOURCE:
        out.append({"id": _sid("quelle", "whatsapp"), "art": "quelle", "titel": "WhatsApp-Bilder",
                    "grund": f"{wa} Bilder und Videos aus WhatsApp",
                    "regel": {"name": "Vorschlag: WhatsApp", "tag": "Quelle/WhatsApp", "dateiname": WHATSAPP_RE}})
    return out


def smart_results(clients: dict[str, ImmichClient], lib: Library, query: str,
                  exclude: set[str], size: int = SMART_SIZE) -> list[str]:
    """Treffer der KI-Suche beider Benutzer, abwechselnd nach Rang zusammengeführt (nur eigene Medien).

    Schon getaggte, vorgemerkte und ausgeblendete (``exclude``) werden übersprungen und weiter hinten
    nachgeholt – so kommen beim nächsten Suchen wirklich die nächsten Treffer."""
    size = max(1, min(size, SMART_MAX))
    per_user: list[list[str]] = []
    for name, client in clients.items():
        ids: list[str] = []
        page, scanned = 1, 0
        while len(ids) < size and scanned < SMART_SCAN:
            items, more = client.smart_search_page(query, SMART_PAGE if size > SMART_PAGE // 2 else min(SMART_PAGE, size * 2), page)
            scanned += len(items)
            ids += [raw["id"] for raw in items if raw.get("id") in lib.assets and lib.assets[raw["id"]].owner == name
                    and raw["id"] not in exclude and raw["id"] not in ids]
            if not more or not items:
                break
            page += 1
        per_user.append(ids[:size])
    merged: list[str] = []
    for rank in range(max((len(x) for x in per_user), default=0)):
        for ids in per_user:
            if rank < len(ids) and ids[rank] not in merged:
                merged.append(ids[rank])
    return merged


class SmartHidden:
    """Treffer der KI-Suche, die zu einem Tag nicht passen und nicht mehr erscheinen sollen
    (DATA_DIR/ki_ausgeblendet.json, je Tag)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, list[str]] = {}
        try:
            if path.exists():
                self.data = json.loads(path.read_text(encoding="utf-8")).get("ausgeblendet", {})
        except (OSError, ValueError) as exc:
            log.warning("%s unlesbar: %s", path, exc)

    @staticmethod
    def key(tag: str) -> str:
        return tag.strip().strip("/").lower()

    def ids(self, tag: str) -> set[str]:
        return set(self.data.get(self.key(tag), []))

    def update(self, tag: str, ids: Iterable[str], remove: bool = False) -> int:
        with self._lock:
            k = self.key(tag)
            cur = set(self.data.get(k, []))
            cur = cur - set(ids) if remove else cur | set(ids)
            if cur:
                self.data[k] = sorted(cur)
            else:
                self.data.pop(k, None)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ausgeblendet": self.data}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            return len(cur)


class HiddenList:
    """„Kein Interesse“ an einem Vorschlag (DATA_DIR/vorschlaege_ausgeblendet.json)."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.ids: set[str] = set()
        try:
            if path.exists():
                self.ids = set(json.loads(path.read_text(encoding="utf-8")).get("ausgeblendet", []))
        except (OSError, ValueError) as exc:
            log.warning("%s unlesbar: %s", path, exc)

    def update(self, ids: Iterable[str], remove: bool = False) -> None:
        with self._lock:
            self.ids = self.ids - set(ids) if remove else self.ids | set(ids)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"ausgeblendet": sorted(self.ids)}), encoding="utf-8")
            tmp.replace(self.path)
