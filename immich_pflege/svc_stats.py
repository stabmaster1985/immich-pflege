"""Startseite, Statistik, Speicherprognose, Menüzähler.

Mixin der Klasse :class:`immich_pflege.service.Pflege` – nutzt deren Zustand (self.library(), self.clients …)."""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from .client import ImmichError
from .library import Library
from .models import Asset
from .svc_base import (
    STORAGE_CACHE_S,
    ActionError,
    key_permissions,
)

log = logging.getLogger(__name__)


class StatsMixin:
    def stats(self, year: str | None = None) -> dict[str, Any]:
        """Statistik: Jahre (je Benutzer), mit ``year`` dessen Monate, dazu Kameras, Länder, Orte, Formate,
        Wochentage und Uhrzeiten – für alle Jahre oder nur das gewählte."""
        lib = self.library()
        key = (lib.uid, lib.rev, year, len(self.history.entries))
        cached = self._stats_cache.get(key)
        if cached is None:
            cached = self._stats(lib, year)
            self._stats_cache = {k: v for k, v in self._stats_cache.items() if k[:2] == key[:2]}  # alte Stände weg
            self._stats_cache[key] = cached
        # Personen und Speicher haben eigene Zwischenspeicher (Abfragen bei Immich)
        return {**cached, "personen": self.top_people(), "speicher": self.storage_forecast()}

    def _stats(self, lib: Library, year: str | None) -> dict[str, Any]:
        owners = sorted({a.owner for a in lib.assets.values()})

        def bucket() -> dict[str, Any]:
            return {"medien": 0, "groesse": 0, "videos": 0, "ohne_gps": 0, "je_benutzer": {u: 0 for u in owners},
                    "groesse_je_benutzer": {u: 0 for u in owners}}

        def add(b: dict[str, Any], a: Asset) -> None:
            b["medien"] += 1
            b["groesse"] += a.file_size or 0
            b["videos"] += a.type == "VIDEO"
            b["ohne_gps"] += not a.has_gps
            b["je_benutzer"][a.owner] += 1
            b["groesse_je_benutzer"][a.owner] += a.file_size or 0

        years: dict[str, dict[str, Any]] = {}
        months = {f"{year}-{m:02d}": bucket() for m in range(1, 13)} if year else {}
        scope: list[Asset] = []
        undated = 0
        for a in lib.assets.values():
            if not a.local_dt:
                undated += 1
                if not year:
                    scope.append(a)
                continue
            y = str(a.local_dt.year)
            add(years.setdefault(y, bucket()), a)
            if year is None or y == year:
                scope.append(a)
                if year:
                    add(months[a.local_dt.strftime("%Y-%m")], a)
        if year and year not in years:
            raise ActionError(f"Keine Aufnahmen aus {year}")

        def top(values, n: int) -> list[dict[str, Any]]:
            return [{"name": k, "anzahl": c} for k, c in Counter(v for v in values if v).most_common(n)]

        cams = []
        for a in scope:
            if a.make or a.model:
                make, model = (a.make or "").strip(), (a.model or "").strip()
                cams.append(model if make and model.lower().startswith(make.lower()) else f"{make} {model}".strip())
        weekdays, hours = [0] * 7, [0] * 24
        heat = [[0] * 24 for _ in range(7)]  # Wochentag × Stunde
        for a in scope:
            if a.local_dt:
                weekdays[a.local_dt.weekday()] += 1
                hours[a.local_dt.hour] += 1
                heat[a.local_dt.weekday()][a.local_dt.hour] += 1
        return {
            "benutzer": owners,
            "jahr": year,
            "jahre": [{"jahr": k, **v} for k, v in sorted(years.items())],
            "monate": [{"monat": k, **v} for k, v in months.items()],
            "gesamt": {"medien": len(scope), "groesse": sum(a.file_size or 0 for a in scope),
                       "videos": sum(a.type == "VIDEO" for a in scope), "ohne_gps": sum(not a.has_gps for a in scope),
                       "extern": sum(a.is_external for a in scope), "ohne_datum": 0 if year else undated},
            "kameras": top(cams, 8),
            "laender": top((a.country for a in scope), 8),
            "orte": top((a.city for a in scope), 10),
            "formate": top(((a.file_name or "").rsplit(".", 1)[-1].upper() for a in scope if "." in (a.file_name or "")), 8),
            "wochentage": weekdays,  # Montag zuerst
            "stunden": hours,
            "heatmap": heat,
        }

    def storage_forecast(self) -> dict[str, Any] | None:
        """Belegter/freier Platz laut Immich und wann er bei gleichem Zuwachs voll ist. Zuwachs: Mittel der
        letzten 12 vollen Monate nach dem Datum, an dem die Medien in Immich kamen (sonst Aufnahmedatum)."""
        if not self.clients:
            return None
        if self._storage_cache and time.monotonic() - self._storage_cache[0] < STORAGE_CACHE_S:
            return self._storage_cache[1]
        try:
            st = next(iter(self.clients.values())).server_storage()
        except ImmichError as exc:
            log.info("Speicherplatz von Immich nicht abrufbar: %s", exc)
            st = {}
        lib = self.library()
        today = datetime.now().date().replace(day=1)
        months: list[str] = []
        d = today
        for _ in range(12):  # die 12 vollen Monate vor dem aktuellen
            d = (d - timedelta(days=1)).replace(day=1)
            months.insert(0, d.strftime("%Y-%m"))
        growth = {m: 0 for m in months}
        for a in lib.assets.values():
            when = (a.added_at or a.file_created_at or "")[:7]
            if when in growth:
                growth[when] += a.file_size or 0
        per_month = sum(growth.values()) / len(months)
        free = st.get("diskAvailableRaw")
        out: dict[str, Any] = {
            "gesamt": st.get("diskSizeRaw"), "belegt": st.get("diskUseRaw"), "frei": free,
            "prozent": st.get("diskUsagePercentage"), "medien_groesse": sum(a.file_size or 0 for a in lib.assets.values()),
            "zuwachs_monat": round(per_month), "monate": [{"monat": m, "groesse": growth[m]} for m in months],
        }
        if free and per_month > 0:
            left = free / per_month
            out["monate_bis_voll"] = round(left, 1)
            out["voll_am"] = (datetime.now() + timedelta(days=left * 30.44)).date().isoformat() if left < 1200 else None
        self._storage_cache = (time.monotonic(), out)
        return out

    def stats_media(self, month: str, user: str | None = None) -> dict[str, Any]:
        """Alle Medien eines Monats (JJJJ-MM) zum Ansehen, optional nur eines Benutzers."""
        lib = self.library()
        ids = [a.id for a in lib.assets.values() if a.local_dt and a.local_dt.strftime("%Y-%m") == month
               and (not user or a.owner == user)]
        return {"monat": month, "medien": self._review_media(ids)}

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
        loc = self.location_counts()
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

    def duplicate_savings(self) -> tuple[int, int]:
        """Offene Duplikat-Gruppen (wie „offen“ in der Liste) und wie viele Bytes der Vorschlag frei machen würde."""
        groups = [g for g in self._filter_groups(self.duplicate_groups()) if not g.done()]
        return len(groups), sum(a.file_size or 0 for g in groups for a in g.assets if a.id != g.suggested_keep)

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
            "videos": cln["videos"]["anzahl"],
            "ausrichtung": cln["ausrichtung"]["anzahl"],
            "qualitaet": cln["qualitaet"]["anzahl"],
            "verwaist": cln["verwaist"]["anzahl"],
            "ort": self.location_counts()["mit_vorschlag"],
            "zeit": sum(self.timefix_view(limit=1)["arten"].values()),
            "tags": len(self.suggestions_view()["vorschlaege"]),
            "reisen": self.albums_view(limit=1)["offen"] if albums_ready else None,
            "ordner": folders["status"]["neu"] + folders["status"]["ergaenzen"] if folders and "status" in folders else None,
            "albenpflege": sum(a["anzahl"] for a in care["arten"].values()) if care and "arten" in care else None,
            "stage": self.staging.summary()["anzahl"],
            # Personen nur aus dem Zwischenspeicher (sonst viele Anfragen an Immich bei jedem Zählen)
            "personen": len(self._people_view_cache[1]["doppelt"]) if self._people_view_cache else None,
        }

    # ------------------------------------------------------------ Übersicht
    def key_warnings(self) -> list[dict[str, Any]]:
        """Fehlende Rechte der API-Keys (einmal je Programmlauf abgefragt, für die Startseite)."""
        if self._key_warnings is None:
            out = []
            for name, client in self.clients.items():
                info = key_permissions(client)
                if info.get("rechte_fehlend"):
                    out.append({"benutzer": name, "fehlend": info["rechte_fehlend"]})
                    log.warning("API-Key von %s: es fehlen Rechte %s", name,
                                ", ".join(p["recht"] for p in info["rechte_fehlend"]))
            self._key_warnings = out
        return self._key_warnings

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
