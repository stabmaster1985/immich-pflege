"""Personen: unbenannte Gesichter mit „meist zusammen mit“, doppelte Personen zusammenführen."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def own(state, user):
    return [i for i, a in state.assets.items() if state.user_by_id(a["ownerId"])["name"].lower() == user]


def test_unnamed_people_and_who_they_are_with(web, state):
    fr = own(state, "frank")
    state.add_person("frank", "Julia", fr[:4])
    stranger = state.add_person("frank", "", fr[1:4])  # immer mit Julia zusammen
    alone = state.add_person("frank", "", fr[4:5])
    r = web.get("/api/people").json()
    by_id = {u["id"]: u for u in r["unbenannt"]}
    assert by_id[stranger]["anzahl"] == 3 and by_id[stranger]["mit"] == {"name": "Julia", "anzahl": 3}
    assert by_id[alone]["mit"] is None and r["unbenannt"][0]["id"] == stranger  # meiste Fotos zuerst
    assert web.get(f"/person-thumb/frank/{stranger}").status_code == 200


def test_merge_double_people(web, state):
    fr = own(state, "frank")
    big = state.add_person("frank", "Oma Ilse", fr[:3])
    small = state.add_person("frank", "oma  ilse", fr[3:5])
    state.add_person("julia", "Oma Ilse", own(state, "julia")[:2])  # anderer Benutzer: kein Doppel
    d = web.get("/api/people").json()["doppelt"]
    assert len(d) == 1 and d[0]["behalten"] == big and [p["id"] for p in d[0]["personen"]] == [big, small]
    web.post("/api/staged/people-merge", json={"eintraege": [{"benutzer": "frank", "behalten": big, "ids": [small]}]})
    assert web.get("/api/people").json()["doppelt"] == []  # vorgemerkt -> nicht mehr angeboten
    entry = web.get("/api/staged").json()["eintraege"][0]
    assert entry["typ"] == "personen" and "zusammenführen" in entry["titel"]
    assert web.get(f"/api/staged/{entry['id']}/media").status_code == 400
    r = web.post("/api/staged/apply", json={}).json()
    assert r["uebertragen"] == 1
    assert small not in state.people and all(big in state.assets[i]["_people"] for i in fr[:5])
    hist = web.get("/api/history").json()["eintraege"][0]
    assert hist["rueckgaengig_moeglich"] is False and "nicht wieder trennen" in hist["nicht_rueckgaengig"]
    bad = web.post("/api/staged/people-merge", json={"eintraege": [{"benutzer": "frank", "behalten": big, "ids": ["x"]}]})
    assert bad.status_code == 400
