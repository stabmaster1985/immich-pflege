"""Stapeln: aus eigenen Alben, Serienbilder, Serien unter den Duplikaten.

Mixin der Klasse :class:`immich_pflege.service.Pflege` – nutzt deren Zustand (self.library(), self.clients …)."""

from __future__ import annotations

import logging
from typing import Any

from .duplicates import PlannedStep
from .stacking import propose as propose_stacks
from .stacking import whole_album
from .svc_base import (
    ActionError,
)

log = logging.getLogger(__name__)


class StacksMixin:
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

    def stage_burst_stacks(self, ids: list[str], keep: dict[str, str] | None = None,
                           without: dict[str, list[str]] | None = None, drop_action: str = "album") -> dict[str, Any]:
        """Serienbilder aus „Aufräumen“ stapeln statt wegräumen. ``keep``: {Eintrag: Bild oben};
        ``without``: {Eintrag: Bilder, die nicht in den Stapel sollen} – die gehen ins Prüf-Album bzw. in den
        Papierkorb (``drop_action``, externe nie in den Papierkorb). Bleibt nur ein Bild, wird nichts gestapelt."""
        if drop_action not in ("album", "papierkorb"):
            raise ActionError("Aussortierte: album oder papierkorb")
        keep, without = keep or {}, without or {}
        with self._lock:
            chosen = self._cleanup_selection(ids, None)
            stacks, steps, touched = [], [], set()
            for item in chosen:
                if item.kategorie != "serien":
                    raise ActionError("Stapeln geht nur für Serienbilder")
                out = set(without.get(item.id) or [])
                if out - item.ids:
                    raise ActionError(f"Bild gehört nicht zu Eintrag {item.id}")
                members = [a for a in item.assets if a.id not in out]
                if not members:
                    raise ActionError("Mindestens ein Bild muss bleiben")
                top = keep.get(item.id) if keep.get(item.id) in {a.id for a in members} else \
                    next((a.id for a in members if a.id not in item.drop), members[0].id)
                ordered = [a for a in members if a.id == top] + [a for a in members if a.id != top]
                if len(ordered) > 1:
                    stacks.append({"user": ordered[0].owner, "ids": [a.id for a in ordered]})
                for a in item.assets:
                    if a.id in out:
                        act = "album" if drop_action == "papierkorb" and a.is_external and not a.offline else drop_action
                        steps.append(PlannedStep(a, act, "Serienbild aussortiert"))
                touched |= item.ids
            if stacks:
                n = sum(len(s["ids"]) for s in stacks)
                self.staging.add("stapel", f"📚 Serienbilder: {len(stacks)} Stapel aus {n} Medien",
                                 {"stapel": stacks, "album": None, "aus_album": False,
                                  "alle_medien": sorted(touched)},
                                 [{**self.library().assets[s["ids"][0]].summary(), "oben": True} for s in stacks[:8]], n)
            if steps:
                target = "Papierkorb" if drop_action == "papierkorb" else "Prüf-Album"
                self.staging.add("aufraeumen", f"🧹 Serienbilder: {len(steps)} aussortiert → {target}", {
                    "aktion": drop_action, "eintraege": [i.id for i in chosen], "alle_medien": sorted(touched),
                    "schritte": [s.to_dict() for s in steps]}, [{**s.asset.summary(), "aktion": s.action} for s in steps], len(steps))
            if not stacks and not steps:
                raise ActionError("Nichts zu tun – je Serie bleibt nur ein Bild und nichts geht weg")
            return {"vorgemerkt": len(stacks), "medien": sum(len(s["ids"]) for s in stacks), "aussortiert": len(steps)}
