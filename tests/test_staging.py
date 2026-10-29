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


def test_view_and_deselect_media_of_staged_entry(web, state):
    over = web.get("/api/no-location?overview=true").json()
    web.post("/api/staged/no-location", json={"ort": over["orte"][0]["key"], "label": "San Gimignano"})
    gid = next(g["id"] for g in web.get("/api/duplicates").json()["gruppen"] if g["art"] == "aehnlich")
    web.post("/api/staged/duplicates", json={"action": "papierkorb", "groups": [{"id": gid}]})
    entries = {e["typ"]: e for e in web.get("/api/staged").json()["eintraege"]}

    ort = web.get(f"/api/staged/{entries['ort']['id']}/media").json()
    assert len(ort["medien"]) == 2 and all(m["marke"] for m in ort["medien"])
    drop = ort["medien"][0]["id"]
    r = web.post(f"/api/staged/{entries['ort']['id']}/ohne", json={"ohne": [drop]}).json()
    assert r == {"entfernt": 1, "uebrig": 1}
    e = next(x for x in web.get("/api/staged").json()["eintraege"] if x["typ"] == "ort")
    assert e["anzahl"] == 1 and [ch["asset_id"] for ch in e["daten"]["aenderungen"]] != [drop]
    assert drop in {m["id"] for s in web.get("/api/no-location?only_suggestions=false").json()["serien"]
                    for m in s["medien"]}  # wieder in der Übersicht

    dup = web.get(f"/api/staged/{entries['duplikat']['id']}/media").json()
    assert [m["marke"] for m in dup["medien"]] == ["🗑"]
    # alles abgewählt -> Eintrag fällt weg
    r = web.post(f"/api/staged/{entries['duplikat']['id']}/ohne", json={"ohne": [dup["medien"][0]["id"]]}).json()
    assert r["uebrig"] == 0
    assert {x["typ"] for x in web.get("/api/staged").json()["eintraege"]} == {"ort"}
    assert web.get("/api/staged/unbekannt/media").status_code == 400


def test_stack_series_from_duplicates(env, http, state):
    did = "d0000000-0000-4000-8000-000000000099"
    ids = [state.add_asset("frank", f"IMG_{n}.HEIC", f"2024-08-01T10:00:0{i}.000Z", utc=f"2024-08-01T08:00:0{i}.000Z",
                           duplicate_id=did) for i, n in enumerate((4711, 4712))]
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as web:
        r = web.get("/api/duplicates", params={"art": "serie"}).json()
        assert r["arten"]["serie"]["anzahl"] == 1 and r["gruppen"][0]["art_text"] == "Serienbild – eher stapeln"
        g = r["gruppen"][0]
        res = web.post("/api/staged/duplicate-stacks", json={"groups": [{"id": g["id"], "keep": ids[1]}]}).json()
        assert res == {"vorgemerkt": 1, "medien": 2}
        assert web.get("/api/duplicates", params={"art": "serie"}).json()["gesamt"] == 0
        e = web.get("/api/staged").json()["eintraege"][0]
        assert e["typ"] == "stapel" and e["daten"]["stapel"][0]["ids"] == [ids[1], ids[0]]
        assert web.post("/api/staged/apply", json={}).json()["uebertragen"] == 1
        assert not any(c[0] == "DELETE" for c in state.calls)  # nichts gelöscht


def test_duplicate_group_all_gone(web, state):
    """„Alle weg“: keins behalten – Schutzregeln (extern, anderer Benutzer) gelten weiter."""
    groups = web.get("/api/duplicates").json()["gruppen"]
    g = next(x for x in groups if x["art"] == "aehnlich")  # zwei Uploads von Julia
    plan = web.post("/api/duplicates/apply", json={"action": "papierkorb", "groups": [{"id": g["id"], "alle": True}],
                                                    "dry_run": True}).json()
    assert plan["papierkorb"] == len(g["medien"]) == 2
    web.post("/api/staged/duplicates", json={"action": "papierkorb", "groups": [{"id": g["id"], "alle": True}]})
    e = web.get("/api/staged").json()["eintraege"][0]
    assert "alle 2 weg" in e["titel"] and not any(m["bleibt"] for m in e["medien"])
    ext = next(x for x in groups if any(m["extern"] for m in x["medien"]) and x["id"] != g["id"])
    plan = web.post("/api/duplicates/apply", json={"action": "papierkorb", "groups": [{"id": ext["id"], "alle": True}],
                                                    "dry_run": True}).json()
    by_id = {s["id"]: s["aktion"] for s in plan["schritte"]}
    assert all(by_id[m["id"]] == "album" for m in ext["medien"] if m["extern"])  # extern nie in den Papierkorb
    assert len(by_id) == len(ext["medien"])


def test_messenger_copy_original_kept_and_takes_over_album(env, http, state):
    """WhatsApp-Kopie im geteilten Gruppen-Album: das Original bleibt und kommt ins Album."""
    did = "d0000000-0000-4000-8000-000000000077"
    orig = state.add_asset("frank", "IMG_9000.HEIC", "2024-09-01T12:00:00.000Z", utc="2024-09-01T10:00:00.000Z",
                           duplicate_id=did)
    copy = state.add_asset("frank", "IMG-20240902-WA0007.jpg", "2024-09-02T08:00:00.000Z", utc="2024-09-02T06:00:00.000Z",
                           duplicate_id=did, make=None, model=None, width=1600, height=1200)
    album = state.add_album("julia", "Gruppe Wandern", [copy], shared={"frank": "editor"})
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as web:
        g = web.get("/api/duplicates", params={"art": "messenger"}).json()["gruppen"][0]
        assert g["art_text"] == "Messenger-Kopie" and g["behalten"] == orig  # trotz Album der Kopie
        web.post("/api/staged/duplicates", json={"action": "papierkorb", "groups": [{"id": g["id"]}]})
        r = web.post("/api/staged/apply", json={"confirm": "PAPIERKORB"}).json()
        res = r["eintraege"][0]["ergebnis"]
        assert res["papierkorb"] == 1 and res["alben_uebernommen"] == 1
        assert orig in state.asset_ids_in_album(album)
        # Rückgängig nimmt das Original wieder aus dem Album
        hist = web.get("/api/history").json()["eintraege"][0]
        web.post(f"/api/history/{hist['id']}/undo")
        assert orig not in state.asset_ids_in_album(album)


def test_auto_stage_preview_and_stage(web, state):
    pre = web.get("/api/auto-stage").json()["arten"]
    assert set(pre) == {"orte", "identisch", "messenger", "bearbeitung", "serien"}
    assert pre["identisch"]["anzahl"] == 1 and pre["orte"]["anzahl"] >= 1
    res = web.post("/api/auto-stage", json={"arten": ["identisch", "orte"], "aktion": "papierkorb"}).json()
    assert res["vorgemerkt"]["identisch"] == 1 and res["vorgemerkt"]["orte"] >= 1
    st = web.get("/api/staged").json()
    dup = next(e for e in st["eintraege"] if e["typ"] == "duplikat")
    assert dup["titel"].startswith("⚡") and dup["daten"]["automatisch"] == "identisch"
    assert web.get("/api/duplicates", params={"art": "identisch"}).json()["gesamt"] == 0  # vorgemerkt -> weg
    assert web.get("/api/auto-stage").json()["arten"]["identisch"]["anzahl"] == 0
    assert writes(state) == []  # nichts an Immich
    assert web.post("/api/auto-stage", json={"arten": ["quatsch"]}).status_code == 422
    # zurücknehmen bringt die Gruppe zurück
    web.delete(f"/api/staged/{dup['id']}")
    assert web.get("/api/duplicates", params={"art": "identisch"}).json()["gesamt"] == 1
