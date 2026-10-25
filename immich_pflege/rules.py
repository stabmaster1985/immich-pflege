"""Regeln für Massen-Tagging aus regeln.yaml einlesen, prüfen und anwenden."""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .client import ImmichClient
from .library import Library
from .models import Asset

log = logging.getLogger(__name__)

BEDINGUNGEN = ("pfad", "dateiname", "von", "bis", "album", "person", "hersteller", "modell",
               "bibliothek", "typ")
ERLAUBT = ("name", "tag", "tags", "benutzer", "aktiv", *BEDINGUNGEN)
SAMPLE = 12


class _Loader(yaml.SafeLoader):
    """SafeLoader ohne automatische Datumserkennung – Daten prüfen wir selbst (bessere Fehler)."""


_Loader.yaml_implicit_resolvers = {
    k: [(tag, rx) for tag, rx in v if tag != "tag:yaml.org,2002:timestamp"]
    for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class RuleError(Exception):
    """Regeldatei fehlt oder ist fehlerhaft. ``errors`` enthält alle gefundenen Probleme."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass
class Rule:
    name: str
    tags: list[str]
    line: int | None = None
    aktiv: bool = True
    benutzer: list[str] | None = None
    pfad: re.Pattern | None = None
    dateiname: re.Pattern | None = None
    von: date | None = None
    bis: date | None = None
    album: list[str] = field(default_factory=list)
    person: list[str] = field(default_factory=list)
    hersteller: str | None = None
    modell: re.Pattern | None = None
    bibliothek: str | None = None  # extern | upload
    typ: str | None = None  # foto | video
    raw: dict[str, Any] = field(default_factory=dict)

    def matches_local(self, a: Asset) -> bool:
        """Alle Bedingungen, die ohne weitere API-Aufrufe prüfbar sind (UND-verknüpft)."""
        if self.benutzer is not None and a.owner not in self.benutzer:
            return False
        if self.pfad and not self.pfad.search(a.path):
            return False
        if self.dateiname and not self.dateiname.search(a.file_name):
            return False
        if self.von or self.bis:
            day = a.local_day
            if day is None or (self.von and day < self.von) or (self.bis and day > self.bis):
                return False
        if self.hersteller and (a.make or "").strip().lower() != self.hersteller.lower():
            return False
        if self.modell and not self.modell.search(a.model or ""):
            return False
        if self.bibliothek == "extern" and not a.is_external:
            return False
        if self.bibliothek == "upload" and a.is_external:
            return False
        if self.typ == "video" and a.type != "VIDEO":
            return False
        if self.typ == "foto" and a.type != "IMAGE":
            return False
        return True

    def describe(self) -> dict[str, Any]:
        return {k: (v.isoformat() if isinstance(v, (date, datetime)) else v)
                for k, v in self.raw.items() if k not in ("name", "tag", "tags", "aktiv")}


# ------------------------------------------------------------------ Einlesen
def _item_lines(text: str) -> list[int]:
    try:
        node = yaml.compose(text, Loader=_Loader)
    except yaml.YAMLError:
        return []
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            if k.value == "regeln":
                node = v
                break
    if isinstance(node, yaml.SequenceNode):
        return [item.start_mark.line + 1 for item in node.value]
    return []


def _compile(value: Any, where: str, key: str, errors: list[str]) -> re.Pattern | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{where}: '{key}' muss ein Text (regulärer Ausdruck) sein")
        return None
    try:
        return re.compile(value, re.IGNORECASE)
    except re.error as exc:
        errors.append(f"{where}: '{key}' ist kein gültiger regulärer Ausdruck ({exc}). "
                      f"Tipp: Punkte als \\. schreiben und in einfache Anführungszeichen setzen.")
        return None


def _date(value: Any, where: str, key: str, errors: list[str]) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    errors.append(f"{where}: '{key}' muss ein Datum im Format JJJJ-MM-TT sein (ist: {value!r})")
    return None


def _str_list(value: Any, where: str, key: str, errors: list[str]) -> list[str]:
    items = value if isinstance(value, list) else [value]
    out = []
    for v in items:
        if not isinstance(v, (str, int)) or str(v).strip() == "":
            errors.append(f"{where}: '{key}' muss ein Text oder eine Liste von Texten sein")
            return []
        out.append(str(v).strip())
    return out


def _tag_name(value: str) -> str:
    return "/".join(p.strip() for p in value.split("/") if p.strip())


def parse_rules(text: str, known_users: list[str] | None = None) -> list[Rule]:
    try:
        data = yaml.load(text, Loader=_Loader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        pos = f"Zeile {mark.line + 1}, Spalte {mark.column + 1}: " if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise RuleError([f"YAML-Syntaxfehler – {pos}{problem}. "
                         f"Häufige Ursache: Einrückung mit Tabs oder fehlendes Leerzeichen nach ':'"])
    if data is None:
        return []
    items = data.get("regeln") if isinstance(data, dict) else data
    if isinstance(data, dict) and "regeln" not in data:
        raise RuleError(["Oberster Schlüssel 'regeln:' fehlt (siehe regeln.example.yaml)"])
    if items is None:
        return []
    if not isinstance(items, list):
        raise RuleError(["'regeln' muss eine Liste sein – jede Regel beginnt mit '- name: …'"])

    lines = _item_lines(text)
    errors: list[str] = []
    rules: list[Rule] = []
    names: set[str] = set()
    for i, item in enumerate(items):
        line = lines[i] if i < len(lines) else None
        label = f"Regel {i + 1}"
        if isinstance(item, dict) and item.get("name"):
            label += f" „{item['name']}“"
        where = f"{label} (Zeile {line})" if line else label
        if not isinstance(item, dict):
            errors.append(f"{where}: Eine Regel muss aus Schlüssel: Wert-Paaren bestehen")
            continue
        n_err = len(errors)
        for key in item:
            if key not in ERLAUBT:
                hint = difflib.get_close_matches(str(key), ERLAUBT, n=1)
                tip = f" – meintest du '{hint[0]}'?" if hint else f" (erlaubt: {', '.join(ERLAUBT)})"
                errors.append(f"{where}: unbekannter Schlüssel '{key}'{tip}")

        name = str(item.get("name") or f"Regel {i + 1}").strip()
        if name in names:
            errors.append(f"{where}: Name '{name}' ist doppelt vergeben")
        names.add(name)

        raw_tags: list[str] = []
        if "tag" in item and "tags" in item:
            errors.append(f"{where}: bitte nur 'tag' oder 'tags' verwenden, nicht beides")
        for key in ("tag", "tags"):
            if key in item:
                raw_tags += _str_list(item[key], where, key, errors)
        tags = [_tag_name(t) for t in raw_tags if _tag_name(t)]
        if not tags:
            errors.append(f"{where}: es fehlt 'tag' (z. B. tag: Reisen/Italien/2024)")

        if not any(k in item for k in BEDINGUNGEN):
            errors.append(f"{where}: mindestens eine Bedingung nötig ({', '.join(BEDINGUNGEN)}), "
                          f"sonst würde die ganze Bibliothek getaggt")

        rule = Rule(name=name, tags=tags, line=line, raw=dict(item))
        aktiv = item.get("aktiv", True)
        if not isinstance(aktiv, bool):
            errors.append(f"{where}: 'aktiv' muss true oder false sein")
        rule.aktiv = aktiv is not False

        if "benutzer" in item:
            users = [u.lower() for u in _str_list(item["benutzer"], where, "benutzer", errors)]
            unknown = [u for u in users if known_users is not None and u not in known_users]
            if unknown:
                errors.append(f"{where}: unbekannte(r) Benutzer {', '.join(unknown)} "
                              f"(konfiguriert: {', '.join(known_users or [])})")
            rule.benutzer = users
        for key in ("pfad", "dateiname", "modell"):
            if key in item:
                setattr(rule, key, _compile(item[key], where, key, errors))
        for key in ("von", "bis"):
            if key in item:
                setattr(rule, key, _date(item[key], where, key, errors))
        if rule.von and rule.bis and rule.von > rule.bis:
            errors.append(f"{where}: 'von' ({rule.von}) liegt nach 'bis' ({rule.bis})")
        for key in ("album", "person"):
            if key in item:
                setattr(rule, key, _str_list(item[key], where, key, errors))
        if "hersteller" in item:
            v = _str_list(item["hersteller"], where, "hersteller", errors)
            if len(v) > 1:
                errors.append(f"{where}: 'hersteller' erwartet genau einen Namen "
                              f"(für mehrere: modell mit Regex oder zwei Regeln)")
            rule.hersteller = v[0] if v else None
        if "bibliothek" in item:
            v = str(item["bibliothek"]).strip().lower()
            if v not in ("extern", "upload"):
                errors.append(f"{where}: 'bibliothek' muss 'extern' oder 'upload' sein (ist: {item['bibliothek']!r})")
            rule.bibliothek = v
        if "typ" in item:
            v = str(item["typ"]).strip().lower()
            if v not in ("foto", "video"):
                errors.append(f"{where}: 'typ' muss 'foto' oder 'video' sein (ist: {item['typ']!r})")
            rule.typ = v
        if len(errors) == n_err:
            rules.append(rule)
    if errors:
        raise RuleError(errors)
    return rules


def load_rules(path: Path, known_users: list[str] | None = None) -> list[Rule]:
    """Fehlende Datei = noch keine Regeln (werden in der Oberfläche angelegt)."""
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuleError([f"Regeldatei {path} nicht lesbar: {exc}"])
    return parse_rules(text, known_users)


EXAMPLE_FILE = Path(__file__).parent / "regeln.example.yaml"
HEADER = ("# Regeln für immich-pflege – am einfachsten in der Oberfläche (Tab Tags) bearbeiten.\n"
          "# Aufbau und alle Bedingungen: siehe regeln.example.yaml im Projekt.\n")
KEY_ORDER = ("name", "tag", "tags", *BEDINGUNGEN, "benutzer", "aktiv")


def rule_to_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalisiert eine Regel für Oberfläche und Speicherung (leere Werte weg, feste Reihenfolge)."""
    item: dict[str, Any] = {}
    tags = raw.get("tags") if raw.get("tags") not in (None, "", []) else raw.get("tag")
    tags = [t for t in (tags if isinstance(tags, list) else [tags]) if t not in (None, "")]
    for key in KEY_ORDER:
        if key in ("tag", "tags"):
            if key == "tag" and len(tags) == 1:
                item["tag"] = str(tags[0])
            elif key == "tags" and len(tags) > 1:
                item["tags"] = [str(t) for t in tags]
            continue
        value = raw.get(key)
        if isinstance(value, list):
            value = [v for v in value if str(v).strip()]
            if len(value) == 1:
                value = value[0]
        if value in (None, "", []):
            continue
        if key == "aktiv":
            if value is True or str(value).lower() == "true":
                continue  # Standard
            value = False if str(value).lower() == "false" else value
        if isinstance(value, (date, datetime)):
            value = value.isoformat()[:10]
        item[key] = value
    for key, value in raw.items():  # Unbekanntes behalten, damit die Prüfung es meldet
        if key not in KEY_ORDER and key not in item:
            item[key] = value
    return item


def dump_rules(items: list[dict[str, Any]]) -> str:
    body = yaml.safe_dump({"regeln": [rule_to_dict(i) for i in items]}, allow_unicode=True,
                          sort_keys=False, default_flow_style=False, width=1000)
    return HEADER + "\n" + body


def read_rules_raw(path: Path) -> tuple[str, list[dict[str, Any]] | None, list[str]]:
    """Text, Regeln als Dicts (None bei Fehlern) und Fehlerliste – für den Editor."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        data = yaml.load(text, Loader=_Loader) if text.strip() else None
    except yaml.YAMLError:
        data = None
    items = data.get("regeln") if isinstance(data, dict) else None
    try:
        parse_rules(text)
    except RuleError as exc:
        return text, items if isinstance(items, list) else None, exc.errors
    return text, [rule_to_dict(i) for i in (items or []) if isinstance(i, dict)], []


def save_rules(path: Path, *, items: list[dict[str, Any]] | None = None, text: str | None = None,
               known_users: list[str] | None = None) -> list[Rule]:
    """Prüft und speichert Regeln (aus Formular oder YAML-Text). Bei Fehlern wird nichts geschrieben."""
    if text is None:
        text = dump_rules(items or [])
    rules = parse_rules(text, known_users)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.with_suffix(".yaml.bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise RuleError([f"Regeldatei {path} nicht speicherbar: {exc}"])
    log.info("Regeldatei %s gespeichert (%d Regeln)", path, len(rules))
    return rules


def example_rules() -> list[dict[str, Any]]:
    data = yaml.load(EXAMPLE_FILE.read_text(encoding="utf-8"), Loader=_Loader)
    return [rule_to_dict({**i, "aktiv": False}) for i in data["regeln"]]


# ------------------------------------------------------------- Auswertung
class Resolver:
    """Löst Album-, Personen- und Tag-Bedingungen per API auf (mit Zwischenspeicher)."""

    def __init__(self, clients: dict[str, ImmichClient]):
        self.clients = clients
        self._albums: dict[str, list[dict]] = {}
        self._tags: dict[str, dict[str, str]] = {}
        self._cache: dict[tuple, set[str]] = {}
        self.warnings: list[str] = []

    def _warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)

    def album_assets(self, user: str, name: str) -> set[str]:
        key = ("album", user, name.lower())
        if key not in self._cache:
            client = self.clients[user]
            if user not in self._albums:
                self._albums[user] = client.albums()
            ids = [a["id"] for a in self._albums[user] if a.get("albumName", "").lower() == name.lower()]
            if not ids:
                self._warn(f"Album „{name}“ bei {user} nicht gefunden")
            found: set[str] = set()
            for aid in ids:
                found |= client.search_ids(albumIds=[aid])
            self._cache[key] = found
        return self._cache[key]

    def person_assets(self, user: str, name: str) -> set[str]:
        key = ("person", user, name.lower())
        if key not in self._cache:
            client = self.clients[user]
            people = [p for p in client.search_person(name)
                      if (p.get("name") or "").strip().lower() == name.lower()]
            if not people:
                self._warn(f"Person „{name}“ bei {user} nicht gefunden (Name muss exakt passen)")
            found: set[str] = set()
            for p in people:
                found |= client.search_ids(personIds=[p["id"]])
            self._cache[key] = found
        return self._cache[key]

    def tag_id(self, user: str, value: str) -> str | None:
        if user not in self._tags:
            self._tags[user] = {t["value"]: t["id"] for t in self.clients[user].tags()}
        return self._tags[user].get(value)

    def tagged_assets(self, user: str, value: str) -> set[str]:
        tid = self.tag_id(user, value)
        if not tid:
            return set()
        key = ("tag", user, tid)
        if key not in self._cache:
            self._cache[key] = self.clients[user].search_ids(tagIds=[tid])
        return self._cache[key]

    def forget_tags(self, user: str) -> None:
        self._tags.pop(user, None)
        self._cache = {k: v for k, v in self._cache.items() if not (k[0] == "tag" and k[1] == user)}


@dataclass
class UserMatch:
    user: str
    matched: list[Asset]
    missing: dict[str, list[str]]  # Tag -> Asset-IDs ohne diesen Tag

    @property
    def new_ids(self) -> set[str]:
        return {i for ids in self.missing.values() for i in ids}


def evaluate_rule(rule: Rule, lib: Library, resolver: Resolver) -> list[UserMatch]:
    users = rule.benutzer if rule.benutzer is not None else list(resolver.clients)
    out = []
    for user in users:
        if user not in resolver.clients:
            continue
        matched = [a for a in lib.assets.values() if a.owner == user and rule.matches_local(a)]
        for name in rule.album:
            if matched:
                ids = resolver.album_assets(user, name)
                matched = [a for a in matched if a.id in ids]
        for name in rule.person:
            if matched:
                ids = resolver.person_assets(user, name)
                matched = [a for a in matched if a.id in ids]
        missing = {}
        for tag in rule.tags:
            tagged = resolver.tagged_assets(user, tag) if matched else set()
            missing[tag] = [a.id for a in matched if a.id not in tagged]
        out.append(UserMatch(user, matched, missing))
    return out


def preview(rules: list[Rule], lib: Library, resolver: Resolver) -> list[dict[str, Any]]:
    result = []
    for rule in rules:
        entry: dict[str, Any] = {"name": rule.name, "tags": rule.tags, "aktiv": rule.aktiv,
                                 "zeile": rule.line, "bedingungen": rule.describe()}
        if rule.aktiv:
            matches = evaluate_rule(rule, lib, resolver)
            treffer = sum(len(m.matched) for m in matches)
            neu = sum(len(m.new_ids) for m in matches)
            new_ids = set().union(*(m.new_ids for m in matches)) if matches else set()
            samples = [a.summary() for m in matches for a in m.matched if a.id in new_ids][:SAMPLE]
            entry.update({
                "treffer": treffer,
                "schon_getaggt": treffer - neu,
                "neu": neu,
                "benutzer": {m.user: {"treffer": len(m.matched), "neu": len(m.new_ids)} for m in matches},
                "beispiele": samples,
            })
        result.append(entry)
    return result


def apply(rules: list[Rule], lib: Library, resolver: Resolver) -> list[dict[str, Any]]:
    """Ergänzt fehlende Tags. Entfernt niemals Tags."""
    result = []
    for rule in rules:
        if not rule.aktiv:
            result.append({"name": rule.name, "uebersprungen": "inaktiv"})
            continue
        tagged_total = 0
        per_user = {}
        undo: list[dict[str, Any]] = []
        for m in evaluate_rule(rule, lib, resolver):
            if not m.new_ids:
                per_user[m.user] = 0
                continue
            client = resolver.clients[m.user]
            upserted = client.upsert_tags(list(m.missing))
            ids_by_value = {t.get("value"): t["id"] for t in upserted}
            resolver.forget_tags(m.user)
            for tag, asset_ids in m.missing.items():
                tid = ids_by_value.get(tag) or resolver.tag_id(m.user, tag)
                if not tid:
                    raise RuntimeError(f"Tag „{tag}“ konnte bei {m.user} nicht angelegt werden")
                if asset_ids:
                    client.tag_assets([tid], asset_ids)
                    undo.append({"op": "tag_entfernen", "user": m.user, "tag": tid, "ids": sorted(asset_ids)})
            per_user[m.user] = len(m.new_ids)
            tagged_total += len(m.new_ids)
            log.info("Regel „%s“: %d Medien von %s getaggt (%s)", rule.name, len(m.new_ids), m.user,
                     ", ".join(rule.tags))
            resolver.forget_tags(m.user)
        result.append({"name": rule.name, "tags": rule.tags, "getaggt": tagged_total,
                       "benutzer": per_user, "rueck": undo})
    return result
