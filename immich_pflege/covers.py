"""Bessere Titelbilder für Alben.

Ein Titelbild gilt als schlecht, wenn es ein Video, ein Bildschirmfoto, sehr dunkel oder unscharf ist
oder die Datei fehlt. Vorgeschlagen wird das beste Foto aus dem Album: Favoriten zuerst, dann scharf
und mittelhell (gleiche Werte wie beim Aufräumen). Setzen darf das Titelbild nur der Besitzer des
Albums; Rückgängig stellt das alte wieder ein.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .albumcare import _info  # Albumkarte wie bei den anderen Einträgen
from .cleanup import BLUR_MAX, DARK_MAX
from .client import ImmichClient
from .imagehash import HashStore
from .library import Library
from .location import is_screenshot
from .models import Asset

CHOICES = 8  # so viele Fotos stehen zur Auswahl
SHARP_FULL = 40.0  # ab dieser Schärfe zählt ein Foto als voll scharf


def problem(a: Asset | None, store: HashStore) -> str | None:
    """Warum dieses Titelbild schlecht ist – oder None."""
    if a is None:
        return "kein Titelbild"
    if a.offline:
        return "die Datei fehlt"
    if a.type == "VIDEO":
        return "ein Video"
    if is_screenshot(a):
        return "ein Bildschirmfoto"
    q = store.quality(a)
    if q:
        if q[1] <= DARK_MAX:
            return "sehr dunkel"
        if q[0] <= BLUR_MAX:
            return "unscharf"
    return None


def candidates(lib: Library, album: dict[str, Any], store: HashStore) -> list[Asset]:
    """Gute Fotos des Albums, die besten zuerst."""
    out = []
    for i in album["medien"]:
        a = lib.assets.get(i)
        if a is None or a.type != "IMAGE" or a.offline or is_screenshot(a):
            continue
        q = store.quality(a)
        if q is None or q[1] <= DARK_MAX or q[0] <= BLUR_MAX:
            continue
        sharp, bright = q
        score = min(sharp, SHARP_FULL) / SHARP_FULL + 1 - abs(bright - 128) / 128
        out.append((a.favorite, score, a))
    out.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in out]


def find_covers(lib: Library, store: HashStore) -> list[dict[str, Any]]:
    items = []
    for al in lib.albums.values():
        if not al["besitzer"] or not al["medien"]:
            continue
        current = al.get("titelbild")
        if current and current not in lib.assets:
            continue  # Medium eines anderen Benutzers – nicht beurteilbar
        why = problem(lib.assets.get(current) if current else None, store)
        if why is None:
            continue
        best = candidates(lib, al, store)
        if not best:
            continue
        key = f"titelbild:{al['id']}:{current}"
        items.append({"id": "p" + hashlib.sha1(key.encode()).hexdigest()[:11], "art": "titelbild",
                      "art_text": "Titelbild", "grund": f"Das Titelbild ist {why}" if current else "Kein Titelbild",
                      "ziel": al["id"], "alben": [{**_info(al, lib), "beispiele": []}],
                      "titelbild": lib.assets[current].summary() if current else None,
                      "vorschlag": best[0].id, "auswahl": [a.summary() for a in best[:CHOICES]]})
    items.sort(key=lambda it: it["alben"][0]["name"].lower())
    return items


def plan_cover(lib: Library, album_id: str, asset_id: str) -> dict[str, Any]:
    al = lib.albums[album_id]
    if asset_id not in al["medien"]:
        raise ValueError("Das Foto liegt nicht in diesem Album")
    return {"aktion": "titelbild", "ziel": album_id, "besitzer": al["besitzer"], "titelbild": asset_id,
            "alt": al.get("titelbild"), "loeschen": [], "alle_medien": [asset_id]}


def execute_cover(lib: Library, clients: dict[str, ImmichClient], plan: dict[str, Any]) -> list[dict[str, Any]]:
    owner, album_id = plan["besitzer"], plan["ziel"]
    clients[owner].update_album(album_id, albumThumbnailAssetId=plan["titelbild"])
    old = lib.albums[album_id].get("titelbild") if album_id in lib.albums else plan["alt"]
    if album_id in lib.albums:
        lib.albums[album_id]["titelbild"] = plan["titelbild"]
    return [{"op": "titelbild", "user": owner, "album": album_id, "asset": old}] if old else []
