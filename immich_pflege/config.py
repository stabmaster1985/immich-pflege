"""Einstellungen: in der Oberfläche gepflegt (DATA_DIR/einstellungen.json), optional per .env.

Rangfolge je Wert: Umgebungsvariable (.env) > gespeicherte Einstellung > Standardwert.
Per Umgebungsvariable gesetzte Werte sind in der Oberfläche gesperrt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

log = logging.getLogger(__name__)

KEY_PREFIX = "IMMICH_KEY_"
DEFAULT_URL = ""  # wird in der Oberfläche eingetragen, z. B. http://192.168.1.20:2283
DEFAULT_REPO = "stabmaster1985/immich-pflege"
REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
USER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SETTINGS_FILE = "einstellungen.json"


class ConfigError(Exception):
    """Fehlerhafte oder unvollständige Konfiguration."""


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return default
    v = str(value).strip().lower()
    if v in ("1", "true", "ja", "yes", "on"):
        return True
    if v in ("0", "false", "nein", "no", "off"):
        return False
    raise ConfigError(f"Ungültiger Wahrheitswert: {value!r} (erlaubt: true/false, ja/nein, 1/0)")


def normalize_url(value: str) -> str:
    url = (value or "").strip().rstrip("/")
    url = re.sub(r"/api$", "", url)
    if not re.match(r"^https?://[^\s/]+", url):
        raise ConfigError(f"Immich-Adresse muss mit http:// oder https:// beginnen (ist: {value!r})")
    return url


def parse_hours(value: Any) -> float:
    try:
        hours = float(str(value).replace(",", "."))
    except ValueError as exc:
        raise ConfigError("Zeitfenster muss eine Zahl sein (z. B. 2 oder 1,5)") from exc
    if not 0 < hours <= 48:
        raise ConfigError("Zeitfenster muss zwischen 0 und 48 Stunden liegen")
    return hours


def parse_repo(value: Any) -> str:
    repo = str(value or "").strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if not REPO_RE.match(repo):
        raise ConfigError(f"GitHub-Repository bitte als besitzer/name angeben (ist: {value!r})")
    return repo


def parse_webhook_url(value: Any) -> str:
    url = str(value or "").strip()
    if not re.match(r"^https?://\S+$", url):
        raise ConfigError(f"Webhook-Adresse muss mit http:// oder https:// beginnen (ist: {value!r})")
    return url


def check_user_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not USER_RE.match(name):
        raise ConfigError(f"Benutzername {name!r} ungültig – erlaubt: a–z, 0–9, - und _ (max. 32 Zeichen)")
    return name


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), digest_hex)


@dataclass
class Settings:
    immich_url: str = DEFAULT_URL
    users: dict[str, str] = field(default_factory=dict)  # Benutzername -> API-Key
    review_album: str = "Duplikat-Prüfung"
    location_max_hours: float = 2.0
    location_include_external: bool = False
    location_skip_screenshots: bool = True
    dup_image_hash: bool = True
    web_user: str | None = None
    web_password: str | None = None  # nur aus .env (Klartext)
    web_password_hash: str | None = None  # aus der Oberfläche
    auto_scan: str = "aus"  # aus | taeglich | intervall
    auto_scan_time: str = "03:00"
    auto_scan_hours: int = 6
    timezone: str = "Europe/Berlin"
    update_check: bool = True
    update_repo: str = DEFAULT_REPO
    update_github_token: str = ""  # nur nötig, solange das Repository privat ist
    update_webhook_url: str = ""  # n8n-Workflow n8n/immich-pflege-update.json
    update_webhook_header: str = "X-Update-Key"
    update_webhook_secret: str = ""
    data_dir: Path = Path("/data")
    rules_file: Path | None = None
    timeout: float = 60.0
    locked: set[str] = field(default_factory=set)  # per .env festgelegte Felder

    def __post_init__(self) -> None:
        if self.rules_file is None:
            self.rules_file = self.data_dir / "regeln.yaml"

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
    def settings_file(self) -> Path:
        return self.data_dir / SETTINGS_FILE

    @property
    def configured(self) -> bool:
        return bool(self.immich_url and self.users)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.web_user and (self.web_password or self.web_password_hash))

    def check_login(self, user: str, password: str) -> bool:
        if not self.auth_enabled:
            return True
        user_ok = hmac.compare_digest(user.encode(), (self.web_user or "").encode())
        if self.web_password:
            pw_ok = hmac.compare_digest(password.encode(), self.web_password.encode())
        else:
            pw_ok = verify_password(password, self.web_password_hash or "")
        return user_ok and pw_ok

    # ----------------------------------------------------------- Laden
    @classmethod
    def load(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        data_dir = Path(env.get("DATA_DIR") or "/data")
        stored = read_stored(data_dir / SETTINGS_FILE)
        locked: set[str] = set()

        def pick(env_key: str, stored_key: str, default: Any, parse=lambda v: v) -> Any:
            raw = env.get(env_key)
            if raw is not None and str(raw).strip() != "":
                locked.add(stored_key)
                return parse(raw)  # Fehler in .env sind echte Fehler
            if stored_key in stored and stored[stored_key] not in (None, ""):
                try:
                    return parse(stored[stored_key])
                except ConfigError as exc:
                    log.warning("Gespeicherte Einstellung %s ungültig (%s) – nutze Standard", stored_key, exc)
            return default

        env_users = {k[len(KEY_PREFIX):].strip().lower(): v.strip()
                     for k, v in env.items()
                     if k.upper().startswith(KEY_PREFIX) and v and v.strip() and k[len(KEY_PREFIX):].strip()}
        if env_users:
            locked.add("users")
            users = env_users
        else:
            users = {str(k).lower(): str(v) for k, v in (stored.get("users") or {}).items() if v}

        web_user = pick("WEB_USER", "web_user", None, lambda v: str(v).strip() or None)
        web_password = (env.get("WEB_PASSWORD") or "").strip() or None
        if web_password:
            locked.add("web_password")
        if "web_user" in locked and not web_password:
            raise ConfigError("WEB_USER ist in .env gesetzt, WEB_PASSWORD fehlt")

        rules = env.get("RULES_FILE")
        update = dict(
            auto_scan=pick("AUTO_SCAN", "auto_scan", "aus", parse_auto_scan),
            auto_scan_time=pick("AUTO_SCAN_TIME", "auto_scan_time", "03:00", parse_time),
            auto_scan_hours=pick("AUTO_SCAN_HOURS", "auto_scan_hours", 6, parse_scan_hours),
            timezone=pick("TZ", "timezone", "Europe/Berlin", parse_timezone),
            update_check=pick("UPDATE_CHECK", "update_check", True, lambda v: _bool(v, True)),
            update_repo=pick("UPDATE_REPO", "update_repo", DEFAULT_REPO, parse_repo),
            update_github_token=pick("UPDATE_GITHUB_TOKEN", "update_github_token", "", lambda v: str(v).strip()),
            update_webhook_url=pick("UPDATE_WEBHOOK_URL", "update_webhook_url", "", parse_webhook_url),
            update_webhook_header=pick("UPDATE_WEBHOOK_HEADER", "update_webhook_header", "X-Update-Key",
                                       lambda v: str(v).strip()),
            update_webhook_secret=pick("UPDATE_WEBHOOK_SECRET", "update_webhook_secret", "",
                                       lambda v: str(v).strip()),
        )
        if "update_webhook_header" not in locked and stored.get("update_webhook_header") == "":
            update["update_webhook_header"] = ""  # bewusst leer = Webhook ohne Authentifizierung
        return cls(
            **update,
            immich_url=pick("IMMICH_URL", "immich_url", DEFAULT_URL, normalize_url),
            users=dict(sorted(users.items())),
            review_album=pick("REVIEW_ALBUM", "review_album", "Duplikat-Prüfung", lambda v: str(v).strip()),
            location_max_hours=pick("LOCATION_MAX_HOURS", "location_max_hours", 2.0, parse_hours),
            dup_image_hash=pick("DUP_IMAGE_HASH", "dup_image_hash", True, lambda v: _bool(v, True)),
            location_skip_screenshots=pick("LOCATION_SKIP_SCREENSHOTS", "location_skip_screenshots", True,
                                           lambda v: _bool(v, True)),
            location_include_external=pick("LOCATION_INCLUDE_EXTERNAL", "location_include_external",
                                           False, lambda v: _bool(v, False)),
            web_user=web_user,
            web_password=web_password,
            web_password_hash=None if web_password else stored.get("web_password_hash"),
            data_dir=data_dir,
            rules_file=Path(rules) if rules else data_dir / "regeln.yaml",
            timeout=float(env.get("IMMICH_TIMEOUT") or 60),
            locked=locked,
        )

    # ------------------------------------------------- für die Oberfläche
    def public(self) -> dict[str, Any]:
        """Einstellungen ohne Geheimnisse (Keys nur maskiert)."""
        return {
            "immich_url": self.immich_url,
            "benutzer": [{"name": n, "key_gesetzt": bool(k), "key_ende": k[-4:] if len(k) > 8 else ""}
                         for n, k in self.users.items()],
            "review_album": self.review_album,
            "location_max_hours": self.location_max_hours,
            "location_include_external": self.location_include_external,
            "location_skip_screenshots": self.location_skip_screenshots,
            "dup_image_hash": self.dup_image_hash,
            "web_user": self.web_user or "",
            "login_aktiv": self.auth_enabled,
            "gesperrt": sorted(self.locked),
            "eingerichtet": self.configured,
            "datenordner": str(self.data_dir),
            "auto_scan": self.auto_scan,
            "auto_scan_time": self.auto_scan_time,
            "auto_scan_hours": self.auto_scan_hours,
            "timezone": self.timezone,
            "update_check": self.update_check,
            "update_repo": self.update_repo,
            "update_github_token_gesetzt": bool(self.update_github_token),
            "update_webhook_url": self.update_webhook_url,
            "update_webhook_header": self.update_webhook_header,
            "update_webhook_secret_gesetzt": bool(self.update_webhook_secret),
        }


def read_stored(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        log.warning("Einstellungsdatei %s unlesbar: %s", path, exc)
        return {}


def update_settings(current: Settings, changes: Mapping[str, Any]) -> dict[str, Any]:
    """Prüft Änderungen aus der Oberfläche und speichert sie. Gibt die neue Speicherung zurück.

    ``changes["benutzer"]``: Liste von {name, key?}. Fehlt ``key``, bleibt der bisherige Key
    (ggf. unter altem Namen ``alt``) erhalten; nicht aufgeführte Benutzer werden entfernt.
    ``changes["web_password"]``: neues Passwort; leer + leerer web_user schaltet den Login ab.
    """
    stored = read_stored(current.settings_file)
    errors: list[str] = []

    def blocked(key: str) -> bool:
        if key in current.locked:
            errors.append(f"'{key}' ist in der .env festgelegt und kann hier nicht geändert werden")
            return True
        return False

    def attempt(key: str, fn) -> None:
        if key in changes and not blocked(key):
            try:
                stored[key] = fn(changes[key])
            except ConfigError as exc:
                errors.append(str(exc))

    attempt("immich_url", normalize_url)
    attempt("review_album", lambda v: _non_empty(v, "Name des Prüf-Albums"))
    attempt("location_max_hours", parse_hours)
    attempt("location_include_external", lambda v: _bool(v, False))
    attempt("location_skip_screenshots", lambda v: _bool(v, True))
    attempt("dup_image_hash", lambda v: _bool(v, True))

    attempt("auto_scan", parse_auto_scan)
    attempt("auto_scan_time", parse_time)
    attempt("auto_scan_hours", parse_scan_hours)
    attempt("timezone", parse_timezone)
    attempt("update_check", lambda v: _bool(v, True))
    attempt("update_repo", parse_repo)
    attempt("update_webhook_url", lambda v: parse_webhook_url(v) if str(v or "").strip() else "")
    attempt("update_webhook_header", lambda v: str(v or "").strip())
    if stored.get("update_webhook_header") == "" and "update_webhook_secret" not in current.locked:
        stored.pop("update_webhook_secret", None)  # ohne Header-Name kein Header-Wert
        changes = {k: v for k, v in changes.items() if k != "update_webhook_secret"}
    for secret in ("update_github_token", "update_webhook_secret"):
        # leer = unverändert, null = löschen
        if secret in changes and not blocked(secret):
            if changes[secret] is None:
                stored.pop(secret, None)
            elif str(changes[secret]).strip():
                stored[secret] = str(changes[secret]).strip()

    if "benutzer" in changes and not blocked("users"):
        old = dict(stored.get("users") or current.users)
        new: dict[str, str] = {}
        for entry in changes["benutzer"] or []:
            try:
                name = check_user_name(entry.get("name", ""))
            except ConfigError as exc:
                errors.append(str(exc))
                continue
            if name in new:
                errors.append(f"Benutzer {name!r} ist doppelt")
                continue
            key = (entry.get("key") or "").strip()
            if not key:
                key = old.get((entry.get("alt") or name).lower(), "")
            if not key:
                errors.append(f"Für {name!r} fehlt der API-Key")
                continue
            new[name] = key
        stored["users"] = new

    if "web_user" in changes or "web_password" in changes:
        if not blocked("web_user") and not blocked("web_password"):
            user = (changes.get("web_user", stored.get("web_user")) or "").strip()
            pw = changes.get("web_password") or ""
            if not user:
                stored.pop("web_user", None)
                stored.pop("web_password_hash", None)
            else:
                if pw:
                    if len(pw) < 6:
                        errors.append("Passwort bitte mit mindestens 6 Zeichen")
                    else:
                        stored["web_password_hash"] = hash_password(pw)
                elif not stored.get("web_password_hash"):
                    errors.append("Für den Login bitte ein Passwort setzen")
                stored["web_user"] = user

    if errors:
        raise ConfigError("\n".join(errors))
    try:
        current.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = current.settings_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(current.settings_file)
    except OSError as exc:
        raise ConfigError(f"Einstellungen nicht speicherbar in {current.data_dir}: {exc} "
                          f"(Rechte des data-Ordners prüfen: chown 1000:1000)") from exc
    return stored


def parse_auto_scan(value: Any) -> str:
    v = str(value or "").strip().lower().replace("ä", "ae")
    if v in ("", "0", "false", "nein", "off"):
        return "aus"
    if v not in ("aus", "taeglich", "intervall"):
        raise ConfigError(f"Automatisch einlesen: 'aus', 'taeglich' oder 'intervall' (ist: {value!r})")
    return v


def parse_time(value: Any) -> str:
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", str(value or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ConfigError(f"Uhrzeit bitte als HH:MM angeben, z. B. 03:00 (ist: {value!r})")
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def parse_scan_hours(value: Any) -> int:
    try:
        hours = int(float(str(value).replace(",", ".")))
    except ValueError as exc:
        raise ConfigError("Intervall muss eine ganze Zahl von Stunden sein") from exc
    if not 1 <= hours <= 168:
        raise ConfigError("Intervall muss zwischen 1 und 168 Stunden liegen")
    return hours


def parse_timezone(value: Any) -> str:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    tz = str(value or "").strip()
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigError(f"Unbekannte Zeitzone {value!r} – z. B. Europe/Berlin") from exc
    return tz


def _non_empty(value: Any, label: str) -> str:
    v = str(value or "").strip()
    if not v:
        raise ConfigError(f"{label} darf nicht leer sein")
    return v
