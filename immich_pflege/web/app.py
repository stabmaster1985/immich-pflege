"""FastAPI-Anwendung: JSON-API (auch für n8n), Vorschaubild-Proxy und Oberfläche.

Start: uvicorn immich_pflege.web.app:create_app --factory --host 0.0.0.0 --port 2222
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
import re
import threading
import time
from pathlib import Path
from urllib.parse import quote
from typing import Any, Literal, Mapping, Optional

import httpx
from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..client import ImmichClient
from ..config import ConfigError, Settings, normalize_url, update_settings
from ..logsetup import setup_logging
from ..rules import RuleError, example_rules, read_rules_raw, save_rules
from ..service import ActionError, ImmichError, NotConfigured, Pflege, check_server
from ..scheduler import AutoScan
from ..updater import BUSY, Updater
from ..version import Version
from .auth import COOKIE, RENEW_BELOW_S, Sessions, basic_credentials

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
HELP = Path(__file__).parent.parent / "hilfe"
HELP_TOPICS = ("duplikate", "ohne-ort", "alben", "tags", "vorgemerkt", "einstellungen")
SLOW_REQUEST_S = 2.0  # langsamere API-Aufrufe landen im Log
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
OPEN_PATHS = {"/healthz", "/login", "/api/login", "/api/logout", "/favicon.ico"}
OPEN_PREFIXES = ("/static/",)


class ScanRequest(BaseModel):
    wait: bool = True


class GroupSelection(BaseModel):
    id: str
    keep: Optional[str] = None


class DuplicatesApply(BaseModel):
    action: Literal["album", "papierkorb"]
    groups: Optional[list[GroupSelection]] = None
    all: bool = False
    art: Optional[Literal["identisch", "sehr_wahrscheinlich", "format", "bearbeitung", "raw_paar", "aehnlich"]] = None
    monat: Optional[str] = None
    benutzeruebergreifend: bool = False
    confirm: Optional[str] = None
    dry_run: bool = False


class Place(BaseModel):
    breite: float = Field(ge=-90, le=90)
    laenge: float = Field(ge=-180, le=180)
    name: Optional[str] = None


class StageDuplicates(BaseModel):
    action: Literal["album", "papierkorb"]
    groups: Optional[list[GroupSelection]] = None
    all: bool = False
    art: Optional[Literal["identisch", "sehr_wahrscheinlich", "format", "bearbeitung", "raw_paar", "aehnlich"]] = None
    monat: Optional[str] = None
    benutzeruebergreifend: bool = False


class StagedApply(BaseModel):
    ids: Optional[list[str]] = None
    confirm: Optional[str] = None


class DuplicatesIgnore(BaseModel):
    groups: list[str]
    undo: bool = False


class NoLocationApply(BaseModel):
    ids: list[str] = Field(default_factory=list)
    series: list[str] = Field(default_factory=list)
    min_confidence: Optional[Literal["niedrig", "mittel", "hoch"]] = None
    place: Optional[Place] = None
    ort: Optional[str] = None
    monat: Optional[str] = None
    label: Optional[str] = None  # nur beim Vormerken: Titel in der Liste
    max_hours: Optional[float] = Field(default=None, gt=0, le=48)


class TagsApply(BaseModel):
    rules: Optional[list[str]] = None


class CleanupStage(BaseModel):
    action: Literal["album", "papierkorb"]
    ids: Optional[list[str]] = None
    kategorie: Optional[str] = None
    keep: Optional[dict[str, str]] = None


class CleanupKeep(BaseModel):
    ids: list[str]
    undo: bool = False


class TripSelection(BaseModel):
    id: str
    album: Optional[str] = None  # weglassen = Vorschlag, null = neues Album, sonst Album-ID
    name: Optional[str] = Field(None, max_length=200)


class AlbumsApply(BaseModel):
    trips: list[TripSelection]


class AlbumsIgnore(BaseModel):
    trips: list[str]
    undo: bool = False


class UpdaterApply(BaseModel):
    bereit: str


class LoginRequest(BaseModel):
    benutzer: str
    passwort: str
    angemeldet_bleiben: bool = True


class RulesSave(BaseModel):
    regeln: Optional[list[dict[str, Any]]] = None
    yaml: Optional[str] = None


def create_app(env: Mapping[str, str] | None = None, http: httpx.Client | None = None,
               ext_http: httpx.Client | None = None, version: Version | None = None,
               auto_scan_enabled: bool = True) -> FastAPI:
    """Parameter nur für Tests: ``env`` (Umgebung), ``http`` (Immich), ``ext_http`` (GitHub/n8n),
    ``version`` (Versionsquelle)."""
    first = Settings.load(env)
    setup_logging(first.log_file)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if auto_scan_enabled:
            app.state.auto_scan.start()
        app.state.service.warm_up_background()  # Zwischenspeicher laden und Tabs vorab berechnen
        yield
        app.state.auto_scan.stop()

    app = FastAPI(title="immich-pflege", version=__version__, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json", lifespan=lifespan)
    # Album-Inhalte nach dem Einlesen im Hintergrund lesen (Tests: PFLEGE_ALBEN_HINTERGRUND=0)
    background_albums = (os.environ if env is None else env).get("PFLEGE_ALBEN_HINTERGRUND", "1") != "0"
    app.state.service = Pflege(first, http=http)
    app.state.service.background_albums = background_albums
    app.state.auto_scan = AutoScan(lambda: app.state.service)
    app.state.version = version or Version("", http=ext_http)
    sessions = Sessions(first.data_dir)

    def configure_version(settings: Settings) -> None:
        v = app.state.version
        v.repo, v.token = settings.update_repo, settings.update_github_token
        v.enabled = settings.update_check and bool(settings.update_repo)

    configure_version(first)
    if not first.configured:
        log.info("Noch nicht eingerichtet – bitte in der Oberfläche unter Einstellungen konfigurieren")

    def svc() -> Pflege:
        return app.state.service

    def reload_settings() -> Settings:
        old = svc()
        new = Settings.load(env)
        fresh = Pflege(new, http=http)
        fresh.background_albums = background_albums
        if old._lib and new.immich_url == old.settings.immich_url and new.users == old.settings.users:
            fresh._lib = old._lib  # Bibliothek weiterverwenden, wenn sich Immich-Zugang nicht ändert
        app.state.service = fresh
        configure_version(new)
        return new

    def set_session_cookie(response: Response, request: Request, settings: Settings, remember: bool) -> None:
        value, max_age = sessions.issue(settings, remember)
        response.set_cookie(COOKIE, value, max_age=max_age, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https", path="/")

    def client_id(request: Request) -> str:
        return request.client.host if request.client else "?"

    @app.middleware("http")
    async def log_slow(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        took = time.monotonic() - started
        if took > SLOW_REQUEST_S and request.url.path.startswith("/api/"):
            log.info("Langsam: %s %s – %.1f s", request.method, request.url.path, took)
        return response

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        settings = svc().settings
        path = request.url.path
        if not settings.auth_enabled or path in OPEN_PATHS or path.startswith(OPEN_PREFIXES):
            return await call_next(request)
        session = sessions.check(request.cookies.get(COOKIE), settings)
        if session:
            response = await call_next(request)
            if session.get("r") and session["exp"] - time.time() < RENEW_BELOW_S:
                set_session_cookie(response, request, settings, True)  # gleitend verlängern
            return response
        # Basic Auth für n8n, curl & Co.
        creds = basic_credentials(request.headers.get("authorization"))
        if creds:
            client = client_id(request)
            if sessions.locked(client):
                return JSONResponse({"fehler": "Zu viele Fehlversuche – bitte kurz warten"}, 429)
            if settings.check_login(*creds):
                sessions.succeeded(client)
                return await call_next(request)
            sessions.failed(client)
        # Oberfläche: zur Anmeldeseite; API: 401 (Basic-Challenge nur für fremde Clients,
        # damit der Browser kein eigenes Anmeldefenster öffnet)
        if request.method == "GET" and "text/html" in request.headers.get("accept", "") \
                and not path.startswith("/api/"):
            target = path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
        headers = {} if request.headers.get("x-requested-with") == "pflege" else \
            {"WWW-Authenticate": 'Basic realm="immich-pflege", charset="UTF-8"'}
        return JSONResponse({"fehler": "Anmeldung erforderlich", "anmeldung": True}, 401, headers=headers)

    @app.exception_handler(ImmichError)
    async def immich_error(_: Request, exc: ImmichError):
        log.error("Immich-Fehler: %s", exc)
        return JSONResponse({"fehler": str(exc)}, status_code=502)

    @app.exception_handler(RuleError)
    async def rule_error(_: Request, exc: RuleError):
        return JSONResponse({"fehler": "Regeln fehlerhaft", "details": exc.errors}, status_code=422)

    @app.exception_handler(NotConfigured)
    async def not_configured(_: Request, exc: NotConfigured):
        return JSONResponse({"fehler": str(exc), "einrichtung": True}, status_code=409)

    @app.exception_handler(ActionError)
    async def action_error(_: Request, exc: ActionError):
        return JSONResponse({"fehler": str(exc)}, status_code=400)

    @app.exception_handler(ConfigError)
    async def config_error(_: Request, exc: ConfigError):
        return JSONResponse({"fehler": "Einstellungen ungültig", "details": str(exc).split("\n")},
                            status_code=422)

    # ------------------------------------------------------------ Basis
    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True, "version": __version__}

    @app.get("/api/status")
    def status(server: bool = True):
        return {**svc().status(check_server=server), "auto_einlesen": app.state.auto_scan.info()}

    @app.post("/api/scan")
    def scan(body: Optional[ScanRequest] = None):
        body = body or ScanRequest()
        service = svc()
        if not body.wait:
            if not service.settings.configured:
                raise NotConfigured()
            if service.scanning:
                return JSONResponse({"gestartet": False, "grund": "Einlesen läuft bereits"}, 409)

            def run():
                try:
                    service.scan()
                except ImmichError as exc:
                    log.error("Einlesen fehlgeschlagen: %s", exc)

            app.state.scan_thread = threading.Thread(target=run, daemon=True)
            app.state.scan_thread.start()
            return JSONResponse({"gestartet": True}, 202)
        lib = service.scan()
        return {"stand": lib.scanned_at, "dauer_s": lib.duration_s, **lib.counts(),
                "warnungen": lib.warnings}

    # ------------------------------------------------------------ Anmeldung
    @app.get("/login", include_in_schema=False)
    def login_page(request: Request):
        settings = svc().settings
        if not settings.auth_enabled or sessions.check(request.cookies.get(COOKIE), settings):
            return RedirectResponse("/", status_code=303)
        return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-cache"})

    @app.post("/api/login")
    async def login(body: LoginRequest, request: Request):
        settings = svc().settings
        if not settings.auth_enabled:
            return {"ok": True}
        client = client_id(request)
        wait = sessions.locked(client)
        if wait:
            return JSONResponse({"fehler": f"Zu viele Fehlversuche – bitte {wait // 60 + 1} Minuten warten"}, 429)
        if not settings.check_login(body.benutzer.strip(), body.passwort):
            sessions.failed(client)
            await asyncio.sleep(1)  # Raten bremsen
            log.warning("Fehlgeschlagene Anmeldung von %s", client)
            return JSONResponse({"fehler": "Benutzername oder Passwort falsch"}, 401)
        sessions.succeeded(client)
        response = JSONResponse({"ok": True})
        set_session_cookie(response, request, settings, body.angemeldet_bleiben)
        log.info("Anmeldung von %s", client)
        return response

    @app.post("/api/logout")
    def logout():
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE, path="/")
        return response

    # ------------------------------------------------------- Einstellungen
    @app.get("/api/settings")
    def get_settings():
        return svc().settings.public()

    @app.put("/api/settings")
    def put_settings(request: Request, body: dict[str, Any] = Body(...)):
        before = svc().settings
        update_settings(before, body)
        new = reload_settings()
        log.info("Einstellungen gespeichert")
        login_changed = (new.auth_enabled, new.web_user) != (before.auth_enabled, before.web_user) or \
            bool(body.get("web_password"))
        response = JSONResponse({**new.public(), "login_geaendert": login_changed and new.auth_enabled})
        if login_changed and new.auth_enabled:
            # Wer den Login gerade selbst gesetzt hat, bleibt angemeldet
            set_session_cookie(response, request, new, True)
        return response

    @app.post("/api/settings/test")
    def test_settings(body: dict[str, Any] = Body(default_factory=dict)):
        current = svc().settings
        url = normalize_url(body["immich_url"]) if body.get("immich_url") else current.immich_url
        if not url:
            raise ActionError("Bitte zuerst die Adresse von Immich eintragen")
        users: dict[str, str] = {}
        if body.get("benutzer") is not None:
            for entry in body["benutzer"]:
                name = (entry.get("name") or "").strip().lower()
                key = (entry.get("key") or "").strip() or current.users.get(
                    (entry.get("alt") or name).lower(), "")
                if name and key:
                    users[name] = key
        else:
            users = dict(current.users)
        if not users:
            raise ActionError("Mindestens einen Benutzer mit API-Key eintragen")
        clients = {n: ImmichClient(url + "/api", k, n, http=http, timeout=15) for n, k in users.items()}
        return {"immich_url": url, **check_server(clients)}

    # ------------------------------------------------- Update-Dienst (Host)
    def updater() -> Updater:
        return Updater(svc().settings.data_dir)

    @app.get("/api/updater")
    def updater_status():
        return updater().status()

    @app.post("/api/updater/prepare")
    def updater_prepare():
        u = updater()
        st = u.status()
        if not st["verfuegbar"]:
            raise ActionError("Update-Dienst auf dem Server ist nicht eingerichtet (updater/install.sh)")
        if st.get("phase") in BUSY:
            raise ActionError("Der Update-Dienst arbeitet gerade – bitte kurz warten")
        u.request("vorbereiten")
        return {**u.status(), "auftrag": "vorbereiten"}

    @app.post("/api/updater/apply")
    def updater_apply(body: UpdaterApply):
        u = updater()
        st = u.status()
        if not st["verfuegbar"]:
            raise ActionError("Update-Dienst auf dem Server ist nicht eingerichtet (updater/install.sh)")
        if st.get("phase") != "bereit" or not st.get("bereit"):
            raise ActionError("Es ist keine Version vorbereitet")
        if body.bereit != st["bereit"]:
            # „letzter Blick“: nur die Version starten, die angezeigt wurde
            raise ActionError("Inzwischen wurde eine andere Version vorbereitet – bitte neu laden und prüfen")
        u.request("umschalten")
        return {**u.status(), "auftrag": "umschalten"}

    # ---------------------------------------------------------- Version/Update
    @app.get("/api/version")
    def api_version():
        v = app.state.version
        if v.stale:  # höchstens stündlich, im Hintergrund – die Antwort wartet nicht auf GitHub
            threading.Thread(target=v.refresh, daemon=True).start()
        settings = svc().settings
        host = Updater(settings.data_dir).status()
        return {**v.get(), "update_available": v.update_available or host.get("phase") == "bereit",
                "update_moeglich": bool(settings.update_webhook_url), "dienst": host}

    @app.post("/api/version/check")
    def api_version_check():
        app.state.version.refresh(force=True)
        return api_version()

    @app.post("/api/version/update")
    def api_version_update():
        settings = svc().settings
        if not settings.update_webhook_url:
            raise ActionError("Kein Update-Webhook eingetragen (Einstellungen → Updates)")
        info = app.state.version.get()
        headers = {}
        if settings.update_webhook_header and settings.update_webhook_secret:
            headers[settings.update_webhook_header] = settings.update_webhook_secret
        payload = {"typ": "update", "von": info["current"].get("commit"),
                   "auf": (info.get("latest") or {}).get("commit")}
        try:
            if ext_http is not None:
                response = ext_http.post(settings.update_webhook_url, json=payload, headers=headers, timeout=20)
            else:
                response = httpx.post(settings.update_webhook_url, json=payload, headers=headers, timeout=20)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.error("Update-Webhook fehlgeschlagen: %s", exc)
            return JSONResponse({"ok": False, "fehler": f"n8n-Webhook nicht erreichbar oder abgelehnt: {exc}"}, 502)
        log.info("Update über n8n angestoßen (von %s)", payload["von"])
        return {"ok": True, "status": response.status_code, "von": payload["von"]}

    # --------------------------------------------------------------- Regeln
    def rules_view() -> dict[str, Any]:
        service = svc()
        text, items, errors = read_rules_raw(service.settings.rules_file)
        return {"datei": str(service.settings.rules_file), "yaml": text, "regeln": items,
                "fehler": errors, "benutzer": list(service.clients)}

    @app.get("/api/rules")
    def get_rules():
        return rules_view()

    @app.put("/api/rules")
    def put_rules(body: RulesSave):
        service = svc()
        if body.yaml is None and body.regeln is None:
            raise ActionError("regeln oder yaml angeben")
        save_rules(service.settings.rules_file, items=body.regeln, text=body.yaml,
                   known_users=list(service.clients) or None)
        return rules_view()

    @app.get("/api/rules/example")
    def rules_example():
        return {"regeln": example_rules()}

    # -------------------------------------------------------- Duplikate
    @app.get("/api/duplicates")
    def duplicates(offset: int = Query(0, ge=0), limit: int = Query(50, ge=0, le=5000),
                   include_done: bool = True,
                   art: Optional[Literal["identisch", "sehr_wahrscheinlich", "format", "bearbeitung", "raw_paar", "aehnlich"]] = None,
                   monat: Optional[str] = None, benutzeruebergreifend: bool = False,
                   ignoriert: bool = False):
        return svc().duplicates_view(offset, limit, include_done, art, monat, benutzeruebergreifend, ignoriert)

    @app.get("/api/fingerprints")
    def fingerprints():
        return svc().hash_status()

    @app.post("/api/fingerprints/start")
    def fingerprints_start():
        service = svc()
        if not service.settings.dup_image_hash:
            raise ActionError("Bild-Fingerabdruck ist in den Einstellungen abgeschaltet")
        started = service.start_hashing()
        return {"gestartet": started, **service.hash_status()}

    @app.post("/api/duplicates/ignore")
    def duplicates_ignore(body: DuplicatesIgnore):
        return svc().ignore_duplicates(body.groups, body.undo)

    @app.post("/api/duplicates/apply")
    def duplicates_apply(body: DuplicatesApply):
        groups = [g.model_dump() for g in body.groups] if body.groups else None
        return svc().apply_duplicates(body.action, groups, body.all, body.confirm, body.dry_run,
                                      body.art, body.monat, body.benutzeruebergreifend)

    # --------------------------------------------------------- Ohne Ort
    @app.get("/api/no-location")
    def no_location(max_hours: Optional[float] = Query(None, gt=0, le=48),
                    offset: int = Query(0, ge=0), limit: int = Query(20, ge=0, le=5000),
                    only_suggestions: bool = False,
                    min_confidence: Optional[Literal["niedrig", "mittel", "hoch"]] = None,
                    ort: Optional[str] = None, monat: Optional[str] = None, overview: bool = False):
        return svc().no_location_view(max_hours, offset, limit, only_suggestions, min_confidence,
                                      ort, monat, overview)

    @app.post("/api/no-location/apply")
    def no_location_apply(body: NoLocationApply):
        return svc().apply_no_location(body.ids, body.max_hours, body.min_confidence, body.series,
                                       body.place.model_dump() if body.place else None, body.ort, body.monat)

    @app.get("/api/places")
    def places(q: str = Query("", max_length=100)):
        return svc().search_places(q)

    # ------------------------------------------------------------- Tags
    @app.get("/api/tags")
    def tags(rules: Optional[list[str]] = Query(None)):
        return svc().tags_preview(rules)

    @app.post("/api/tags/apply")
    def tags_apply(body: Optional[TagsApply] = None):
        return svc().tags_apply(body.rules if body else None)

    # ------------------------------------------------------------- Vormerken
    # ------------------------------------------------------------ Aufräumen
    @app.get("/api/cleanup")
    def cleanup(art: Optional[Literal["speicher", "serien", "qualitaet"]] = None, kategorie: Optional[str] = None,
                ignoriert: bool = False, offset: int = Query(0, ge=0), limit: int = Query(30, ge=0, le=5000)):
        return svc().cleanup_view(art, kategorie, ignoriert, offset, limit)

    @app.post("/api/staged/cleanup")
    def stage_cleanup(body: CleanupStage):
        return svc().stage_cleanup(body.action, body.ids, body.kategorie, body.keep)

    @app.post("/api/cleanup/keep")
    def cleanup_keep(body: CleanupKeep):
        return svc().keep_cleanup(body.ids, body.undo)

    # ---------------------------------------------------------------- Alben
    @app.get("/api/album-suggestions")
    def album_suggestions(status: Optional[Literal["neu", "ergaenzen", "vorhanden"]] = None,
                          ignoriert: bool = False, jahr: Optional[str] = None,
                          offset: int = Query(0, ge=0), limit: int = Query(20, ge=0, le=5000)):
        return svc().albums_view(status, ignoriert, jahr, offset, limit)

    @app.post("/api/album-suggestions/apply")
    def album_suggestions_apply(body: AlbumsApply):
        return svc().apply_albums([t.model_dump(exclude_unset=True) for t in body.trips])

    @app.post("/api/album-suggestions/ignore")
    def album_suggestions_ignore(body: AlbumsIgnore):
        return svc().ignore_albums(body.trips, body.undo)

    @app.post("/api/staged/albums")
    def stage_albums(body: AlbumsApply):
        return svc().stage_albums([t.model_dump(exclude_unset=True) for t in body.trips])

    # -------------------------------------------------------------- Verlauf
    @app.get("/api/history")
    def history(limit: int = Query(50, ge=1, le=500)):
        return svc().history_view(limit)

    @app.post("/api/history/{entry_id}/undo")
    def history_undo(entry_id: str):
        return svc().undo(entry_id)

    @app.get("/api/staged")
    def staged():
        return svc().staged_view()

    @app.post("/api/staged/duplicates")
    def stage_duplicates(body: StageDuplicates):
        groups = [g.model_dump() for g in body.groups] if body.groups else None
        return svc().stage_duplicates(body.action, groups, body.all, body.art, body.monat,
                                      body.benutzeruebergreifend)

    @app.post("/api/staged/no-location")
    def stage_no_location(body: NoLocationApply):
        return svc().stage_no_location(
            label=body.label, ids=body.ids, max_hours=body.max_hours, min_confidence=body.min_confidence,
            series=body.series, place=body.place.model_dump() if body.place else None,
            ort=body.ort, monat=body.monat)

    @app.post("/api/staged/tags")
    def stage_tags(body: TagsApply):
        return svc().stage_tags(body.rules or [])

    @app.delete("/api/staged/{entry_id}")
    def unstage(entry_id: str):
        return svc().unstage([entry_id])

    @app.post("/api/staged/apply")
    def apply_staged(body: Optional[StagedApply] = None):
        body = body or StagedApply()
        return svc().apply_staged(body.ids, body.confirm)

    # ---------------------------------------------------------------- Hilfe
    @app.get("/api/help/{topic}")
    def help_text(topic: str):
        if topic not in HELP_TOPICS:
            return JSONResponse({"fehler": f"Unbekanntes Hilfethema – vorhanden: {', '.join(HELP_TOPICS)}"}, 404)
        return Response((HELP / f"{topic}.md").read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")

    # ------------------------------------------------------ Vorschaubild
    @app.get("/thumb/{asset_id}", include_in_schema=False)
    def thumb(asset_id: str, size: Literal["thumbnail", "preview"] = "thumbnail"):
        if not UUID_RE.match(asset_id):
            return Response("Ungültige ID", status_code=400)
        try:
            data, ctype = svc().thumbnail(asset_id, size)
        except ImmichError as exc:
            return Response(str(exc), status_code=404 if exc.status in (400, 404) else 502)
        return Response(data, media_type=ctype,
                        headers={"Cache-Control": "private, max-age=86400"})

    # -------------------------------------------------------- Oberfläche
    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
