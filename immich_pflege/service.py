"""Gemeinsame Anwendungslogik für Web-Oberfläche, JSON-API und CLI."""

from __future__ import annotations

import logging
import threading
from dataclasses import replace
from datetime import datetime, timedelta
import time
from typing import Any

import httpx

from . import __version__
from .albums import STATUS as ALBUM_STATUS, AlbumError, ExcludedMedia, Home, TripIgnoreList, execute_plan, overlaps, plan_title, plan_trip, suggest
from .client import ImmichClient, ImmichError
from .config import Settings
from .duplicates import (AKTIONEN, ARTEN, OPTIONAL_KINDS, DuplicateGroup, IgnoreList, PlannedStep,
                         clear_immich_duplicates, execute_steps, find_groups, plan_group)
from .cleanup import ARTEN as CLEANUP_ARTEN, KATEGORIEN as CLEANUP_KATEGORIEN, KeepList, find_items
from .history import HistoryStore, undo_ops
from .timefix import (ARTEN as TIME_ARTEN, execute_shifts, find_fixes, fmt_offset, plan_shifts, shifted,
                      summary as time_summary)
from .imagehash import HashProgress, HashStore, compute_missing, similar_pairs
from .library import Library, apply_album_membership, read_albums, scan_library
from .models import Asset
from .location import (LEVELS, LocationChange, analyze, execute_location_changes, level_at_least,
                       month_facets, month_key, month_label, place_facets, place_key, resolve_locations)
from .rules import (Resolver, Rule, RuleError, apply as apply_rules, dump_rules, load_rules, parse_rules,
                    preview as preview_rules, tag_ids)
from .suggestions import BEGRIFFE, HiddenList, data_suggestions, smart_results
from .stacking import execute_stacks, propose as propose_stacks, whole_album
from .staging import StagingStore

log = logging.getLogger(__name__)

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
        # gleich anlegen: bei verzögertem Anlegen konnten Vorberechnung und Anfrage zwei Listen erzeugen
        self._staging = StagingStore(settings.data_dir / "vorgemerkt.json")
        self.history = HistoryStore(settings.data_dir / "verlauf.json")
        self._trips_cache: tuple[tuple, Any] | None = None
        self._groups_cache: tuple[tuple, list[DuplicateGroup]] | None = None
        self._analysis_cache: tuple[tuple, Any] | None = None
        self._cleanup_cache: tuple[tuple, Any] | None = None
        self._time_cache: tuple[tuple, Any] | None = None
        self._calc_lock = threading.RLock()  # gleiche Berechnung nicht doppelt (Vorberechnung + Anfrage)
        self.background_albums = False  # Web: Album-Inhalte nach dem Einlesen im Hintergrund lesen
        self._albums_thread: threading.Thread | None = None

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
                lib = scan_library(self.clients, self.settings.review_album, self.cached_library(),
                                   read_album_contents=not self.background_albums)
            except ImmichError as exc:
                self.last_error = str(exc)
                raise
            finally:
                self.scanning = False
            self.last_error = None
            lib.immich_url = self.settings.immich_url
            self._lib = lib
            lib.save(self.settings.cache_file)
        if not lib.albums_ready:
            self._albums_thread = threading.Thread(target=self._read_albums, args=(lib,), name="alben-lesen", daemon=True)
            self._albums_thread.start()
        if self.settings.dup_image_hash:
            self.start_hashing()
        self.warm_up_background()
        return lib

    def _read_albums(self, lib: Library) -> None:
        try:
            skip = {a for a in lib.review_albums.values() if a}
            albums = read_albums(self.clients, lib.users, skip, lib.albums)
        except ImmichError as exc:
            log.error("Alben konnten nicht gelesen werden: %s", exc)
            albums = None
        with self._lock:
            if albums is not None:
                lib.albums = albums
                apply_album_membership(lib)
            lib.albums_ready = True
            if self._lib is lib:
                self._save()

    def albums_pending(self, wait_s: float = 0) -> bool:
        lib = self.library()
        if not lib.albums_ready and self._albums_thread is not None:
            self._albums_thread.join(wait_s)
        return not lib.albums_ready

    def _save(self) -> None:
        if self._lib is not None:
            self._lib.rev += 1  # Zwischenergebnisse (Gruppen, Serien, Reisen) neu berechnen
            self._lib.save(self.settings.cache_file)

    def warm_up(self) -> None:
        """Duplikate, Orte und Reisen vorab berechnen, damit die Tabs sofort da sind."""
        if not self.clients or self.cached_library() is None:
            return
        started = time.monotonic()
        try:
            self.all_groups()
            self._analysis()
            self.cleanup_items()
            self.time_fixes()
            if not self.albums_pending():
                self._trips()
        except Exception as exc:  # nur Vorarbeit – Fehler zeigen sich beim echten Aufruf
            log.warning("Vorberechnung fehlgeschlagen: %s", exc)
            return
        log.info("Vorberechnung fertig in %.1f s", time.monotonic() - started)

    def warm_up_background(self) -> None:
        threading.Thread(target=self.warm_up, name="vorberechnen", daemon=True).start()

    def status(self, check_server: bool = True) -> dict[str, Any]:
        lib = self.cached_library()  # einmal laden und behalten statt bei jedem Status neu
        out: dict[str, Any] = {
            "version": __version__,
            "immich_url": self.settings.immich_url,
            "eingerichtet": self.settings.configured,
            "benutzer": list(self.clients),
            "pruef_album": self.settings.review_album,
            "ort_max_stunden": self.settings.location_max_hours,
            "ort_extern_erlaubt": self.settings.location_include_external,
            "link_url": self.settings.browser_url,
            "vorgemerkt": self.staging.summary(),
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
        key = (lib.uid, lib.rev, len(self.hash_store.data))
        hashing = self._hash_thread is not None and self._hash_thread.is_alive()
        # Während der Berechnung nicht bei jedem neuen Fingerabdruck neu vergleichen – erst danach
        if hashing and self._pairs_cache and self._pairs_cache[0][:2] == key[:2]:
            return self._pairs_cache[1]
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

    def all_groups(self) -> list[DuplicateGroup]:
        """Alle Gruppen, zwischengespeichert bis sich Bibliothek oder Fingerabdrücke ändern."""
        lib = self.library()
        pairs = self.image_pairs()
        key = (lib.uid, lib.rev, self._pairs_cache[0] if self._pairs_cache else None, self.settings.dup_edit_keep)
        with self._calc_lock:
            cache = self._groups_cache
            if not cache or cache[0] != key:
                groups = find_groups(lib, pairs, self.settings.dup_edit_keep)
                # schon in einem gemeinsamen Immich-Stapel (z. B. von Immich gestapelte Handy-Bearbeitung): erledigt
                groups = [g for g in groups if len({a.stack_id for a in g.assets}) > 1 or g.assets[0].stack_id is None]
                cache = self._groups_cache = (key, groups)
        return cache[1]

    def duplicate_groups(self, include_ignored: bool = False) -> list[DuplicateGroup]:
        staged = self.staging.asset_ids("duplikat")
        groups = [g for g in self.all_groups() if not (g.asset_ids & staged)]
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
        staged = self.staging.asset_ids("duplikat")
        all_groups = [g for g in self.all_groups() if not (g.asset_ids & staged)]
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
            groups = {g.id: g for g in self.all_groups()}
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
            self._record("duplikat", f"Duplikate: {summary['gruppen']} Gruppen ({'Papierkorb' if action == 'papierkorb' else 'Prüf-Album'})",
                         result["album"] + result["papierkorb"], result, "api")
            return {"vorschau": False, **summary, "ergebnis": result}

    # ------------------------------------------------------------- Ohne Ort
    def _analysis(self, max_hours: float | None = None):
        hours = max_hours or self.settings.location_max_hours
        lib = self.library()
        staged = frozenset(self.staging.asset_ids("ort"))
        key = (lib.uid, lib.rev, hours, self.settings.location_include_external,
               self.settings.location_skip_screenshots, staged)
        with self._calc_lock:
            cache = self._analysis_cache
            if not cache or cache[0] != key:
                cache = self._analysis_cache = (key, analyze(lib, hours, self.settings.location_include_external,
                                                             self.settings.location_skip_screenshots, staged))
        return hours, cache[1]

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

    def _select_locations(self, ids=None, max_hours=None, min_confidence=None, series=None, place=None,
                          ort=None, monat=None):
        """Auswahl auflösen: ids und/oder series (Serien-IDs); ort/monat wählt alle Serien eines
        Ortes bzw. Monats; place = {breite, laenge, name} setzt einen von Hand gewählten Ort;
        min_confidence ohne Auswahl = alle ab dieser Sicherheit. Vorgemerktes zählt nicht mit."""
        if min_confidence and min_confidence not in LEVELS:
            raise ActionError(f"Sicherheit muss {', '.join(LEVELS)} sein")
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
        return resolve_locations(self.library(), selected, hours, self.settings.location_include_external,
                                 skip_screenshots=self.settings.location_skip_screenshots,
                                 min_confidence=min_confidence if selected is None else None,
                                 manual=manual, exclude=self.staging.asset_ids("ort"))

    def apply_no_location(self, ids: list[str] | None = None, max_hours: float | None = None,
                          min_confidence: str | None = None, series: list[str] | None = None,
                          place: dict | None = None, ort: str | None = None,
                          monat: str | None = None) -> dict[str, Any]:
        """Orte direkt in Immich setzen (API/n8n). Die Oberfläche merkt erst vor."""
        with self._lock:
            changes, skipped = self._select_locations(ids, max_hours, min_confidence, series, place, ort, monat)
            res = execute_location_changes(self.library(), self.clients, changes)
            self._save()
            places = sorted({ch.place or "Koordinaten" for ch in changes})
            self._record("ort", "📍 " + (places[0] if len(places) == 1 else f"{len(places)} Orte"),
                         res["aktualisiert"], res, "api")
            return {"aktualisiert": res["aktualisiert"], "uebersprungen": skipped + res["uebersprungen"]}

    # -------------------------------------------------------------- Vormerken
    @property
    def staging(self) -> StagingStore:
        return self._staging

    def stage_no_location(self, label: str | None = None, **selection) -> dict[str, Any]:
        with self._lock:
            changes, skipped = self._select_locations(**selection)
            if not changes:
                raise ActionError("Nichts vorzumerken – " + (skipped[0]["grund"] if skipped else "keine Auswahl"))
            lib = self.library()
            places = sorted({ch.place or "Koordinaten" for ch in changes})
            title = label or (places[0] if len(places) == 1 else f"{len(places)} Orte")
            media = [{**lib.assets[ch.asset_id].summary(), "neuer_ort": ch.place, "sicherheit": ch.confidence}
                     for ch in changes if ch.asset_id in lib.assets]
            entry = self.staging.add("ort", f"📍 {title}", {"aenderungen": [ch.to_dict() for ch in changes]},
                                     media, len(changes))
            return {"vorgemerkt": len(changes), "uebersprungen": skipped, "eintrag": entry["id"]}

    def stage_duplicates(self, action: str, groups: list[dict] | None = None, all_groups: bool = False,
                         art: str | None = None, monat: str | None = None, cross_user: bool = False) -> dict:
        with self._lock:
            selection, _ = self.plan_duplicates(action, groups, all_groups, art, monat, cross_user)
            staged = 0
            for g, keep in selection:
                steps = [s for s in plan_group(g, keep, action) if s.action != "keine"]
                if not steps:
                    continue
                keeper = g.asset(keep)
                trash = sum(1 for s in steps if s.action == "papierkorb")
                title = (f"{keeper.file_name}: {len(steps)} {'Kopie' if len(steps) == 1 else 'Kopien'} → "
                         + ("Papierkorb" if trash == len(steps) else "Prüf-Album" if not trash else "Papierkorb/Prüf-Album"))
                media = [{**a.summary(), "bleibt": a.id == keep,
                          "aktion": next((s.action for s in steps if s.asset.id == a.id), "bleibt")} for a in g.assets]
                self.staging.add("duplikat", title, {
                    "aktion": action, "gruppe": g.id, "behalten": keep, "art": g.kind,
                    "alle_medien": sorted(g.asset_ids),
                    "schritte": [s.to_dict() for s in steps],
                }, media, len(steps), key=g.id)
                staged += 1
            if not staged:
                raise ActionError("Nichts vorzumerken")
            return {"vorgemerkt": staged}

    def stage_tags(self, names: list[str]) -> dict[str, Any]:
        if not names:
            raise ActionError("Keine Regeln ausgewählt")
        preview = {p["name"]: p for p in self.tags_preview(names)["regeln"]}
        for name in names:
            p = preview[name]
            if not p.get("aktiv"):
                raise ActionError(f"Regel „{name}“ ist ausgeschaltet")
            self.staging.add("tag", f"🏷 {name}: {', '.join(p['tags'])}", {"regel": name, "tags": p["tags"]},
                             p.get("beispiele", []), p.get("neu", 0), key=name)
        return {"vorgemerkt": len(names)}

    # ------------------------------------------------------ Tag-Vorschläge
    def hidden_suggestions(self) -> HiddenList:
        return HiddenList(self.settings.data_dir / "vorschlaege_ausgeblendet.json")

    def _suggestion_rules(self) -> list[tuple[dict[str, Any], Rule]]:
        defs = data_suggestions(self.library())
        rules = parse_rules(dump_rules([d["regel"] for d in defs]), list(self.clients)) if defs else []
        return list(zip(defs, rules))

    def suggestions_view(self, hidden: bool = False) -> dict[str, Any]:
        """Tag-Vorschläge aus den Daten (gezählt wie eine Regel) und die Begriffe für die KI-Suche."""
        lib = self.library()
        key = (lib.uid, lib.rev, len(self.history.entries))
        with self._calc_lock:
            if not getattr(self, "_sugg_cache", None) or self._sugg_cache[0] != key:
                pairs = self._suggestion_rules()
                previews = preview_rules([r for _, r in pairs], lib, Resolver(self.clients)) if pairs else []
                self._sugg_cache = (key, [{**d, "tag": r.tags[0], **{k: p[k] for k in
                                           ("treffer", "schon_getaggt", "neu", "beispiele", "benutzer")}}
                                          for (d, r), p in zip(pairs, previews)])
            items = self._sugg_cache[1]
        off = self.hidden_suggestions().ids
        staged = {e.get("key") for e in self.staging.of_type("tag")}
        shown = [s for s in items if (s["id"] in off) == hidden and s["id"] not in staged and (hidden or s["neu"])]
        return {"stand": lib.scanned_at, "vorschlaege": shown, "ausgeblendet": sum(1 for s in items if s["id"] in off),
                "begriffe": [{"name": n, "tag": t} for n, _, t in BEGRIFFE]}

    def smart_view(self, begriff: str | None = None, query: str | None = None, tag: str | None = None) -> dict[str, Any]:
        """KI-Suche: Treffer nach Passgenauigkeit, ohne schon getaggte und vorgemerkte."""
        known = {n: (q, t) for n, q, t in BEGRIFFE}
        if begriff:
            if begriff not in known:
                raise ActionError(f"Unbekannter Begriff {begriff!r}")
            query, default_tag = known[begriff]
            tag = tag or default_tag
        if not query or not query.strip():
            raise ActionError("Suchbegriff fehlt")
        tag = (tag or f"KI/{query.strip()}").strip("/ ")
        lib = self.library()
        resolver = Resolver(self.clients)
        exclude = {i for u in self.clients for i in resolver.tagged_assets(u, tag)}
        exclude |= {i for e in self.staging.of_type("tag") for ids in (e["daten"].get("medien") or {}).values() for i in ids}
        try:
            ids = smart_results(self.clients, lib, query.strip(), exclude)
        except ImmichError as exc:
            raise ActionError(f"KI-Suche nicht möglich (ist das maschinelle Lernen in Immich aktiv?): {exc}") from exc
        return {"begriff": begriff, "suche": query, "tag": tag, "medien": [lib.assets[i].summary() for i in ids]}

    def stage_suggestions(self, ids: list[str]) -> dict[str, Any]:
        view = {s["id"]: s for s in self.suggestions_view()["vorschlaege"]}
        missing = [i for i in ids if i not in view]
        if not ids or missing:
            raise ActionError("Vorschlag nicht (mehr) vorhanden – bitte neu laden")
        for i in ids:
            s = view[i]
            self.staging.add("tag", f"🏷 {s['titel']} → {s['tag']}", {"regel_def": s["regel"], "tags": [s["tag"]]},
                             s.get("beispiele", []), s["neu"], key=i)
        return {"vorgemerkt": len(ids)}

    def stage_smart(self, tag: str, ids: list[str], label: str | None = None) -> dict[str, Any]:
        tag = "/".join(p.strip() for p in (tag or "").split("/") if p.strip())
        if not tag:
            raise ActionError("Tag fehlt")
        lib = self.library()
        chosen = [i for i in ids if i in lib.assets]
        if not chosen:
            raise ActionError("Keine Medien ausgewählt")
        by_user: dict[str, list[str]] = {}
        for i in chosen:
            by_user.setdefault(lib.assets[i].owner, []).append(i)
        self.staging.add("tag", f"🏷 {label or tag}: {len(chosen)} Medien (KI-Suche) → {tag}",
                         {"medien": by_user, "tags": [tag]}, [lib.assets[i].summary() for i in chosen[:8]], len(chosen))
        return {"vorgemerkt": len(chosen)}

    def hide_suggestions(self, ids: list[str], undo: bool = False) -> dict[str, Any]:
        self.hidden_suggestions().update(ids, remove=undo)
        return {"vorschlaege": len(ids), "rueckgaengig": undo}

    def _apply_staged_tag(self, data: dict[str, Any]) -> dict[str, Any]:
        """Vorgemerkte Tags: eigene Regel (Name), Vorschlag (Regel-Definition) oder ausgewählte Medien."""
        if "regel" in data:
            return self.tags_apply([data["regel"]], record=False)
        resolver = Resolver(self.clients)
        lib = self.library()
        if "regel_def" in data:
            rules = parse_rules(dump_rules([data["regel_def"]]), list(self.clients))
            res = apply_rules(rules, lib, resolver)
            return {"regeln": res, "warnungen": resolver.warnings, "getaggt": sum(r.get("getaggt", 0) for r in res),
                    "rueck": [op for r in res for op in r.pop("rueck", [])]}
        ids = [i for ids in data["medien"].values() for i in ids]
        return tag_ids(data["tags"][0], ids, lib, resolver)

    def unstage(self, entry_ids: list[str]) -> dict[str, Any]:
        for e in self.staging.entries:
            if e["id"] in entry_ids and e["typ"] == "album" and e["daten"].get("ohne"):
                self.album_excluded().update(e["daten"]["ohne"], remove=True)  # Abwahl zurücknehmen
        return {"entfernt": self.staging.remove(entry_ids)}

    def staged_view(self) -> dict[str, Any]:
        return {**self.staging.summary(), "eintraege": self.staging.entries}

    def apply_staged(self, entry_ids: list[str] | None = None, confirm: str | None = None) -> dict[str, Any]:
        """Vorgemerktes an Immich übertragen. Erfolgreiche Einträge verschwinden aus der Liste."""
        with self._lock:
            lib = self.library()
            entries = [e for e in self.staging.entries if entry_ids is None or e["id"] in entry_ids]
            if not entries:
                raise ActionError("Nichts zu übertragen")
            trash = sum(1 for e in entries if e["typ"] in ("duplikat", "aufraeumen")
                        for s in e["daten"]["schritte"] if s["aktion"] == "papierkorb")
            if trash and confirm != CONFIRM_TRASH:
                raise ActionError(f'{trash} Medien gehen in den Papierkorb – nur mit confirm="{CONFIRM_TRASH}"')
            done, results = [], []
            for e in entries:
                try:
                    if e["typ"] in ("duplikat", "aufraeumen"):
                        steps, skipped = [], []
                        for st in e["daten"]["schritte"]:
                            a = lib.assets.get(st["id"])
                            if a is None:
                                skipped.append({"id": st["id"], "grund": "nicht mehr vorhanden"})
                            else:
                                steps.append(PlannedStep(a, st["aktion"], st["grund"]))
                        res = execute_steps(lib, self.clients, steps, self.settings.review_album)
                        res["uebersprungen"] = skipped
                    elif e["typ"] == "ort":
                        res = execute_location_changes(lib, self.clients, [
                            LocationChange.from_dict(ch) for ch in e["daten"]["aenderungen"]])
                    elif e["typ"] == "album":
                        res = execute_plan(lib, self.clients, e["daten"])
                    elif e["typ"] == "zeit":
                        res = execute_shifts(lib, self.clients, e["daten"]["aenderungen"])
                    elif e["typ"] == "stapel":
                        res = execute_stacks(lib, self.clients, e["daten"])
                    else:
                        res = self._apply_staged_tag(e["daten"])
                except (ImmichError, ActionError, RuleError, AlbumError) as exc:
                    self.staging.set_error(e["id"], str(exc))
                    results.append({"id": e["id"], "titel": e["titel"], "fehler": str(exc)})
                    continue
                done.append(e["id"])
                count = {"duplikat": lambda r: r["album"] + r["papierkorb"],
                         "aufraeumen": lambda r: r["album"] + r["papierkorb"], "ort": lambda r: r["aktualisiert"],
                         "album": lambda r: r["hinzugefuegt"], "tag": lambda r: r["getaggt"],
                         "zeit": lambda r: r["verschoben"], "stapel": lambda r: r["medien"]}[e["typ"]](res)
                self._record(e["typ"], e["titel"], count, res, "oberflaeche")
                results.append({"id": e["id"], "titel": e["titel"], "ergebnis": res})
            self.staging.remove(done)
            self._save()
            log.info("Vorgemerktes übertragen: %d von %d Einträgen", len(done), len(entries))
            return {"uebertragen": len(done), "fehler": len(entries) - len(done), "eintraege": results}

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

    # ------------------------------------------------------------- Aufräumen
    def _hash_key(self) -> int:
        """Stand der Fingerabdrücke – während der Berechnung eingefroren (stabile Listen)."""
        hashing = self._hash_thread is not None and self._hash_thread.is_alive()
        if hashing and self._cleanup_cache:
            return self._cleanup_cache[0][2]
        return len(self.hash_store.data)

    def cleanup_items(self):
        lib = self.library()
        key = (lib.uid, lib.rev, self._hash_key())
        with self._calc_lock:
            if not self._cleanup_cache or self._cleanup_cache[0] != key:
                self._cleanup_cache = (key, find_items(lib, self.hash_store))
            items = self._cleanup_cache[1]
        staged = (self.staging.asset_ids("aufraeumen") | self.staging.asset_ids("duplikat")
                  | self.staging.asset_ids("stapel"))
        return lib, [i for i in items if not (i.ids & staged if i.kategorie == "serien" else i.drop & staged)]

    def keep_list(self) -> KeepList:
        return KeepList(self.settings.data_dir / "aufraeumen_behalten.json")

    def cleanup_view(self, art: str | None = None, kategorie: str | None = None, ignored: bool = False,
                     offset: int = 0, limit: int = 30) -> dict[str, Any]:
        if art and art not in CLEANUP_ARTEN:
            raise ActionError(f"Art muss {', '.join(CLEANUP_ARTEN)} sein")
        if kategorie and kategorie not in CLEANUP_KATEGORIEN:
            raise ActionError(f"Kategorie muss {', '.join(CLEANUP_KATEGORIEN)} sein")
        lib, items = self.cleanup_items()
        keep = self.keep_list().ids
        base = [i for i in items if (i.id in keep) == ignored]
        cats = {k: {"art": a, "name": label, "anzahl": sum(1 for i in base if i.kategorie == k),
                    "groesse": sum(i.size for i in base if i.kategorie == k)}
                for k, (a, label) in CLEANUP_KATEGORIEN.items()}
        chosen = [i for i in base if (not art or CLEANUP_KATEGORIEN[i.kategorie][0] == art)
                  and (not kategorie or i.kategorie == kategorie)]
        page = chosen[offset: offset + limit] if limit > 0 else chosen[offset:]
        hs = self.hash_status()
        return {
            "stand": lib.scanned_at,
            "arten": {k: {"name": v, "anzahl": sum(c["anzahl"] for c in cats.values() if c["art"] == k),
                          "groesse": sum(c["groesse"] for c in cats.values() if c["art"] == k)}
                      for k, v in CLEANUP_ARTEN.items()},
            "kategorien": cats,
            "filter": {"art": art, "kategorie": kategorie, "ignoriert": ignored},
            "ausgeblendet": sum(1 for i in items if i.id in keep),
            "gesamt": len(chosen),
            "groesse": sum(i.size for i in chosen),
            "fingerabdruck": hs,
            "offset": offset,
            "eintraege": [i.to_dict() for i in page],
        }

    def _cleanup_selection(self, ids: list[str] | None, kategorie: str | None):
        _, items = self.cleanup_items()
        keep = self.keep_list().ids
        known = {i.id: i for i in items if i.id not in keep}
        if ids:
            missing = [i for i in ids if i not in known]
            if missing:
                raise ActionError(f"Eintrag/Einträge {', '.join(missing)} nicht gefunden – bitte neu laden")
            return [known[i] for i in ids]
        if kategorie:
            return [i for i in known.values() if i.kategorie == kategorie]
        raise ActionError("Keine Einträge ausgewählt (ids oder kategorie)")

    def stage_cleanup(self, action: str, ids: list[str] | None = None, kategorie: str | None = None,
                      keep: dict[str, str] | None = None) -> dict[str, Any]:
        """``keep``: {Eintrag: Medium} – anderes Bild behalten (z. B. bei Serienbildern)."""
        if action not in ("album", "papierkorb"):
            raise ActionError("Aktion muss album oder papierkorb sein")
        with self._lock:
            chosen = self._cleanup_selection(ids, kategorie)
            for n, item in enumerate(chosen):
                if keep and item.id in keep:
                    if keep[item.id] not in item.ids:
                        raise ActionError(f"Medium {keep[item.id]!r} gehört nicht zu Eintrag {item.id}")
                    chosen[n] = replace(item, drop=item.ids - {keep[item.id]})
            if not chosen:
                raise ActionError("Nichts vorzumerken")
            steps = [s for i in chosen for s in i.steps(action)]
            labels = sorted({CLEANUP_KATEGORIEN[i.kategorie][1] for i in chosen})
            size = sum(i.size for i in chosen)
            target = "Papierkorb" if action == "papierkorb" else "Prüf-Album"
            title = f"🧹 {', '.join(labels)}: {len(steps)} Medien ({size / 1048576:.0f} MB) → {target}"
            media = [{**s.asset.summary(), "aktion": s.action} for s in steps]
            self.staging.add("aufraeumen", title, {
                "aktion": action, "eintraege": [i.id for i in chosen],
                "alle_medien": sorted({a for i in chosen for a in i.ids}),
                "schritte": [s.to_dict() for s in steps],
            }, media, len(steps))
            return {"vorgemerkt": len(chosen), "medien": len(steps), "groesse": size}

    def keep_cleanup(self, ids: list[str], undo: bool = False) -> dict[str, Any]:
        if not ids:
            raise ActionError("Keine Einträge angegeben")
        self.keep_list().update(ids, remove=undo)
        return {"eintraege": len(ids), "rueckgaengig": undo}

    # ------------------------------------------------------------- Stapeln
    def stack_albums(self) -> list[dict[str, Any]]:
        lib = self.library()
        out = []
        for al in lib.albums.values():
            members = [lib.assets[i] for i in al["medien"] if i in lib.assets]
            if len(members) >= 2:
                out.append({"id": al["id"], "name": al["name"], "besitzer": al["besitzer"] or "anderer Benutzer",
                            "anzahl": len(members), "gestapelt": sum(1 for a in members if a.stack_id)})
        return sorted(out, key=lambda a: a["name"].lower())

    def stack_view(self, album_id: str | None = None, whole: bool = False) -> dict[str, Any]:
        if self.albums_pending(wait_s=3):
            return {"laedt": True}
        albums = self.stack_albums()
        out: dict[str, Any] = {"alben": albums, "album": None, "vorschlaege": [], "zahlen": None}
        if not album_id:
            return out
        lib = self.library()
        if album_id not in lib.albums:
            raise ActionError("Album nicht gefunden – bitte neu einlesen")
        proposals, stats = propose_stacks(lib, album_id, self.hash_store)
        if whole:
            proposals = whole_album(lib, album_id, self.hash_store)
        staged = self.staging.asset_ids("stapel")
        proposals = [p for p in proposals if not ({a.id for a in p.assets} & staged)]
        out.update(album={"id": album_id, "name": lib.albums[album_id]["name"]},
                   vorschlaege=[p.to_dict() for p in proposals], zahlen=stats, ganz=whole)
        return out

    def stage_stacks(self, album_id: str, ids: list[str] | None = None, whole: bool = False,
                     top: dict[str, str] | None = None, remove_from_album: bool = False) -> dict[str, Any]:
        """Vorschläge (ids, ohne = alle) eines Albums als Stapel vormerken; ``top``: {Vorschlag: Medium oben}."""
        from .stacking import order

        with self._lock:
            lib = self.library()
            if album_id not in lib.albums:
                raise ActionError("Album nicht gefunden – bitte neu einlesen")
            proposals = whole_album(lib, album_id, self.hash_store) if whole else \
                propose_stacks(lib, album_id, self.hash_store)[0]
            known = {p.id: p for p in proposals}
            missing = [i for i in ids or [] if i not in known]
            if missing:
                raise ActionError(f"Vorschlag/Vorschläge {', '.join(missing)} nicht gefunden – bitte neu laden")
            chosen = [known[i] for i in ids] if ids else proposals
            if not chosen:
                raise ActionError("Nichts zu stapeln")
            stacks = []
            for p in chosen:
                assets = order(p.assets, self.hash_store, (top or {}).get(p.id))
                stacks.append({"user": p.owner, "ids": [a.id for a in assets]})
            name = lib.albums[album_id]["name"]
            n = sum(len(s["ids"]) for s in stacks)
            title = f"📚 „{name}“: {len(stacks)} Stapel aus {n} Medien" + \
                (" – danach aus dem Album" if remove_from_album else "")
            media = [{**lib.assets[s["ids"][0]].summary(), "oben": True} for s in stacks[:8]]
            self.staging.add("stapel", title, {"stapel": stacks, "album": album_id, "aus_album": remove_from_album,
                                               "alle_medien": [i for s in stacks for i in s["ids"]]},
                             media, n, key=f"{album_id}:{'ganz' if whole else ','.join(sorted(p.id for p in chosen))}")
            return {"vorgemerkt": len(stacks), "medien": n}

    def stage_burst_stacks(self, ids: list[str], keep: dict[str, str] | None = None) -> dict[str, Any]:
        """Serienbilder aus „Aufräumen“ stapeln statt wegräumen."""
        with self._lock:
            chosen = self._cleanup_selection(ids, None)
            stacks = []
            for item in chosen:
                if item.kategorie != "serien":
                    raise ActionError("Stapeln geht nur für Serienbilder")
                top = (keep or {}).get(item.id) or next(a.id for a in item.assets if a.id not in item.drop)
                ordered = [a for a in item.assets if a.id == top] + [a for a in item.assets if a.id != top]
                stacks.append({"user": ordered[0].owner, "ids": [a.id for a in ordered]})
            n = sum(len(s["ids"]) for s in stacks)
            self.staging.add("stapel", f"📚 Serienbilder: {len(stacks)} Stapel aus {n} Medien",
                             {"stapel": stacks, "album": None, "aus_album": False,
                              "alle_medien": [i for s in stacks for i in s["ids"]]},
                             [{**self.library().assets[s["ids"][0]].summary(), "oben": True} for s in stacks[:8]], n)
            return {"vorgemerkt": len(stacks), "medien": n}

    # -------------------------------------------------------- Aufnahmezeit
    def time_fixes(self):
        lib = self.library()
        key = (lib.uid, lib.rev)
        with self._calc_lock:
            if not self._time_cache or self._time_cache[0] != key:
                self._time_cache = (key, find_fixes(lib))
            fixes = self._time_cache[1]
        staged = self.staging.asset_ids("zeit")
        keep = self.keep_list().ids
        return lib, [f for f in fixes if not ({a.id for a in f.assets} & staged)], keep

    def timefix_view(self, art: str | None = None, ignored: bool = False, offset: int = 0, limit: int = 30) -> dict[str, Any]:
        if art and art not in TIME_ARTEN:
            raise ActionError(f"Art muss {', '.join(TIME_ARTEN)} sein")
        lib, fixes, keep = self.time_fixes()
        base = [f for f in fixes if (f.id in keep) == ignored]
        chosen = [f for f in base if not art or f.art == art]
        page = chosen[offset: offset + limit] if limit > 0 else chosen[offset:]
        return {"stand": lib.scanned_at, "arten": time_summary(base), "namen": TIME_ARTEN,
                "ausgeblendet": sum(1 for f in fixes if f.id in keep), "gesamt": len(chosen),
                "filter": {"art": art, "ignoriert": ignored}, "offset": offset,
                "eintraege": [f.to_dict() for f in page]}

    def stage_timefix(self, selection: list[dict]) -> dict[str, Any]:
        """selection: [{id, minuten?}] – ohne minuten gilt der Vorschlag; ``ziel`` (ISO-Zeit) für Einzelmedien."""
        from datetime import datetime

        if not selection:
            raise ActionError("Nichts ausgewählt")
        with self._lock:
            _, fixes, _ = self.time_fixes()
            known = {f.id: f for f in fixes}
            staged = 0
            for sel in selection:
                fix = known.get(sel.get("id", ""))
                if fix is None:
                    raise ActionError(f"Eintrag {sel.get('id')!r} nicht gefunden – bitte neu laden")
                minutes = sel.get("minuten")
                if sel.get("ziel"):
                    if len(fix.assets) != 1:
                        raise ActionError("Eine Zielzeit geht nur für ein einzelnes Medium")
                    try:
                        target = datetime.fromisoformat(sel["ziel"])
                    except ValueError as exc:
                        raise ActionError("Zielzeit bitte als JJJJ-MM-TTTHH:MM") from exc
                    minutes = round((target - fix.assets[0].local_dt).total_seconds() / 60)
                if minutes is None:
                    minutes = fix.minutes
                if not minutes:
                    raise ActionError(f"Für „{fix.grund}“ bitte eine Zeit wählen")
                changes = plan_shifts(fix, int(minutes))
                title = (f"🕑 {fix.extra.get('kamera') or fix.assets[0].file_name}: "
                         f"{n_media(len(fix.assets))} um {fmt_offset(int(minutes))}")
                sample = fix.assets[:: max(1, len(fix.assets) // 6)][:6]
                media = [{**a.summary(), "neue_zeit": shifted(a, int(minutes))} for a in sample]
                self.staging.add("zeit", title, {"aenderungen": changes, "alle_medien": [a.id for a in fix.assets]},
                                 media, len(fix.assets), key=fix.id)
                staged += 1
            return {"vorgemerkt": staged}

    # ---------------------------------------------------------------- Alben
    def album_ignore_list(self) -> TripIgnoreList:
        return TripIgnoreList(self.settings.data_dir / "alben_ignoriert.json")

    def album_excluded(self) -> ExcludedMedia:
        return ExcludedMedia(self.settings.data_dir / "alben_ohne.json")

    def trip_media(self, trip_id: str, album_id: str | None = None) -> dict[str, Any]:
        """Alle Medien einer Reise; ``im_album`` bezogen auf das Ziel-Album (Vorschlag oder ``album_id``)."""
        if self.albums_pending(wait_s=3):
            raise ActionError("Die Alben werden gerade noch gelesen – bitte gleich noch einmal")
        lib, _, trips = self._trips()
        trip = next((t for t, _ in trips if t.id == trip_id), None)
        if trip is None:
            raise ActionError("Reise nicht gefunden – bitte neu laden")
        if album_id is None and trip.target:
            album_id = trip.target.album["id"]
        inside = set(lib.albums[album_id]["medien"]) if album_id in lib.albums else set()
        return {"id": trip.id, "album": album_id, "anzahl": len(trip.assets),
                "medien": [{**a.summary(), "im_album": a.id in inside} for a in trip.assets]}

    def _trips(self):
        """Reisen ohne vorgemerkte; ``ignored`` = als „kein Album“ markiert."""
        lib = self.library()
        # Berechnung nur neu, wenn sich Bibliothek, Alben oder Einstellungen geändert haben
        manual = [Home(h["breite"], h["laenge"], h["name"], 0, manual=True) for h in self.settings.album_home]
        without = frozenset(self.album_excluded().ids)
        key = (lib.uid, lib.rev, self.settings.album_min_km, self.settings.album_min_media,
               tuple((h.latitude, h.longitude) for h in manual), without)
        with self._calc_lock:
            if not self._trips_cache or self._trips_cache[0] != key:
                self._trips_cache = (key, suggest(lib, self.settings.album_min_km, self.settings.album_min_media,
                                                  exclude=set(without), homes=manual or None))
            homes, trips = self._trips_cache[1]
        staged = self.staging.id_sets("album")
        ignore = self.album_ignore_list()
        out = [(t, ignore.contains(t.ids)) for t in trips if not overlaps(t.ids, staged)]
        return lib, homes, out

    def albums_view(self, status: str | None = None, ignored: bool = False, jahr: str | None = None,
                    offset: int = 0, limit: int = 20) -> dict[str, Any]:
        """Reisen mit Albumvorschlag. Ohne ``status`` die offenen (neu + ergänzen)."""
        if status and status not in ALBUM_STATUS:
            raise ActionError(f"Status muss {', '.join(ALBUM_STATUS)} sein")
        if self.albums_pending(wait_s=3):
            return {"laedt": True, "stand": self.library().scanned_at}
        lib, homes, trips = self._trips()
        base = [t for t, ign in trips if ign == ignored]
        counts = {k: sum(1 for t in base if t.status == k) for k in ALBUM_STATUS}
        chosen = [t for t in base if (t.status == status if status else t.status != "vorhanden")]
        years: dict[str, int] = {}
        for t in chosen:
            years[str(t.start.year)] = years.get(str(t.start.year), 0) + 1
        if jahr:
            chosen = [t for t in chosen if str(t.start.year) == jahr]
        page = chosen[offset: offset + limit] if limit > 0 else chosen[offset:]
        return {
            "stand": lib.scanned_at,
            "zuhause": [h.to_dict() for h in homes],
            "min_km": self.settings.album_min_km,
            "min_medien": self.settings.album_min_media,
            "alben": len(lib.albums),
            "status": counts,
            "offen": counts["neu"] + counts["ergaenzen"],
            "ignoriert": sum(1 for _, ign in trips if ign),
            "jahre": [{"key": k, "anzahl": v} for k, v in sorted(years.items(), reverse=True)],
            "filter": {"status": status, "jahr": jahr, "ignoriert": ignored},
            "gesamt": len(chosen),
            "offset": offset,
            "reisen": [t.to_dict(lib) for t in page],
        }

    def _album_plans(self, selection: list[dict]) -> list[dict[str, Any]]:
        """selection: [{id, album?: Album-ID oder null = neu, name?}]; ohne album = Vorschlag."""
        if not selection:
            raise ActionError("Keine Reisen ausgewählt")
        if self.albums_pending(wait_s=3):
            raise ActionError("Die Alben werden gerade noch gelesen – bitte gleich noch einmal")
        lib, _, trips = self._trips()
        known = {t.id: t for t, _ in trips}
        plans = []
        for sel in selection:
            trip = known.get(sel.get("id", ""))
            if trip is None:
                raise ActionError(f"Reise {sel.get('id')!r} nicht gefunden – bitte neu laden")
            if "album" in sel:
                album_id = sel["album"]
            else:
                album_id = trip.target.album["id"] if trip.status == "ergaenzen" and trip.target else None
            try:
                plan = plan_trip(trip, lib, album_id, sel.get("name"), set(sel.get("ohne") or []))
            except AlbumError as exc:
                raise ActionError(str(exc)) from exc
            if not plan["anzahl"] and not plan["teilen"]:
                raise ActionError(f"„{plan['name']}“: nichts zu tun – alle Medien liegen schon im Album")
            plan["beispiele"] = [a.summary() for a in trip.assets[:: max(1, len(trip.assets) // 8)][:8]]
            plans.append(plan)
        return plans

    def stage_albums(self, selection: list[dict]) -> dict[str, Any]:
        with self._lock:
            plans = self._album_plans(selection)
            for plan in plans:
                if plan["ohne"]:  # abgewählte gehören nicht zur Reise – auch nach dem Übertragen nicht
                    self.album_excluded().update(plan["ohne"])
                media = plan.pop("beispiele")
                self.staging.add("album", plan_title(plan), plan, media, plan["anzahl"], key=plan["reise"])
            return {"vorgemerkt": len(plans), "hinweise": [h for p in plans for h in p["hinweise"]]}

    def apply_albums(self, selection: list[dict]) -> dict[str, Any]:
        """Direkt in Immich anlegen bzw. ergänzen (API/CLI). Die Oberfläche merkt erst vor."""
        with self._lock:
            plans = self._album_plans(selection)
            results = []
            for plan in plans:
                plan.pop("beispiele")
                if plan["ohne"]:
                    self.album_excluded().update(plan["ohne"])
                try:
                    res = execute_plan(self.library(), self.clients, plan)
                    self._record("album", plan_title(plan), res["hinzugefuegt"], res, "api")
                    results.append({"name": plan["name"], **res, "hinweise": plan["hinweise"]})
                except AlbumError as exc:
                    results.append({"name": plan["name"], "fehler": str(exc)})
            self._save()
            return {"alben": results}

    def ignore_albums(self, trip_ids: list[str], undo: bool = False) -> dict[str, Any]:
        if not trip_ids:
            raise ActionError("Keine Reisen angegeben")
        _, _, trips = self._trips()
        known = {t.id: t for t, _ in trips}
        missing = [i for i in trip_ids if i not in known]
        if missing:
            raise ActionError(f"Reise(n) {', '.join(missing)} nicht gefunden – bitte neu laden")
        ignore = self.album_ignore_list()
        for tid in trip_ids:
            (ignore.remove if undo else ignore.add)(known[tid].ids)
        return {"reisen": len(trip_ids), "rueckgaengig": undo}

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
        staged = {e["daten"].get("regel") for e in self.staging.of_type("tag")}
        regeln = [{**r, "vorgemerkt": r["name"] in staged} for r in preview_rules(rules, lib, resolver)]
        return {"stand": lib.scanned_at, "regeldatei": str(self.settings.rules_file),
                "regeln": regeln, "warnungen": resolver.warnings}

    def tags_apply(self, names: list[str] | None = None, record: bool = True) -> dict[str, Any]:
        with self._lock:
            rules = self._select_rules(names)
            resolver = Resolver(self.clients)
            res = apply_rules(rules, self.library(), resolver)
            out = {"regeln": res, "warnungen": resolver.warnings,
                   "getaggt": sum(r.get("getaggt", 0) for r in res),
                   "rueck": [op for r in res for op in r.pop("rueck", [])]}
            if record:  # sonst trägt der Aufrufer (Vormerkliste) in den Verlauf ein
                self._record("tag", "🏷 " + ", ".join(r["name"] for r in res), out["getaggt"], out, "api")
            return out

    # ------------------------------------------------------------ Übersicht
    def dashboard(self) -> dict[str, Any]:
        """Kennzahlen für die Übersicht und den Wochenbericht (nur aus dem Zwischenspeicher)."""
        lib = self.library()
        users: dict[str, dict[str, int]] = {}
        years: dict[str, dict[str, int]] = {}
        for a in lib.assets.values():
            u = users.setdefault(a.owner, {"medien": 0, "fotos": 0, "videos": 0, "extern": 0, "groesse": 0,
                                           "ohne_gps": 0})
            u["medien"] += 1
            u["videos" if a.type == "VIDEO" else "fotos"] += 1
            u["extern"] += a.is_external
            u["groesse"] += a.file_size or 0
            u["ohne_gps"] += not a.has_gps
            if a.local_dt:
                y = years.setdefault(str(a.local_dt.year), {"medien": 0, "groesse": 0})
                y["medien"] += 1
                y["groesse"] += a.file_size or 0
        dup = self.duplicates_view(limit=1)
        loc = self.no_location_view(overview=True)
        cln = self.cleanup_view(limit=1)
        tf = self.timefix_view(limit=1)
        alb = self.albums_view(limit=1) if not self.albums_pending() else None
        months = self.history.per_month()
        return {
            "stand": lib.scanned_at,
            "benutzer": users,
            "gesamt": {k: sum(u[k] for u in users.values()) for k in ("medien", "fotos", "videos", "groesse", "ohne_gps")},
            "jahre": [{"jahr": k, **v} for k, v in sorted(years.items())],
            "offen": {
                "duplikate": dup["offen"],
                "ohne_ort": loc["medien"],
                "ort_vorschlaege": loc["mit_vorschlag"],
                "ort_sicher": loc["nach_sicherheit"]["hoch"],
                "alben": alb["offen"] if alb else None,
                "aufraeumen": sum(v["anzahl"] for v in cln["arten"].values()),
                "aufraeumen_groesse": sum(v["groesse"] for v in cln["arten"].values()),
                "zeit": sum(tf["arten"].values()),
                "vorgemerkt": self.staging.summary()["anzahl"],
            },
            "erledigt": [{"monat": m, **v} for m, v in sorted(months.items())[-12:]],
        }

    # ------------------------------------------------------------ Papierkorb
    def trash_view(self) -> dict[str, Any]:
        if not self.clients:
            raise NotConfigured()
        first = next(iter(self.clients.values()))
        days = first.server_config().get("trashDays")
        moved = {}  # vom Tool verschoben: Medium -> Zeitpunkt (aus dem Verlauf)
        for e in self.history.entries:
            for op in e["rueck"]:
                if op["op"] == "wiederherstellen" and not e["rueckgaengig"]:
                    for i in op["ids"]:
                        moved[i] = e["zeit"]
        users, items = {}, []
        for name, client in self.clients.items():
            own = [Asset.from_api(raw, name) for raw in client.trashed()]
            users[name] = {"anzahl": len(own), "groesse": sum(a.file_size or 0 for a in own)}
            items += own
        items.sort(key=lambda a: moved.get(a.id, ""), reverse=True)
        out = []
        for a in items[:200]:
            d = a.summary()
            if a.id in moved:
                d["verschoben"] = moved[a.id]
                if days:
                    d["endgueltig"] = (datetime.fromisoformat(moved[a.id]) + timedelta(days=days)).isoformat(timespec="minutes")
            out.append(d)
        return {"tage": days, "benutzer": users, "anzahl": len(items),
                "groesse": sum(u["groesse"] for u in users.values()), "medien": out}

    def trash_restore(self, ids: list[str] | None = None) -> dict[str, Any]:
        """Aus dem Papierkorb holen (ohne ids: alle). Danach neu einlesen, damit sie wieder auftauchen."""
        restored = 0
        for name, client in self.clients.items():
            own = [raw["id"] for raw in client.trashed()]
            chosen = [i for i in own if ids is None or i in ids]
            if chosen:
                restored += client.restore_trash(chosen)
        if restored:
            self.history.add("papierkorb", f"♻️ {restored} Medien aus dem Papierkorb geholt", restored, [], "oberflaeche")
        return {"wiederhergestellt": restored}

    # ------------------------------------------------------------ Verlauf
    def _record(self, typ: str, title: str, count: int, res: dict[str, Any], source: str) -> None:
        """Übertragung in den Verlauf schreiben; die Rückgängig-Schritte bleiben dort, nicht in der Antwort."""
        undo = res.pop("rueck", []) or []
        if count or undo:
            self.history.add(typ, title, count, undo, source)

    def history_view(self, limit: int = 50) -> dict[str, Any]:
        return {"eintraege": self.history.recent(limit)}

    def undo(self, entry_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self.history.get(entry_id)
            if entry is None:
                raise ActionError("Eintrag nicht im Verlauf")
            if entry["rueckgaengig"]:
                raise ActionError("Schon rückgängig gemacht")
            if not entry["rueck"]:
                raise ActionError(entry.get("nicht_rueckgaengig") or "Lässt sich nicht rückgängig machen")
            errors = undo_ops(self.cached_library(), self.clients, entry["rueck"])
            self.history.mark_undone(entry_id, errors)
            self._save()
            log.info("Rückgängig: %s%s", entry["titel"], f" ({len(errors)} Fehler)" if errors else "")
            return {"rueckgaengig": True, "titel": entry["titel"], "fehler": errors}

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
