"""Vorgemerkt: ansehen, einzelne herausnehmen, zurücknehmen, übertragen.

Mixin der Klasse :class:`immich_pflege.service.Pflege` – nutzt deren Zustand (self.library(), self.clients …)."""

from __future__ import annotations

import logging
import re
from typing import Any

from .albumcare import execute_care
from .albums import AlbumError, execute_plan, plan_title
from .client import ImmichError
from .duplicates import PlannedStep, execute_steps
from .location import LocationChange, execute_location_changes
from .rules import RuleError
from .stacking import execute_stacks
from .staging import StagingStore
from .svc_base import (
    CONFIRM_TRASH,
    ActionError,
)
from .timefix import execute_shifts

log = logging.getLogger(__name__)


class StagedMixin:
    # -------------------------------------------------------------- Vormerken
    @property
    def staging(self) -> StagingStore:
        return self._staging

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
            raise ActionError("Dieser Eintrag betrifft ganze Alben oder Personen, keine einzelnen Medien")
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
                    elif e["typ"] == "personen":
                        res = self._merge_people(e["daten"])
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
                         "archiv": lambda r: r["archiviert"],
                         "personen": lambda r: r["zusammengefuehrt"]}[e["typ"]](res)
                self._record(e["typ"], e["titel"], count, res, "oberflaeche")
                results.append({"id": e["id"], "titel": e["titel"], "ergebnis": res})
            self.staging.remove(done)
            self._save()
            log.info("Vorgemerktes übertragen: %d von %d Einträgen", len(done), len(entries))
            return {"uebertragen": len(done), "fehler": len(entries) - len(done), "eintraege": results}
