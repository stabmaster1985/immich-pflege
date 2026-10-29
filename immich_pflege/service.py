"""Gemeinsame Anwendungslogik für Web-Oberfläche, JSON-API und CLI."""

from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
import time
from typing import Any

import httpx

from . import __version__
from .folders import SyncedFolders, folder_missing, pending_sync, plan_folder, proposals as folder_proposals
from .albumcare import ARTEN as CARE_ARTEN, execute_care, find_issues, plan_delete, plan_merge
from .covers import find_covers, plan_cover
from .albums import (STATUS as ALBUM_STATUS, AlbumError, ExcludedMedia, Home, TripIgnoreList, execute_plan, overlaps,
                     plan_title, same_name_album, plan_trip, suggest, twin_map)
from .client import ImmichClient, ImmichError
from .config import Settings
from .duplicates import (AKTIONEN, ARTEN, OPTIONAL_KINDS, DuplicateGroup, IgnoreList, PlannedStep,
                         clear_immich_duplicates, execute_steps, find_groups, plan_group)
from .cleanup import ARTEN as CLEANUP_ARTEN, KATEGORIEN as CLEANUP_KATEGORIEN, KeepList, find_items
from .history import HistoryStore, undo_ops
from .textscan import TextProgress, TextStore, fetch_missing
from .timefix import (ARTEN as TIME_ARTEN, execute_shifts, find_fixes, fmt_offset, plan_shifts, shifted,
                      summary as time_summary)
from .imagehash import HashProgress, HashStore, compute_missing, similar_pairs
from .library import Library, apply_album_membership, read_albums, scan_library
from .models import Asset
from .location import (HERKUNFT, LEVELS, LocationChange, NoPlaceList, analyze, execute_location_changes, is_screenshot,
                       level_at_least, month_facets, month_key, month_label, place_facets, place_key, resolve_locations)
from .rules import (Resolver, Rule, RuleError, apply as apply_rules, dump_rules, evaluate_rule, load_rules, parse_rules,
                    preview as preview_rules, tag_ids)
from .suggestions import BEGRIFFE, SMART_SIZE, HiddenList, SmartHidden, data_suggestions, smart_results
from .stacking import execute_stacks, propose as propose_stacks, whole_album
from .staging import StagingStore

log = logging.getLogger(__name__)

CONFIRM_TRASH = "PAPIERKORB"
FULL_SCAN_EVERY = timedelta(days=7)  # sonst nur Änderungen einlesen


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
        self._scan_lock = threading.RLock()
        self.scanning = False
        self.progress = ""  # was beim Einlesen gerade passiert (für die Oberfläche)
        self.last_error: str | None = None
        self.hash_store = HashStore(settings.data_dir / "bildhash.json")
        self.text_store = TextStore(settings.data_dir / "texterkennung.json")
        self.text_progress = TextProgress()
        self._text_thread: threading.Thread | None = None
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
        if self._lib is not None:  # ohne Sperre: während des Einlesens gilt der bisherige Stand
            return self._lib
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
        if not refresh and self._lib is not None:  # nicht auf ein laufendes Einlesen warten
            return self._lib
        if refresh:
            return self.scan()
        with self._scan_lock:  # erstes Laden: nicht zweimal parallel einlesen
            return self.cached_library() or self.scan()

    def scan(self, full: bool = False) -> Library:
        """Einlesen – normalerweise nur die Änderungen seit dem letzten Mal; vollständig, wenn
        ``full``, beim ersten Mal oder wenn das letzte vollständige Einlesen eine Woche her ist."""
        if not self.clients:
            raise NotConfigured()
        # Eigene Sperre fürs Einlesen (nie zwei gleichzeitig); die Daten-Sperre nur kurz beim Austausch –
        # so warten Listen, Vormerken und Übertragen nicht minutenlang auf ein komplettes Einlesen.
        with self._scan_lock:
            self.scanning = True
            self.progress = "Einlesen startet"
            try:
                previous = self.cached_library()
                if previous and not full:
                    last_full = datetime.fromisoformat(previous.full_scan_at or previous.scanned_at)
                    full = datetime.now(last_full.tzinfo) - last_full > FULL_SCAN_EVERY
                lib = scan_library(self.clients, self.settings.review_album, previous,
                                   read_album_contents=not self.background_albums, incremental=not full,
                                   progress=self._set_progress)
            except ImmichError as exc:
                self.last_error = str(exc)
                raise
            finally:
                self.scanning = False
                self.progress = ""
            self.last_error = None
            lib.immich_url = self.settings.immich_url
            with self._lock:
                self._lib = lib
                lib.save(self.settings.cache_file)
        if not lib.albums_ready:
            self._albums_thread = threading.Thread(target=self._read_albums, args=(lib,), name="alben-lesen", daemon=True)
            self._albums_thread.start()
        else:
            self.sync_folders()
        if self.settings.dup_image_hash:
            self.start_hashing()
        self.start_text_scan()
        self.warm_up_background()
        return lib

    def _set_progress(self, text: str) -> None:
        self.progress = text

    def _read_albums(self, lib: Library) -> None:
        try:
            skip = {a for a in lib.review_albums.values() if a}
            # vollständiges Einlesen: auch Albuminhalte frisch, nicht aus dem Zwischenspeicher
            albums = read_albums(self.clients, lib.users, skip, lib.albums if lib.incremental else None,
                                 progress=self._set_progress)
        except ImmichError as exc:
            log.error("Alben konnten nicht gelesen werden: %s", exc)
            albums = None
        with self._lock:
            if albums is not None:
                lib.albums = albums
                apply_album_membership(lib, recompute=lib.incremental)
            lib.albums_ready = True
            if self._lib is lib:
                self._save()
        if not self.scanning:
            self.progress = ""
        if self._lib is lib:
            self.sync_folders()

    # ------------------------------------------------------- Ordner-Alben
    def synced_folders(self) -> SyncedFolders:
        return SyncedFolders(self.settings.data_dir / "ordner_alben.json")

    def sync_folders(self) -> int:
        """Abgeglichene Ordner: neue Dateien automatisch ins Album (nur hinzufügen, im Verlauf rückgängig)."""
        lib = self._lib
        synced = self.synced_folders()
        if lib is None or not lib.albums_ready or not synced.data:
            return 0
        twins = self.twins()  # vor der Sperre: kann dauern, Anfragen sollen nicht warten
        with self._lock:
            added = 0
            for plan in pending_sync(lib, synced, twins):
                try:
                    res = execute_plan(lib, self.clients, plan)
                except (ImmichError, AlbumError) as exc:
                    log.warning("Ordner-Abgleich „%s“ fehlgeschlagen: %s", plan["ordner"], exc)
                    continue
                self._record("album", f"📁 Ordner-Abgleich „{plan['name']}“: {res['hinzugefuegt']} neue Dateien",
                             res["hinzugefuegt"], res, "automatisch")
                added += res["hinzugefuegt"]
            if added:
                self._save()
                log.info("Ordner-Abgleich: %d neue Dateien in Alben", added)
            return added

    def folders_view(self, status: str | None = None, ignored: bool = False) -> dict[str, Any]:
        if self.albums_pending(wait_s=3):
            return {"laedt": True}
        lib = self.library()
        synced = self.synced_folders().data
        items = folder_proposals(lib, synced, self.twins())
        staged = {e["daten"].get("ordner_key") for e in self.staging.of_type("album")}
        keep = self.keep_list().ids
        items = [p for p in items if p["id"] not in staged]
        base = [p for p in items if (p["id"] in keep) == ignored]
        counts = {k: sum(1 for p in base if p["status"] == k) for k in ("neu", "ergaenzen", "abgeglichen", "vorhanden")}
        shown = [p for p in base if (p["status"] == status if status else p["status"] in ("neu", "ergaenzen"))]
        return {"ordner": shown, "status": counts, "ausgeblendet": sum(1 for p in items if p["id"] in keep)}

    def folder_media(self, folder_id: str, album_id: str | None = None) -> dict[str, Any]:
        """Medien eines Ordners, die noch nicht im Ziel-Album liegen – für die Prüf-Ansicht."""
        lib = self.library()
        p = next((x for x in folder_proposals(lib, self.synced_folders().data, self.twins()) if x["id"] == folder_id), None)
        if p is None:
            raise ActionError("Ordner nicht gefunden – bitte neu laden")
        return {"id": folder_id, "ordner": p["ordner"],
                "medien": self._review_media(folder_missing(lib, p["benutzer"], p["ordner"], album_id, self.twins()))}

    def stage_folders(self, selection: list[dict]) -> dict[str, Any]:
        """selection: [{id, name?, album? (null = neu), sync, ohne?}]."""
        with self._lock:
            lib = self.library()
            twins = self.twins()
            known = {p["id"]: p for p in folder_proposals(lib, self.synced_folders().data, twins)}
            staged = 0
            for sel in selection:
                p = known.get(sel.get("id", ""))
                if p is None:
                    raise ActionError("Ordner nicht gefunden – bitte neu laden")
                album_id = sel["album"] if "album" in sel else (p["album"]["id"] if p["album"] else None)
                if album_id and album_id not in lib.albums:
                    raise ActionError("Album nicht gefunden – bitte neu einlesen")
                plan = plan_folder(lib, p["benutzer"], p["ordner"], sel.get("name"), album_id, bool(sel.get("sync")),
                                   set(sel.get("ohne") or []), twins)
                if not plan["anzahl"] and not plan["sync"]:
                    raise ActionError(f"„{plan['name']}“: alles schon im Album")
                self._same_name_hint(plan)
                title = (f"📁 Ordner {p['ordner']} → " + (f"„{plan['name']}“ ergänzen" if album_id else f"neues Album „{plan['name']}“")
                         + f" ({plan['anzahl']} Medien" + (f", {len(plan['ordner_ohne'])} abgewählt" if plan["ordner_ohne"] else "") + ")"
                         + (", danach automatisch aktuell halten" if plan["sync"] else ""))
                self.staging.add("album", title, plan, p["beispiele"], plan["anzahl"], key=p["id"])
                staged += 1
            return {"vorgemerkt": staged}

    def _after_album_plan(self, plan: dict[str, Any], res: dict[str, Any]) -> None:
        if plan.get("ordner") and plan.get("sync"):
            self.synced_folders().set(plan["ordner_key"], plan["besitzer"], plan["ordner"], res["album_id"],
                                      plan.get("ordner_ohne"))

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
            "fortschritt": self.progress,
            "alben_laeuft": bool(lib and not lib.albums_ready),
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

    def start_text_scan(self) -> bool:
        """Texterkennung für Bilder ohne Ort im Hintergrund holen (falls nicht schon läuft)."""
        if self._text_thread and self._text_thread.is_alive():
            return False
        lib = self.cached_library()
        if lib is None or not self.background_albums:
            return False  # nur in der Weboberfläche im Hintergrund; Kommandozeile und Tests: fetch_texts()
        self.text_progress = TextProgress()
        no_gps = [a for a in lib.assets.values() if not a.has_gps]
        self._text_thread = threading.Thread(target=fetch_missing, args=(no_gps, self.clients, self.text_store, self.text_progress),
                                             name="texterkennung", daemon=True)
        self._text_thread.start()
        return True

    def fetch_texts(self) -> dict[str, Any]:
        """Synchron holen (CLI und Tests)."""
        self.text_progress = TextProgress()
        fetch_missing([a for a in self.library().assets.values() if not a.has_gps], self.clients, self.text_store,
                      self.text_progress)
        return self.text_progress.to_dict()

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

    def done_recently(self, types: tuple[str, ...]) -> dict[str, int]:
        """Übertragene Medien laut Verlauf: heute und in den letzten 7 Tagen."""
        now = datetime.now().astimezone()
        today, week = now.date(), now - timedelta(days=7)
        out = {"heute": 0, "woche": 0}
        for e in self.history.entries:
            if e.get("typ") not in types or e.get("rueckgaengig"):
                continue
            try:
                t = datetime.fromisoformat(e["zeit"]).astimezone()
            except (KeyError, ValueError):
                continue
            if t >= week:
                out["woche"] += e.get("anzahl") or 0
                if t.date() == today:
                    out["heute"] += e.get("anzahl") or 0
        return out

    def _staged_dup_ids(self) -> set[str]:
        """Vorgemerkt als Duplikat oder (Serienbild) als Stapel."""
        return self.staging.asset_ids("duplikat") | self.staging.asset_ids("stapel")

    def duplicate_groups(self, include_ignored: bool = False) -> list[DuplicateGroup]:
        staged = self._staged_dup_ids()
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
                        ignored: bool = False, sort: str = "datum") -> dict:
        """Gruppen mit Filtern. ``ignored=True`` zeigt nur die als „kein Duplikat“ markierten."""
        lib = self.library()
        staged = self._staged_dup_ids()
        all_groups = [g for g in self.all_groups() if not (g.asset_ids & staged)]
        ignore = self.ignore_list()
        n_ignored = sum(1 for g in all_groups if ignore.contains(g))
        base = [g for g in all_groups if ignore.contains(g) == ignored]
        if not include_done:
            base = [g for g in base if not g.done()]
        groups = self._filter_groups(base, art, monat, cross_user, include_optional=True)
        if sort == "speicher":  # zuerst, was am meisten Platz frei macht
            groups = sorted(groups, key=lambda g: -sum(a.file_size or 0 for a in g.assets if a.id != g.suggested_keep))
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
            "filter": {"art": art, "monat": monat, "benutzeruebergreifend": cross_user, "sortierung": sort},
            "fortschritt": self.done_recently(("duplikat", "stapel")),
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
                keep = None if sel.get("alle") else sel.get("keep") or g.suggested_keep
                if keep is not None and keep not in {a.id for a in g.assets}:
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
        np = self.no_place_list()
        no_place, show = frozenset(np.hidden), frozenset(np.shown)
        key = (lib.uid, lib.rev, hours, self.settings.location_include_external,
               self.settings.location_skip_screenshots, staged, no_place, show, self.text_store.rev)
        with self._calc_lock:
            cache = self._analysis_cache
            if not cache or cache[0] != key:
                cache = self._analysis_cache = (key, analyze(lib, hours, self.settings.location_include_external,
                                                             self.settings.location_skip_screenshots, staged,
                                                             no_place, show, self.text_store))
        return hours, cache[1]

    def no_place_list(self) -> NoPlaceList:
        return NoPlaceList(self.settings.data_dir / "ohne_ort_ausgeblendet.json")

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

    @staticmethod
    def _member_filter(series, herkunft=None, benutzer=None):
        """Serien nur mit den Medien dieser Herkunft bzw. dieses Benutzers; leere fallen weg."""
        if not herkunft and not benutzer:
            return series
        out = []
        for s in series:
            members = [c for c in s.members if (not herkunft or c.origin == herkunft)
                       and (not benutzer or c.asset.owner == benutzer)]
            if members:
                out.append(replace(s, members=members))
        return out

    def no_location_view(self, max_hours: float | None = None, offset: int = 0, limit: int = 20,
                         only_suggestions: bool = False, min_confidence: str | None = None,
                         ort: str | None = None, monat: str | None = None,
                         overview: bool = False, herkunft: str | None = None,
                         benutzer: str | None = None, sort: str = "datum") -> dict[str, Any]:
        """Serien ohne Ort. ``overview`` liefert nur die Orte mit Mengen (ohne Serien).
        ``herkunft`` / ``benutzer``: nur die Medien dieser Herkunft bzw. dieses Benutzers."""
        if herkunft and herkunft not in HERKUNFT:
            raise ActionError(f"Herkunft muss {', '.join(HERKUNFT)} sein")
        if benutzer and benutzer not in self.clients:
            raise ActionError(f"Benutzer muss {', '.join(self.clients)} sein")
        lib = self.library()
        if self.text_progress.finished_at is None:
            self.start_text_scan()  # einmal je Programmstart; danach nach jedem Einlesen
        hours, an = self._analysis(max_hours)
        # Serien (und damit Orte, Monate, Zahlen) nur mit den Medien dieser Herkunft / dieses Benutzers
        base = self._member_filter(self._filter_series(an.series, only_suggestions, min_confidence), herkunft, benutzer)
        series = self._filter_series(base, ort=ort, monat=monat)
        if sort == "menge":  # große Serien zuerst – ein Tipp erledigt viele Medien
            series = sorted(series, key=lambda s: -len(s.members))
        # Herkunft und Benutzer zählen im gewählten Ort/Monat – jeweils ohne den eigenen Filter (wie bei Ort und Monat)
        scope = self._filter_series(self._filter_series(an.series, only_suggestions, min_confidence), ort=ort, monat=monat)
        members = [c for s in scope for c in s.members]
        origins = Counter(c.origin for c in members if not benutzer or c.asset.owner == benutzer)
        owners = Counter(c.asset.owner for c in members if not herkunft or c.origin == herkunft)
        applicable = [c for c in an.candidates if c.applicable]
        out = {
            "stand": lib.scanned_at,
            "max_stunden": hours,
            "extern_erlaubt": self.settings.location_include_external,
            "screenshots_ausgeblendet": an.screenshots,
            "kein_ort_ausgeblendet": sum(1 for _, why in an.hidden if why == "kein_ort"),
            "archiviert_ausgeblendet": sum(1 for _, why in an.hidden if why == "archiviert"),
            "texterkennung": self.text_progress.to_dict(),
            "herkunft": {k: {"name": v, "anzahl": origins.get(k, 0)} for k, v in HERKUNFT.items()},
            "benutzer": {u: owners.get(u, 0) for u in self.clients},
            "medien": len(an.candidates),
            "mit_vorschlag": len(applicable),
            "nach_sicherheit": {lvl: sum(1 for c in applicable if c.suggestion.confidence == lvl)
                                for lvl in reversed(LEVELS)},
            # Mengen je Ort (für den aktuellen Monat) und je Monat (für den aktuellen Ort)
            "orte": place_facets(self._filter_series(base, monat=monat)),
            "monate": month_facets(self._filter_series(base, ort=ort)),
            "filter": {"ort": ort, "monat": monat, "herkunft": herkunft, "benutzer": benutzer, "sortierung": sort},
            "fortschritt": self.done_recently(("ort",)),
            "serien_gesamt": len(series),
            "medien_gefiltert": sum(len(s.members) for s in series),
            "offset": offset,
        }
        if not overview:
            page = series[offset: offset + limit] if limit > 0 else series[offset:]
            out["serien"] = [s.to_dict() for s in page]
        return out

    def _select_locations(self, ids=None, max_hours=None, min_confidence=None, series=None, place=None,
                          ort=None, monat=None, herkunft=None, benutzer=None):
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
                             if c.editable and (place or c.suggestion) and (not herkunft or c.origin == herkunft)
                             and (not benutzer or c.asset.owner == benutzer)
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
                                 manual=manual, exclude=self.staging.asset_ids("ort"),
                                 no_place=self.no_place_list().hidden, show=self.no_place_list().shown)

    def origin_media(self, herkunft: str, max_hours: float | None = None, ort: str | None = None,
                     monat: str | None = None, benutzer: str | None = None) -> dict[str, Any]:
        """Alle Medien ohne Ort einer Herkunft – zum Prüfen und Ausblenden („kein Ort nötig“);
        mit ``ort``/``monat`` nur aus diesem Ort bzw. Monat."""
        if herkunft not in HERKUNFT:
            raise ActionError(f"Herkunft muss {', '.join(HERKUNFT)} sein")
        _, an = self._analysis(max_hours)
        series = self._filter_series(an.series, ort=ort, monat=monat)
        return {"herkunft": herkunft, "name": HERKUNFT[herkunft],
                "medien": self._review_media([c.asset.id for s in series for c in s.members if c.origin == herkunft
                                              and (not benutzer or c.asset.owner == benutzer)])}

    def hidden_location_media(self, max_hours: float | None = None) -> dict[str, Any]:
        """Ausgeblendete Medien ohne Ort: „kein Ort nötig“, in Immich archiviert, erkannte Screenshots."""
        _, an = self._analysis(max_hours)
        why = {a.id: reason for a, reason in an.hidden}
        media = self._review_media(list(why))
        for m in media:
            m["grund"] = why[m["id"]]
        return {"medien": media}

    def set_no_place(self, ids: list[str], undo: bool = False) -> dict[str, Any]:
        """„Kein Ort nötig“ setzen – oder zurücknehmen (bei archivierten und Screenshots: trotzdem zeigen)."""
        if not ids:
            raise ActionError("Keine Medien angegeben")
        lib = self.library()
        np = self.no_place_list()
        if undo:
            np.update(hidden=set(), unhide=set(ids),
                      show={i for i in ids if i in lib.assets
                            and (is_screenshot(lib.assets[i]) or lib.assets[i].visibility == "archive")})
        else:
            np.update(hidden=set(ids), unhide=set(), show=set())
        return {"medien": len(ids), "rueckgaengig": undo}

    def location_media(self, min_confidence: str = "hoch", max_hours: float | None = None,
                       benutzer: str | None = None, herkunft: str | None = None) -> dict[str, Any]:
        """Alle Medien mit Ortsvorschlag ab dieser Sicherheit – für die Prüf-Ansicht, mit dem neuen Ort;
        optional nur eines Benutzers bzw. einer Herkunft."""
        changes, _ = self._select_locations(max_hours=max_hours, min_confidence=min_confidence)
        _, an = self._analysis(max_hours)
        new = {ch.asset_id: ch for ch in changes if (not benutzer or ch.owner == benutzer)
               and (not herkunft or (ch.asset_id in an.by_id and an.by_id[ch.asset_id].origin == herkunft))}
        media = self._review_media(list(new))
        for m in media:
            ch = new[m["id"]]
            m["ort_neu"] = ch.place or f"{ch.latitude:.3f}, {ch.longitude:.3f}"
        return {"sicherheit": min_confidence, "medien": media}

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
                keeper = g.asset(keep or g.suggested_keep)
                trash = sum(1 for s in steps if s.action == "papierkorb")
                title = (f"{keeper.file_name}: " + (f"alle {len(steps)} weg → " if keep is None else
                                                    f"{len(steps)} {'Kopie' if len(steps) == 1 else 'Kopien'} → ")
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
                self._sugg_cache = (key, [{**d, "tag": r.tags[0], "archivierbar": len(self._archivable(lib, r)),
                                           **{k: p[k] for k in ("treffer", "schon_getaggt", "neu", "beispiele", "benutzer")}}
                                          for (d, r), p in zip(pairs, previews)])
            items = self._sugg_cache[1]
        off = self.hidden_suggestions().ids
        staged = {e.get("key") for e in self.staging.of_type("tag")}
        staged |= {e.get("key") for e in self.staging.of_type("archiv")}
        shown = [s for s in items if (s["id"] in off) == hidden and s["id"] not in staged
                 and (hidden or s["neu"] or (s["art"] == "quelle" and s["archivierbar"]))]
        return {"stand": lib.scanned_at, "vorschlaege": shown, "ausgeblendet": sum(1 for s in items if s["id"] in off),
                "begriffe": [{"name": n, "tag": t} for n, _, t in BEGRIFFE]}

    def smart_view(self, begriff: str | None = None, query: str | None = None, tag: str | None = None,
                   size: int | None = None) -> dict[str, Any]:
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
        hidden = self.smart_hidden().ids(tag)
        try:
            ids = smart_results(self.clients, lib, query.strip(), exclude | hidden, size or SMART_SIZE)
        except ImmichError as exc:
            raise ActionError(f"KI-Suche nicht möglich (ist das maschinelle Lernen in Immich aktiv?): {exc}") from exc
        return {"begriff": begriff, "suche": query, "tag": tag, "medien": [lib.assets[i].summary() for i in ids],
                "ausgeblendet": len(hidden & set(lib.assets))}

    def smart_hidden(self) -> SmartHidden:
        return SmartHidden(self.settings.data_dir / "ki_ausgeblendet.json")

    def smart_hide(self, tag: str, ids: list[str], undo: bool = False) -> dict[str, Any]:
        """KI-Treffer, die zu diesem Tag nicht passen, künftig nicht mehr zeigen (``undo``: wieder zeigen)."""
        if not tag.strip():
            raise ActionError("Tag fehlt")
        return {"ausgeblendet": self.smart_hidden().update(tag, ids, remove=undo)}

    def smart_hidden_media(self, tag: str) -> dict[str, Any]:
        return {"tag": tag, "medien": self._review_media(sorted(self.smart_hidden().ids(tag)))}

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

    def _suggestion_ids(self, sugg_id: str, action: str) -> tuple[dict[str, Any], Rule, list[str]]:
        """Was ein Vorschlag betrifft: noch nicht getaggte Treffer bzw. noch nicht archivierte."""
        pairs = {d["id"]: (d, r) for d, r in self._suggestion_rules()}
        if sugg_id not in pairs:
            raise ActionError("Vorschlag nicht (mehr) vorhanden – bitte neu laden")
        d, rule = pairs[sugg_id]
        lib = self.library()
        if action == "archiv":
            return d, rule, self._archivable(lib, rule)
        new = set().union(*(m.new_ids for m in evaluate_rule(rule, lib, Resolver(self.clients))))
        return d, rule, [i for i in lib.assets if i in new]

    def suggestion_media(self, sugg_id: str, action: str = "tag") -> dict[str, Any]:
        """Alle Medien eines Vorschlags zum Prüfen, neueste zuerst (knapp gehalten, auch für Tausende)."""
        d, rule, ids = self._suggestion_ids(sugg_id, action)
        return {"id": sugg_id, "titel": d["titel"], "tag": rule.tags[0], "aktion": action, "medien": self._review_media(ids)}

    def _review_media(self, ids: list[str]) -> list[dict[str, Any]]:
        """Medien für die Prüf-Ansicht: neueste zuerst, knapp gehalten (auch für Tausende)."""
        lib = self.library()
        assets = sorted((lib.assets[i] for i in ids if i in lib.assets), key=lambda a: a.local_dt or datetime.min, reverse=True)
        return [{"id": a.id, "dateiname": a.file_name, "aufnahme": a.local_dt.isoformat(sep=" ") if a.local_dt else None,
                 "benutzer": a.owner, "typ": "video" if a.type == "VIDEO" else "foto", "extern": a.is_external,
                 "dauer_s": round(a.duration_ms / 1000, 1) if a.duration_ms else None} for a in assets]

    def _rule_missing(self, name: str) -> tuple[Rule, dict[str, set[str]]]:
        """Eigene Regel: je Tag die Medien, denen er noch fehlt."""
        rules = self._select_rules([name])
        rule = rules[0]
        missing: dict[str, set[str]] = {t: set() for t in rule.tags}
        for m in evaluate_rule(rule, self.library(), Resolver(self.clients)):
            for tag, ids in m.missing.items():
                missing[tag] |= set(ids)
        return rule, missing

    def rule_media(self, name: str) -> dict[str, Any]:
        rule, missing = self._rule_missing(name)
        return {"regel": name, "tags": rule.tags, "medien": self._review_media(sorted(set().union(*missing.values())))}

    def stage_rule_selection(self, name: str, without: list[str]) -> dict[str, Any]:
        """Eigene Regel ohne die abgewählten Medien vormerken (ein Eintrag je Tag)."""
        rule, missing = self._rule_missing(name)
        off = set(without)
        if not off:
            return self.stage_tags([name])
        lib = self.library()
        total = 0
        for tag, ids in missing.items():
            chosen = sorted(ids - off)
            if not chosen:
                continue
            by_user: dict[str, list[str]] = {}
            for i in chosen:
                by_user.setdefault(lib.assets[i].owner, []).append(i)
            self.staging.add("tag", f"🏷 {name} → {tag}: {len(chosen)} von {len(ids)} Medien (geprüft)",
                             {"medien": by_user, "tags": [tag], "regel_name": name},
                             [lib.assets[i].summary() for i in chosen[:8]], len(chosen), key=f"{name}|{tag}")
            total += len(chosen)
        if not total:
            raise ActionError("Alles abgewählt – nichts vorzumerken")
        return {"vorgemerkt": total}

    def stage_suggestion_selection(self, sugg_id: str, without: list[str], action: str = "tag") -> dict[str, Any]:
        """Vorschlag ohne die abgewählten Medien vormerken (taggen oder archivieren)."""
        d, rule, ids = self._suggestion_ids(sugg_id, action)
        off = set(without)
        chosen = [i for i in ids if i not in off]
        if not chosen:
            raise ActionError("Alles abgewählt – nichts vorzumerken")
        lib = self.library()
        if action == "archiv":
            return self._stage_archive(lib, chosen, d["titel"], key=sugg_id)
        tag = rule.tags[0]
        if not off:  # nichts abgewählt: wie „Taggen“ (Regel, beim Übertragen neu ausgewertet)
            return self.stage_suggestions([sugg_id])
        by_user: dict[str, list[str]] = {}
        for i in chosen:
            by_user.setdefault(lib.assets[i].owner, []).append(i)
        self.staging.add("tag", f"🏷 {d['titel']} → {tag}: {len(chosen)} von {len(ids)} Medien (geprüft)",
                         {"medien": by_user, "tags": [tag]}, [lib.assets[i].summary() for i in chosen[:8]], len(chosen), key=sugg_id)
        return {"vorgemerkt": len(chosen)}

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

    # ----------------------------------------------------------- Archivieren
    @staticmethod
    def _archivable(lib: Library, rule: Rule) -> list[str]:
        return [a.id for a in lib.assets.values() if a.visibility != "archive" and rule.matches_local(a)]

    def stage_archive_suggestion(self, sugg_id: str) -> dict[str, Any]:
        """Vorschlag (z. B. Screenshots, WhatsApp) archivieren statt taggen."""
        pairs = {d["id"]: (d, r) for d, r in self._suggestion_rules()}
        if sugg_id not in pairs:
            raise ActionError("Vorschlag nicht (mehr) vorhanden – bitte neu laden")
        d, rule = pairs[sugg_id]
        lib = self.library()
        ids = self._archivable(lib, rule)
        if not ids:
            raise ActionError("Alles schon archiviert")
        return self._stage_archive(lib, ids, d["titel"], key=sugg_id)

    def stage_archive(self, ids: list[str], label: str | None = None) -> dict[str, Any]:
        lib = self.library()
        chosen = [i for i in ids if i in lib.assets and lib.assets[i].visibility != "archive"]
        if not chosen:
            raise ActionError("Keine Medien ausgewählt (oder schon archiviert)")
        return self._stage_archive(lib, chosen, label or "Auswahl")

    def _stage_archive(self, lib: Library, ids: list[str], label: str, key: str | None = None) -> dict[str, Any]:
        by_user: dict[str, list[str]] = {}
        for i in ids:
            by_user.setdefault(lib.assets[i].owner, []).append(i)
        self.staging.add("archiv", f"🗄 {label}: {len(ids)} Medien archivieren (aus der Zeitleiste nehmen)",
                         {"medien": by_user, "alle_medien": ids}, [lib.assets[i].summary() for i in ids[:8]], len(ids), key=key)
        return {"vorgemerkt": len(ids)}

    def _archive(self, lib: Library, by_user: dict[str, list[str]]) -> dict[str, Any]:
        done, undo = 0, []
        for user, ids in by_user.items():
            ids = [i for i in ids if i in lib.assets and lib.assets[i].visibility != "archive"]
            if not ids:
                continue
            self.clients[user].set_visibility(ids, "archive")
            for i in ids:
                lib.assets[i].visibility = "archive"
            done += len(ids)
            undo.append({"op": "sichtbarkeit", "user": user, "ids": ids, "sichtbarkeit": "timeline"})
        return {"archiviert": done, "rueck": undo}

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

    def _staged_entry(self, entry_id: str) -> dict[str, Any]:
        e = self.staging.get(entry_id)
        if e is None:
            raise ActionError("Eintrag nicht (mehr) vorgemerkt – bitte neu laden")
        return e

    def _staged_ids(self, e: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        """Alle Medien eines vorgemerkten Eintrags und je Medium ein kurzes Merkmal (z. B. 🗑, neuer Ort)."""
        d, typ = e["daten"], e["typ"]
        by_user = lambda m: [i for ids in m.values() for i in ids]  # noqa: E731
        marks: dict[str, str] = {}
        if typ in ("duplikat", "aufraeumen"):
            ids = [s["id"] for s in d["schritte"]]
            marks = {s["id"]: "🗑" if s["aktion"] == "papierkorb" else "Prüf-Album" for s in d["schritte"]}
        elif typ == "ort":
            ids = [ch["asset_id"] for ch in d["aenderungen"]]
            marks = {ch["asset_id"]: ch.get("place") or "" for ch in d["aenderungen"]}
        elif typ in ("album", "archiv"):
            ids = by_user(d["medien"])
        elif typ == "zeit":
            ids = [i for ch in d["aenderungen"] for i in ch["ids"]]
        elif typ == "stapel":
            ids = [i for s in d["stapel"] for i in s["ids"]]
            marks = {s["ids"][0]: "oben" for s in d["stapel"]}
        elif typ == "tag" and "medien" in d:
            ids = by_user(d["medien"])
        elif typ == "tag" and "regel" in d:
            ids = sorted(set().union(*self._rule_missing(d["regel"])[1].values()))
        elif typ == "tag" and "regel_def" in d:
            ids = self._suggestion_ids(e["key"], "tag")[2]
        else:
            raise ActionError("Dieser Eintrag betrifft ganze Alben, keine einzelnen Medien")
        return ids, marks

    def staged_media(self, entry_id: str) -> dict[str, Any]:
        """Alle Medien eines vorgemerkten Eintrags für die Prüf-Ansicht."""
        e = self._staged_entry(entry_id)
        ids, marks = self._staged_ids(e)
        media = self._review_media(ids)
        for m in media:
            if marks.get(m["id"]):
                m["marke"] = marks[m["id"]]
        return {"id": e["id"], "typ": e["typ"], "titel": e["titel"], "medien": media}

    def staged_without(self, entry_id: str, without: list[str]) -> dict[str, Any]:
        """Einzelne Medien aus einem vorgemerkten Eintrag nehmen. Ist danach nichts mehr übrig, fällt er weg."""
        with self._lock:
            e = self._staged_entry(entry_id)
            d, typ = e["daten"], e["typ"]
            ids, _ = self._staged_ids(e)
            off = set(without) & set(ids)
            if not off:
                return {"entfernt": 0, "uebrig": len(ids)}
            if typ == "tag" and "regel" in d:  # Regel → feste Auswahl (ein Eintrag je Tag)
                self.staging.remove([e["id"]])
                try:
                    self.stage_rule_selection(d["regel"], sorted(off))
                except ActionError:
                    pass  # alles abgewählt
                return {"entfernt": len(off), "uebrig": len(ids) - len(off)}
            if typ == "tag" and "regel_def" in d:
                try:
                    self.stage_suggestion_selection(e["key"], sorted(off))
                except ActionError:
                    self.staging.remove([e["id"]])
                return {"entfernt": len(off), "uebrig": len(ids) - len(off)}
            keep = lambda m: {u: r for u, v in m.items() if (r := [i for i in v if i not in off])}  # noqa: E731
            if typ in ("duplikat", "aufraeumen"):
                d["schritte"] = [s for s in d["schritte"] if s["id"] not in off]
            elif typ == "ort":
                d["aenderungen"] = [ch for ch in d["aenderungen"] if ch["asset_id"] not in off]
            elif typ in ("album", "archiv", "tag"):
                d["medien"] = keep(d["medien"])
                if typ == "archiv":
                    d["alle_medien"] = [i for i in d["alle_medien"] if i not in off]
                if typ == "album":
                    d["anzahl"] = sum(len(v) for v in d["medien"].values())
                    if d.get("ordner"):
                        d["ordner_ohne"] = sorted(set(d.get("ordner_ohne") or []) | off)
                    else:  # abgewählte gehören nicht zur Reise – wie in der Prüf-Ansicht
                        d["ohne"] = sorted(set(d.get("ohne") or []) | off)
                        self.album_excluded().update(off)
            elif typ == "zeit":
                d["aenderungen"] = [ch for ch in ({**ch, "ids": [i for i in ch["ids"] if i not in off]}
                                                  for ch in d["aenderungen"]) if ch["ids"]]
                d["alle_medien"] = [i for i in d["alle_medien"] if i not in off]
            elif typ == "stapel":
                d["stapel"] = [s for s in ({**s, "ids": [i for i in s["ids"] if i not in off]} for s in d["stapel"])
                               if len(s["ids"]) > 1]
                d["alle_medien"] = [i for s in d["stapel"] for i in s["ids"]]
            left = len(self._staged_ids(e)[0])
            if not left and not (typ == "album" and d.get("sync")):
                self.staging.remove([e["id"]])
                return {"entfernt": len(off), "uebrig": 0}
            old, e["anzahl"] = e["anzahl"], left
            e["titel"] = plan_title(d) if typ == "album" and d.get("reise") else \
                re.sub(rf"\b{old}\b(?= (Medi|Kopie|Stapel))", str(left), e["titel"], count=1)
            e["medien"] = [m for m in e["medien"] if m.get("id") not in off]
            e["fehler"] = None
            self.staging.save()
            return {"entfernt": len(off), "uebrig": left}

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
                                steps.append(PlannedStep(a, st["aktion"], st["grund"], lib.assets.get(st.get("behalten") or "")))
                        res = execute_steps(lib, self.clients, steps, self.settings.review_album)
                        res["uebersprungen"] = skipped
                    elif e["typ"] == "ort":
                        res = execute_location_changes(lib, self.clients, [
                            LocationChange.from_dict(ch) for ch in e["daten"]["aenderungen"]])
                    elif e["typ"] == "album":
                        res = execute_plan(lib, self.clients, e["daten"])
                        self._after_album_plan(e["daten"], res)
                    elif e["typ"] == "zeit":
                        res = execute_shifts(lib, self.clients, e["daten"]["aenderungen"])
                    elif e["typ"] == "stapel":
                        res = execute_stacks(lib, self.clients, e["daten"])
                    elif e["typ"] == "albenpflege":
                        res = execute_care(lib, self.clients, e["daten"])
                    elif e["typ"] == "archiv":
                        res = self._archive(lib, e["daten"]["medien"])
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
                         "zeit": lambda r: r["verschoben"], "stapel": lambda r: r["medien"],
                         "albenpflege": lambda r: r["hinzugefuegt"] + r["geloescht"] + r.get("titelbild", 0),
                         "archiv": lambda r: r["archiviert"]}[e["typ"]](res)
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

    def place_name(self, lat: float, lon: float) -> dict[str, Any]:
        """Ortsname für einen Punkt auf der Karte (Immichs eigene Ortsdaten)."""
        if not self.clients:
            raise NotConfigured()
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ActionError("Koordinaten außerhalb des gültigen Bereichs")
        try:
            hits = next(iter(self.clients.values())).reverse_geocode(lat, lon)
        except ImmichError:
            hits = []
        p = hits[0] if hits else {}
        return {"name": p.get("city"), "region": ", ".join(x for x in (p.get("state"), p.get("country")) if x),
                "breite": lat, "laenge": lon}

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
                     offset: int = 0, limit: int = 30, sort: str = "standard") -> dict[str, Any]:
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
        if sort == "speicher":
            chosen = sorted(chosen, key=lambda i: -i.size)
        elif sort == "menge":
            chosen = sorted(chosen, key=lambda i: -len(i.assets))
        page = chosen[offset: offset + limit] if limit > 0 else chosen[offset:]
        hs = self.hash_status()
        return {
            "stand": lib.scanned_at,
            "arten": {k: {"name": v, "anzahl": sum(c["anzahl"] for c in cats.values() if c["art"] == k),
                          "groesse": sum(c["groesse"] for c in cats.values() if c["art"] == k)}
                      for k, v in CLEANUP_ARTEN.items()},
            "kategorien": cats,
            "filter": {"art": art, "kategorie": kategorie, "ignoriert": ignored, "sortierung": sort},
            "fortschritt": self.done_recently(("aufraeumen", "stapel", "zeit", "archiv")),
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

    # ------------------------------------------------------- Alben aufräumen
    def album_care_view(self, ignored: bool = False) -> dict[str, Any]:
        if self.albums_pending(wait_s=3):
            return {"laedt": True}
        lib = self.library()
        items = self._care_items(lib)
        keep = self.keep_list().ids
        staged = {a for e in self.staging.of_type("albenpflege") for a in e["daten"]["alben"]}
        items = [it for it in items if not ({a["id"] for a in it["alben"]} & staged)]
        shown = [it for it in items if (it["id"] in keep) == ignored]
        return {"eintraege": shown, "arten": {k: {"name": v, "anzahl": sum(1 for it in items if it["art"] == k and it["id"] not in keep)}
                                               for k, v in CARE_ARTEN.items()},
                "ausgeblendet": sum(1 for it in items if it["id"] in keep)}

    def _care_items(self, lib: Library) -> list[dict[str, Any]]:
        return find_issues(lib) + find_covers(lib, self.hash_store)

    def stage_album_care(self, item_id: str, action: str, target: str | None = None, delete_rest: bool = True,
                         cover: str | None = None) -> dict[str, Any]:
        """action: zusammenfuehren (in ``target``), loeschen oder titelbild (``cover``, sonst der Vorschlag)."""
        with self._lock:
            lib = self.library()
            item = next((it for it in self._care_items(lib) if it["id"] == item_id), None)
            if item is None:
                raise ActionError("Eintrag nicht gefunden – bitte neu laden")
            ids = [a["id"] for a in item["alben"]]
            names = " + ".join(f"„{a['name']}“ ({a['besitzer']})" for a in item["alben"])
            if (item["art"] == "titelbild") != (action == "titelbild"):
                raise ActionError("Diese Aktion passt nicht zu diesem Eintrag")
            if action == "zusammenfuehren":
                if len(ids) < 2:
                    raise ActionError("Zum Zusammenführen braucht es mindestens zwei Alben")
                target = target or item["ziel"]
                if target not in ids:
                    raise ActionError("Ziel-Album gehört nicht zu diesem Eintrag")
                plan = plan_merge(lib, ids, target, delete_rest)
                n = sum(len(v) for v in plan["medien"].values())
                title = (f"🗂 {names} → in „{plan['ziel_name']}“ ({lib.albums[target]['besitzer']}) zusammenführen: {n} Medien dazu"
                         + (f", {len(plan['loeschen'])} Album gelöscht" if plan["loeschen"] else "")
                         + (f", geteilt mit {', '.join(plan['teilen'])}" if plan["teilen"] else ""))
            elif action == "titelbild":
                try:
                    plan = plan_cover(lib, ids[0], cover or item["vorschlag"])
                except ValueError as exc:
                    raise ActionError(str(exc)) from None
                n = 1
                title = f"🖼 Neues Titelbild für {names}"
                media = [lib.assets[plan["titelbild"]].summary()]
                plan["alben"] = ids
                self.staging.add("albenpflege", title, plan, media, n, key=item_id)
                return {"vorgemerkt": 1}
            elif action == "loeschen":
                plan = plan_delete(lib, ids)
                n = len(ids)
                title = f"🗂 {names} löschen (die Fotos bleiben in Immich)"
            else:
                raise ActionError("Aktion muss zusammenfuehren, loeschen oder titelbild sein")
            plan["alben"] = ids
            media = [m for a in item["alben"] for m in a["beispiele"]][:8]
            self.staging.add("albenpflege", title, plan, media, n, key=item_id)
            return {"vorgemerkt": 1}

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

    # ------------------------------------------------- Automatisch vormerken
    AUTO_LABELS = {"orte": "Sichere Orte", "identisch": "Identische Duplikate", "messenger": "Messenger-Kopien",
                   "bearbeitung": "Original + Bearbeitung", "serien": "Serienbilder stapeln"}

    def _auto_dup_groups(self, kind: str) -> list[DuplicateGroup]:
        return [g for g in self.duplicate_groups() if g.kind == kind and not g.done()]

    def _auto_bursts(self) -> list[str]:
        _, items = self.cleanup_items()
        keep = self.keep_list().ids
        return [i.id for i in items if i.kategorie == "serien" and i.id not in keep]

    def auto_stage_preview(self, action: str = "album") -> dict[str, Any]:
        """Was „Eindeutiges vormerken“ jetzt erfassen würde – je Art Einträge und Medien."""
        out: dict[str, Any] = {}
        loc = self.no_location_view(overview=True)
        out["orte"] = {"anzahl": loc["nach_sicherheit"]["hoch"], "medien": loc["nach_sicherheit"]["hoch"]}
        for kind in ("identisch", "messenger", "bearbeitung"):
            groups = self._auto_dup_groups(kind)
            steps = [s for g in groups for s in plan_group(g, g.suggested_keep, action) if s.action != "keine"]
            out[kind] = {"anzahl": len(groups), "medien": len(steps),
                         "papierkorb": sum(1 for s in steps if s.action == "papierkorb")}
        series = self._auto_dup_groups("serie")
        _, items = self.cleanup_items()
        bursts = set(self._auto_bursts())
        out["serien"] = {"anzahl": len(series) + len(bursts),
                         "medien": sum(len(g.assets) for g in series) + sum(len(i.ids) for i in items if i.id in bursts)}
        return {"arten": {k: {"name": self.AUTO_LABELS[k], **v} for k, v in out.items()}, "aktion": action}

    def auto_stage(self, kinds: list[str], action: str = "album", label: str = "Eindeutiges") -> dict[str, Any]:
        """Eindeutige Fälle gesammelt vormerken (je Art ein Eintrag). Übertragen wird erst unter Vorgemerkt –
        mit denselben Schutzregeln und der Papierkorb-Bestätigung wie sonst."""
        unknown = [k for k in kinds if k not in self.AUTO_LABELS]
        if unknown or action not in AKTIONEN:
            raise ActionError(f"Arten: {', '.join(self.AUTO_LABELS)}; Aktion: album oder papierkorb")
        done: dict[str, int] = {}
        with self._lock:
            if "orte" in kinds:
                try:
                    done["orte"] = self.stage_no_location(label=f"⚡ {label}: sichere Orte", min_confidence="hoch")["vorgemerkt"]
                except ActionError:
                    done["orte"] = 0
            lib = self.library()
            for kind in ("identisch", "messenger", "bearbeitung"):
                if kind not in kinds:
                    continue
                groups = self._auto_dup_groups(kind)
                steps = [s for g in groups for s in plan_group(g, g.suggested_keep, action) if s.action != "keine"]
                done[kind] = len(groups) if steps else 0
                if not steps:
                    continue
                trash = sum(1 for s in steps if s.action == "papierkorb")
                where = "Papierkorb" if trash == len(steps) else "Prüf-Album" if not trash else "Papierkorb/Prüf-Album"
                media = [{**s.asset.summary(), "bleibt": False, "aktion": s.action} for s in steps[:8]]
                self.staging.add("duplikat", f"⚡ {label}: {len(groups)} × {ARTEN[kind]} – {len(steps)} Kopien → {where}", {
                    "aktion": action, "gruppen": [g.id for g in groups], "automatisch": kind,
                    "alle_medien": sorted({i for g in groups for i in g.asset_ids}),
                    "schritte": [s.to_dict() for s in steps]}, media, len(steps))
            if "serien" in kinds:
                n = 0
                if self._auto_dup_groups("serie"):
                    n += self.stage_duplicate_stacks(all_groups=True)["vorgemerkt"]
                bursts = self._auto_bursts()
                if bursts:
                    n += self.stage_burst_stacks(bursts)["vorgemerkt"]
                done["serien"] = n
            log.info("Automatisch vorgemerkt (%s): %s", label, done)
            return {"vorgemerkt": done, "gesamt": sum(done.values())}

    def stage_duplicate_stacks(self, groups: list[dict] | None = None, all_groups: bool = False) -> dict[str, Any]:
        """Serienbilder unter den Duplikaten stapeln statt wegräumen: alle bleiben, ``keep`` liegt oben."""
        from .stacking import order
        with self._lock:
            found = {g.id: g for g in self.duplicate_groups()}
            if all_groups:
                selection = [(g, g.suggested_keep) for g in found.values() if g.kind == "serie"]
            else:
                if not groups:
                    raise ActionError("Keine Gruppen ausgewählt")
                selection = []
                for sel in groups:
                    g = found.get(sel.get("id", ""))
                    if g is None:
                        raise ActionError(f"Gruppe {sel.get('id')!r} nicht gefunden – bitte neu einlesen")
                    selection.append((g, sel.get("keep") or g.suggested_keep))
            stacks = []
            for g, keep in selection:
                if len(g.users) > 1:
                    raise ActionError("Stapeln geht nur mit Medien desselben Benutzers – Immich stapelt nur eigene")
                ordered = order(g.assets, self.hash_store, keep)
                stacks.append({"user": ordered[0].owner, "ids": [a.id for a in ordered]})
            if not stacks:
                raise ActionError("Nichts zu stapeln")
            n = sum(len(s["ids"]) for s in stacks)
            lib = self.library()
            self.staging.add("stapel", f"📚 Serienbilder aus Duplikaten: {len(stacks)} Stapel aus {n} Medien",
                             {"stapel": stacks, "album": None, "aus_album": False,
                              "alle_medien": [i for s in stacks for i in s["ids"]]},
                             [{**lib.assets[s["ids"][0]].summary(), "oben": True} for s in stacks[:8]], n)
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

    def timefix_media(self, fix_id: str) -> dict[str, Any]:
        """Alle Medien eines Eintrags (in der Liste steht nur eine Auswahl)."""
        _, fixes, _ = self.time_fixes()
        fix = next((f for f in fixes if f.id == fix_id), None)
        if fix is None:
            raise ActionError("Eintrag nicht gefunden – bitte neu laden")
        return {"id": fix.id, "medien": fix.media(sorted(fix.assets, key=lambda a: (a.local_dt is None, a.local_dt)))}

    def stage_timefix(self, selection: list[dict]) -> dict[str, Any]:
        """selection: [{id, minuten?, ohne?}] – ohne minuten gilt der Vorschlag; ``ziel`` (ISO-Zeit) für
        Einzelmedien; ``ohne``: Medien des Eintrags, die nicht verschoben werden."""
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
                without = set(sel.get("ohne") or [])
                assets = [a for a in fix.assets if a.id not in without]
                if not assets:
                    raise ActionError("Alles abgewählt – nichts vorzumerken")
                changes = plan_shifts(fix, int(minutes), without)
                title = (f"🕑 {fix.extra.get('kamera') or fix.assets[0].file_name}: "
                         f"{n_media(len(assets))}{f' von {len(fix.assets)}' if without else ''} um {fmt_offset(int(minutes))}")
                sample = assets[:: max(1, len(assets) // 6)][:6]
                media = [{**a.summary(), "neue_zeit": shifted(a, int(minutes))} for a in sample]
                self.staging.add("zeit", title, {"aenderungen": changes, "alle_medien": [a.id for a in assets]},
                                 media, len(assets), key=fix.id)
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
        album = lib.albums.get(album_id)
        inside = set(album["medien"]) if album else set()
        out = []
        for a in trip.assets:
            twin = None if a.id in inside else trip.twin_in(a, album)
            out.append({**a.summary(), "im_album": a.id in inside or twin is not None,
                        "kopie_im_album": lib.assets[twin].file_name if twin in lib.assets else None})
        return {"id": trip.id, "album": album_id, "anzahl": len(trip.assets), "medien": out}

    def album_check(self, asset_id: str, album_id: str) -> dict[str, Any]:
        """Liegt das Medium im Album? Fragt Immich direkt (GET /albums?assetId=) und vergleicht mit dem
        Stand des Tools. Weicht es ab, wird das Album sofort neu gelesen (alle Besitzer)."""
        lib = self.library()
        album = lib.albums.get(album_id)
        if album is None or asset_id not in lib.assets:
            raise ActionError("Album oder Medium nicht gefunden – bitte neu einlesen")
        twins = self.twins()
        twin = next((t for t in twins.get(asset_id, ()) if t in set(album["medien"])), None)
        seen: dict[str, str] = {}
        for client in self.clients.values():
            try:
                for al in client.albums(asset_id=asset_id):
                    seen[al["id"]] = al.get("albumName") or ""
            except ImmichError as exc:
                log.warning("Albumprüfung für %s: %s", asset_id, exc)
        in_tool = asset_id in album["medien"]
        in_immich = album_id in seen
        fixed = False
        if in_immich and not in_tool:
            ids: set[str] = set()
            for client in self.clients.values():
                try:
                    ids |= client.album_timeline_ids(album_id) | client.album_asset_ids(album_id)
                except ImmichError:
                    continue
            with self._lock:
                album["medien"] = sorted(set(album["medien"]) | ids | {asset_id})
                apply_album_membership(lib, recompute=True)
                self._save()
            fixed = True
            log.warning("Album „%s“ war unvollständig gelesen (%s fehlte) – neu gelesen", album["name"], asset_id)
        if in_immich:
            text = "Liegt laut Immich im Album." + (" Das Tool hatte das übersehen und hat das Album neu gelesen."
                                                     if fixed else "")
        elif twin:
            text = f"Nicht dieses Medium, aber eine Kopie davon liegt im Album ({lib.assets[twin].file_name})."
        else:
            def label(aid: str, name: str) -> str:
                owner = (lib.albums.get(aid) or {}).get("besitzer")
                return f"„{name}“" + (f" von {owner}" if owner else "")
            same = [aid for aid, name in seen.items() if name.strip().lower() == album["name"].strip().lower()]
            text = f"Liegt laut Immich nicht in „{album['name']}“" + (f" von {album['besitzer']}" if album["besitzer"] else "") + "."
            if seen:
                text += " Es liegt in: " + ", ".join(label(k, v) for k, v in seen.items()) + "."
            else:
                text += " Es liegt in keinem Album."
            if same:
                text += (" Achtung: ein anderes Album mit demselben Namen – unter Alben → Alben aufräumen lassen sich"
                         " die beiden zusammenführen.")
        return {"asset": asset_id, "album": album_id, "im_album_tool": in_tool or fixed, "im_album_immich": in_immich,
                "kopie": lib.assets[twin].file_name if twin else None, "alben_immich": [{"id": k, "name": v} for k, v in seen.items()],
                "korrigiert": fixed, "text": text}

    def twins(self) -> dict[str, set[str]]:
        """Kopien derselben Aufnahme (Duplikat-Gruppen außer „ähnlich“) und Medien im selben Immich-Stapel.
        Liegt eins davon im Album, gilt das Album für alle als vollständig."""
        lib = self.library()
        groups = [g.asset_ids for g in self.all_groups() if g.kind != "aehnlich"]
        key = (lib.uid, lib.rev, self._pairs_cache[0] if self._pairs_cache else None)
        cache = getattr(self, "_twins_cache", None)
        if cache and cache[0] == key:
            return cache[1]
        stacks: dict[str, set[str]] = {}
        for a in lib.assets.values():
            if a.stack_id:
                stacks.setdefault(a.stack_id, set()).add(a.id)
        twins = twin_map([s for s in stacks.values() if len(s) > 1] + groups)
        self._twins_cache = (key, twins)
        return twins

    def _trips(self):
        """Reisen ohne vorgemerkte; ``ignored`` = als „kein Album“ markiert."""
        lib = self.library()
        # Berechnung nur neu, wenn sich Bibliothek, Alben oder Einstellungen geändert haben
        manual = [Home(h["breite"], h["laenge"], h["name"], 0, manual=True) for h in self.settings.album_home]
        without = frozenset(self.album_excluded().ids)
        key = (lib.uid, lib.rev, self.settings.album_min_km, self.settings.album_min_media,
               tuple((h.latitude, h.longitude) for h in manual), without,
               self._pairs_cache[0] if self._pairs_cache else None)  # neue Fingerabdrücke -> neue Kopien
        twins = self.twins()  # vor der Sperre: braucht library() und damit self._lock
        with self._calc_lock:
            if not self._trips_cache or self._trips_cache[0] != key:
                self._trips_cache = (key, suggest(lib, self.settings.album_min_km, self.settings.album_min_media,
                                                  exclude=set(without), homes=manual or None, twins=twins))
            homes, trips = self._trips_cache[1]
        staged = self.staging.id_sets("album")
        ignore = self.album_ignore_list()
        out = [(t, ignore.contains(t.ids)) for t in trips if not overlaps(t.ids, staged)]
        return lib, homes, out

    def album_media(self, album_id: str, trip_id: str | None = None) -> dict[str, Any]:
        """Inhalt eines Albums zum Ansehen; mit ``trip_id`` stehen die noch fehlenden Medien der Reise vorn."""
        lib = self.library()
        album = lib.albums.get(album_id)
        if album is None:
            raise ActionError("Album nicht gefunden – bitte neu einlesen")
        missing: list[dict[str, Any]] = []
        if trip_id:
            trip = next((t for t, _ in self._trips()[2] if t.id == trip_id), None)
            if trip is not None:
                missing = self._review_media([a.id for a in trip.missing(album)])
                for m in missing:
                    m["fehlt"], m["marke"] = True, "fehlt"
        inside = self._review_media(album["medien"])
        return {"id": album_id, "name": album["name"], "besitzer": album.get("besitzer"), "anzahl": len(inside),
                "fehlend": len(missing), "medien": missing + inside}

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

    def _same_name_hint(self, plan: dict[str, Any]) -> None:
        """Neues Album mit einem Namen, den es schon gibt oder der schon vorgemerkt ist: beim Übertragen
        kommt alles in dasselbe Album (siehe execute_plan)."""
        if plan["aktion"] != "neu":
            return
        key = plan["name"].strip().lower()
        if same_name_album(self.library(), plan["name"]):
            plan["hinweise"].append(f"Album „{plan['name']}“ gibt es schon – die Medien kommen dort hinein, kein zweites Album")
        elif any(e["daten"].get("aktion") == "neu" and e["daten"].get("name", "").strip().lower() == key
                 and e.get("key") != plan.get("reise") for e in self.staging.of_type("album")):
            plan["hinweise"].append(f"„{plan['name']}“ ist schon als neues Album vorgemerkt – "
                                    "beim Übertragen kommt beides in dasselbe Album")

    def stage_albums(self, selection: list[dict]) -> dict[str, Any]:
        with self._lock:
            plans = self._album_plans(selection)
            for plan in plans:
                if plan["ohne"]:  # abgewählte gehören nicht zur Reise – auch nach dem Übertragen nicht
                    self.album_excluded().update(plan["ohne"])
                self._same_name_hint(plan)
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
        staged = {e["daten"].get("regel") or e["daten"].get("regel_name") for e in self.staging.of_type("tag")}
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

    def nav_counts(self) -> dict[str, Any]:
        """Offene Einträge je Menüpunkt (None = gerade nicht bekannt, z. B. Alben werden noch gelesen)."""
        self.library()
        cln = self.cleanup_view(limit=1)["arten"]
        albums_ready = not self.albums_pending()
        folders = self.folders_view() if albums_ready else None
        care = self.album_care_view() if albums_ready else None
        return {
            "dup": self.duplicates_view(limit=1)["offen"],
            "serien": cln["serien"]["anzahl"],
            "speicher": cln["speicher"]["anzahl"],
            "qualitaet": cln["qualitaet"]["anzahl"],
            "verwaist": cln["verwaist"]["anzahl"],
            "ort": self.no_location_view(overview=True)["mit_vorschlag"],
            "zeit": sum(self.timefix_view(limit=1)["arten"].values()),
            "tags": len(self.suggestions_view()["vorschlaege"]),
            "reisen": self.albums_view(limit=1)["offen"] if albums_ready else None,
            "ordner": folders["status"]["neu"] + folders["status"]["ergaenzen"] if folders and "status" in folders else None,
            "albenpflege": sum(a["anzahl"] for a in care["arten"].values()) if care and "arten" in care else None,
            "stage": self.staging.summary()["anzahl"],
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
