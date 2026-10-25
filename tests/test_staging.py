"""Vormerkliste: erst sammeln, prüfen, dann übertragen."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def writes(state):
    return [c for c in state.calls if c[0] in ("PUT", "DELETE") or (c[0] == "POST" and c[1] == "/api/albums")]


def test_stage_duplicates_nothing_sent_and_hidden(web, state):
    r = web.get("/api/duplicates").json()
    gid = next(g["id"] for g in r["gruppen"] if g["art"] == "sehr_wahrscheinlich")
    res = web.post("/api/staged/duplicates", json={"action": "papierkorb", "groups": [{"id": gid}]}).json()
    assert res["vorgemerkt"] == 1
    assert writes(state) == []  # nichts an Immich
    after = web.get("/api/duplicates").json()
    assert after["gesamt"] == r["gesamt"] - 1 and gid not in [g["id"] for g in after["gruppen"]]
    st = web.get("/api/staged").json()
    assert st["anzahl"] == 1 and st["nach_typ"]["duplikat"] == 1
    e = st["eintraege"][0]
    # behalten wird die externe Kopie, der Upload ginge in den Papierkorb – aber erst beim Übertragen
    assert e["daten"]["schritte"][0]["aktion"] == "papierkorb" and st["papierkorb"] == 1
    # zweimal vormerken ersetzt den Eintrag statt ihn zu verdoppeln
    web.post("/api/staged/duplicates", json={"action": "album", "all": True})
    assert web.get("/api/staged").json()["nach_typ"]["duplikat"] == 3
    assert web.get("/api/duplicates").json()["gesamt"] == 0


def test_unstage_brings_group_back(web):
    gid = web.get("/api/duplicates").json()["gruppen"][0]["id"]
    web.post("/api/staged/duplicates", json={"action": "album", "groups": [{"id": gid}]})
    entry = web.get("/api/staged").json()["eintraege"][0]["id"]
    assert web.delete(f"/api/staged/{entry}").json()["entfernt"] == 1
    assert gid in [g["id"] for g in web.get("/api/duplicates").json()["gruppen"]]


def test_stage_locations_and_apply_all(web, state):
    over = web.get("/api/no-location?overview=true").json()
    key = over["orte"][0]["key"]  # San Gimignano
    res = web.post("/api/staged/no-location", json={"ort": key, "label": "San Gimignano"}).json()
    assert res["vorgemerkt"] == 2 and writes(state) == []
    assert all(o["key"] != key for o in web.get("/api/no-location?overview=true").json()["orte"])
    web.post("/api/staged/no-location", json={"min_confidence": "hoch"})  # IMG_0200 2.JPG
    gid = next(g["id"] for g in web.get("/api/duplicates").json()["gruppen"] if g["art"] == "identisch")
    web.post("/api/staged/duplicates", json={"action": "papierkorb", "groups": [{"id": gid}]})

    st = web.get("/api/staged").json()
    assert {k: v for k, v in st["nach_typ"].items() if v} == {"duplikat": 1, "ort": 2} and st["medien"] == 4

    # Papierkorb steckt drin -> Bestätigung nötig (hier: Julias Favorit bleibt, Franks Kopie
    # ist anderer Benutzer -> Prüf-Album, also kein Papierkorb)
    r = web.post("/api/staged/apply").json()
    assert r["uebertragen"] == 3 and r["fehler"] == 0
    assert web.get("/api/staged").json()["anzahl"] == 0
    puts = [c for c in state.calls if c[:2] == ("PUT", "/api/assets")]
    assert sum(len(c[3]["ids"]) for c in puts) == 3


def test_trash_needs_confirmation_at_transfer(web, state):
    gid = next(g["id"] for g in web.get("/api/duplicates").json()["gruppen"] if g["art"] == "aehnlich")
    web.post("/api/staged/duplicates", json={"action": "papierkorb", "groups": [{"id": gid}]})
    assert web.get("/api/staged").json()["papierkorb"] == 1
    r = web.post("/api/staged/apply")
    assert r.status_code == 400 and "PAPIERKORB" in r.json()["fehler"]
    assert not any(c[0] == "DELETE" for c in state.calls)
    r = web.post("/api/staged/apply", json={"confirm": "PAPIERKORB"}).json()
    assert r["uebertragen"] == 1
    assert any(c[0] == "DELETE" for c in state.calls)


def test_stale_entries_are_skipped(web, state):
    over = web.get("/api/no-location?overview=true").json()
    web.post("/api/staged/no-location", json={"ort": over["orte"][0]["key"]})
    # direkt per API (n8n) inzwischen gesetzt -> beim Übertragen überspringen
    lib_ids = [ch["asset_id"] for ch in web.get("/api/staged").json()["eintraege"][0]["daten"]["aenderungen"]]
    web.app.state.service.library().assets[lib_ids[0]].latitude = 1.0
    web.app.state.service.library().assets[lib_ids[0]].longitude = 1.0
    r = web.post("/api/staged/apply").json()
    res = r["eintraege"][0]["ergebnis"]
    assert res["aktualisiert"] == 1 and res["uebersprungen"][0]["grund"] == "hat inzwischen einen Ort"


def test_stage_tags(web, settings):
    settings.rules_file.parent.mkdir(parents=True, exist_ok=True)
    settings.rules_file.write_text("regeln:\n  - name: Sony\n    tag: Kamera/Sony\n    hersteller: SONY\n")
    web.post("/api/staged/tags", json={"rules": ["Sony"]})
    assert web.get("/api/tags").json()["regeln"][0]["vorgemerkt"] is True
    r = web.post("/api/staged/apply").json()
    assert r["eintraege"][0]["ergebnis"]["getaggt"] == 6


def test_staging_survives_restart(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as a:
        gid = a.get("/api/duplicates").json()["gruppen"][0]["id"]
        a.post("/api/staged/duplicates", json={"action": "album", "groups": [{"id": gid}]})
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as b:
        assert b.get("/api/staged").json()["anzahl"] == 1
