"""Automatisches Einlesen der Bibliothek (täglich zu einer Uhrzeit oder alle X Stunden)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from .client import ImmichError
from .config import Settings
from .models import parse_dt

log = logging.getLogger(__name__)

TICK_S = 30
RETRY_AFTER = timedelta(minutes=15)  # nach einem Fehler nicht sofort wieder versuchen


def _daily_slot(settings: Settings, now: datetime) -> datetime:
    """Letzter geplanter Zeitpunkt (heute oder gestern) zur eingestellten Ortszeit, als UTC."""
    tz = ZoneInfo(settings.timezone)
    local_now = now.astimezone(tz)
    hh, mm = (int(x) for x in settings.auto_scan_time.split(":"))
    slot = datetime.combine(local_now.date(), time(hh, mm), tzinfo=tz)
    if slot > local_now:
        slot = datetime.combine(local_now.date() - timedelta(days=1), time(hh, mm), tzinfo=tz)
    return slot.astimezone(timezone.utc)


def due_at(settings: Settings, last_scan: datetime | None, now: datetime) -> datetime | None:
    """Zeitpunkt, ab dem das nächste Einlesen fällig ist (kann in der Vergangenheit liegen)."""
    if settings.auto_scan == "aus" or not settings.configured:
        return None
    if settings.auto_scan == "intervall":
        if last_scan is None:
            return now
        return last_scan + timedelta(hours=settings.auto_scan_hours)
    slot = _daily_slot(settings, now)
    if last_scan is None or last_scan < slot:
        return slot  # heutiger (oder verpasster) Termin steht noch aus
    return slot + timedelta(days=1)


class AutoScan:
    def __init__(self, get_service: Callable, now: Callable[[], datetime] | None = None):
        self._get_service = get_service
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_run: datetime | None = None
        self.last_error: str | None = None
        self._last_attempt: datetime | None = None

    def _last_scan(self) -> datetime | None:
        lib = self._get_service().cached_library()  # liest nie selbst bei Immich ein
        return parse_dt(lib.scanned_at) if lib else None

    def next_run(self) -> datetime | None:
        svc = self._get_service()
        if svc.settings.auto_scan == "aus" or not svc.settings.configured:
            return None
        lib = svc._lib
        last = parse_dt(lib.scanned_at) if lib else None
        now = self._now()
        due = due_at(svc.settings, last, now)
        return max(due, now) if due else None

    def tick(self) -> bool:
        """Einmal prüfen und ggf. einlesen. True, wenn eingelesen wurde."""
        svc = self._get_service()
        settings = svc.settings
        if settings.auto_scan == "aus" or not settings.configured or svc.scanning:
            return False
        now = self._now()
        if self._last_attempt and self.last_error and now - self._last_attempt < RETRY_AFTER:
            return False
        due = due_at(settings, self._last_scan(), now)
        if due is None or due > now:
            return False
        self._last_attempt = now
        log.info("Automatisches Einlesen (%s)", "täglich " + settings.auto_scan_time
                 if settings.auto_scan == "taeglich" else f"alle {settings.auto_scan_hours} h")
        try:
            svc.scan()
        except ImmichError as exc:
            self.last_error = str(exc)
            log.error("Automatisches Einlesen fehlgeschlagen: %s", exc)
            return False
        self.last_error = None
        self.last_run = self._now()
        if settings.auto_stage_locations:
            self._stage_locations(svc)
        return True

    def _stage_locations(self, svc) -> None:
        """Sichere Ortsvorschläge vormerken – übertragen wird erst nach Prüfung in der App."""
        from .service import ActionError

        day = self._now().astimezone(ZoneInfo(svc.settings.timezone)).strftime("%d.%m.%Y")
        try:
            r = svc.stage_no_location(label=f"Automatisch {day}: sichere Orte", min_confidence="hoch")
            log.info("Automatisch %d sichere Orte vorgemerkt", r["vorgemerkt"])
        except ActionError:
            pass  # nichts Neues
        except ImmichError as exc:
            log.warning("Sichere Orte nicht vorgemerkt: %s", exc)

    def info(self) -> dict:
        nxt = self.next_run()
        return {
            "modus": self._get_service().settings.auto_scan,
            "naechstes": nxt.isoformat(timespec="seconds") if nxt else None,
            "letztes": self.last_run.isoformat(timespec="seconds") if self.last_run else None,
            "fehler": self.last_error,
        }

    # ------------------------------------------------------------- Thread
    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="auto-einlesen", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.tick()
            except Exception:  # der Zeitplaner darf nie sterben
                log.exception("Fehler im Zeitplaner")
