"""FastAPI-Anwendung: JSON-API (auch für n8n), Vorschaubild-Proxy und Oberfläche.

Start: uvicorn immich_pflege.web.app:create_app --factory --host 0.0.0.0 --port 8090
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import secrets
import threading
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Settings
from ..logsetup import setup_logging
from ..rules import RuleError
from ..service import ActionError, ImmichError, Pflege

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


def _check_basic_auth(header: str | None, user: str, password: str) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    given_user, _, given_pw = decoded.partition(":")
    return secrets.compare_digest(given_user.encode(), user.encode()) & secrets.compare_digest(
        given_pw.encode(), password.encode())


def create_app(service: Pflege | None = None) -> FastAPI:
    if service is None:
        settings = Settings.from_env()
        setup_logging(settings.log_file)
        service = Pflege(settings)
    svc = service
    settings = svc.settings

    app = FastAPI(title="immich-pflege", version=__version__, docs_url="/api/docs",
                  redoc_url=None, openapi_url="/api/openapi.json")
    app.state.service = svc

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        if settings.auth_enabled and request.url.path not in OPEN_PATHS:
            if not _check_basic_auth(request.headers.get("authorization"),
                                     settings.web_user or "", settings.web_password or ""):
                return Response("Anmeldung erforderlich", status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="immich-pflege", charset="UTF-8"'})
        return await call_next(request)

    @app.exception_handler(ImmichError)
    async def immich_error(_: Request, exc: ImmichError):
        log.error("Immich-Fehler: %s", exc)
        return JSONResponse({"fehler": str(exc)}, status_code=502)

    @app.exception_handler(RuleError)
    async def rule_error(_: Request, exc: RuleError):
        return JSONResponse({"fehler": "Regeldatei fehlerhaft", "details": exc.errors}, status_code=422)

    @app.exception_handler(ActionError)
    async def action_error(_: Request, exc: ActionError):
        return JSONResponse({"fehler": str(exc)}, status_code=400)

    # ------------------------------------------------------------ Basis
    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"ok": True, "version": __version__}

    @app.get("/api/status")
    def status(server: bool = True):
        return svc.status(check_server=server)

    @app.post("/api/scan")
    def scan(body: Optional[ScanRequest] = None):
        body = body or ScanRequest()
        if not body.wait:
            if svc.scanning:
                return JSONResponse({"gestartet": False, "grund": "Einlesen läuft bereits"}, 409)

            def run():
                try:
                    svc.scan()
                except ImmichError as exc:
                    log.error("Einlesen fehlgeschlagen: %s", exc)

            app.state.scan_thread = threading.Thread(target=run, daemon=True)
            app.state.scan_thread.start()
            return JSONResponse({"gestartet": True}, 202)
        lib = svc.scan()
        return {"stand": lib.scanned_at, "dauer_s": lib.duration_s, **lib.counts(),
                "warnungen": lib.warnings}

    # -------------------------------------------------------- Duplikate
    @app.get("/api/duplicates")
    def duplicates(offset: int = Query(0, ge=0), limit: int = Query(50, ge=0, le=5000),
                   include_done: bool = True):
        return svc.duplicates_view(offset, limit, include_done)

    @app.post("/api/duplicates/apply")
    def duplicates_apply(body: DuplicatesApply):
        groups = [g.model_dump() for g in body.groups] if body.groups else None
        return svc.apply_duplicates(body.action, groups, body.all, body.confirm, body.dry_run)

    # --------------------------------------------------------- Ohne Ort
    @app.get("/api/no-location")
    def no_location(max_hours: Optional[float] = Query(None, gt=0, le=48),
                    offset: int = Query(0, ge=0), limit: int = Query(30, ge=0, le=5000),
                    only_suggestions: bool = False):
        return svc.no_location_view(max_hours, offset, limit, only_suggestions)

    @app.post("/api/no-location/apply")
    def no_location_apply(body: NoLocationApply):
        return svc.apply_no_location(body.ids, body.max_hours)

    # ------------------------------------------------------------- Tags
    @app.get("/api/tags")
    def tags(rules: Optional[list[str]] = Query(None)):
        return svc.tags_preview(rules)

    @app.post("/api/tags/apply")
    def tags_apply(body: Optional[TagsApply] = None):
        return svc.tags_apply(body.rules if body else None)

    # ------------------------------------------------------ Vorschaubild
    @app.get("/thumb/{asset_id}", include_in_schema=False)
    def thumb(asset_id: str, size: Literal["thumbnail", "preview"] = "thumbnail"):
        if not UUID_RE.match(asset_id):
            return Response("Ungültige ID", status_code=400)
        try:
            data, ctype = svc.thumbnail(asset_id, size)
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
