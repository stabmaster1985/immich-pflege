import re
import base64

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http)) as c:
        yield c


def test_healthz_and_ui(web):
    assert web.get("/healthz").json()["ok"] is True
    r = web.get("/")
    assert r.status_code == 200 and "Immich-Pflege" in r.text
    assert web.get("/static/app.js").status_code == 200
    # keine externen Ressourcen
    for f in ("/", "/static/app.js", "/static/app.css", "/sw.js", "/static/manifest.webmanifest"):
        text = web.get(f).text
        assert not re.search(r'(src|href)\s*=\s*["\']https?://', text), f
        assert "url(http" not in text and "@import" not in text


def test_status_and_scan(web):
    st = web.get("/api/status").json()
    assert st["server"]["version"] == "3.2.4" and st["bibliothek"] is None
    r = web.post("/api/scan")
    assert r.status_code == 200 and r.json()["gesamt"] == 12
    st = web.get("/api/status?server=false").json()
    assert st["bibliothek"]["gesamt"] == 12 and "server" not in st


def test_scan_in_background(web):
    r = web.post("/api/scan", json={"wait": False})
    assert r.status_code == 202
    web.app.state.scan_thread.join(10)
    assert web.get("/api/status?server=false").json()["bibliothek"]["gesamt"] == 12


def test_duplicates_paging_and_apply(web, state):
    r = web.get("/api/duplicates?limit=2").json()
    assert r["gesamt"] == 3 and len(r["gruppen"]) == 2
    rest = web.get("/api/duplicates?offset=2&limit=2").json()
    assert len(rest["gruppen"]) == 1
    groups = r["gruppen"] + rest["gruppen"]
    sel = [{"id": g["id"]} for g in groups]

    preview = web.post("/api/duplicates/apply", json={"action": "papierkorb", "groups": sel, "dry_run": True}).json()
    assert preview["vorschau"] and preview["papierkorb"] == 2

    r = web.post("/api/duplicates/apply", json={"action": "papierkorb", "groups": sel})
    assert r.status_code == 400 and "PAPIERKORB" in r.json()["fehler"]
    r = web.post("/api/duplicates/apply", json={"action": "papierkorb", "groups": sel, "confirm": "ja"})
    assert r.status_code == 400
    assert not any(c[0] == "DELETE" for c in state.calls)

    r = web.post("/api/duplicates/apply", json={"action": "papierkorb", "groups": sel, "confirm": "PAPIERKORB"})
    assert r.status_code == 200 and r.json()["ergebnis"]["papierkorb"] == 2


def test_duplicates_apply_validation(web):
    assert web.post("/api/duplicates/apply", json={"action": "album"}).status_code == 400
    assert web.post("/api/duplicates/apply", json={"action": "loeschen", "all": True}).status_code == 422
    r = web.post("/api/duplicates/apply", json={"action": "album", "groups": [{"id": "gibtsnicht"}]})
    assert r.status_code == 400 and "nicht gefunden" in r.json()["fehler"]
    g = web.get("/api/duplicates").json()["gruppen"][0]
    r = web.post("/api/duplicates/apply", json={"action": "album", "groups": [{"id": g["id"], "keep": "fremd"}]})
    assert r.status_code == 400


def test_album_all(web, state):
    r = web.post("/api/duplicates/apply", json={"action": "album", "all": True}).json()
    assert r["ergebnis"]["album"] == 3
    assert web.get("/api/duplicates").json()["offen"] == 0
    assert web.get("/api/duplicates?include_done=false").json()["gesamt"] == 0


def test_duplicate_filters_and_kinds(web):
    r = web.get("/api/duplicates").json()
    assert {k: v["anzahl"] for k, v in r["arten"].items()} == {"identisch": 1, "sehr_wahrscheinlich": 1, "format": 0, "bearbeitung": 0,
                                                                "raw_paar": 0, "aehnlich": 1}
    assert r["monate"] == [{"key": "2024-07", "name": "Juli 2024", "anzahl": 3}]
    assert web.get("/api/duplicates?art=identisch").json()["gesamt"] == 1
    assert web.get("/api/duplicates?benutzeruebergreifend=true").json()["gesamt"] == 1
    assert web.get("/api/duplicates?monat=2023-01").json()["gesamt"] == 0
    # Alle identischen auf einmal ins Prüf-Album
    plan = web.post("/api/duplicates/apply", json={"action": "album", "all": True, "art": "identisch",
                                                    "dry_run": True}).json()
    assert plan["gruppen"] == 1 and plan["album"] == 1


def test_raw_pairs_are_optional(web, state):
    state.add_asset("frank", "DSC0001.ARW", "2024-08-01T10:00:00.000Z", make="SONY", model="ILCE-7M4")
    state.add_asset("frank", "DSC0001.JPG", "2024-08-01T10:00:00.000Z", make="SONY", model="ILCE-7M4")
    web.post("/api/scan")
    r = web.get("/api/duplicates").json()
    assert r["gesamt"] == 4 and r["offen"] == 3  # RAW + JPG wird gezeigt, zählt aber nicht als offen
    assert r["arten"]["raw_paar"]["anzahl"] == 1
    plan = web.post("/api/duplicates/apply", json={"action": "album", "all": True, "dry_run": True}).json()
    assert plan["gruppen"] == 3  # „Alle“ ohne Art lässt RAW + JPG aus
    plan = web.post("/api/duplicates/apply", json={"action": "album", "all": True, "art": "raw_paar",
                                                    "dry_run": True}).json()
    assert plan["gruppen"] == 1
    assert web.get("/api/duplicates?art=raw_paar").json()["offen"] == 1


def test_not_a_duplicate(web, state):
    r = web.get("/api/duplicates?art=aehnlich").json()
    gid = r["gruppen"][0]["id"]
    res = web.post("/api/duplicates/ignore", json={"groups": [gid]}).json()
    assert res["in_immich_entfernt"] == 2
    # in Immich (Mock) ist die duplicateId weg
    assert not any(a["duplicateId"] for a in state.assets.values())
    r = web.get("/api/duplicates").json()
    assert r["gesamt"] == 2 and r["ignoriert"] == 0  # Immich-Gruppe existiert nicht mehr
    # Prüfsummen-Gruppe ausblenden und wieder aufnehmen
    gid = r["gruppen"][0]["id"]
    web.post("/api/duplicates/ignore", json={"groups": [gid]})
    r = web.get("/api/duplicates").json()
    assert r["gesamt"] == 1 and r["ignoriert"] == 1
    assert web.get("/api/duplicates?ignoriert=true").json()["gruppen"][0]["id"] == gid
    web.post("/api/duplicates/ignore", json={"groups": [gid], "undo": True})
    assert web.get("/api/duplicates").json()["gesamt"] == 2
    assert web.post("/api/duplicates/ignore", json={"groups": ["x"]}).status_code == 400


def test_no_location(web):
    r = web.get("/api/no-location").json()
    assert r["medien"] == 7 and r["screenshots_ausgeblendet"] == 1 and r["mit_vorschlag"] == 3
    assert r["nach_sicherheit"] == {"hoch": 2, "mittel": 1, "niedrig": 0}
    assert r["serien_gesamt"] == 5
    assert web.get("/api/no-location?max_hours=4").json()["mit_vorschlag"] == 4
    only_sure = web.get("/api/no-location?min_confidence=hoch").json()
    assert only_sure["serien_gesamt"] == 2

    serie = next(s for s in r["serien"] if s["anzahl"] == 2 and s["vorschlag"])
    res = web.post("/api/no-location/apply", json={"series": [serie["id"]]}).json()
    assert res["aktualisiert"] == 2
    assert web.get("/api/no-location").json()["medien"] == 5
    assert web.post("/api/no-location/apply", json={}).status_code == 400
    assert web.post("/api/no-location/apply", json={"series": ["gibtsnicht"]}).status_code == 400

    res = web.post("/api/no-location/apply", json={"min_confidence": "hoch"}).json()
    assert res["aktualisiert"] == 1  # IMG_0200 2.JPG


def test_no_location_manual_place_and_search(web, state):
    r = web.get("/api/no-location").json()
    camera = next(s for s in r["serien"] if s["anzahl"] == 2 and not s["vorschlag"])  # DSC09812
    body = {"series": [camera["id"]], "place": {"breite": 43.4642, "laenge": 11.0413, "name": "San Gimignano"}}
    res = web.post("/api/no-location/apply", json=body).json()
    assert res["aktualisiert"] == 1 and res["uebersprungen"] == []  # externe Kopie wird nicht ausgewählt
    places = web.get("/api/places?q=san gim").json()
    assert places[0] == {"name": "San Gimignano", "region": "Siena, Toskana", "breite": 43.4677, "laenge": 11.0432}
    assert web.get("/api/places?q=s").json() == []
    bad = {"ids": ["x"], "place": {"breite": 99, "laenge": 0}}
    assert web.post("/api/no-location/apply", json=bad).status_code == 422


def test_no_location_by_place(web):
    over = web.get("/api/no-location?overview=true").json()
    assert "serien" not in over
    names = [(o["name"], o["anzahl"]) for o in over["orte"]]
    assert names[0] == ("San Gimignano, Italien", 2) and names[-1] == ("Ohne Vorschlag", 4)
    assert [m["name"] for m in over["monate"]] == ["Juli 2024"]

    key = over["orte"][0]["key"]
    r = web.get("/api/no-location", params={"ort": key}).json()
    assert r["serien_gesamt"] == 1 and r["medien_gefiltert"] == 2
    assert r["filter"] == {"ort": key, "monat": None}
    assert web.get("/api/no-location", params={"ort": "~ohne"}).json()["medien_gefiltert"] == 4
    assert web.get("/api/no-location", params={"monat": "2024-06"}).json()["serien_gesamt"] == 0

    res = web.post("/api/no-location/apply", json={"ort": key}).json()
    assert res["aktualisiert"] == 2
    assert all(o["key"] != key for o in web.get("/api/no-location?overview=true").json()["orte"])
    assert web.post("/api/no-location/apply", json={"ort": "gibtsnicht"}).status_code == 400


def test_manual_place_for_whole_group(web):
    body = {"ort": "~ohne", "monat": "2024-07", "place": {"breite": 43.3188, "laenge": 11.3308, "name": "Siena"}}
    res = web.post("/api/no-location/apply", json=body).json()
    assert res["aktualisiert"] == 2  # DSC09812 (Upload) + DSC10002; externe bleiben gesperrt
    over = web.get("/api/no-location?overview=true").json()
    # Die externe DSC09812-Kopie hat nun über ihre verortete Upload-Kopie einen Vorschlag
    assert next(o for o in over["orte"] if o["key"] == "~ohne")["anzahl"] == 1  # nur DSC20000


def test_settings_screenshots_toggle(web):
    web.put("/api/settings", json={"location_skip_screenshots": False})
    assert web.get("/api/no-location").json()["medien"] == 8


def test_tags_endpoints(web, settings):
    assert web.get("/api/tags").json()["regeln"] == []  # noch keine Regeldatei
    settings.rules_file.parent.mkdir(parents=True, exist_ok=True)
    settings.rules_file.write_text("regeln:\n  - name: Sony\n    tag: Kamera/Sony\n    hersteller: SONY\n"
                                   "  - name: Shots\n    tag: Screens\n    dateiname: '^Screenshot'\n")
    prev = web.get("/api/tags").json()
    assert [p["neu"] for p in prev["regeln"]] == [6, 1]
    only = web.get("/api/tags?rules=Shots").json()
    assert [p["name"] for p in only["regeln"]] == ["Shots"]
    res = web.post("/api/tags/apply", json={"rules": ["Sony"]}).json()
    assert res["getaggt"] == 6
    assert web.post("/api/tags/apply", json={"rules": ["Gibts nicht"]}).status_code == 400


def test_thumbnail_proxy(web, state):
    aid = next(iter(state.assets))
    r = web.get(f"/thumb/{aid}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")
    assert "key-" not in r.text
    assert web.get("/thumb/../../etc").status_code in (400, 404)
    assert web.get("/thumb/nicht-uuid").status_code == 400


def test_immich_down_gives_502(env):
    import httpx

    def boom(request):
        raise httpx.ConnectError("weg")
    with TestClient(create_app(env, http=httpx.Client(transport=httpx.MockTransport(boom)))) as c:
        r = c.get("/api/duplicates")
        assert r.status_code == 502 and "nicht erreichbar" in r.json()["fehler"]
        st = c.get("/api/status").json()
        assert st["server"]["erreichbar"] is False


def test_basic_auth(env, http):
    env = {**env, "WEB_USER": "frank", "WEB_PASSWORD": "geheim"}
    with TestClient(create_app(env, http=http)) as c:
        assert c.get("/healthz").status_code == 200
        r = c.get("/api/status")
        assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
        assert c.get("/", auth=("frank", "falsch")).status_code == 401
        assert c.get("/api/status?server=false", auth=("frank", "geheim")).status_code == 200
        bad = base64.b64encode(b"\xff\xfe").decode()
        assert c.get("/", headers={"Authorization": "Basic " + bad}).status_code == 401
