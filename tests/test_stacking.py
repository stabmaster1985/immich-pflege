"""Stapeln aus eigenen Alben."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app
from tests.mock_immich import MockState


def stack_state() -> MockState:
    s = MockState()
    s.add_user("frank", "key-frank")
    s.add_user("julia", "key-julia")
    ids = s.ids = {}
    ids["raw"] = s.add_asset("frank", "DSC0001.ARW", "2024-05-01T10:00:00.000Z", make="SONY", model="ILCE-7M4")
    ids["jpg"] = s.add_asset("frank", "DSC0001.JPG", "2024-05-01T10:00:00.000Z", make="SONY", model="ILCE-7M4")
    ids["serie"] = [s.add_asset("frank", f"IMG_02{i}.HEIC", f"2024-05-02T10:00:0{i}.000Z", image=f"burst#{b}")
                    for i, b in enumerate((2, 0, 3))]
    ids["aehnlich"] = [s.add_asset("frank", "IMG_0300.HEIC", "2024-05-03T10:00:00.000Z", image="see"),
                       s.add_asset("frank", "IMG_0301.HEIC", "2024-05-03T10:00:40.000Z", image="see")]
    ids["einzeln"] = s.add_asset("frank", "IMG_0400.HEIC", "2024-05-04T10:00:00.000Z")
    ids["julia"] = [s.add_asset("julia", "IMG_0500.HEIC", "2024-05-05T10:00:00.000Z"),
                    s.add_asset("julia", "IMG_0501.HEIC", "2024-05-05T12:00:00.000Z")]
    album = [ids["raw"], ids["jpg"], *ids["serie"], *ids["aehnlich"], ids["einzeln"], *ids["julia"]]
    ids["album"] = s.add_album("frank", "Zum Stapeln", album, shared={"julia": "editor"})
    # von Immich 3.3 gestapelte Handy-Bearbeitung: kein Duplikat mehr
    orig = s.add_asset("julia", "IMG_0700.HEIC", "2024-05-07T10:00:00.000Z")
    edit = s.add_asset("julia", "IMG_E0700.HEIC", "2024-05-07T10:00:00.000Z")
    s.stacks["st-1"] = {"ownerId": s.user_id("julia"), "assetIds": [edit, orig]}
    return s


@pytest.fixture
def state():
    return stack_state()


@pytest.fixture
def web(env, http):
    env = {**env, "DUP_IMAGE_HASH": "true"}
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        svc = c.app.state.service
        svc.library()
        svc._hash_thread.join(10)
        yield c


def test_proposals(web, state):
    r = web.get("/api/stacks").json()
    assert [a["name"] for a in r["alben"]] == ["Zum Stapeln"] and r["vorschlaege"] == []
    r = web.get("/api/stacks", params={"album": state.ids["album"]}).json()
    groups = {frozenset(m["id"] for m in p["medien"]): p for p in r["vorschlaege"]}
    raw = groups[frozenset({state.ids["raw"], state.ids["jpg"]})]
    assert raw["oben"] == state.ids["jpg"] and "gleicher Name" in raw["grund"]  # JPG statt RAW oben
    serie = groups[frozenset(state.ids["serie"])]
    assert serie["oben"] == state.ids["serie"][1]  # das schärfste
    assert frozenset(state.ids["aehnlich"]) in groups  # 40 s, gleiches Motiv
    assert len(groups) == 3 and r["zahlen"]["einzeln"] == 3
    whole = web.get("/api/stacks", params={"album": state.ids["album"], "ganz": True}).json()["vorschlaege"]
    assert sorted(p["anzahl"] for p in whole) == [2, 8]  # je Benutzer ein Stapel


def test_stage_apply_remove_and_undo(web, state):
    alb = state.ids["album"]
    prop = web.get("/api/stacks", params={"album": alb}).json()["vorschlaege"]
    serie = next(p for p in prop if p["anzahl"] == 3)
    res = web.post("/api/staged/stacks", json={"album": alb, "aus_album": True,
                                                "oben": {serie["id"]: state.ids["serie"][0]}}).json()
    assert res == {"vorgemerkt": 3, "medien": 7}
    assert len(state.stacks) == 1  # noch nichts an Immich
    assert web.get("/api/stacks", params={"album": alb}).json()["vorschlaege"] == []
    assert web.post("/api/staged/apply", json={}).json()["uebertragen"] == 1
    made = {tuple(st["assetIds"]) for sid, st in state.stacks.items() if sid != "st-1"}
    assert (state.ids["jpg"], state.ids["raw"]) in made
    assert any(st[0] == state.ids["serie"][0] for st in made)  # eigene Wahl liegt oben
    left = state.asset_ids_in_album(alb)
    assert left == {state.ids["einzeln"], *state.ids["julia"]}  # gestapelte aus dem Album genommen
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["typ"] == "stapel" and e["anzahl"] == 7
    assert web.post(f"/api/history/{e['id']}/undo").json()["fehler"] == []
    assert list(state.stacks) == ["st-1"] and len(state.asset_ids_in_album(alb)) == 10
    assert len(web.get("/api/stacks", params={"album": alb}).json()["vorschlaege"]) == 3


def test_stacked_edit_is_no_duplicate(web):
    groups = web.get("/api/duplicates", params={"art": "bearbeitung"}).json()["gruppen"]
    assert groups == []


def test_burst_from_cleanup(web, state):
    item = web.get("/api/cleanup", params={"kategorie": "serien"}).json()["eintraege"][0]
    web.post("/api/staged/cleanup", json={"action": "stapel", "ids": [item["id"]]})
    assert web.get("/api/cleanup", params={"kategorie": "serien"}).json()["gesamt"] == 0
    web.post("/api/staged/apply", json={})
    st = next(st for sid, st in state.stacks.items() if sid != "st-1")
    assert st["assetIds"][0] == state.ids["serie"][1] and set(st["assetIds"]) == set(state.ids["serie"])
