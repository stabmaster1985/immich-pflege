"""Mock eines Immich-v3.2.4-Servers für Tests und lokale Vorführungen.

Bildet nur die Endpunkte nach, die immich-pflege verwendet. Antwortformate folgen der
OpenAPI-Spezifikation v3.2.4 (Vorlage: fixtures/asset_response.json).

Lokal starten (mit Demo-Daten):
    uvicorn tests.mock_immich:demo_app --port 2283
"""

from __future__ import annotations

import base64
import copy
import json
import uuid
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

TEMPLATE = json.loads((Path(__file__).parent / "fixtures" / "asset_response.json").read_text())
_ids = count(1)


def new_id() -> str:
    return str(uuid.UUID(int=next(_ids) * 7919 + (1 << 100), version=4))


@dataclass
class MockState:
    users: dict[str, dict[str, Any]] = field(default_factory=dict)  # key -> user
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)
    albums: dict[str, dict[str, Any]] = field(default_factory=dict)
    tags: dict[str, dict[str, Any]] = field(default_factory=dict)
    people: dict[str, dict[str, Any]] = field(default_factory=dict)
    paging: str = "cursor"  # "cursor" (v3.2) oder "page" (älter)
    version: tuple[int, int, int] = (3, 2, 4)
    calls: list[tuple[str, str, str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------ Aufbau
    def add_user(self, name: str, key: str) -> str:
        uid = new_id()
        self.users[key] = {"id": uid, "name": name.capitalize(), "email": f"{name}@example.org"}
        return uid

    def user_id(self, name: str) -> str:
        for u in self.users.values():
            if u["name"].lower() == name.lower():
                return u["id"]
        raise KeyError(name)

    def add_asset(self, owner: str, file_name: str, local: str | None, *, utc: str | None = None,
                  checksum: str | None = None, library: bool = False, lat: float | None = None,
                  lon: float | None = None, city: str | None = None, country: str | None = None,
                  favorite: bool = False, width: int = 4032, height: int = 3024,
                  make: str | None = "Apple", model: str | None = "iPhone 15 Pro",
                  path: str | None = None, type: str = "IMAGE", visibility: str = "timeline",
                  trashed: bool = False, duplicate_id: str | None = None, size: int = 2_000_000,
                  asset_id: str | None = None) -> str:
        a = copy.deepcopy(TEMPLATE)
        aid = asset_id or new_id()
        uid = self.user_id(owner)
        a.update({
            "id": aid,
            "ownerId": uid,
            "libraryId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" if library else None,
            "type": type,
            "originalFileName": file_name,
            "originalPath": path or (f"/mnt/fotos/{file_name}" if library
                                     else f"/usr/src/app/upload/upload/{uid}/{file_name}"),
            "localDateTime": local,
            "fileCreatedAt": utc or local,
            "isFavorite": favorite,
            "isTrashed": trashed,
            "visibility": visibility,
            "width": width,
            "height": height,
            "checksum": checksum or base64.b64encode(uuid.uuid4().bytes[:15]).decode(),
            "duplicateId": duplicate_id,
        })
        a["exifInfo"].update({
            "latitude": lat, "longitude": lon, "city": city, "country": country,
            "state": None if lat is None else a["exifInfo"]["state"],
            "make": make, "model": model, "exifImageWidth": width, "exifImageHeight": height,
            "fileSizeInByte": size, "dateTimeOriginal": utc or local,
        })
        a["_albums"] = set()
        a["_tags"] = set()
        a["_people"] = set()
        self.assets[aid] = a
        return aid

    def add_album(self, owner: str, name: str, asset_ids: list[str] = ()) -> str:
        alid = new_id()
        self.albums[alid] = {"id": alid, "albumName": name, "ownerId": self.user_id(owner)}
        for aid in asset_ids:
            self.assets[aid]["_albums"].add(alid)
        return alid

    def add_person(self, owner: str, name: str, asset_ids: list[str] = ()) -> str:
        pid = new_id()
        self.people[pid] = {"id": pid, "name": name, "ownerId": self.user_id(owner)}
        for aid in asset_ids:
            self.assets[aid]["_people"].add(pid)
        return pid

    def upsert_tag(self, owner_id: str, value: str) -> dict[str, Any]:
        parent = None
        tag = None
        parts = [p for p in value.split("/") if p]
        for i in range(len(parts)):
            full = "/".join(parts[: i + 1])
            tag = next((t for t in self.tags.values()
                        if t["ownerId"] == owner_id and t["value"] == full), None)
            if tag is None:
                tid = new_id()
                tag = {"id": tid, "name": parts[i], "value": full, "ownerId": owner_id,
                       "parentId": parent, "createdAt": "2024-01-01T00:00:00.000Z",
                       "updatedAt": "2024-01-01T00:00:00.000Z"}
                self.tags[tid] = tag
            parent = tag["id"]
        return tag

    def asset_ids_in_album(self, album_id: str) -> set[str]:
        return {aid for aid, a in self.assets.items() if album_id in a["_albums"]}


def public(asset: dict[str, Any], with_exif: bool = True) -> dict[str, Any]:
    out = {k: v for k, v in asset.items() if not k.startswith("_")}
    if not with_exif:
        out.pop("exifInfo", None)
    return out


def create_app(state: MockState) -> FastAPI:
    app = FastAPI(title="Mock-Immich")
    app.state.mock = state

    def auth(request: Request) -> dict[str, Any]:
        key = request.headers.get("x-api-key")
        user = state.users.get(key or "")
        if not user:
            raise HTTPException(401, "Invalid API key")
        return user

    async def record(request: Request, user: dict[str, Any]) -> Any:
        body = None
        raw = await request.body()
        if raw:
            body = json.loads(raw)
        state.calls.append((request.method, request.url.path, user["name"].lower(), body))
        return body

    def visible(user: dict[str, Any], with_deleted: bool = False):
        for a in state.assets.values():
            if a["ownerId"] != user["id"]:
                continue
            if a["isTrashed"] and not with_deleted:
                continue
            if a["visibility"] == "locked":
                continue
            yield a

    @app.get("/api/server/version")
    async def server_version(request: Request):
        auth(request)
        major, minor, patch = state.version
        return {"major": major, "minor": minor, "patch": patch, "prerelease": None}

    @app.get("/api/users/me")
    async def me(request: Request):
        return auth(request)

    @app.post("/api/search/metadata")
    async def search(request: Request):
        user = auth(request)
        body = await record(request, user) or {}
        size = int(body.get("size", 250))
        if size > 1000:
            return JSONResponse({"message": ["size must not be greater than 1000"]}, 400)
        items = list(visible(user, body.get("withDeleted", False)))
        if body.get("isNotInAlbum"):
            items = [a for a in items if not a["_albums"]]
        if body.get("albumIds"):
            items = [a for a in items if set(body["albumIds"]) <= a["_albums"]]
        if body.get("personIds"):
            items = [a for a in items if set(body["personIds"]) <= a["_people"]]
        if body.get("tagIds"):
            items = [a for a in items if set(body["tagIds"]) <= a["_tags"]]
        items.sort(key=lambda a: (a["fileCreatedAt"] or "", a["id"]), reverse=True)

        if state.paging == "cursor":
            offset = int(base64.b64decode(body["cursor"]).decode()) if body.get("cursor") else 0
        else:
            offset = (int(body.get("page", 1)) - 1) * size
        page_items = items[offset: offset + size]
        more = offset + size < len(items)
        next_cursor = base64.b64encode(str(offset + size).encode()).decode() if more else None
        next_page = str(offset // size + 2) if more else None
        return {
            "albums": {"total": 0, "count": 0, "items": [], "facets": []},
            "assets": {
                "total": len(items),
                "count": len(page_items),
                "items": [public(a, bool(body.get("withExif"))) for a in page_items],
                "facets": [],
                "nextCursor": next_cursor if state.paging == "cursor" else None,
                "nextPage": next_page if state.paging == "page" else None,
            },
        }

    @app.get("/api/search/places")
    async def search_places(request: Request, name: str = ""):
        auth(request)
        places = [
            {"name": "San Gimignano", "admin2name": "Siena", "admin1name": "Toskana",
             "latitude": 43.4677, "longitude": 11.0432},
            {"name": "Siena", "admin2name": "Siena", "admin1name": "Toskana",
             "latitude": 43.3188, "longitude": 11.3308},
            {"name": "Florenz", "admin2name": "Florenz", "admin1name": "Toskana",
             "latitude": 43.7696, "longitude": 11.2558},
        ]
        return [p for p in places if name.lower() in p["name"].lower()]

    @app.get("/api/search/person")
    async def search_person(request: Request, name: str = ""):
        user = auth(request)
        return [p for p in state.people.values()
                if p["ownerId"] == user["id"] and name.lower() in p["name"].lower()]

    @app.get("/api/duplicates")
    async def duplicates(request: Request):
        user = auth(request)
        groups: dict[str, list[dict[str, Any]]] = {}
        for a in visible(user):
            if a["duplicateId"]:
                groups.setdefault(a["duplicateId"], []).append(a)
        out = []
        for did, assets in groups.items():
            if len(assets) < 2:
                continue
            best = max(assets, key=lambda a: a["exifInfo"]["fileSizeInByte"] or 0)
            out.append({"duplicateId": did, "assets": [public(a) for a in assets],
                        "suggestedKeepAssetIds": [best["id"]]})
        return out

    @app.get("/api/albums")
    async def albums(request: Request, isOwned: bool | None = None, assetId: str | None = None):
        user = auth(request)
        out = []
        for al in state.albums.values():
            if al["ownerId"] != user["id"]:
                continue
            if assetId and al["id"] not in state.assets.get(assetId, {}).get("_albums", set()):
                continue
            out.append({**al, "assetCount": len(state.asset_ids_in_album(al["id"])),
                        "shared": False, "albumUsers": [], "hasSharedLink": False,
                        "description": "", "albumThumbnailAssetId": None,
                        "isActivityEnabled": True, "createdAt": "2024-01-01T00:00:00.000Z",
                        "updatedAt": "2024-01-01T00:00:00.000Z"})
        return out

    @app.post("/api/albums", status_code=201)
    async def create_album(request: Request):
        user = auth(request)
        body = await record(request, user)
        alid = new_id()
        state.albums[alid] = {"id": alid, "albumName": body["albumName"], "ownerId": user["id"]}
        return {**state.albums[alid], "assetCount": 0}

    @app.put("/api/albums/{album_id}/assets")
    async def add_album_assets(album_id: str, request: Request):
        user = auth(request)
        body = await record(request, user)
        if len(body["ids"]) > 500:
            return JSONResponse({"message": "Mock: mehr als 500 IDs"}, 400)
        album = state.albums.get(album_id)
        if not album or album["ownerId"] != user["id"]:
            raise HTTPException(400, "Not found or no album.addAsset access")
        out = []
        for aid in body["ids"]:
            a = state.assets.get(aid)
            if a is None or a["ownerId"] != user["id"]:
                out.append({"id": aid, "success": False, "error": "no_permission"})
            elif album_id in a["_albums"]:
                out.append({"id": aid, "success": False, "error": "duplicate"})
            else:
                a["_albums"].add(album_id)
                out.append({"id": aid, "success": True})
        return out

    @app.delete("/api/assets", status_code=204)
    async def delete_assets(request: Request):
        user = auth(request)
        body = await record(request, user)
        if len(body["ids"]) > 500:
            return JSONResponse({"message": "Mock: mehr als 500 IDs"}, 400)
        for aid in body["ids"]:
            a = state.assets.get(aid)
            if a is None or a["ownerId"] != user["id"]:
                raise HTTPException(400, "Not found or no asset.delete access")
            if body.get("force"):
                del state.assets[aid]
            else:
                a["isTrashed"] = True
        return Response(status_code=204)

    @app.put("/api/assets", status_code=204)
    async def update_assets(request: Request):
        user = auth(request)
        body = await record(request, user)
        if len(body["ids"]) > 500:
            return JSONResponse({"message": "Mock: mehr als 500 IDs"}, 400)
        for aid in body["ids"]:
            a = state.assets.get(aid)
            if a is None or a["ownerId"] != user["id"]:
                raise HTTPException(400, "Not found or no asset.update access")
            if "latitude" in body:
                a["exifInfo"]["latitude"] = body["latitude"]
                a["exifInfo"]["longitude"] = body["longitude"]
            if "duplicateId" in body:
                a["duplicateId"] = body["duplicateId"]
        return Response(status_code=204)

    @app.get("/api/assets/{asset_id}/thumbnail")
    async def thumbnail(asset_id: str, request: Request, size: str = "preview"):
        user = auth(request)
        a = state.assets.get(asset_id)
        if a is None or a["ownerId"] != user["id"]:
            raise HTTPException(400, "Not found or no asset.view access")
        hue = int(asset_id[:2], 16) * 360 // 256
        label = a["originalFileName"][:14]
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="250" height="250">'
               f'<rect width="250" height="250" fill="hsl({hue},45%,55%)"/>'
               f'<text x="125" y="130" font-size="20" text-anchor="middle" fill="#fff" '
               f'font-family="sans-serif">{label}</text></svg>')
        return Response(svg, media_type="image/svg+xml")

    @app.get("/api/tags")
    async def tags(request: Request):
        user = auth(request)
        return [t for t in state.tags.values() if t["ownerId"] == user["id"]]

    @app.put("/api/tags")
    async def upsert_tags(request: Request):
        user = auth(request)
        body = await record(request, user)
        return [state.upsert_tag(user["id"], name) for name in body["tags"]]

    @app.put("/api/tags/assets")
    async def tag_assets(request: Request):
        user = auth(request)
        body = await record(request, user)
        if len(body["assetIds"]) > 500:
            return JSONResponse({"message": "Mock: mehr als 500 IDs"}, 400)
        n = 0
        for aid in body["assetIds"]:
            a = state.assets.get(aid)
            if a is None or a["ownerId"] != user["id"]:
                continue
            for tid in body["tagIds"]:
                if tid not in a["_tags"]:
                    a["_tags"].add(tid)
                    n += 1
        return {"count": n}

    return app


# --------------------------------------------------------------------- Demo
def demo_state() -> MockState:
    """Beispiel-Bibliothek: Italien-Urlaub von Frank und Julia plus externe Kamera-Bibliothek."""
    s = MockState()
    s.add_user("frank", "key-frank")
    s.add_user("julia", "key-julia")

    # Gleiches Foto bei beiden Benutzern (per AirDrop geteilt) -> identische Prüfsumme
    shared = s.add_asset("frank", "IMG_0101.HEIC", "2024-07-14T11:12:33.000Z",
                         utc="2024-07-14T09:12:33.000Z", checksum="SAME-0101",
                         lat=43.7696, lon=11.2558, city="Florenz", country="Italien")
    s.add_asset("julia", "IMG_0101.HEIC", "2024-07-14T11:12:33.000Z",
                utc="2024-07-14T09:12:33.000Z", checksum="SAME-0101",
                lat=43.7696, lon=11.2558, city="Florenz", country="Italien", favorite=True)
    # Upload und externe Bibliothek: gleicher Dateiname, gleiche Aufnahmezeit
    s.add_asset("frank", "DSC09812.JPG", "2024-07-15T16:40:00.000Z",
                utc="2024-07-15T14:40:00.000Z", make="SONY", model="ILCE-7M4",
                width=7008, height=4672, size=14_000_000)
    s.add_asset("frank", "DSC09812.JPG", "2024-07-15T16:40:00.000Z",
                utc="2024-07-15T14:40:00.000Z", library=True, make="SONY", model="ILCE-7M4",
                width=7008, height=4672, size=14_000_000, path="/mnt/fotos/2024/Italien/DSC09812.JPG")
    # Von Immich erkannte, ähnliche Bilder (verschiedene Prüfsummen)
    s.add_asset("julia", "IMG_0200.HEIC", "2024-07-16T10:00:00.000Z",
                utc="2024-07-16T08:00:00.000Z", duplicate_id="d0000000-0000-4000-8000-000000000001",
                lat=43.3188, lon=11.3308, city="Siena", country="Italien", size=3_000_000)
    s.add_asset("julia", "IMG_0200 2.JPG", "2024-07-16T10:00:01.000Z",
                utc="2024-07-16T08:00:01.000Z", duplicate_id="d0000000-0000-4000-8000-000000000001",
                width=1920, height=1440, size=800_000)

    # Fotos ohne Ort, zeitlich nahe an Fotos mit GPS
    s.add_asset("julia", "IMG_0300.HEIC", "2024-07-16T12:30:00.000Z",
                utc="2024-07-16T10:30:00.000Z", lat=43.4642, lon=11.0413,
                city="San Gimignano", country="Italien")
    # 5 min, 40 min und 3 h 35 min nach dem GPS-Foto (das letzte liegt außerhalb von ±2 h)
    for i, (local, utc) in enumerate((("12:35", "10:35"), ("13:10", "11:10"), ("16:05", "14:05"))):
        s.add_asset("frank", f"DSC1000{i}.JPG", f"2024-07-16T{local}:00.000Z",
                    utc=f"2024-07-16T{utc}:00.000Z", make="SONY", model="ILCE-7M4")
    s.add_asset("frank", "DSC20000.JPG", "2024-07-17T09:00:00.000Z",
                utc="2024-07-17T07:00:00.000Z", library=True, make="SONY", model="ILCE-7M4",
                path="/mnt/fotos/2024/Italien/DSC20000.JPG")
    s.add_asset("julia", "Screenshot 2024-07-20.png", "2024-07-20T20:00:00.000Z",
                make=None, model=None, width=1179, height=2556)
    # Live-Photo-Video (versteckt) und Papierkorb werden ignoriert
    s.add_asset("frank", "IMG_0101.MOV", "2024-07-14T11:12:33.000Z", type="VIDEO",
                visibility="hidden", checksum="LIVE-0101")
    s.add_asset("frank", "alt.jpg", "2020-01-01T00:00:00.000Z", trashed=True)

    s.add_album("frank", "Italien 2024", [shared])
    s.add_person("julia", "Frank", [])
    return s


demo_app = create_app(demo_state())
