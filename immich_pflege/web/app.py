"""FastAPI-Anwendung: JSON-API (auch für n8n), Vorschaubild-Proxy und Oberfläche.

Start: uvicorn immich_pflege.web.app:create_app --factory --host 0.0.0.0 --port 2222
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import threading
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

import httpx
from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..client import ImmichClient
from ..config import ConfigError, Settings, normalize_url, update_settings
from ..logsetup import setup_logging
from ..rules import RuleError, example_rules, read_rules_raw, save_rules
from ..service import ActionError, ImmichError, NotConfigured, Pflege, check_server
from ..version import Version

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
OPEN_PATHS = {"/healthz"}


class ScanRequest(BaseModel):
    wait: bool = True


class GroupSelection(BaseModel):
    id: str
    keep: Optional[str] = None


class DuplicatesApply(BaseModel):
    action: Literal["album", "papierkorb"]
    groups: Optional[list[GroupSelection]] = None
    all: bool = False
    confirm: Optional[str] = None
    dry_run: bool = False


class NoLocationApply(BaseModel):
    ids: list[str] = Field(default_factory=list)
    max_hours: Optional[float] = Field(default=None, gt=0, le=48)


class TagsApply(BaseModel):
    rules: Optional[list[str]] = None


class RulesSave(BaseModel):
    regeln: Optional[list[dict[str, Any]]] = None
    yaml: Optional[str] = None


def _basic_credentials(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    user, _, password = decoded.partition(":")
    return user, password


def create_app(env: Mapping[str, str] | None = None, http: httpx.Client | None = None,
               ext_http: httpx.Client | None = None, version: Version | None = None) -> FastAPI:
    """Parameter nur für Tests: ``env`` (Umgebung), ``http`` (Immich), ``ext_http`` (GitHub/n8n),
    ``version`` (Versionsquelle)."""
    first = Settings.load(env)
    setup_logging(first.log_file)

    app = FastAPI(title="immich-pflege", version=__version__, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.service = Pflege(first, http=http)
    app.state.version = version or Version("", http=ext_http)

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
        if old._lib and new.immich_url == old.settings.immich_url and new.users == old.settings.users:
            fresh._lib = old._lib  # Bibliothek weiterverwenden, wenn sich Immich-Zugang nicht ändert
        app.state.service = fresh
        configure_version(new)
        return new

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        settings = svc().settings
        if settings.auth_enabled and request.url.path not in OPEN_PATHS:
            creds = _basic_credentials(request.headers.get("authorization"))
            if not creds or not settings.check_login(*creds):
                return Response("Anmeldung erforderlich", status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="immich-pflege", charset="UTF-8"'})
        return await call_next(request)

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
        return svc().status(check_server=server)

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

    # ------------------------------------------------------- Einstellungen
    @app.get("/api/settings")
    def get_settings():
        return svc().settings.public()

    @app.put("/api/settings")
    def put_settings(body: dict[str, Any] = Body(...)):
        before = svc().settings
        update_settings(before, body)
        new = reload_settings()
        log.info("Einstellungen gespeichert")
        login_changed = (new.auth_enabled, new.web_user) != (before.auth_enabled, before.web_user) or \
            bool(body.get("web_password"))
        return {**new.public(), "neu_anmelden": login_changed and new.auth_enabled}

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

    # ---------------------------------------------------------- Version/Update
    @app.get("/api/version")
    def api_version():
        v = app.state.version
        if v.stale:  # höchstens stündlich, im Hintergrund – die Antwort wartet nicht auf GitHub
            threading.Thread(target=v.refresh, daemon=True).start()
        settings = svc().settings
        return {**v.get(), "update_available": v.update_available,
                "update_moeglich": bool(settings.update_webhook_url)}

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
                   include_done: bool = True):
        return svc().duplicates_view(offset, limit, include_done)

    @app.post("/api/duplicates/apply")
    def duplicates_apply(body: DuplicatesApply):
        groups = [g.model_dump() for g in body.groups] if body.groups else None
        return svc().apply_duplicates(body.action, groups, body.all, body.confirm, body.dry_run)

    # --------------------------------------------------------- Ohne Ort
    @app.get("/api/no-location")
    def no_location(max_hours: Optional[float] = Query(None, gt=0, le=48),
                    offset: int = Query(0, ge=0), limit: int = Query(30, ge=0, le=5000),
                    only_suggestions: bool = False):
        return svc().no_location_view(max_hours, offset, limit, only_suggestions)

    @app.post("/api/no-location/apply")
    def no_location_apply(body: NoLocationApply):
        return svc().apply_no_location(body.ids, body.max_hours)

    # ------------------------------------------------------------- Tags
    @app.get("/api/tags")
    def tags(rules: Optional[list[str]] = Query(None)):
        return svc().tags_preview(rules)

    @app.post("/api/tags/apply")
    def tags_apply(body: Optional[TagsApply] = None):
        return svc().tags_apply(body.rules if body else None)

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
