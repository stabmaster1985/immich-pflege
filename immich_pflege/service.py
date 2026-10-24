"""Gemeinsame Anwendungslogik für Web-Oberfläche, JSON-API und CLI."""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from . import __version__
from .client import ImmichClient, ImmichError
from .config import Settings
from .duplicates import AKTIONEN, DuplicateGroup, execute_steps, find_groups, plan_group
from .library import Library, scan_library
from .location import apply_locations, find_candidates, group_by_day
from .rules import Resolver, Rule, RuleError, apply as apply_rules, load_rules, preview as preview_rules

log = logging.getLogger(__name__)

CONFIRM_TRASH = "PAPIERKORB"


class ActionError(ValueError):
    """Ungültige Anfrage (z. B. fehlende Bestätigung, unbekannte Gruppe)."""


class Pflege:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        self.settings = settings
        self.clients = {
            name: ImmichClient(settings.api_url, key, name, http=http, timeout=settings.timeout)
            for name, key in settings.users.items()
        }
        self._lib: Library | None = None
        self._lock = threading.RLock()
        self.scanning = False
        self.last_error: str | None = None

    # ------------------------------------------------------------ Bibliothek
    def library(self, refresh: bool = False) -> Library:
        with self._lock:
            if refresh:
                return self.scan()
            if self._lib is None:
                cached = Library.load(self.settings.cache_file)
                if cached and set(cached.users) == set(self.clients):
                    log.info("Bibliothek aus Zwischenspeicher geladen (Stand %s)", cached.scanned_at)
                    self._lib = cached
                else:
                    return self.scan()
            return self._lib

    def scan(self) -> Library:
        with self._lock:
            self.scanning = True
            try:
                lib = scan_library(self.clients, self.settings.review_album)
            except ImmichError as exc:
                self.last_error = str(exc)
                raise
            finally:
                self.scanning = False
            self.last_error = None
            self._lib = lib
            lib.save(self.settings.cache_file)
            return lib

    def _save(self) -> None:
        if self._lib is not None:
            self._lib.save(self.settings.cache_file)

    def status(self, check_server: bool = True) -> dict[str, Any]:
        lib = self._lib or Library.load(self.settings.cache_file)
        out: dict[str, Any] = {
            "version": __version__,
            "immich_url": self.settings.immich_url,
            "benutzer": list(self.clients),
            "pruef_album": self.settings.review_album,
            "ort_max_stunden": self.settings.location_max_hours,
            "ort_extern_erlaubt": self.settings.location_include_external,
            "regeldatei": str(self.settings.rules_file),
            "einlesen_laeuft": self.scanning,
            "letzter_fehler": self.last_error,
            "bibliothek": None,
            "warnungen": [],
        }
        if lib:
            out["bibliothek"] = {"stand": lib.scanned_at, "dauer_s": lib.duration_s, **lib.counts()}
            out["warnungen"] += lib.warnings
        if check_server:
            out["server"] = self.check_server()
            out["warnungen"] += out["server"].get("warnungen", [])
        return out

    def check_server(self) -> dict[str, Any]:
        result: dict[str, Any] = {"erreichbar": False, "version": None, "schluessel": {},
                                  "warnungen": []}
        for name, client in self.clients.items():
            try:
                if result["version"] is None:
                    v = client.server_version()
                    result["version"] = f"{v.get('major')}.{v.get('minor')}.{v.get('patch')}"
                    result["erreichbar"] = True
                    if v.get("major") != 3:
                        result["warnungen"].append(
                            f"Immich {result['version']} erkannt – getestet ist das Tool mit 3.x")
                me = client.me()
                result["schluessel"][name] = {"ok": True, "konto": me.get("email") or me.get("name")}
            except ImmichError as exc:
                result["schluessel"][name] = {"ok": False, "fehler": str(exc)}
                if exc.status in (401, 403):
                    result["erreichbar"] = True
        return result

    # --------------------------------------------------------------- Duplikate
    def duplicate_groups(self) -> list[DuplicateGroup]:
        return find_groups(self.library())

    def duplicates_view(self, offset: int = 0, limit: int = 50, include_done: bool = True) -> dict:
        lib = self.library()
        groups = find_groups(lib)
        if not include_done:
            groups = [g for g in groups if not g.done()]
        page = groups[offset: offset + limit] if limit > 0 else groups[offset:]
        return {
            "stand": lib.scanned_at,
            "gesamt": len(groups),
            "offen": sum(1 for g in groups if not g.done()),
            "benutzeruebergreifend": sum(1 for g in groups if len(g.users) > 1),
            "offset": offset,
            "gruppen": [g.to_dict() for g in page],
        }

    def plan_duplicates(self, action: str, groups: list[dict] | None = None, all_groups: bool = False):
        if action not in AKTIONEN:
            raise ActionError(f"Unbekannte Aktion {action!r} – erlaubt: {', '.join(AKTIONEN)}")
        found = {g.id: g for g in self.duplicate_groups()}
        selection: list[tuple[DuplicateGroup, str]] = []
        if all_groups:
            selection = [(g, g.suggested_keep) for g in found.values() if not g.done()]
        else:
            if not groups:
                raise ActionError("Keine Gruppen ausgewählt (groups: [{id, keep}] oder all: true)")
            for sel in groups:
                g = found.get(sel.get("id", ""))
                if g is None:
                    raise ActionError(f"Gruppe {sel.get('id')!r} nicht gefunden – bitte neu einlesen")
                keep = sel.get("keep") or g.suggested_keep
                if keep not in {a.id for a in g.assets}:
                    raise ActionError(f"Medium {keep!r} gehört nicht zu Gruppe {g.id}")
                selection.append((g, keep))
        steps = []
        for g, keep in selection:
            steps += plan_group(g, keep, action)
        return selection, steps

    def apply_duplicates(self, action: str, groups: list[dict] | None = None, all_groups: bool = False,
                         confirm: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        with self._lock:
            selection, steps = self.plan_duplicates(action, groups, all_groups)
            summary = {
                "aktion": action,
                "gruppen": len(selection),
                "papierkorb": sum(1 for s in steps if s.action == "papierkorb"),
                "album": sum(1 for s in steps if s.action == "album"),
                "keine": sum(1 for s in steps if s.action == "keine"),
                "schritte": [s.to_dict() for s in steps],
            }
            if dry_run:
                return {"vorschau": True, **summary}
            if action == "papierkorb" and summary["papierkorb"] and confirm != CONFIRM_TRASH:
                raise ActionError(f'Papierkorb nur mit Bestätigung: confirm="{CONFIRM_TRASH}"')
            result = execute_steps(self.library(), self.clients, steps, self.settings.review_album)
            self._save()
            return {"vorschau": False, **summary, "ergebnis": result}

    # ------------------------------------------------------------- Ohne Ort
    def no_location_view(self, max_hours: float | None = None, offset: int = 0, limit: int = 30,
                         only_suggestions: bool = False) -> dict[str, Any]:
        lib = self.library()
        hours = max_hours or self.settings.location_max_hours
        cands = find_candidates(lib, hours, self.settings.location_include_external)
        if only_suggestions:
            cands = [c for c in cands if c.suggestion and c.editable]
        days = group_by_day(cands)
        page = days[offset: offset + limit] if limit > 0 else days[offset:]
        return {
            "stand": lib.scanned_at,
            "max_stunden": hours,
            "extern_erlaubt": self.settings.location_include_external,
            "medien": len(cands),
            "mit_vorschlag": sum(1 for c in cands if c.suggestion and c.editable),
            "tage_gesamt": len(days),
            "offset": offset,
            "tage": page,
        }

    def apply_no_location(self, ids: list[str], max_hours: float | None = None) -> dict[str, Any]:
        if not ids:
            raise ActionError("Keine Medien ausgewählt (ids: [...])")
        with self._lock:
            res = apply_locations(self.library(), self.clients, ids,
                                  max_hours or self.settings.location_max_hours,
                                  self.settings.location_include_external)
            self._save()
            return res

    # ----------------------------------------------------------------- Tags
    def rules(self) -> list[Rule]:
        return load_rules(self.settings.rules_file, list(self.clients))

    def _select_rules(self, names: list[str] | None) -> list[Rule]:
        rules = self.rules()
        if names:
            known = {r.name for r in rules}
            unknown = [n for n in names if n not in known]
            if unknown:
                raise ActionError(f"Unbekannte Regel(n): {', '.join(unknown)}")
            rules = [r for r in rules if r.name in names]
        return rules

    def tags_preview(self, names: list[str] | None = None) -> dict[str, Any]:
        rules = self._select_rules(names)
        resolver = Resolver(self.clients)
        lib = self.library()
        return {"stand": lib.scanned_at, "regeldatei": str(self.settings.rules_file),
                "regeln": preview_rules(rules, lib, resolver), "warnungen": resolver.warnings}

    def tags_apply(self, names: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            rules = self._select_rules(names)
            resolver = Resolver(self.clients)
            res = apply_rules(rules, self.library(), resolver)
            return {"regeln": res, "warnungen": resolver.warnings,
                    "getaggt": sum(r.get("getaggt", 0) for r in res)}

    # ------------------------------------------------------------- Vorschau
    def thumbnail(self, asset_id: str, size: str = "thumbnail") -> tuple[bytes, str]:
        lib = self._lib
        owner = lib.assets[asset_id].owner if lib and asset_id in lib.assets else None
        order = [owner] if owner else []
        order += [n for n in self.clients if n != owner]
        last: ImmichError | None = None
        for name in order:
            try:
                return self.clients[name].thumbnail(asset_id, size)
            except ImmichError as exc:
                last = exc
        raise last or ImmichError("Kein Benutzer konfiguriert")


__all__ = ["Pflege", "ActionError", "RuleError", "ImmichError", "CONFIRM_TRASH"]
