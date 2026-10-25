"""Verlauf und Rückgängig."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app
from tests.mock_immich import album_state


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def test_trash_and_album_undo(web, state):
    groups = web.get("/api/duplicates").json()["gruppen"]
    for g in groups:
        web.post("/api/staged/duplicates", json={"action": "papierkorb", "groups": [{"id": g["id"]}]})
    r = web.post("/api/staged/apply", json={"confirm": "PAPIERKORB"}).json()
    assert r["uebertragen"] == len(groups)
    assert "rueck" not in str(r)  # Rückgängig-Daten bleiben im Verlauf
    trashed = {a for a, v in state.assets.items() if v["isTrashed"] and v["originalFileName"] != "alt.jpg"}
    assert trashed
    hist = web.get("/api/history").json()["eintraege"]
    assert len(hist) == len(groups) and all(e["rueckgaengig_moeglich"] for e in hist)
    for e in hist:
        res = web.post(f"/api/history/{e['id']}/undo").json()
        assert res["fehler"] == []
    assert not any(state.assets[a]["isTrashed"] for a in trashed)
    review = [al for al in state.albums.values() if al["albumName"] == "Duplikat-Prüfung"]
    assert all(not state.asset_ids_in_album(al["id"]) for al in review)
    # wieder da – ohne neu einzulesen
    assert web.get("/api/duplicates").json()["gesamt"] == len(groups)
    assert web.post(f"/api/history/{hist[0]['id']}/undo").status_code == 400  # nur einmal


def test_location_not_undoable(web):
    web.post("/api/no-location/apply", json={"min_confidence": "hoch"})
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["typ"] == "ort" and not e["rueckgaengig_moeglich"] and "nicht entfernen" in e["nicht_rueckgaengig"]
    assert web.post(f"/api/history/{e['id']}/undo").status_code == 400


def test_tags_undo(web, state):
    web.put("/api/rules", json={"regeln": [{"name": "Sony", "tag": "Kamera/Sony", "hersteller": "SONY"}]})
    web.post("/api/staged/tags", json={"rules": ["Sony"]})
    web.post("/api/staged/apply", json={})
    tagged = [a for a in state.assets.values() if a["_tags"]]
    assert tagged
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["typ"] == "tag" and e["anzahl"] == len(tagged)
    web.post(f"/api/history/{e['id']}/undo")
    assert not any(a["_tags"] for a in state.assets.values())


@pytest.fixture
def album_web(env, monkeypatch):
    from tests.mock_immich import create_app as mock_app
    s = album_state()
    with TestClient(mock_app(s), base_url="http://immich-server:2283") as http:
        with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
            yield c, s


def test_album_undo(album_web):
    web, s = album_web
    trips = web.get("/api/album-suggestions").json()["reisen"]
    for t in trips:
        web.post("/api/staged/albums", json={"trips": [{"id": t["id"]}]})
    web.post("/api/staged/apply", json={})
    assert {a["albumName"] for a in s.albums.values()} == {"Toskana 2024", "Wien", "Kopenhagen, September 2024"}
    for e in web.get("/api/history").json()["eintraege"]:
        assert web.post(f"/api/history/{e['id']}/undo").json()["fehler"] == []
    assert {a["albumName"] for a in s.albums.values()} == {"Toskana 2024", "Wien"}  # neues Album gelöscht
    toskana = next(a for a in s.albums.values() if a["albumName"] == "Toskana 2024")
    assert len(s.asset_ids_in_album(toskana["id"])) == 5 and toskana["members"] == {}  # wie vorher
    assert web.get("/api/album-suggestions").json()["offen"] == 2
