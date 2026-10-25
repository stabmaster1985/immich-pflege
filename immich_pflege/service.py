"""Gemeinsame Anwendungslogik für Web-Oberfläche, JSON-API und CLI."""

from __future__ import annotations

import logging
import threading
from typing import Any

import httpx

from . import __version__
from .client import ImmichClient, ImmichError
from .config import Settings
from .duplicates import (AKTIONEN, ARTEN, OPTIONAL_KINDS, DuplicateGroup, IgnoreList, clear_immich_duplicates, execute_steps,
                         find_groups, plan_group)
from .imagehash import HashProgress, HashStore, compute_missing, similar_pairs
from .library import Library, scan_library
from .location import (LEVELS, analyze, apply_locations, level_at_least, month_facets, month_key,
                       month_label, place_facets, place_key)
from .rules import Resolver, Rule, RuleError, apply as apply_rules, load_rules, preview as preview_rules

log = logging.getLogger(__name__)

CONFIRM_TRASH = "PAPIERKORB"


class ActionError(ValueError):
    """Ungültige Anfrage (z. B. fehlende Bestätigung, unbekannte Gruppe)."""


class NotConfigured(ActionError):
    """Immich-Adresse oder API-Keys fehlen noch."""

    def __init__(self) -> None:
        super().__init__("Noch nicht eingerichtet – bitte unter Einstellungen Immich-Adresse "
                         "und mindestens einen API-Key eintragen")


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
            result["schluessel"][name] = {"ok": True, "konto": me.get("email") or me.get("name")}
        except ImmichError as exc:
            result["schluessel"][name] = {"ok": False, "fehler": str(exc)}
            if exc.status in (401, 403):
                result["erreichbar"] = True
    return result


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
        self.hash_store = HashStore(settings.data_dir / "bildhash.json")
        self.hash_progress = HashProgress()
        self._hash_thread: threading.Thread | None = None
        self._pairs_cache: tuple[tuple, list[tuple[str, str]]] | None = None

    # ------------------------------------------------------------ Bibliothek
    def cached_library(self) -> Library | None:
        """Bibliothek aus Speicher oder Zwischenspeicher – ohne bei Immich einzulesen."""
        with self._lock:
            if self._lib is None:
                cached = Library.load(self.settings.cache_file)
                if (cached and set(cached.users) == set(self.clients)
                        and cached.immich_url in ("", self.settings.immich_url)):
                    log.info("Bibliothek aus Zwischenspeicher geladen (Stand %s)", cached.scanned_at)
                    self._lib = cached
            return self._lib

    def library(self, refresh: bool = False) -> Library:
        if not self.clients:
            raise NotConfigured()
        with self._lock:
            if refresh:
                return self.scan()
            return self.cached_library() or self.scan()

    def scan(self) -> Library:
        if not self.clients:
            raise NotConfigured()
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
            lib.immich_url = self.settings.immich_url
            self._lib = lib
            lib.save(self.settings.cache_file)
        if self.settings.dup_image_hash:
            self.start_hashing()
        return lib

    def _save(self) -> None:
        if self._lib is not None:
            self._lib.save(self.settings.cache_file)

    def status(self, check_server: bool = True) -> dict[str, Any]:
        lib = self._lib or Library.load(self.settings.cache_file)
        out: dict[str, Any] = {
            "version": __version__,
            "immich_url": self.settings.immich_url,
            "eingerichtet": self.settings.configured,
            "benutzer": list(self.clients),
            "pruef_album": self.settings.review_album,
            "ort_max_stunden": self.settings.location_max_hours,
            "ort_extern_erlaubt": self.settings.location_include_external,
            "link_url": self.settings.browser_url,
            "regeldatei": str(self.settings.rules_file),
            "einlesen_laeuft": self.scanning,
            "letzter_fehler": self.last_error,
            "bibliothek": None,
            "warnungen": [],
        }
        if lib:
            out["bibliothek"] = {"stand": lib.scanned_at, "dauer_s": lib.duration_s, **lib.counts()}
            out["warnungen"] += lib.warnings
        if check_server and self.clients:
            out["server"] = self.check_server()
            out["warnungen"] += out["server"].get("warnungen", [])
        return out

    def check_server(self) -> dict[str, Any]:
        if not self.clients:
            raise NotConfigured()
        return check_server(self.clients)

    # --------------------------------------------------------------- Duplikate
    # ------------------------------------------------------ Bild-Fingerabdruck
    def start_hashing(self) -> bool:
        """Fehlende Bild-Fingerabdrücke im Hintergrund berechnen (falls nicht schon läuft)."""
        if self._hash_thread and self._hash_thread.is_alive():
            return False
        lib = self.cached_library()
        if lib is None:
            return False
        self.hash_progress = HashProgress()
        self._hash_thread = threading.Thread(
            target=compute_missing, args=(lib, self.clients, self.hash_store, self.hash_progress),
            name="bild-fingerabdruck", daemon=True)
        self._hash_thread.start()
        return True

    def compute_hashes(self) -> dict[str, Any]:
        """Synchron rechnen (CLI und Tests)."""
        self.hash_progress = HashProgress()
        compute_missing(self.library(), self.clients, self.hash_store, self.hash_progress)
        return self.hash_progress.to_dict()

    def image_pairs(self) -> list[tuple[str, str]]:
        if not self.settings.dup_image_hash:
            return []
        lib = self.library()
        key = (lib.scanned_at, len(lib.assets), len(self.hash_store.data))
        if not self._pairs_cache or self._pairs_cache[0] != key:
            self._pairs_cache = (key, similar_pairs(lib, self.hash_store))
        return self._pairs_cache[1]

    def hash_status(self) -> dict[str, Any]:
        lib = self._lib
        missing = len(self.hash_store.missing(lib)) if lib else None
        return {"aktiv": self.settings.dup_image_hash, **self.hash_progress.to_dict(),
                "vorhanden": len(self.hash_store.data), "fehlend": missing}

    def ignore_list(self) -> IgnoreList:
        return IgnoreList(self.settings.data_dir / "duplikate_ignoriert.json")

    def duplicate_groups(self, include_ignored: bool = False) -> list[DuplicateGroup]:
        groups = find_groups(self.library(), self.image_pairs(), self.settings.dup_edit_keep)
        if include_ignored:
            return groups
        ignored = self.ignore_list()
        return [g for g in groups if not ignored.contains(g)]

    @staticmethod
    def _filter_groups(groups, art=None, monat=None, cross_user=False, include_optional=False):
        """Ohne Art-Filter fallen optionale Arten (RAW + JPG) weg, außer include_optional."""
        if art and art not in ARTEN:
            raise ActionError(f"Art muss {', '.join(ARTEN)} sein")
        if art:
            groups = [g for g in groups if g.kind == art]
        elif not include_optional:
            groups = [g for g in groups if g.kind not in OPTIONAL_KINDS]
        if monat:
            groups = [g for g in groups if g.month == monat]
        if cross_user:
            groups = [g for g in groups if len(g.users) > 1]
        return groups

    def duplicates_view(self, offset: int = 0, limit: int = 50, include_done: bool = True,
                        art: str | None = None, monat: str | None = None, cross_user: bool = False,
                        ignored: bool = False) -> dict:
        """Gruppen mit Filtern. ``ignored=True`` zeigt nur die als „kein Duplikat“ markierten."""
        lib = self.library()
        all_groups = find_groups(lib, self.image_pairs(), self.settings.dup_edit_keep)
        ignore = self.ignore_list()
        n_ignored = sum(1 for g in all_groups if ignore.contains(g))
        base = [g for g in all_groups if ignore.contains(g) == ignored]
        if not include_done:
            base = [g for g in base if not g.done()]
        groups = self._filter_groups(base, art, monat, cross_user, include_optional=True)
        counted = self._filter_groups(base, art, monat, cross_user)  # ohne RAW + JPG, außer gewählt
        page = groups[offset: offset + limit] if limit > 0 else groups[offset:]
        # Mengen je Art (für den aktuellen Monat) und je Monat (für die aktuelle Art)
        for_kinds = self._filter_groups(base, monat=monat, cross_user=cross_user, include_optional=True)
        months: dict[str, int] = {}
        for g in self._filter_groups(base, art=art, cross_user=cross_user, include_optional=True):
            months[g.month] = months.get(g.month, 0) + 1
        return {
            "stand": lib.scanned_at,
            "gesamt": len(groups),
            "offen": sum(1 for g in counted if not g.done()),
            "benutzeruebergreifend": sum(1 for g in groups if len(g.users) > 1),
            "ignoriert": n_ignored,
            "arten": {k: {"name": label, "anzahl": sum(1 for g in for_kinds if g.kind == k),
                          "offen": sum(1 for g in for_kinds if g.kind == k and not g.done())}
                      for k, label in ARTEN.items()},
            "monate": [{"key": k, "name": month_label(k), "anzahl": v} for k, v in sorted(months.items(), reverse=True)],
            "filter": {"art": art, "monat": monat, "benutzeruebergreifend": cross_user},
            "fingerabdruck": self.hash_status(),
            "offset": offset,
            "gruppen": [g.to_dict() for g in page],
        }

    def plan_duplicates(self, action: str, groups: list[dict] | None = None, all_groups: bool = False,
                        art: str | None = None, monat: str | None = None, cross_user: bool = False):
        if action not in AKTIONEN:
            raise ActionError(f"Unbekannte Aktion {action!r} – erlaubt: {', '.join(AKTIONEN)}")
        found = {g.id: g for g in self.duplicate_groups()}
        selection: list[tuple[DuplicateGroup, str]] = []
        if all_groups:
            chosen = self._filter_groups(list(found.values()), art, monat, cross_user)
            selection = [(g, g.suggested_keep) for g in chosen if not g.done()]
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

    def ignore_duplicates(self, group_ids: list[str], undo: bool = False) -> dict[str, Any]:
        """„Kein Duplikat“: Gruppen dauerhaft ausblenden (bzw. mit undo wieder aufnehmen)."""
        if not group_ids:
            raise ActionError("Keine Gruppen angegeben")
        with self._lock:
            lib = self.library()
            groups = {g.id: g for g in find_groups(lib, self.image_pairs(), self.settings.dup_edit_keep)}
            missing = [i for i in group_ids if i not in groups]
            if missing:
                raise ActionError(f"Gruppe(n) {', '.join(missing)} nicht gefunden – bitte neu laden")
            ignore = self.ignore_list()
            cleared = 0
            for gid in group_ids:
                g = groups[gid]
                if undo:
                    ignore.remove(g.asset_ids)
                else:
                    ignore.add(g.asset_ids)
                    cleared += clear_immich_duplicates(lib, self.clients, g)
            if cleared:
                self._save()
            log.info("%d Gruppe(n) %s", len(group_ids), "wieder aufgenommen" if undo else "als „kein Duplikat“ markiert")
            return {"gruppen": len(group_ids), "in_immich_entfernt": cleared, "rueckgaengig": undo}

    def apply_duplicates(self, action: str, groups: list[dict] | None = None, all_groups: bool = False,
                         confirm: str | None = None, dry_run: bool = False, art: str | None = None,
                         monat: str | None = None, cross_user: bool = False) -> dict[str, Any]:
        with self._lock:
            selection, steps = self.plan_duplicates(action, groups, all_groups, art, monat, cross_user)
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
    def _analysis(self, max_hours: float | None = None):
        hours = max_hours or self.settings.location_max_hours
        return hours, analyze(self.library(), hours, self.settings.location_include_external,
                              self.settings.location_skip_screenshots)

    @staticmethod
    def _filter_series(series, only_suggestions=False, min_confidence=None, ort=None, monat=None):
        if min_confidence and min_confidence not in LEVELS:
            raise ActionError(f"Sicherheit muss {', '.join(LEVELS)} sein")
        if only_suggestions or min_confidence:
            def keep(c):
                return c.applicable and (not min_confidence or level_at_least(c.suggestion.confidence, min_confidence))
            series = [s for s in series if any(keep(c) for c in s.members)]
        if ort:
            series = [s for s in series if place_key(s) == ort]
        if monat:
            series = [s for s in series if month_key(s) == monat]
        return series

    def no_location_view(self, max_hours: float | None = None, offset: int = 0, limit: int = 20,
                         only_suggestions: bool = False, min_confidence: str | None = None,
                         ort: str | None = None, monat: str | None = None,
                         overview: bool = False) -> dict[str, Any]:
        """Serien ohne Ort. ``overview`` liefert nur die Orte mit Mengen (ohne Serien)."""
        lib = self.library()
        hours, an = self._analysis(max_hours)
        base = self._filter_series(an.series, only_suggestions, min_confidence)
        series = self._filter_series(base, ort=ort, monat=monat)
        applicable = [c for c in an.candidates if c.applicable]
        out = {
            "stand": lib.scanned_at,
            "max_stunden": hours,
            "extern_erlaubt": self.settings.location_include_external,
            "screenshots_ausgeblendet": an.screenshots,
            "medien": len(an.candidates),
            "mit_vorschlag": len(applicable),
            "nach_sicherheit": {lvl: sum(1 for c in applicable if c.suggestion.confidence == lvl)
                                for lvl in reversed(LEVELS)},
            # Mengen je Ort (für den aktuellen Monat) und je Monat (für den aktuellen Ort)
            "orte": place_facets(self._filter_series(base, monat=monat)),
            "monate": month_facets(self._filter_series(base, ort=ort)),
            "filter": {"ort": ort, "monat": monat},
            "serien_gesamt": len(series),
            "medien_gefiltert": sum(len(s.members) for s in series),
            "offset": offset,
        }
        if not overview:
            page = series[offset: offset + limit] if limit > 0 else series[offset:]
            out["serien"] = [s.to_dict() for s in page]
        return out

    def apply_no_location(self, ids: list[str] | None = None, max_hours: float | None = None,
                          min_confidence: str | None = None, series: list[str] | None = None,
                          place: dict | None = None, ort: str | None = None,
                          monat: str | None = None) -> dict[str, Any]:
        """ids und/oder series (Serien-IDs) übernehmen; ort/monat wählt alle Serien eines Ortes
        bzw. Monats; place = {breite, laenge, name} setzt einen von Hand gewählten Ort;
        min_confidence ohne Auswahl = alle ab dieser Sicherheit."""
        if min_confidence and min_confidence not in LEVELS:
            raise ActionError(f"Sicherheit muss {', '.join(LEVELS)} sein")
        with self._lock:
            hours, an = self._analysis(max_hours)
            selected: list[str] | None = list(ids or [])
            if ort or monat:
                chosen = self._filter_series(an.series, ort=ort, monat=monat)
                if not chosen:
                    raise ActionError("Keine Serien für diesen Ort/Monat – bitte neu laden")
                series = list(series or []) + [s.id for s in chosen]
            if series:
                known = {s.id: s for s in an.series}
                missing = [sid for sid in series if sid not in known]
                if missing:
                    raise ActionError(f"Serie(n) {', '.join(missing)} nicht gefunden – bitte neu laden")
                for sid in series:
                    selected += [c.asset.id for c in known[sid].members
                                 if c.editable and (place or c.suggestion)
                                 and (not min_confidence or (c.suggestion and
                                      level_at_least(c.suggestion.confidence, min_confidence)))]
            if not selected:
                if not min_confidence or place:
                    raise ActionError("Keine Medien ausgewählt (ids, series oder min_confidence)")
                selected = None
            manual = None
            if place:
                try:
                    manual = (float(place["breite"]), float(place["laenge"]), place.get("name"))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ActionError("place braucht breite und laenge") from exc
                if not (-90 <= manual[0] <= 90 and -180 <= manual[1] <= 180):
                    raise ActionError("Koordinaten außerhalb des gültigen Bereichs")
            res = apply_locations(self.library(), self.clients, selected, hours,
                                  self.settings.location_include_external,
                                  skip_screenshots=self.settings.location_skip_screenshots,
                                  min_confidence=min_confidence if selected is None else None,
                                  manual=manual)
            self._save()
            return res

    def search_places(self, name: str) -> list[dict[str, Any]]:
        if not self.clients:
            raise NotConfigured()
        if len(name.strip()) < 2:
            return []
        client = next(iter(self.clients.values()))
        out = []
        for p in client.search_places(name.strip())[:15]:
            region = ", ".join(x for x in (p.get("admin2name"), p.get("admin1name")) if x)
            out.append({"name": p.get("name"), "region": region,
                        "breite": p.get("latitude"), "laenge": p.get("longitude")})
        return out

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


__all__ = ["Pflege", "ActionError", "NotConfigured", "check_server", "RuleError", "ImmichError", "CONFIRM_TRASH"]
