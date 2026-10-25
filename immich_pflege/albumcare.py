"""Alben aufräumen: doppelte, fast gleiche, leere und Mini-Alben.

- **doppelt:** gleicher Name (Groß-/Kleinschreibung, Leerzeichen egal), z. B. bei beiden Benutzern
  „Toskana 2024“ → zu einem gemeinsamen Album zusammenführen
- **überlappend:** das kleinere Album liegt zu mindestens 90 % im größeren
- **leer** und **mini** (1–2 Medien) → löschen (die Fotos bleiben in Immich)

Zusammenführen: Der Besitzer des Ziel-Albums teilt es bei Bedarf mit dem anderen Benutzer, jeder
legt seine eigenen Medien hinein, danach werden die anderen Alben gelöscht. Rückgängig nimmt die
Medien wieder heraus, hebt die Freigabe auf und legt gelöschte Alben mit Inhalt und Freigaben neu an.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .client import ImmichClient
from .library import Library

OVERLAP = 0.9
MINI_MAX = 2
ARTEN = {"doppelt": "Gleicher Name", "ueberlappend": "Fast gleicher Inhalt", "leer": "Leer", "mini": "Nur 1–2 Medien",
         "titelbild": "Titelbild"}
WRITE_ROLES = ("owner", "editor")


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip().lower()


def _info(al: dict[str, Any], lib: Library) -> dict[str, Any]:
    members = [lib.assets[i] for i in al["medien"] if i in lib.assets]
    step = max(1, len(members) // 6)
    return {"id": al["id"], "name": al["name"], "besitzer": al["besitzer"],
            "geteilt_mit": sorted(u for u, r in al["rollen"].items() if r != "owner"),
            "anzahl": len(al["medien"]), "beispiele": [a.summary() for a in members[::step][:6]]}


def _item(art: str, albums: list[dict[str, Any]], lib: Library, grund: str) -> dict[str, Any]:
    # Ziel: schon geteilt, sonst das größte
    target = max(albums, key=lambda al: (len(al["rollen"]) > 1, len(al["medien"])))
    key = art + ":" + ",".join(sorted(al["id"] for al in albums))
    return {"id": "p" + hashlib.sha1(key.encode()).hexdigest()[:11], "art": art, "art_text": ARTEN[art],
            "grund": grund, "ziel": target["id"], "alben": [_info(al, lib) for al in albums]}


def find_issues(lib: Library) -> list[dict[str, Any]]:
    albums = [al for al in lib.albums.values() if al["besitzer"]]  # nur Alben eingerichteter Benutzer
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    by_name: dict[str, list[dict[str, Any]]] = {}
    for al in albums:
        by_name.setdefault(_norm(al["name"]), []).append(al)
    for group in by_name.values():
        if len(group) > 1 and _norm(group[0]["name"]):
            owners = sorted({al["besitzer"] for al in group})
            items.append(_item("doppelt", group, lib, f"„{group[0]['name']}“ gibt es {len(group)}× ({', '.join(owners)})"))
            seen |= {al["id"] for al in group}
    sets = {al["id"]: set(al["medien"]) for al in albums}
    big = sorted((al for al in albums if len(al["medien"]) > MINI_MAX and al["id"] not in seen),
                 key=lambda al: len(al["medien"]))
    for i, small in enumerate(big):
        if small["id"] in seen:
            continue
        for large in big[i + 1:]:
            if large["id"] in seen:
                continue
            inside = len(sets[small["id"]] & sets[large["id"]])
            if inside >= OVERLAP * len(sets[small["id"]]):
                items.append(_item("ueberlappend", [large, small], lib,
                                   f"{inside} von {len(sets[small['id']])} Medien aus „{small['name']}“ liegen auch in „{large['name']}“"))
                seen |= {small["id"], large["id"]}
                break
    for al in albums:
        if al["id"] in seen:
            continue
        n = len(al["medien"])
        if n == 0:
            items.append(_item("leer", [al], lib, "Album ohne Medien"))
        elif n <= MINI_MAX:
            items.append(_item("mini", [al], lib, f"nur {n} {'Medium' if n == 1 else 'Medien'}"))
    order = {k: i for i, k in enumerate(ARTEN)}
    items.sort(key=lambda it: (order[it["art"]], it["alben"][0]["name"].lower()))
    return items


def plan_merge(lib: Library, album_ids: list[str], target_id: str, delete_rest: bool = True) -> dict[str, Any]:
    target = lib.albums[target_id]
    owner = target["besitzer"]
    sources = [lib.albums[i] for i in album_ids if i != target_id]
    inside = set(target["medien"])
    add: dict[str, list[str]] = {}
    for al in sources:
        for i in al["medien"]:
            a = lib.assets.get(i)
            if a and i not in inside and i not in add.get(a.owner, []):
                add.setdefault(a.owner, []).append(i)
    share = sorted(u for u in add if target["rollen"].get(u) not in WRITE_ROLES and u != owner)
    return {"aktion": "zusammenfuehren", "ziel": target_id, "ziel_name": target["name"], "besitzer": owner,
            "teilen": share, "medien": add, "loeschen": [al["id"] for al in sources] if delete_rest else [],
            "alle_medien": sorted({i for al in sources for i in al["medien"]} | inside)}


def plan_delete(lib: Library, album_ids: list[str]) -> dict[str, Any]:
    return {"aktion": "loeschen", "loeschen": list(album_ids),
            "alle_medien": sorted({i for a in album_ids for i in lib.albums[a]["medien"]})}


def _snapshot(lib: Library, album_id: str) -> dict[str, Any]:
    """Alles, um ein gelöschtes Album wieder anzulegen."""
    al = lib.albums[album_id]
    media: dict[str, list[str]] = {}
    for i in al["medien"]:
        if i in lib.assets:
            media.setdefault(lib.assets[i].owner, []).append(i)
    return {"op": "album_wiederherstellen", "user": al["besitzer"], "name": al["name"],
            "rollen": {u: r for u, r in al["rollen"].items() if r != "owner"}, "medien": media}


def execute_care(lib: Library, clients: dict[str, ImmichClient], plan: dict[str, Any]) -> dict[str, Any]:
    undo: list[dict[str, Any]] = []
    added = 0
    if plan["aktion"] == "titelbild":
        from .covers import execute_cover
        return {"hinzugefuegt": 0, "geloescht": 0, "titelbild": 1, "rueck": execute_cover(lib, clients, plan)}
    if plan["aktion"] == "zusammenfuehren":
        target_id, owner = plan["ziel"], plan["besitzer"]
        target = lib.albums[target_id]
        if plan["teilen"]:
            users = [{"userId": lib.users[u]["id"], "role": "editor"} for u in plan["teilen"]]
            clients[owner].share_album(target_id, users)
            for u in plan["teilen"]:
                target["rollen"][u] = "editor"
            undo += [{"op": "teilen_aufheben", "user": owner, "album": target_id, "nutzer": x["userId"]} for x in users]
        for user, ids in plan["medien"].items():
            ids = [i for i in ids if i in lib.assets and i not in target["medien"]]
            if not ids:
                continue
            new = [r["id"] for r in clients[user].add_to_album(target_id, ids) if r.get("success")]
            if new:
                added += len(new)
                target["medien"] = sorted(set(target["medien"]) | set(new))
                undo.append({"op": "album_entfernen", "user": user, "album": target_id, "ids": new})
    deleted = 0
    for album_id in plan["loeschen"]:
        if album_id not in lib.albums:
            continue
        snap = _snapshot(lib, album_id)
        clients[snap["user"]].delete_album(album_id)
        lib.albums.pop(album_id)
        undo.append(snap)
        deleted += 1
    return {"hinzugefuegt": added, "geloescht": deleted, "rueck": undo}


def restore_album(lib: Library | None, clients: dict[str, ImmichClient], op: dict[str, Any]) -> None:
    """Rückgängig für ein gelöschtes Album: neu anlegen, freigeben, Medien je Besitzer hinein."""
    owner = op["user"]
    ids_by_name = {n: u["id"] for n, u in (lib.users.items() if lib else [])}
    users = [{"userId": ids_by_name[u], "role": r} for u, r in op["rollen"].items() if u in ids_by_name]
    created = clients[owner].create_album(op["name"], users)
    album_id = created["id"]
    members: set[str] = set()
    for user, ids in op["medien"].items():
        if user in clients and ids:
            members |= {r["id"] for r in clients[user].add_to_album(album_id, ids) if r.get("success")}
    if lib is not None:
        lib.albums[album_id] = {"id": album_id, "name": op["name"], "besitzer": owner,
                                "rollen": {owner: "owner", **op["rollen"]}, "anzahl": len(members),
                                "start": None, "ende": None, "medien": sorted(members)}
