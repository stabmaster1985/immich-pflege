"""Personen: unbenannte Gesichter, doppelte Personen, Top-Personen.

Mixin der Klasse :class:`immich_pflege.service.Pflege` – nutzt deren Zustand (self.library(), self.clients …)."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .client import ImmichError
from .svc_base import (
    PEOPLE_PARALLEL,
    ActionError,
)

log = logging.getLogger(__name__)


class PeopleMixin:
    # ------------------------------------------------------------- Personen
    def people_view(self, unnamed_per_user: int = 30, named_per_user: int = 15) -> dict[str, Any]:
        """Unbenannte Personen mit den meisten Fotos (und mit wem sie meist zusammen auf Fotos sind) und
        Personen, die Immich doppelt angelegt hat (gleicher Name beim selben Benutzer). Zwischengespeichert
        bis zum nächsten Einlesen bzw. bis etwas zusammengeführt wurde."""
        lib = self.library()
        key = (lib.uid, lib.rev, len(self.history.entries))
        if self._people_view_cache and self._people_view_cache[0] == key:
            data = self._people_view_cache[1]
        else:
            unnamed, doubles, totals, errors = [], [], {"anzahl_benannt": 0, "anzahl_unbenannt": 0}, []
            for user, client in self.clients.items():
                try:
                    people = client.people()
                except ImmichError as exc:
                    errors.append(f"{user}: {exc}")
                    continue
                named = [p for p in people if (p.get("name") or "").strip()]
                nameless = [p for p in people if not (p.get("name") or "").strip()]
                totals["anzahl_benannt"] += len(named)
                totals["anzahl_unbenannt"] += len(nameless)
                try:
                    # viele kleine Anfragen: parallel statt nacheinander
                    asked = named[:named_per_user] + nameless[:unnamed_per_user]
                    with ThreadPoolExecutor(max_workers=PEOPLE_PARALLEL) as pool:
                        found = dict(zip((p["id"] for p in asked),
                                         pool.map(lambda p: client.search_ids(personIds=[p["id"]]), asked)))
                    named_sets = {p["name"].strip(): found[p["id"]] for p in named[:named_per_user]}
                    for p in nameless[:unnamed_per_user]:
                        ids = found[p["id"]]
                        if not ids:
                            continue
                        best = max(((n, len(ids & s)) for n, s in named_sets.items()), key=lambda x: x[1], default=None)
                        unnamed.append({"id": p["id"], "benutzer": user, "anzahl": len(ids),
                                        "mit": {"name": best[0], "anzahl": best[1]} if best and best[1] else None})
                    groups: dict[str, list[dict[str, Any]]] = {}
                    for p in named:
                        groups.setdefault(re.sub(r"\s+", " ", p["name"]).strip().lower(), []).append(p)
                    for same in groups.values():
                        if len(same) < 2:
                            continue
                        members = sorted(({"id": p["id"], "name": p["name"].strip(),
                                           "anzahl": len(found[p["id"]]) if p["id"] in found else client.person_statistics(p["id"])}
                                          for p in same), key=lambda m: -m["anzahl"])
                        doubles.append({"benutzer": user, "name": members[0]["name"], "personen": members,
                                        "behalten": members[0]["id"]})
                except ImmichError as exc:
                    errors.append(f"{user}: {exc}")
            unnamed.sort(key=lambda u: -u["anzahl"])
            data = {"unbenannt": unnamed, "doppelt": doubles, **totals, "fehler": errors}
            self._people_view_cache = (key, data)
        staged = {i for e in self.staging.of_type("personen") for i in e["daten"]["ids"]}
        return {**data, "doppelt": [d for d in data["doppelt"]
                                    if not {p["id"] for p in d["personen"]} & staged]}

    def person_thumbnail(self, user: str, person_id: str) -> tuple[bytes, str]:
        if user not in self.clients:
            raise ActionError("Unbekannter Benutzer")
        return self.clients[user].person_thumbnail(person_id)

    def stage_people_merge(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Doppelte Personen zum Zusammenführen vormerken: [{benutzer, behalten, ids}] – ids gehen in behalten auf."""
        known = {(d["benutzer"], p["id"]): (d, p) for d in self.people_view()["doppelt"] for p in d["personen"]}
        staged = 0
        for it in items:
            user, keep, ids = it.get("benutzer"), it.get("behalten"), [i for i in it.get("ids") or [] if i != it.get("behalten")]
            if (user, keep) not in known or not ids or any((user, i) not in known for i in ids):
                raise ActionError("Person nicht (mehr) gefunden – bitte neu laden")
            d, p = known[(user, keep)]
            n = sum(known[(user, i)][1]["anzahl"] for i in ids)
            self.staging.add("personen", f"👤 „{p['name']}“ ({user}): {len(ids) + 1} Einträge zu einem zusammenführen",
                             {"benutzer": user, "behalten": keep, "ids": ids, "name": p["name"]}, [], p["anzahl"] + n,
                             key=f"{user}|{keep}")
            staged += 1
        return {"vorgemerkt": staged}

    def _merge_people(self, data: dict[str, Any]) -> dict[str, Any]:
        res = self.clients[data["benutzer"]].merge_people(data["behalten"], data["ids"])
        failed = [r for r in res if not r.get("success")]
        if failed and len(failed) == len(res):
            raise ActionError(f"Zusammenführen abgelehnt: {failed[0].get('error')}")
        self._people_view_cache = None
        self._people_cache = None
        return {"zusammengefuehrt": len(res) - len(failed), "fehler": [r.get("error") for r in failed], "rueck": []}

    def top_people(self, per_user: int = 12) -> list[dict[str, Any]]:
        """Benannte Personen mit den meisten Fotos (Gesichtserkennung), je Name über beide Benutzer.
        Zwischengespeichert bis zum nächsten Einlesen; ohne Recht/Gesichtserkennung leer."""
        lib = self.library()
        key = (lib.uid, lib.rev)
        if self._people_cache and self._people_cache[0] == key:
            return self._people_cache[1]
        names: dict[str, dict[str, Any]] = {}
        for user, client in self.clients.items():
            try:
                named = [p for p in client.people() if (p.get("name") or "").strip() and not p.get("isHidden")][:per_user]
                with ThreadPoolExecutor(max_workers=PEOPLE_PARALLEL) as pool:
                    counts = list(pool.map(lambda p: client.person_statistics(p["id"]), named))
                for p, count in zip(named, counts):
                    n = p["name"].strip()
                    e = names.setdefault(n.lower(), {"name": n, "anzahl": 0, "je_benutzer": {}})
                    e["anzahl"] += count
                    e["je_benutzer"][user] = e["je_benutzer"].get(user, 0) + count
            except ImmichError as exc:
                log.info("Top-Personen für %s nicht verfügbar: %s", user, exc)
        out = sorted(names.values(), key=lambda e: -e["anzahl"])[:10]
        self._people_cache = (key, out)
        return out
