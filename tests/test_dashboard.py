"""Übersicht, Papierkorb und Wochenbericht."""

from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from immich_pflege.config import Settings
from immich_pflege.report import Reporter, build_text
from immich_pflege.service import Pflege
from immich_pflege.web.app import create_app


@pytest.fixture
def sent():
    return []


@pytest.fixture
def ext(sent):
    def handler(request: httpx.Request):
        sent.append((str(request.url), request.headers.get("Title"), request.content.decode()))
        return httpx.Response(200, json={"ok": True})
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def web(env, http, ext):
    with TestClient(create_app(env, http=http, ext_http=ext, auto_scan_enabled=False)) as c:
        yield c


def test_dashboard_numbers(web):
    d = web.get("/api/dashboard").json()
    assert d["gesamt"]["medien"] == 12 and set(d["benutzer"]) == {"frank", "julia"}
    assert d["benutzer"]["frank"]["extern"] == 2
    assert d["offen"]["duplikate"] == 3 and d["offen"]["ort_vorschlaege"] >= 1
    assert [y["jahr"] for y in d["jahre"]] == ["2024"]
    assert d["bericht"]["kanal"] == "aus" and d["erledigt"] == []
    web.post("/api/no-location/apply", json={"min_confidence": "hoch"})
    assert web.get("/api/dashboard").json()["erledigt"][0]["ort"] >= 1


def test_trash_view_and_restore(web, state):
    t = web.get("/api/trash").json()
    assert t["tage"] == 30 and t["anzahl"] == 1 and t["benutzer"]["frank"]["anzahl"] == 1
    gid = next(g["id"] for g in web.get("/api/duplicates").json()["gruppen"] if g["art"] == "sehr_wahrscheinlich")
    web.post("/api/duplicates/apply", json={"action": "papierkorb", "groups": [{"id": gid}], "confirm": "PAPIERKORB"})
    t = web.get("/api/trash").json()
    assert t["anzahl"] == 2
    ours = [m for m in t["medien"] if "verschoben" in m]
    assert len(ours) == 1 and ours[0]["endgueltig"] > ours[0]["verschoben"]
    r = web.post("/api/trash/restore", json={"ids": [ours[0]["id"]]}).json()
    assert r["wiederhergestellt"] == 1 and web.get("/api/trash").json()["anzahl"] == 1
    assert web.post("/api/trash/restore", json={}).json()["wiederhergestellt"] == 1
    assert not any(a["isTrashed"] for a in state.assets.values())


def test_report_text_and_test_message(web, sent):
    assert web.post("/api/report/test").status_code == 502  # ausgeschaltet
    web.put("/api/settings", json={"report_channel": "ntfy", "report_ntfy_url": "https://ntfy.example.org/pflege"})
    r = web.post("/api/report/test").json()
    assert r["gesendet"] and "Duplikat-Gruppen offen" in r["text"]
    assert sent[0][0] == "https://ntfy.example.org/pflege" and sent[0][1] == "Immich-Pflege: Wochenbericht"
    web.put("/api/settings", json={"report_channel": "telegram", "report_telegram_chat": "123"})
    assert web.post("/api/report/test").status_code == 502  # Token fehlt
    web.put("/api/settings", json={"report_telegram_token": "abc:def"})
    web.post("/api/report/test")
    assert sent[-1][0] == "https://api.telegram.org/botabc:def/sendMessage"
    s = web.get("/api/settings").json()
    assert s["report_telegram_token_gesetzt"] and "abc:def" not in str(s)


def test_weekly_schedule(env, http, ext, sent):
    svc = Pflege(Settings.load({**env, "REPORT_CHANNEL": "ntfy", "REPORT_NTFY_URL": "https://n.example/x",
                                "REPORT_DAY": "Mo", "REPORT_TIME": "08:00"}), http=http)
    svc.library()
    clock = {"now": datetime(2026, 10, 26, 6, 30, tzinfo=timezone.utc)}  # Mo 07:30 Berlin (Winterzeit)
    rep = Reporter(lambda: svc, http=ext, now=lambda: clock["now"])
    assert rep.tick() is False  # noch nicht 8 Uhr
    clock["now"] = datetime(2026, 10, 26, 7, 5, tzinfo=timezone.utc)  # 08:05
    assert rep.tick() is True and len(sent) == 1
    clock["now"] = datetime(2026, 10, 28, 7, 5, tzinfo=timezone.utc)
    assert rep.tick() is False  # diese Woche schon gesendet
    assert rep.info()["naechster"].startswith("2026-11-02T07:00")


def test_build_text_all_done():
    d = {"gesamt": {"medien": 5, "groesse": 0}, "offen": {k: 0 for k in (
        "duplikate", "ort_vorschlaege", "ort_sicher", "alben", "aufraeumen", "aufraeumen_groesse", "zeit", "vorgemerkt")}}
    assert "Alles aufgeräumt" in build_text(d)
