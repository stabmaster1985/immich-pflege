"""Eindeutiges automatisch vormerken.

Mixin der Klasse :class:`immich_pflege.service.Pflege` – nutzt deren Zustand (self.library(), self.clients …)."""

from __future__ import annotations

import logging
from typing import Any

from .duplicates import AKTIONEN, ARTEN, DuplicateGroup, plan_group
from .svc_base import (
    ActionError,
)

log = logging.getLogger(__name__)


class AutoStageMixin:
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
        loc = self.location_counts()
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
