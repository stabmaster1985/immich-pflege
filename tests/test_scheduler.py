from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from immich_pflege.config import ConfigError, Settings, update_settings
from immich_pflege.scheduler import AutoScan, due_at
from immich_pflege.service import Pflege
from immich_pflege.web.app import create_app

UTC = timezone.utc


def cfg(**kw) -> Settings:
    base = dict(immich_url="http://immich:2283", users={"frank": "k"}, auto_scan="taeglich",
                auto_scan_time="03:00", timezone="Europe/Berlin")
    return Settings(**{**base, **kw})


def test_daily_uses_local_time_and_dst():
    s = cfg()
    # Sommerzeit: 03:00 Berlin = 01:00 UTC
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    last = datetime(2026, 7, 10, 1, 5, tzinfo=UTC)  # heute schon gelaufen
    assert due_at(s, last, now) == datetime(2026, 7, 11, 1, 0, tzinfo=UTC)
    # Winterzeit: 03:00 Berlin = 02:00 UTC
    now = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)
    last = datetime(2026, 12, 10, 2, 5, tzinfo=UTC)
    assert due_at(s, last, now) == datetime(2026, 12, 11, 2, 0, tzinfo=UTC)


def test_daily_missed_run_is_caught_up():
    s = cfg()
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    last = datetime(2026, 7, 9, 1, 5, tzinfo=UTC)  # gestern, heute 01:00 UTC verpasst
    assert due_at(s, last, now) == datetime(2026, 7, 10, 1, 0, tzinfo=UTC)  # liegt in der Vergangenheit
    # vor 03:00 Ortszeit: gestriger Termin zählt
    early = datetime(2026, 7, 10, 0, 30, tzinfo=UTC)
    assert due_at(s, datetime(2026, 7, 9, 1, 5, tzinfo=UTC), early) == datetime(2026, 7, 10, 1, 0, tzinfo=UTC)
    assert due_at(s, None, now) <= now


def test_interval_and_off():
    s = cfg(auto_scan="intervall", auto_scan_hours=6)
    last = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    assert due_at(s, last, last + timedelta(hours=1)) == datetime(2026, 7, 10, 14, 0, tzinfo=UTC)
    assert due_at(cfg(auto_scan="aus"), last, last) is None
    assert due_at(cfg(users={}), last, last) is None  # nicht eingerichtet


def test_settings_validation(tmp_path):
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    update_settings(s, {"auto_scan": "täglich", "auto_scan_time": "4.30", "auto_scan_hours": "12",
                        "timezone": "Europe/Vienna"})
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    assert (s.auto_scan, s.auto_scan_time, s.auto_scan_hours, s.timezone) == ("taeglich", "04:30", 12, "Europe/Vienna")
    with pytest.raises(ConfigError) as exc:
        update_settings(s, {"auto_scan": "manchmal", "auto_scan_time": "25:00", "auto_scan_hours": 0,
                            "timezone": "Mond/Krater"})
    msg = str(exc.value)
    assert "HH:MM" in msg and "1 und 168" in msg and "Zeitzone" in msg and "intervall" in msg


def test_tick_scans_when_due(settings, http, state):
    svc = Pflege(settings, http=http)
    svc.settings.auto_scan = "intervall"
    svc.settings.auto_scan_hours = 6
    lib = svc.library()  # erstes Einlesen
    scanned = datetime.fromisoformat(lib.scanned_at)
    clock = {"now": scanned + timedelta(hours=1)}
    auto = AutoScan(lambda: svc, now=lambda: clock["now"])
    assert auto.tick() is False
    assert auto.info()["naechstes"].startswith((scanned + timedelta(hours=6)).isoformat()[:16])

    state.add_asset("frank", "NEU.HEIC", "2026-10-25T10:00:00.000Z")
    clock["now"] = scanned + timedelta(hours=7)
    assert auto.tick() is True
    assert any(a.file_name == "NEU.HEIC" for a in svc.library().assets.values())
    assert auto.info()["letztes"] is not None


def test_tick_stages_sure_locations(settings, http, state):
    svc = Pflege(settings, http=http)
    svc.settings.auto_scan = "intervall"
    svc.settings.auto_stage_locations = True
    scanned = datetime.fromisoformat(svc.library().scanned_at)
    auto = AutoScan(lambda: svc, now=lambda: scanned + timedelta(hours=7))
    assert auto.tick() is True
    entries = svc.staging.of_type("ort")
    assert len(entries) == 1 and entries[0]["titel"].startswith("📍 Automatisch")
    assert all(ch["confidence"] == "hoch" for ch in entries[0]["daten"]["aenderungen"])
    assert not [c for c in state.calls if c[0] == "PUT"]  # nur vorgemerkt, nichts an Immich
    auto2 = AutoScan(lambda: svc, now=lambda: scanned + timedelta(hours=20))
    auto2.tick()
    assert len(svc.staging.of_type("ort")) == 1  # nichts Neues -> kein leerer Eintrag


def test_tick_backs_off_after_error(settings):
    import httpx

    def boom(_):
        raise httpx.ConnectError("weg")
    svc = Pflege(settings, http=httpx.Client(transport=httpx.MockTransport(boom)))
    svc.settings.auto_scan = "intervall"
    clock = {"now": datetime(2026, 10, 25, 12, 0, tzinfo=UTC)}
    calls = []
    real_scan = svc.scan
    svc.scan = lambda: (calls.append(1), real_scan())[1]
    auto = AutoScan(lambda: svc, now=lambda: clock["now"])
    assert auto.tick() is False and auto.last_error
    n = len(calls)
    clock["now"] += timedelta(minutes=5)
    auto.tick()
    assert len(calls) == n  # nicht sofort erneut
    clock["now"] += timedelta(minutes=20)
    auto.tick()
    assert len(calls) == n + 1


def test_status_shows_schedule(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        assert c.get("/api/status?server=false").json()["auto_einlesen"]["modus"] == "aus"
        c.put("/api/settings", json={"auto_scan": "taeglich", "auto_scan_time": "03:00"})
        c.post("/api/scan")
        info = c.get("/api/status?server=false").json()["auto_einlesen"]
        assert info["modus"] == "taeglich" and info["naechstes"]
        assert c.get("/api/settings").json()["auto_scan_time"] == "03:00"
