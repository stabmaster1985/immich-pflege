"""Falsche Aufnahmezeit und Kamera-Zeitversatz."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from immich_pflege.timefix import name_date
from immich_pflege.web.app import create_app
from tests.mock_immich import MockState


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def time_state() -> MockState:
    s = MockState()
    s.add_user("frank", "key-frank")
    s.add_user("julia", "key-julia")
    s.ids = {"sony": []}
    t = datetime(2024, 4, 1, 10, 0)
    for day in range(20):  # Handy mit GPS (richtige Zeit) und Sony ohne GPS, deren Uhr 1 h vorgeht
        for k in range(3):
            real = t + timedelta(days=day, hours=2 * k)
            s.add_asset("julia", f"IMG_{day:02d}{k}.HEIC", iso(real), lat=51.6, lon=7.2, city="Oer-Erkenschwick")
            s.ids["sony"].append(s.add_asset("frank", f"DSC{day:02d}{k}.JPG", iso(real + timedelta(hours=1, minutes=3)),
                                              make="SONY", model="ILCE-7M4", library=True))
    s.ids["whatsapp"] = s.add_asset("julia", "IMG-20230815-WA0007.jpg", "2024-01-03T18:00:00.000Z",
                                    make=None, model=None)
    s.ids["1970"] = s.add_asset("frank", "IMG_0001.JPG", "1970-01-01T00:00:00.000Z")
    s.ids["zukunft"] = s.add_asset("frank", "DSCF0001.JPG", "2031-06-01T12:00:00.000Z", make="FUJIFILM", model="X-T5")
    return s


@pytest.fixture
def state():
    return time_state()


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def test_name_date():
    assert name_date("IMG_20190714_123456.jpg") == datetime(2019, 7, 14, 12, 34, 56)
    assert name_date("PXL_20230101_101112345.jpg") == datetime(2023, 1, 1, 10, 11, 12)
    assert name_date("2019-07-14 12.34.56.jpg") == datetime(2019, 7, 14, 12, 34, 56)
    assert name_date("IMG-20240718-WA0003.jpg") == datetime(2024, 7, 18)
    assert name_date("IMG_1234.HEIC") is None and name_date("DSC_99999999.JPG") is None


def test_detects_offset_and_singles(web, state):
    r = web.get("/api/timefix").json()
    assert r["arten"] == {"zeitversatz": 1, "dateiname": 1, "zukunft": 1, "standard": 1}
    cam = r["eintraege"][0]
    assert cam["art"] == "zeitversatz" and cam["minuten"] == -60 and cam["anzahl"] == 60
    assert "SONY ILCE-7M4" in cam["grund"] and "1 h vor" in cam["grund"]
    wa = next(e for e in r["eintraege"] if e["art"] == "dateiname")
    assert wa["medien"][0]["neue_zeit"].startswith("2023-08-15 18:00")
    assert next(e for e in r["eintraege"] if e["art"] == "zukunft")["minuten"] is None
    # in der Liste nur eine Auswahl, für die Großansicht alle
    assert len(cam["medien"]) == 6
    alle = web.get(f"/api/timefix/{cam['id']}/media").json()["medien"]
    assert len(alle) == 60 and all(m["neue_zeit"] for m in alle)
    assert alle == sorted(alle, key=lambda m: m["aufnahme"])
    assert web.get("/api/timefix/zgibtsnicht/media").status_code == 400


def test_stage_apply_and_undo(web, state):
    r = web.get("/api/timefix").json()
    cam = next(e for e in r["eintraege"] if e["art"] == "zeitversatz")
    one = next(e for e in r["eintraege"] if e["art"] == "standard")
    web.post("/api/staged/timefix", json={"eintraege": [{"id": cam["id"]}, {"id": one["id"], "ziel": "1998-05-02T14:30"}]})
    assert web.get("/api/timefix").json()["gesamt"] == 2
    assert not [c for c in state.calls if c[0] == "PUT"]
    assert web.post("/api/staged/apply", json={}).json()["uebertragen"] == 2
    sony = state.assets[state.ids["sony"][0]]
    assert sony["localDateTime"] == "2024-04-01T10:03:00.000Z"
    assert state.assets[state.ids["1970"]]["localDateTime"] == "1998-05-02T14:30:00.000Z"
    after = web.get("/api/timefix").json()
    assert after["arten"]["zeitversatz"] == 0 and after["arten"]["standard"] == 0
    for e in web.get("/api/history").json()["eintraege"]:
        assert e["typ"] == "zeit"
        web.post(f"/api/history/{e['id']}/undo")
    assert state.assets[state.ids["sony"][0]]["localDateTime"] == "2024-04-01T11:03:00.000Z"
    assert web.get("/api/timefix").json()["arten"]["zeitversatz"] == 1


def test_manual_time_needed(web):
    r = web.get("/api/timefix", params={"art": "zukunft"}).json()
    assert web.post("/api/staged/timefix", json={"eintraege": [{"id": r["eintraege"][0]["id"]}]}).status_code == 400


def test_stage_without_some(web, state):
    cam = next(e for e in web.get("/api/timefix").json()["eintraege"] if e["art"] == "zeitversatz")
    alle = [m["id"] for m in web.get(f"/api/timefix/{cam['id']}/media").json()["medien"]]
    web.post("/api/staged/timefix", json={"eintraege": [{"id": cam["id"], "ohne": alle[:10]}]})
    entry = web.get("/api/staged").json()["eintraege"][0]
    assert entry["anzahl"] == 50 and "von 60" in entry["titel"]
    web.post("/api/staged/apply", json={})
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["anzahl"] == 50
