"""Anmeldung: signiertes Sitzungs-Cookie für die Oberfläche, Basic Auth für n8n/curl."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from ..config import Settings

log = logging.getLogger(__name__)

COOKIE = "pflege_sitzung"
LONG_S = 90 * 24 * 3600  # „Angemeldet bleiben“
SHORT_S = 12 * 3600  # ohne Häkchen: bis Browser-Ende, höchstens 12 h
RENEW_BELOW_S = 60 * 24 * 3600  # lange Sitzungen bei Benutzung verlängern
MAX_FAILS = 5
LOCK_S = 300


def basic_credentials(header: str | None) -> tuple[str, str] | None:
    if not header or not header.lower().startswith("basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    user, _, password = decoded.partition(":")
    return user, password


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Sessions:
    """Zustandslose Sitzungen: Inhalt im Cookie, mit HMAC signiert.

    Der Schlüssel liegt in DATA_DIR/session.key. Die Signatur hängt zusätzlich am
    aktuellen Login (Benutzer + Passwort-Hash) – ein neues Passwort meldet alle ab.
    """

    def __init__(self, data_dir: Path):
        self.key = self._load_key(data_dir / "session.key")
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _load_key(path: Path) -> bytes:
        try:
            if path.exists():
                key = path.read_bytes()
                if len(key) >= 32:
                    return key
            path.parent.mkdir(parents=True, exist_ok=True)
            key = secrets.token_bytes(32)
            path.write_bytes(key)
            os.chmod(path, 0o600)
            return key
        except OSError as exc:
            log.warning("Sitzungsschlüssel %s nicht speicherbar (%s) – Anmeldungen gelten bis zum Neustart", path, exc)
            return secrets.token_bytes(32)

    @staticmethod
    def _login_id(settings: Settings) -> bytes:
        secret = settings.web_password or settings.web_password_hash or ""
        return hashlib.sha256(f"{settings.web_user}\0{secret}".encode()).digest()

    def _sign(self, payload: str, settings: Settings) -> str:
        return _b64(hmac.new(self.key + self._login_id(settings), payload.encode(), hashlib.sha256).digest())

    def issue(self, settings: Settings, remember: bool) -> tuple[str, int | None]:
        """Cookie-Wert und max_age (None = Sitzungs-Cookie)."""
        lifetime = LONG_S if remember else SHORT_S
        payload = _b64(json.dumps({"u": settings.web_user, "exp": int(time.time()) + lifetime,
                                   "r": remember}).encode())
        return f"{payload}.{self._sign(payload, settings)}", lifetime if remember else None

    def check(self, value: str | None, settings: Settings) -> dict | None:
        if not value or "." not in value:
            return None
        payload, sig = value.rsplit(".", 1)
        if not hmac.compare_digest(sig, self._sign(payload, settings)):
            return None
        try:
            data = json.loads(_unb64(payload))
        except (ValueError, binascii.Error):
            return None
        if data.get("u") != settings.web_user or data.get("exp", 0) < time.time():
            return None
        return data

    # ------------------------------------------------- Schutz vor Raten
    def locked(self, client: str) -> int:
        """Sekunden, die dieser Client noch gesperrt ist (0 = frei)."""
        with self._lock:
            now = time.monotonic()
            fails = [t for t in self._fails.get(client, []) if now - t < LOCK_S]
            self._fails[client] = fails
            if len(fails) >= MAX_FAILS:
                return int(LOCK_S - (now - fails[-MAX_FAILS])) + 1
            return 0

    def failed(self, client: str) -> None:
        with self._lock:
            self._fails.setdefault(client, []).append(time.monotonic())

    def succeeded(self, client: str) -> None:
        with self._lock:
            self._fails.pop(client, None)
