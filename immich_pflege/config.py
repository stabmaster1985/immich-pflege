"""Konfiguration aus Umgebungsvariablen (.env)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

KEY_PREFIX = "IMMICH_KEY_"


class ConfigError(Exception):
    """Fehlerhafte oder unvollständige Konfiguration."""


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    v = value.strip().lower()
    if v in ("1", "true", "ja", "yes", "on"):
        return True
    if v in ("0", "false", "nein", "no", "off"):
        return False
    raise ConfigError(f"Ungültiger Wahrheitswert: {value!r} (erlaubt: true/false, ja/nein, 1/0)")


@dataclass
class Settings:
    immich_url: str
    users: dict[str, str]  # Benutzername -> API-Key
    review_album: str = "Duplikat-Prüfung"
    location_max_hours: float = 2.0
    location_include_external: bool = False
    web_user: str | None = None
    web_password: str | None = None
    data_dir: Path = Path("/data")
    config_dir: Path = Path("/config")
    rules_file: Path = field(default=Path("/config/regeln.yaml"))
    timeout: float = 60.0

    @property
    def api_url(self) -> str:
        return self.immich_url.rstrip("/") + "/api"

    @property
    def cache_file(self) -> Path:
        return self.data_dir / "bibliothek.json"

    @property
    def log_file(self) -> Path:
        return self.data_dir / "pflege.log"

    @property
    def auth_enabled(self) -> bool:
        return bool(self.web_user and self.web_password)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        url = (env.get("IMMICH_URL") or "").strip()
        if not url:
            raise ConfigError("IMMICH_URL fehlt (z. B. http://immich-server:2283)")
        url = re.sub(r"/api/?$", "", url.rstrip("/"))

        users: dict[str, str] = {}
        for key, value in env.items():
            if key.upper().startswith(KEY_PREFIX) and value and value.strip():
                name = key[len(KEY_PREFIX):].strip().lower()
                if name:
                    users[name] = value.strip()
        if not users:
            raise ConfigError(
                "Kein API-Key gefunden. Lege mindestens einen an, z. B. IMMICH_KEY_FRANK=..."
            )

        try:
            hours = float(env.get("LOCATION_MAX_HOURS") or 2)
        except ValueError as exc:
            raise ConfigError("LOCATION_MAX_HOURS muss eine Zahl sein (z. B. 2 oder 1.5)") from exc
        if hours <= 0:
            raise ConfigError("LOCATION_MAX_HOURS muss größer als 0 sein")

        data_dir = Path(env.get("DATA_DIR") or "/data")
        config_dir = Path(env.get("CONFIG_DIR") or "/config")
        rules = Path(env.get("RULES_FILE") or (config_dir / "regeln.yaml"))
        web_user = (env.get("WEB_USER") or "").strip() or None
        web_password = (env.get("WEB_PASSWORD") or "").strip() or None
        if bool(web_user) != bool(web_password):
            raise ConfigError("WEB_USER und WEB_PASSWORD bitte gemeinsam setzen (oder beide leer lassen)")

        return cls(
            immich_url=url,
            users=dict(sorted(users.items())),
            review_album=(env.get("REVIEW_ALBUM") or "Duplikat-Prüfung").strip(),
            location_max_hours=hours,
            location_include_external=_bool(env.get("LOCATION_INCLUDE_EXTERNAL"), False),
            web_user=web_user,
            web_password=web_password,
            data_dir=data_dir,
            config_dir=config_dir,
            rules_file=rules,
            timeout=float(env.get("IMMICH_TIMEOUT") or 60),
        )
