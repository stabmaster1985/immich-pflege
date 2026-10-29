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


def test_review_all_media_and_stage_selection(web, state):
    r = web.get("/api/suggestions").json()
    italy = next(s for s in r["vorschlaege"] if s["tag"] == "Reisen/Italien")
    media = web.get(f"/api/suggestions/{italy['id']}/media").json()
    assert media["tag"] == "Reisen/Italien" and len(media["medien"]) == 25
    dates = [m["aufnahme"] for m in media["medien"]]
    assert dates == sorted(dates, reverse=True)  # neueste zuerst
    assert set(media["medien"][0]) >= {"id", "dateiname", "aufnahme", "benutzer", "typ"}
    off = [m["id"] for m in media["medien"][:5]]
    res = web.post(f"/api/staged/suggestions/{italy['id']}/auswahl", json={"ohne": off}).json()
    assert res["vorgemerkt"] == 20
    entry = web.get("/api/staged").json()["eintraege"][0]
    assert "20 von 25" in entry["titel"]
    assert italy["id"] not in {s["id"] for s in web.get("/api/suggestions").json()["vorschlaege"]}
    web.post("/api/staged/apply", json={})
    tagged = {aid for aid, a in state.assets.items() if a["_tags"]}
    assert len(tagged) == 20 and not tagged & set(off)
    # alles abgewählt -> Fehler; unbekannter Vorschlag -> Fehler
    wa = next(s for s in r["vorschlaege"] if s["tag"] == "Quelle/WhatsApp")
    all_wa = [m["id"] for m in web.get(f"/api/suggestions/{wa['id']}/media", params={"aktion": "archiv"}).json()["medien"]]
    assert len(all_wa) == 12
    assert web.post(f"/api/staged/suggestions/{wa['id']}/auswahl", json={"ohne": all_wa, "aktion": "archiv"}).status_code == 400
    assert web.post(f"/api/staged/suggestions/{wa['id']}/auswahl", json={"ohne": all_wa[:2], "aktion": "archiv"}).json()["vorgemerkt"] == 10
    assert web.get("/api/suggestions/vgibtsnicht/media").status_code == 400


def test_smart_search_size_for_review(web, state):
    few = web.get("/api/suggestions/smart", params={"begriff": "Hund", "anzahl": 3}).json()
    assert len(few["medien"]) == 6  # 3 je Benutzer
    many = web.get("/api/suggestions/smart", params={"begriff": "Hund", "anzahl": 400}).json()
    assert len(many["medien"]) > 120
    assert web.get("/api/suggestions/smart", params={"begriff": "Hund", "anzahl": 5001}).status_code == 422
    calls = [c for c in state.calls if c[1] == "/api/search/smart"]
    assert calls  # Immich wurde gefragt


def test_smart_search_skips_excluded_and_pages(web, state):
    """Schon getaggte/ausgeblendete zählen nicht mit – dahinter wird weitergeblättert."""
    first = web.get("/api/suggestions/smart", params={"begriff": "Hund", "anzahl": 3}).json()
    ids = [m["id"] for m in first["medien"]]
    assert web.post("/api/suggestions/smart/hide", json={"tag": first["tag"], "ids": ids}).json()["ausgeblendet"] == len(ids)
    again = web.get("/api/suggestions/smart", params={"begriff": "Hund", "anzahl": 3}).json()
    assert len(again["medien"]) == 6 and not set(ids) & {m["id"] for m in again["medien"]}
    assert again["ausgeblendet"] == len(ids)
    hidden = web.get("/api/suggestions/smart/hidden", params={"tag": first["tag"].upper()}).json()
    assert {m["id"] for m in hidden["medien"]} == set(ids)
    web.post("/api/suggestions/smart/hide", json={"tag": first["tag"], "ids": ids, "undo": True})
    assert web.get("/api/suggestions/smart", params={"begriff": "Hund", "anzahl": 3}).json()["ausgeblendet"] == 0
