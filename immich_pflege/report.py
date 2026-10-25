"""Wochenbericht ohne n8n: kurze Zusammenfassung per ntfy oder Telegram aufs Handy."""

from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

RETRY = timedelta(hours=1)
DAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


class ReportError(Exception):
    pass


def fmt_gb(b: int) -> str:
    return f"{b / 1073741824:.1f} GB".replace(".", ",") if b >= 1073741824 else f"{b / 1048576:.0f} MB"


def build_text(d: dict[str, Any]) -> str:
    o = d["offen"]
    g = d["gesamt"]
    lines = [f"📷 {g['medien']} Medien ({fmt_gb(g['groesse'])})"]
    if o["duplikate"]:
        lines.append(f"🔁 {o['duplikate']} Duplikat-Gruppen offen")
    if o["ort_vorschlaege"]:
        lines.append(f"📍 {o['ort_vorschlaege']} Fotos verortbar, davon {o['ort_sicher']} sicher")
    if o["alben"]:
        lines.append(f"🧳 {o['alben']} Reisen ohne passendes Album")
    if o["aufraeumen"]:
        lines.append(f"🧹 {o['aufraeumen']} Einträge zum Aufräumen ({fmt_gb(o['aufraeumen_groesse'])})")
    if o["zeit"]:
        lines.append(f"🕑 {o['zeit']} falsche Aufnahmezeiten")
    if o["vorgemerkt"]:
        lines.append(f"✓ {o['vorgemerkt']} vorgemerkt – wartet aufs Übertragen")
    if len(lines) == 1:
        lines.append("Alles aufgeräumt 🎉")
    return "\n".join(lines)


class Reporter:
    def __init__(self, get_service: Callable, http: httpx.Client | None = None,
                 now: Callable[[], datetime] | None = None):
        self._get_service = get_service
        self._http = http
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._last_attempt: datetime | None = None
        self.last_error: str | None = None

    def _state_file(self) -> Path:
        return self._get_service().settings.data_dir / "bericht.json"

    def last_sent(self) -> datetime | None:
        try:
            return datetime.fromisoformat(json.loads(self._state_file().read_text())["gesendet"])
        except (OSError, ValueError, KeyError):
            return None

    def due_at(self, now: datetime) -> datetime:
        """Letzter geplanter Termin (Wochentag + Uhrzeit, Ortszeit) bis ``now``."""
        s = self._get_service().settings
        tz = ZoneInfo(s.timezone)
        local = now.astimezone(tz)
        hh, mm = (int(x) for x in s.report_time.split(":"))
        day = local.date() - timedelta(days=(local.weekday() - s.report_day) % 7)
        slot = datetime.combine(day, time(hh, mm), tz)
        if slot > local:
            slot -= timedelta(days=7)
        return slot.astimezone(timezone.utc)

    def next_run(self) -> datetime | None:
        if self._get_service().settings.report_channel == "aus":
            return None
        return self.due_at(self._now()) + timedelta(days=7)

    def tick(self) -> bool:
        svc = self._get_service()
        if svc.settings.report_channel == "aus" or not svc.settings.configured or svc.cached_library() is None:
            return False
        now = self._now()
        slot = self.due_at(now)
        last = self.last_sent()
        if last and last >= slot:
            return False
        if last is None and now - slot > timedelta(days=1):
            return False  # frisch eingeschaltet: nicht sofort einen alten Termin nachholen
        if self._last_attempt and now - self._last_attempt < RETRY:
            return False
        self._last_attempt = now
        try:
            self.send()
        except ReportError as exc:
            self.last_error = str(exc)
            log.warning("Wochenbericht nicht gesendet: %s", exc)
            return False
        return True

    def send(self, test: bool = False) -> str:
        svc = self._get_service()
        text = build_text(svc.dashboard())
        if test:
            text = "Testnachricht von Immich-Pflege\n" + text
        s = svc.settings
        http = self._http or httpx.Client(timeout=20)
        try:
            if s.report_channel == "ntfy":
                if not s.report_ntfy_url:
                    raise ReportError("ntfy-Adresse fehlt")
                headers = {"Title": "Immich-Pflege: Wochenbericht", "Tags": "camera"}
                if s.report_ntfy_token:
                    headers["Authorization"] = f"Bearer {s.report_ntfy_token}"
                resp = http.post(s.report_ntfy_url, content=text.encode(), headers=headers)
            elif s.report_channel == "telegram":
                if not (s.report_telegram_token and s.report_telegram_chat):
                    raise ReportError("Telegram-Bot-Token oder Chat-ID fehlt")
                resp = http.post(f"https://api.telegram.org/bot{s.report_telegram_token}/sendMessage",
                                 json={"chat_id": s.report_telegram_chat, "text": "Immich-Pflege\n" + text})
            else:
                raise ReportError("Wochenbericht ist ausgeschaltet")
        except httpx.HTTPError as exc:
            raise ReportError(f"nicht erreichbar: {exc}") from exc
        finally:
            if self._http is None:
                http.close()
        if resp.status_code >= 400:
            raise ReportError(f"abgelehnt: HTTP {resp.status_code} {resp.text[:200]}")
        if not test:
            self._state_file().write_text(json.dumps({"gesendet": self._now().isoformat()}))
        self.last_error = None
        log.info("Wochenbericht gesendet (%s)", s.report_channel)
        return text

    def info(self) -> dict[str, Any]:
        s = self._get_service().settings
        nxt = self.next_run()
        last = self.last_sent()
        return {"kanal": s.report_channel, "tag": DAYS[s.report_day], "uhrzeit": s.report_time,
                "naechster": nxt.isoformat(timespec="minutes") if nxt else None,
                "letzter": last.isoformat(timespec="minutes") if last else None, "fehler": self.last_error}
