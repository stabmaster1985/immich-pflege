"""Schlanker Immich-API-Client (ein Client pro Benutzer bzw. API-Key)."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Iterator

import httpx

log = logging.getLogger(__name__)

PAGE_SIZE = 1000  # Maximum laut OpenAPI (MetadataSearchDto.size)
CHUNK = 500  # Blockgröße für Bulk-Aufrufe


class ImmichError(Exception):
    """Fehler bei der Kommunikation mit Immich."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def chunked(items: Iterable[str], size: int = CHUNK) -> Iterator[list[str]]:
    batch: list[str] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        msg = data.get("message") if isinstance(data, dict) else None
        if isinstance(msg, list):
            msg = "; ".join(map(str, msg))
        return str(msg or data)
    except ValueError:
        return resp.text[:300]


class ImmichClient:
    def __init__(self, api_url: str, api_key: str, user: str, http: httpx.Client | None = None,
                 timeout: float = 60.0):
        self.api_url = api_url.rstrip("/")
        self.user = user
        self._key = api_key
        self._http = http or httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ Basis
    def request(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                expect_json: bool = True) -> Any:
        url = f"{self.api_url}{path}"
        try:
            resp = self._http.request(method, url, json=json, params=params,
                                      headers={"x-api-key": self._key, "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise ImmichError(f"Immich nicht erreichbar ({self.api_url}): {exc}") from exc
        if resp.status_code == 401:
            raise ImmichError(f"API-Key von '{self.user}' wird abgelehnt (401)", 401)
        if resp.status_code == 403:
            raise ImmichError(
                f"API-Key von '{self.user}' hat keine Berechtigung für {method} {path} (403): "
                f"{_error_text(resp)}", 403)
        if resp.status_code >= 400:
            raise ImmichError(f"{method} {path} fehlgeschlagen ({resp.status_code}): {_error_text(resp)}",
                              resp.status_code)
        if not expect_json or resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # ----------------------------------------------------------------- Server
    def server_version(self) -> dict:
        return self.request("GET", "/server/version")

    def me(self) -> dict:
        return self.request("GET", "/users/me")

    # ------------------------------------------------------------------ Suche
    def search_metadata(self, **filters: Any) -> Iterator[dict]:
        """Alle Treffer von POST /search/metadata, seitenweise.

        Unterstützt sowohl ``nextCursor`` (ab v3.2) als auch das ältere ``nextPage``.
        """
        body: dict[str, Any] = {"size": PAGE_SIZE, **filters}
        seen_tokens: set[str] = set()
        while True:
            data = self.request("POST", "/search/metadata", json=body)
            assets = (data or {}).get("assets") or {}
            yield from assets.get("items") or []
            cursor = assets.get("nextCursor")
            page = assets.get("nextPage")
            body = {k: v for k, v in body.items() if k not in ("cursor", "page")}
            if cursor:
                token = f"c:{cursor}"
                body["cursor"] = cursor
            elif page:
                token = f"p:{page}"
                try:
                    body["page"] = int(page)
                except (TypeError, ValueError) as exc:
                    raise ImmichError(f"Unerwartetes nextPage-Format: {page!r}") from exc
            else:
                return
            if token in seen_tokens:  # Schutz vor Endlosschleifen
                log.warning("Paging von %s wiederholt sich (%s) – breche ab", self.user, token)
                return
            seen_tokens.add(token)

    def search_ids(self, **filters: Any) -> set[str]:
        return {a["id"] for a in self.search_metadata(**filters)}

    def search_places(self, name: str) -> list[dict]:
        return self.request("GET", "/search/places", params={"name": name}) or []

    def search_person(self, name: str) -> list[dict]:
        return self.request("GET", "/search/person", params={"name": name}) or []

    # -------------------------------------------------------------- Duplikate
    def duplicates(self) -> list[dict]:
        return self.request("GET", "/duplicates") or []

    # ----------------------------------------------------------------- Alben
    def albums(self, owned_only: bool = False, asset_id: str | None = None) -> list[dict]:
        params: dict[str, Any] = {}
        if owned_only:
            params["isOwned"] = "true"
        if asset_id:
            params["assetId"] = asset_id
        return self.request("GET", "/albums", params=params or None) or []

    def create_album(self, name: str) -> dict:
        return self.request("POST", "/albums", json={"albumName": name})

    def add_to_album(self, album_id: str, ids: Iterable[str]) -> list[dict]:
        results: list[dict] = []
        for batch in chunked(ids):
            results.extend(self.request("PUT", f"/albums/{album_id}/assets", json={"ids": batch}) or [])
        return results

    # ---------------------------------------------------------------- Assets
    def trash(self, ids: Iterable[str]) -> int:
        n = 0
        for batch in chunked(ids):
            self.request("DELETE", "/assets", json={"ids": batch, "force": False})
            n += len(batch)
        return n

    def set_location(self, ids: Iterable[str], latitude: float, longitude: float) -> int:
        # PUT /assets ist in v3 als "deprecated" markiert, aber (Stand v3.2.4) der einzige
        # Weg, Koordinaten zu setzen. Bei einer späteren Immich-Version hier anpassen.
        n = 0
        for batch in chunked(ids):
            self.request("PUT", "/assets", json={"ids": batch, "latitude": latitude,
                                                  "longitude": longitude})
            n += len(batch)
        return n

    def thumbnail(self, asset_id: str, size: str = "thumbnail") -> tuple[bytes, str]:
        url = f"{self.api_url}/assets/{asset_id}/thumbnail"
        try:
            resp = self._http.get(url, params={"size": size}, headers={"x-api-key": self._key})
        except httpx.HTTPError as exc:
            raise ImmichError(f"Immich nicht erreichbar: {exc}") from exc
        if resp.status_code >= 400:
            raise ImmichError(f"Vorschaubild {asset_id}: HTTP {resp.status_code}", resp.status_code)
        return resp.content, resp.headers.get("content-type", "image/jpeg")

    # ------------------------------------------------------------------ Tags
    def tags(self) -> list[dict]:
        return self.request("GET", "/tags") or []

    def upsert_tags(self, names: list[str]) -> list[dict]:
        return self.request("PUT", "/tags", json={"tags": names}) or []

    def tag_assets(self, tag_ids: list[str], asset_ids: Iterable[str]) -> int:
        n = 0
        for batch in chunked(asset_ids):
            res = self.request("PUT", "/tags/assets", json={"assetIds": batch, "tagIds": tag_ids})
            n += int((res or {}).get("count") or 0)
        return n
