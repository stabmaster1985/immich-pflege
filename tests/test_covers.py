"""Titelbilder: schlechte erkennen, besseres vorschlagen, setzen und rückgängig."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app
from tests.mock_immich import MockState


def cover_state() -> MockState:
    s = MockState()
    s.add_user("frank", "key-frank")
    s.add_user("julia", "key-julia")
    s.ids = {
        "video": s.add_asset("frank", "IMG_1.MOV", "2024-07-10T10:00:00.000Z", type="VIDEO", duration=5000),
        "weich": s.add_asset("frank", "IMG_2.HEIC", "2024-07-10T11:00:00.000Z"),
        "gut": s.add_asset("frank", "IMG_3.HEIC", "2024-07-10T12:00:00.000Z"),
        "dunkel": s.add_asset("frank", "IMG_4.HEIC", "2024-07-10T13:00:00.000Z"),
    }
    s.ids["urlaub"] = s.add_album("frank", "Urlaub", list(s.ids.values()))
    s.albums[s.ids["urlaub"]]["thumb"] = s.ids["video"]
    s.ids["fertig"] = s.add_album("frank", "Fertig", [s.ids["gut"], s.ids["weich"]])
    s.albums[s.ids["fertig"]]["thumb"] = s.ids["gut"]
    return s


QUALITY = {"weich": (8.0, 120.0), "gut": (50.0, 130.0), "dunkel": (50.0, 10.0)}


@pytest.fixture
def state():
    return cover_state()


@pytest.fixture
def web(env, http, state):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        svc = c.app.state.service
        lib = svc.library()
        for key, (sharp, bright) in QUALITY.items():
            svc.hash_store.put(lib.assets[state.ids[key]], 0, sharp, bright)
        yield c


def covers(web):
    return [it for it in web.get("/api/album-care").json()["eintraege"] if it["art"] == "titelbild"]


def test_suggests_better_cover(web, state):
    items = covers(web)
    assert len(items) == 1  # „Fertig“ hat ein gutes Titelbild
    it = items[0]
    assert it["ziel"] == state.ids["urlaub"] and "Video" in it["grund"]
    assert it["titelbild"]["id"] == state.ids["video"]
    assert it["vorschlag"] == state.ids["gut"]
    assert [m["id"] for m in it["auswahl"]] == [state.ids["gut"], state.ids["weich"]]  # dunkles fehlt


def test_set_own_choice_and_undo(web, state):
    it = covers(web)[0]
    r = web.post("/api/staged/album-care", json={"id": it["id"], "aktion": "titelbild", "titelbild": state.ids["weich"]})
    assert r.status_code == 200
    assert covers(web) == []  # vorgemerkt
    assert web.post("/api/staged/apply", json={}).json()["uebertragen"] == 1
    assert state.albums[state.ids["urlaub"]]["thumb"] == state.ids["weich"]
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["anzahl"] == 1 and e["rueckgaengig_moeglich"]
    assert web.post(f"/api/history/{e['id']}/undo").json()["fehler"] == []
    assert state.albums[state.ids["urlaub"]]["thumb"] == state.ids["video"]


def test_rejects_photo_outside_album(web, state):
    other = state.add_asset("frank", "X.HEIC", "2024-01-01T10:00:00.000Z")
    it = covers(web)[0]
    r = web.post("/api/staged/album-care", json={"id": it["id"], "aktion": "titelbild", "titelbild": other})
    assert r.status_code == 400
    # ein Titelbild-Eintrag löscht nie das Album
    assert web.post("/api/staged/album-care", json={"id": it["id"], "aktion": "loeschen"}).status_code == 400
    assert web.get("/api/staged").json()["eintraege"] == []
