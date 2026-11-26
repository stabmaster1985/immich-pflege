"""Gemeinsames für service.py und seine Mixins: Fehler, Bestätigungswort, Rechte der API-Keys."""

from __future__ import annotations

from typing import Any

from .client import ImmichClient, ImmichError

CONFIRM_TRASH = "PAPIERKORB"


class ActionError(ValueError):
    """Ungültige Anfrage (z. B. fehlende Bestätigung, unbekannte Gruppe)."""


class NotConfigured(ActionError):
    """Immich-Adresse oder API-Keys fehlen noch."""

    def __init__(self) -> None:
        super().__init__("Noch nicht eingerichtet – bitte unter Einstellungen Immich-Adresse "
                         "und mindestens einen API-Key eintragen")


def n_media(count: int) -> str:
    return f"{count} {'Medium' if count == 1 else 'Medien'}"


# Rechte, die das Tool vom API-Key braucht (Immich-Namen) – und wofür
KEY_PERMISSIONS = {
    "asset.read": "Medien lesen und suchen",
    "asset.view": "Vorschaubilder",
    "asset.download": "Original als Ersatz, wenn Immich keine Vorschau hat",
    "asset.update": "Ort, Zeit, Archivieren",
    "asset.delete": "Papierkorb",
    "album.read": "Alben lesen",
    "album.create": "Alben anlegen",
    "album.update": "Titelbild",
    "album.delete": "Alben löschen/zusammenführen",
    "albumAsset.create": "Medien in Alben legen",
    "albumAsset.delete": "Medien aus Alben nehmen (Rückgängig)",
    "albumUser.create": "Alben teilen",
    "tag.read": "Tags lesen",
    "tag.create": "Tags anlegen",
    "tag.asset": "Medien taggen",
    "stack.create": "Stapeln",
    "stack.delete": "Stapel auflösen (Rückgängig)",
    "duplicate.read": "Immichs Duplikate lesen",
    "person.read": "Regeln mit Personen",
    "job.create": "Vorschau neu erzeugen lassen",
    "server.storage": "Speicherprognose (freier Platz)",
    "person.statistics": "Top-Personen in der Statistik",
    "person.merge": "doppelte Personen zusammenführen",
}


def key_permissions(client: ImmichClient) -> dict[str, Any]:
    """Rechte des API-Keys (Immich ≥ 1.135: GET /api-keys/me): {rechte_alle, rechte_fehlend: [{recht, wofuer}]}.
    Ältere Immich-Versionen kennen die Abfrage nicht – dann nichts melden."""
    try:
        info = client.my_api_key()
    except ImmichError:
        return {}
    perms = set(info.get("permissions") or [])
    if not perms or "all" in perms:
        return {"rechte_alle": True, "rechte_fehlend": []}
    missing = [{"recht": p, "wofuer": why} for p, why in KEY_PERMISSIONS.items() if p not in perms]
    return {"rechte_alle": False, "rechte_fehlend": missing, "key_name": info.get("name")}


def check_server(clients: dict[str, ImmichClient]) -> dict[str, Any]:
    """Erreichbarkeit, Version und Gültigkeit jedes API-Keys prüfen."""
    result: dict[str, Any] = {"erreichbar": False, "version": None, "schluessel": {}, "warnungen": []}
    for name, client in clients.items():
        try:
            if result["version"] is None:
                v = client.server_version()
                result["version"] = f"{v.get('major')}.{v.get('minor')}.{v.get('patch')}"
                result["erreichbar"] = True
                if v.get("major") != 3:
                    result["warnungen"].append(
                        f"Immich {result['version']} erkannt – getestet ist das Tool mit 3.x")
            me = client.me()
            result["schluessel"][name] = {"ok": True, "konto": me.get("email") or me.get("name"),
                                          **key_permissions(client)}
        except ImmichError as exc:
            result["schluessel"][name] = {"ok": False, "fehler": str(exc)}
            if exc.status in (401, 403):
                result["erreichbar"] = True
    return result


STORAGE_CACHE_S = 600  # Speicherplatz höchstens alle 10 min bei Immich abfragen
PEOPLE_PARALLEL = 6  # gleichzeitige Anfragen bei Personen
