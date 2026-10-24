"""Laufende Version und Prüfung auf Updates (wie im paperless-companion).

Die Version kommt aus version.json (beim Docker-Build erzeugt) oder direkt aus dem
.git-Verzeichnis (bei Start aus einem Klon). Bei GitHub wird höchstens einmal pro
Stunde nachgefragt.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .gitinfo import read_file, read_git_version

CHECK_INTERVAL = 3600
REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILES = (Path("/app/version.json"), REPO_ROOT / "version.json")


class Version:
    def __init__(self, repo: str, enabled: bool = True, token: str = "",
                 http: httpx.Client | None = None, files: tuple[Path, ...] = VERSION_FILES,
                 git_root: Path = REPO_ROOT):
        self.repo = repo
        self.enabled = enabled and bool(repo)
        self.token = token
        self._http = http
        self._files = files
        self._git_root = git_root
        self._lock = threading.Lock()
        self._cached: dict[str, Any] = {}
        self._checked_at = 0.0

    def current(self) -> dict:
        for f in self._files:
            try:
                data = json.loads(read_file(f) or "null")
            except json.JSONDecodeError:
                data = None
            if data and data.get("commit"):
                return data
        return read_git_version(self._git_root)

    def _github(self, path: str) -> dict:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "immich-pflege"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        url = f"https://api.github.com/repos/{self.repo}/{path}"
        if self._http is not None:
            response = self._http.get(url, headers=headers, timeout=10)
        else:
            with httpx.Client(timeout=10) as client:
                response = client.get(url, headers=headers)
        if response.status_code == 404:
            raise RuntimeError("Repository oder Branch nicht gefunden (privates Repo? Dann GitHub-Token eintragen)")
        if response.status_code >= 400:
            raise RuntimeError(f"GitHub: HTTP {response.status_code}")
        return response.json()

    def _check(self) -> dict:
        cur = self.current()
        latest = self._github(f"commits/{cur.get('branch') or 'main'}")
        commit_info = latest.get("commit") or {}
        info: dict[str, Any] = {
            "latest": {
                "commit": latest.get("sha"),
                "date": (commit_info.get("committer") or {}).get("date"),
                "message": (commit_info.get("message") or "").split("\n")[0],
            },
            "behind": 0,
            "commits": [],
            # update: GitHub ist weiter · current: gleich oder lokal neuer · unknown: lokaler Stand unbekannt
            "status": "current" if cur.get("commit") == latest.get("sha") else "unknown",
        }
        if cur.get("commit") and cur["commit"] != latest.get("sha"):
            try:
                cmp = self._github(f"compare/{cur['commit']}...{latest['sha']}")
            except RuntimeError:
                info["behind"] = None  # Commit ist GitHub unbekannt (z. B. lokale Änderungen)
            else:
                info["behind"] = cmp.get("ahead_by", 0)
                info["status"] = "update" if cmp.get("status") in ("ahead", "diverged") else "current"
                info["commits"] = [
                    {
                        "commit": c.get("sha"),
                        "date": ((c.get("commit") or {}).get("committer") or {}).get("date"),
                        "message": ((c.get("commit") or {}).get("message") or "").split("\n")[0],
                    }
                    for c in reversed(cmp.get("commits") or [])
                ][:20]
        return info

    def refresh(self, force: bool = False) -> None:
        """Bei GitHub nachfragen (höchstens stündlich, außer force)."""
        if not self.enabled:
            return
        with self._lock:
            if not force and self._checked_at and time.monotonic() - self._checked_at < CHECK_INTERVAL:
                return
            try:
                self._cached = {**self._check(), "error": None}
            except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                self._cached = {**self._cached, "error": str(exc)}
            self._checked_at = time.monotonic()
            self._cached["checked_at"] = datetime.now(timezone.utc).isoformat()

    @property
    def stale(self) -> bool:
        return self.enabled and (not self._checked_at or time.monotonic() - self._checked_at >= CHECK_INTERVAL)

    def get(self) -> dict:
        """Stand für die Oberfläche (ohne GitHub-Anfrage)."""
        return {"current": self.current(), "repo": self.repo, "enabled": self.enabled, **self._cached}

    @property
    def update_available(self) -> bool:
        return self._cached.get("status") == "update" and not self._cached.get("error")
