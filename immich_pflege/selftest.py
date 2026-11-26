"""Selbsttest: jede Immich-Schnittstelle, die das Tool nutzt, einmal NUR LESEND aufrufen – je Benutzer.

Schreibende Schnittstellen (Orte setzen, taggen, zusammenführen …) werden nicht ausprobiert; für sie zeigt
der Test, ob der API-Key das nötige Recht hat (soweit Immich die Rechte des Keys verrät).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .client import ImmichClient, ImmichError
from .library import Library

# Schreibende Funktionen: Recht des API-Keys → wofür
WRITE_PERMISSIONS = {
    "asset.update": "Ort, Zeit, Archivieren setzen",
    "asset.delete": "Papierkorb",
    "albumAsset.create": "Medien in Alben legen",
    "album.create": "Alben anlegen",
    "albumUser.create": "Alben teilen",
    "tag.create": "Tags anlegen",
    "tag.asset": "Medien taggen",
    "stack.create": "Stapeln",
    "person.merge": "Personen zusammenführen",
    "job.create": "Vorschau/Metadaten neu erzeugen lassen",
}


def _sample(lib: Library | None, user: str, image: bool = True) -> str | None:
    """Ein eigenes Medium als Testobjekt (das kleinste Bild – lädt am schnellsten)."""
    if lib is None:
        return None
    own = [a for a in lib.assets.values() if a.owner == user and (a.type == "IMAGE") == image]
    return min(own, key=lambda a: a.file_size or 0).id if own else None


def _checks(client: ImmichClient, lib: Library | None, user: str) -> list[tuple[str, str, Callable[[], str]]]:
    asset = _sample(lib, user)
    first_person: dict[str, Any] = {}

    def status(path: str, params: dict | None = None) -> str:
        code, text = client.probe(path, params)
        if code >= 400:
            raise ImmichError(f"HTTP {code} {text}".strip(), code)
        return f"HTTP {code}"

    def need_asset() -> str:
        if not asset:
            raise LookupError("kein eigenes Bild zum Testen (noch nicht eingelesen?)")
        return asset

    def people() -> str:
        found = client.people()
        first_person.update(found[0] if found else {})
        return f"{len(found)} Personen"

    def person_stats() -> str:
        if not first_person:
            raise LookupError("keine Person zum Testen")
        return f"{client.person_statistics(first_person['id'])} Fotos bei der ersten Person"

    def person_thumb() -> str:
        if not first_person:
            raise LookupError("keine Person zum Testen")
        return status(f"/people/{first_person['id']}/thumbnail")

    def storage() -> str:
        st = client.server_storage()
        return f"{st.get('diskUsagePercentage', '?')} % belegt"

    return [
        ("Server-Version", "Grundfunktion", lambda: "Immich {major}.{minor}.{patch}".format(**client.server_version())),
        ("Konto", "Grundfunktion", lambda: client.me().get("email") or client.me().get("name") or "ok"),
        ("Medien suchen", "Einlesen", lambda: "ok" if client.request("POST", "/search/metadata", json={"size": 1}) is not None else "leer"),
        ("Vorschaubild", "Vorschauen", lambda: status(f"/assets/{need_asset()}/thumbnail", {"size": "thumbnail"})),
        ("Große Vorschau", "Großansicht", lambda: status(f"/assets/{need_asset()}/thumbnail", {"size": "preview"})),
        ("Original", "Ersatz, wenn die Vorschau fehlt", lambda: status(f"/assets/{need_asset()}/original")),
        ("Alben", "Alben, Reisen, Ordner", lambda: f"{len(client.albums())} Alben"),
        ("Album-Zeitleiste", "Album-Inhalte (geteilte Alben)", lambda: "ok" if client.request(
            "GET", "/timeline/buckets", params={"albumId": (client.albums() or [{}])[0].get("id")}) is not None else "ok"),
        ("Tags", "Tags", lambda: f"{len(client.tags())} Tags"),
        ("Stapel", "Stapeln", lambda: f"{len(client.stacks())} Stapel"),
        ("Duplikate (Immich)", "Duplikate", lambda: f"{len(client.duplicates())} Gruppen"),
        ("Papierkorb-Einstellung", "Papierkorb-Übersicht", lambda: f"{client.server_config().get('trashDays', '?')} Tage"),
        ("Speicherplatz", "Speicherprognose", storage),
        ("Ortssuche", "Ort suchen", lambda: f"{len(client.search_places('Berlin'))} Treffer"),
        ("Ortsname zu Koordinaten", "Karte", lambda: "ok" if client.reverse_geocode(52.52, 13.405) is not None else "ok"),
        ("Texterkennung", "Dokumente erkennen (Ohne Ort)", lambda: f"{len(client.ocr(need_asset()))} Textfelder"),
        ("KI-Suche", "KI-Suche bei Tags", lambda: f"{len(client.smart_search('a photo', 1))} Treffer"),
        ("Personen", "Personen, Top-Personen", people),
        ("Personen-Statistik", "Top-Personen", person_stats),
        ("Gesichtsbild", "Personen", person_thumb),
    ]


def run(clients: dict[str, ImmichClient], lib: Library | None, key_info: Callable[[ImmichClient], dict]) -> dict[str, Any]:
    out: dict[str, Any] = {"benutzer": {}}
    for user, client in clients.items():
        checks = []
        for name, purpose, fn in _checks(client, lib, user):
            started = time.monotonic()
            try:
                detail, ok = fn(), True
            except ImmichError as exc:
                detail, ok = str(exc), False
            except LookupError as exc:
                detail, ok = str(exc), None  # nicht prüfbar
            except Exception as exc:  # noqa: BLE001 – Selbsttest soll nie abbrechen
                detail, ok = f"{exc.__class__.__name__}: {exc}", False
            checks.append({"name": name, "zweck": purpose, "ok": ok, "detail": detail,
                           "ms": round((time.monotonic() - started) * 1000)})
        info = key_info(client)
        perms = None if info.get("rechte_alle") is None else (
            "alle" if info["rechte_alle"] else {f["recht"] for f in info.get("rechte_fehlend", [])})
        writes = [{"recht": p, "zweck": why,
                   "ok": None if perms is None else perms == "alle" or p not in perms} for p, why in WRITE_PERMISSIONS.items()]
        out["benutzer"][user] = {"lesen": checks, "schreiben": writes, "rechte_bekannt": perms is not None,
                                 "fehler": sum(1 for c in checks if c["ok"] is False) + sum(1 for w in writes if w["ok"] is False)}
    out["fehler"] = sum(u["fehler"] for u in out["benutzer"].values())
    return out
