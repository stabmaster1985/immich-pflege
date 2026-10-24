import base64

import pytest
from fastapi.testclient import TestClient

from immich_pflege.service import Pflege
from immich_pflege.web.app import create_app


@pytest.fixture
def web(settings, http):
    with TestClient(create_app(Pflege(settings, http=http))) as c:
        yield c


def test_healthz_and_ui(web):
    assert web.get("/healthz").json()["ok"] is True
    r = web.get("/")
    assert r.status_code == 200 and "Immich-Pflege" in r.text
    assert web.get("/static/app.js").status_code == 200
    # keine externen Ressourcen
    for f in ("/", "/static/app.js", "/static/app.css"):
        assert "https://" not in web.get(f).text


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


def test_no_location(web):
    r = web.get("/api/no-location").json()
    assert r["medien"] == 8 and r["mit_vorschlag"] == 3
    day = next(d for d in r["tage"] if d["datum"] == "2024-07-16")
    ids = [m["id"] for m in day["medien"] if m["vorschlag"]]
    wider = web.get("/api/no-location?max_hours=4").json()
    assert wider["mit_vorschlag"] == 4
    res = web.post("/api/no-location/apply", json={"ids": ids}).json()
    assert res["aktualisiert"] == len(ids)
    assert web.get("/api/no-location").json()["medien"] == 8 - len(ids)
    assert web.post("/api/no-location/apply", json={"ids": []}).status_code == 400


def test_tags_endpoints(web, settings):
    r = web.get("/api/tags")
    assert r.status_code == 422 and "nicht gefunden" in r.json()["details"][0]
    settings.rules_file.parent.mkdir(parents=True)
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


def test_immich_down_gives_502(settings):
    import httpx

    def boom(request):
        raise httpx.ConnectError("weg")
    svc = Pflege(settings, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with TestClient(create_app(svc)) as c:
        r = c.get("/api/duplicates")
        assert r.status_code == 502 and "nicht erreichbar" in r.json()["fehler"]
        st = c.get("/api/status").json()
        assert st["server"]["erreichbar"] is False


def test_basic_auth(settings, http):
    settings.web_user, settings.web_password = "frank", "geheim"
    with TestClient(create_app(Pflege(settings, http=http))) as c:
        assert c.get("/healthz").status_code == 200
        r = c.get("/api/status")
        assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]
        assert c.get("/", auth=("frank", "falsch")).status_code == 401
        assert c.get("/api/status?server=false", auth=("frank", "geheim")).status_code == 200
        bad = base64.b64encode(b"\xff\xfe").decode()
        assert c.get("/", headers={"Authorization": "Basic " + bad}).status_code == 401
