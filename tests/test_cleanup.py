"""Aufräumen: Speicherfresser, Serienbilder, unscharf/dunkel."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.config import Settings
from immich_pflege.service import Pflege
from immich_pflege.web.app import create_app
from tests.mock_immich import MockState, create_app as mock_app

MB = 1024 * 1024


def cleanup_state() -> MockState:
    s = MockState()
    s.add_user("frank", "key-frank")
    s.add_user("julia", "key-julia")
    s.ids = {}
    s.ids["gross"] = s.add_asset("frank", "IMG_0001.MOV", "2024-05-01T10:00:00.000Z", type="VIDEO",
                                 size=900 * MB, duration=600_000)
    s.ids["gross_extern"] = s.add_asset("frank", "C0001.MP4", "2024-05-02T10:00:00.000Z", type="VIDEO",
                                        size=2000 * MB, library=True, make="SONY", model="ILCE-7M4")
    s.ids["klein"] = s.add_asset("frank", "IMG_0002.MOV", "2024-05-01T11:00:00.000Z", type="VIDEO",
                                 size=50 * MB, duration=20_000)
    s.ids["screen"] = s.add_asset("julia", "ScreenRecording_05-03-2024.MP4", "2024-05-03T10:00:00.000Z",
                                  type="VIDEO", size=80 * MB, make=None, model=None)
    s.ids["live_foto"] = s.add_asset("julia", "IMG_0500.HEIC", "2024-05-04T10:00:00.000Z")
    s.ids["live_video"] = s.add_asset("julia", "IMG_0500.MOV", "2024-05-04T10:00:01.000Z", type="VIDEO",
                                      size=4 * MB, duration=2900)
    s.ids["serie"] = [s.add_asset("frank", f"IMG_06{i:02d}.HEIC", f"2024-05-05T10:00:0{i}.000Z", image=f"serie#{b}")
                      for i, b in enumerate((3, 0, 2, 4))]  # das zweite ist das schärfste
    s.ids["dunkel"] = s.add_asset("julia", "IMG_0700.HEIC", "2024-05-06T22:00:00.000Z", image="dunkel1")
    s.ids["unscharf"] = s.add_asset("julia", "IMG_0701.HEIC", "2024-05-06T12:00:00.000Z", image="unscharf1")
    s.ids["fav_dunkel"] = s.add_asset("julia", "IMG_0702.HEIC", "2024-05-06T23:00:00.000Z", image="dunkel2",
                                      favorite=True)
    s.add_asset("frank", "IMG_0800.HEIC", "2024-05-07T12:00:00.000Z")  # normales Foto
    return s


@pytest.fixture
def state():
    return cleanup_state()


@pytest.fixture
def web(env, http, state):
    env = {**env, "DUP_IMAGE_HASH": "true"}
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        svc = c.app.state.service
        svc.library()
        svc._hash_thread.join(10)
        yield c


def by_cat(r, cat):
    return [e for e in r["eintraege"] if e["kategorie"] == cat]


def test_categories(web, state):
    r = web.get("/api/cleanup", params={"limit": 0}).json()
    cats = {k: v["anzahl"] for k, v in r["kategorien"].items()}
    assert cats == {"grosse_videos": 2, "bildschirmaufnahmen": 1, "live_videos": 1, "serien": 1,
                    "versehentlich": 1, "dunkel": 0, "unscharf": 1}
    assert r["arten"]["speicher"]["groesse"] == (900 + 2000 + 80 + 4) * MB
    assert by_cat(r, "grosse_videos")[0]["medien"][0]["id"] == state.ids["gross_extern"]  # größtes zuerst
    live = by_cat(r, "live_videos")[0]
    assert {m["id"]: m["aktion"] for m in live["medien"]} == {state.ids["live_foto"]: "bleibt",
                                                              state.ids["live_video"]: "weg"}
    serie = by_cat(r, "serien")[0]
    keep = [m["id"] for m in serie["medien"] if m["aktion"] == "bleibt"]
    assert keep == [state.ids["serie"][1]] and "schärfste" in serie["grund"]
    assert by_cat(r, "versehentlich")[0]["medien"][0]["id"] == state.ids["dunkel"]  # Favorit bleibt außen vor
    only = web.get("/api/cleanup", params={"art": "qualitaet"}).json()
    assert {e["kategorie"] for e in only["eintraege"]} == {"versehentlich", "unscharf"}


def test_stage_trash_protects_external_and_undo(web, state):
    web.post("/api/staged/cleanup", json={"action": "papierkorb", "kategorie": "grosse_videos"})
    assert not [c for c in state.calls if c[0] == "DELETE"]  # nur vorgemerkt
    assert web.get("/api/cleanup", params={"kategorie": "grosse_videos"}).json()["gesamt"] == 0
    st = web.get("/api/staged").json()
    assert st["papierkorb"] == 1  # das externe Video geht nur ins Prüf-Album
    assert web.post("/api/staged/apply", json={}).status_code == 400  # Bestätigung fehlt
    assert web.post("/api/staged/apply", json={"confirm": "PAPIERKORB"}).json()["uebertragen"] == 1
    assert state.assets[state.ids["gross"]]["isTrashed"]
    assert not state.assets[state.ids["gross_extern"]]["isTrashed"]
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["typ"] == "aufraeumen" and e["anzahl"] == 2
    web.post(f"/api/history/{e['id']}/undo")
    assert not state.assets[state.ids["gross"]]["isTrashed"]


def test_keep_hides_entry(web):
    r = web.get("/api/cleanup", params={"kategorie": "serien"}).json()
    sid = r["eintraege"][0]["id"]
    web.post("/api/cleanup/keep", json={"ids": [sid]})
    after = web.get("/api/cleanup").json()
    assert after["kategorien"]["serien"]["anzahl"] == 0 and after["ausgeblendet"] == 1
    assert web.get("/api/cleanup", params={"ignoriert": True}).json()["eintraege"][0]["id"] == sid
    web.post("/api/cleanup/keep", json={"ids": [sid], "undo": True})
    assert web.get("/api/cleanup").json()["kategorien"]["serien"]["anzahl"] == 1


def test_without_fingerprints_only_storage(env, http):
    svc = Pflege(Settings.load(env), http=http)
    r = svc.cleanup_view(limit=0)
    assert r["arten"]["qualitaet"]["anzahl"] == 0 and r["arten"]["speicher"]["anzahl"] == 4
    assert r["kategorien"]["serien"]["anzahl"] == 1  # Serien gehen auch ohne Fingerabdruck (nur Zeit)


def test_choose_other_burst_photo(web, state):
    item = web.get("/api/cleanup", params={"kategorie": "serien"}).json()["eintraege"][0]
    first = state.ids["serie"][0]
    web.post("/api/staged/cleanup", json={"action": "album", "ids": [item["id"]], "keep": {item["id"]: first}})
    steps = web.get("/api/staged").json()["eintraege"][0]["daten"]["schritte"]
    assert first not in {s["id"] for s in steps} and len(steps) == 3
