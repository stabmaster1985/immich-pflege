"""Tags: Vorschläge, KI-Suche, eigene Regeln – und Archivieren.

Mixin der Klasse :class:`immich_pflege.service.Pflege` – nutzt deren Zustand (self.library(), self.clients …)."""

from __future__ import annotations

import logging
from typing import Any

from .client import ImmichError
from .library import Library
from .rules import (
    Resolver,
    Rule,
    dump_rules,
    evaluate_rule,
    load_rules,
    parse_rules,
    tag_ids,
)
from .rules import apply as apply_rules
from .rules import preview as preview_rules
from .suggestions import (
    BEGRIFFE,
    SMART_SIZE,
    HiddenList,
    SmartHidden,
    data_suggestions,
    smart_results,
)
from .svc_base import (
    ActionError,
)

log = logging.getLogger(__name__)


class TagsMixin:
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
