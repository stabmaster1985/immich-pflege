"""Tag-Vorschläge: aus den Daten und per KI-Suche."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app
from tests.mock_immich import album_state


@pytest.fixture
def state():
    s = album_state()
    s.dogs = [s.add_asset(u, f"IMG_D{i}.HEIC", f"2024-06-0{i + 1}T10:00:00.000Z", motiv="dog")
              for i, u in enumerate(["frank", "julia", "frank", "julia", "frank"])]
    for i in range(12):
        s.add_asset("julia", f"IMG-2024060{i % 9 + 1}-WA00{i:02d}.jpg", "2024-06-10T10:00:00.000Z", make=None, model=None)
    return s


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def test_data_suggestions(web):
    r = web.get("/api/suggestions").json()
    by_tag = {s["tag"]: s for s in r["vorschlaege"]}
    assert {"Reisen/Italien", "Reisen/Dänemark", "Reisen/Österreich"} <= set(by_tag)
    assert "Reisen/Deutschland" not in by_tag  # Heimatland
    assert by_tag["Reisen/Italien"]["neu"] == 25 and by_tag["Reisen/Italien"]["beispiele"]
    assert by_tag["Quelle/WhatsApp"]["neu"] == 12
    assert any(t.startswith("Kamera/") for t in by_tag)
    assert [b["name"] for b in r["begriffe"]][:2] == ["Hund", "Katze"]


def test_stage_apply_hide_and_undo(web, state):
    r = web.get("/api/suggestions").json()
    italy = next(s for s in r["vorschlaege"] if s["tag"] == "Reisen/Italien")
    web.post("/api/staged/suggestions", json={"ids": [italy["id"]]})
    assert italy["id"] not in {s["id"] for s in web.get("/api/suggestions").json()["vorschlaege"]}
    assert web.post("/api/staged/apply", json={}).json()["uebertragen"] == 1
    tagged = [a for a in state.assets.values() if a["_tags"]]
    assert len(tagged) == 25
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["typ"] == "tag" and e["anzahl"] == 25
    web.post(f"/api/history/{e['id']}/undo")
    assert not any(a["_tags"] for a in state.assets.values())
    wa = next(s for s in r["vorschlaege"] if s["tag"] == "Quelle/WhatsApp")
    web.post("/api/suggestions/hide", json={"ids": [wa["id"]]})
    after = web.get("/api/suggestions").json()
    assert wa["id"] not in {s["id"] for s in after["vorschlaege"]} and after["ausgeblendet"] == 1
    assert web.get("/api/suggestions", params={"ausgeblendet": True}).json()["vorschlaege"][0]["id"] == wa["id"]


def test_smart_search_cutoff_and_tag(web, state):
    r = web.get("/api/suggestions/smart", params={"begriff": "Hund"}).json()
    assert r["tag"] == "Tiere/Hund"
    ranked = [m["id"] for m in r["medien"]]
    assert set(ranked[:5]) == set(state.dogs)  # passende zuerst, beide Benutzer gemischt
    web.post("/api/staged/smart", json={"tag": r["tag"], "ids": ranked[:5], "begriff": "Hund"})
    again = web.get("/api/suggestions/smart", params={"begriff": "Hund"}).json()
    assert not set(state.dogs) & {m["id"] for m in again["medien"]}  # vorgemerkte nicht noch einmal
    web.post("/api/staged/apply", json={})
    for aid in state.dogs:
        assert state.assets[aid]["_tags"]
    users = {c[2] for c in state.calls if c[1] == "/api/tags/assets"}
    assert users == {"frank", "julia"}  # jeder taggt seine eigenen
    custom = web.get("/api/suggestions/smart", params={"suche": "dog on the beach", "tag": "Tiere/Strandhund"}).json()
    assert custom["tag"] == "Tiere/Strandhund"
    assert web.get("/api/suggestions/smart").status_code == 400


def test_archive_suggestion_and_smart_and_undo(web, state):
    wa = next(s for s in web.get("/api/suggestions").json()["vorschlaege"] if s["tag"] == "Quelle/WhatsApp")
    assert wa["archivierbar"] == 12
    assert web.post("/api/staged/archive", json={"vorschlag": wa["id"]}).json()["vorgemerkt"] == 12
    assert wa["id"] not in {s["id"] for s in web.get("/api/suggestions").json()["vorschlaege"]}
    smart = web.get("/api/suggestions/smart", params={"begriff": "Hund"}).json()
    web.post("/api/staged/archive", json={"ids": [m["id"] for m in smart["medien"][:2]], "label": "Hund"})
    staged = web.get("/api/staged").json()
    assert staged["nach_typ"]["archiv"] == 2
    assert web.post("/api/staged/apply", json={}).json()["uebertragen"] == 2
    archived = [a for a in state.assets.values() if a["visibility"] == "archive"]
    assert len(archived) == 14
    wa_after = next(s for s in web.get("/api/suggestions").json()["vorschlaege"] if s["tag"] == "Quelle/WhatsApp")
    assert wa_after["archivierbar"] == 0 and wa_after["neu"] == 12  # taggen ginge noch
    for e in web.get("/api/history").json()["eintraege"]:
        assert e["typ"] == "archiv"
        web.post(f"/api/history/{e['id']}/undo")
    assert not any(a["visibility"] == "archive" for a in state.assets.values())
