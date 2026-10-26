"""Ohne Ort: Herkunft erkennen (Kamera, Messenger, ohne Kameradaten, Screenshot) und „kein Ort nötig“."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.location import origin
from immich_pflege.models import Asset
from immich_pflege.web.app import create_app
from tests.mock_immich import demo_state


def asset(name, make=None, model=None, w=4032, h=3024, typ="IMAGE"):
    return Asset(id=name, owner="frank", checksum=name, file_name=name, path=name, local_date_time=None,
                 file_created_at=None, library_id=None, type=typ, make=make, model=model, width=w, height=h)


def test_classify():
    assert origin(asset("Screenshot 2024-07-20.png")) == "screenshot"
    assert origin(asset("IMG_1234.PNG")) == "screenshot"  # iPhone-PNG ohne Kameradaten
    # markiert und als JPG gespeichert: nur noch an der Bildschirmgröße zu erkennen (auch quer)
    assert origin(asset("IMG_4321.JPG", w=1179, h=2556)) == "screenshot"
    assert origin(asset("IMG_4322.JPG", w=2532, h=1170)) == "screenshot"
    assert origin(asset("IMG_4323.JPG", "Apple", "iPhone 15 Pro", 1179, 2556)) == "kamera"  # echtes Foto
    assert origin(asset("clip.mp4", w=1080, h=1920, typ="VIDEO")) == "ohne_kamera"  # Videos nicht über die Größe
    assert origin(asset("IMG-20240716-WA0001.jpg", w=1200, h=1600)) == "messenger"
    assert origin(asset("signal-2024-07-16-101010.jpg", w=1200, h=1600)) == "messenger"
    assert origin(asset("meme.jpg", w=800, h=600)) == "ohne_kamera"
    assert origin(asset("DSC0001.JPG", "SONY", "ILCE-7M4")) == "kamera"


def origin_state():
    s = demo_state()
    s.ids = {
        "shot_jpg": s.add_asset("julia", "IMG_4321.JPG", "2024-07-16T12:40:00.000Z", make=None, model=None,
                                width=1179, height=2556),
        "wa": s.add_asset("julia", "IMG-20240716-WA0001.jpg", "2024-07-16T12:45:00.000Z", make=None, model=None,
                          width=1200, height=1600),
        "meme": s.add_asset("frank", "meme.jpg", "2024-07-16T12:50:00.000Z", make=None, model=None,
                            width=800, height=600),
    }
    return s


@pytest.fixture
def state():
    return origin_state()


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def test_counts_filter_and_hide(web, state):
    r = web.get("/api/no-location").json()
    assert r["screenshots_ausgeblendet"] == 2  # Screenshot.png und das JPG in Bildschirmgröße
    assert {k: v["anzahl"] for k, v in r["herkunft"].items()} == {"kamera": 7, "dokument": 0, "messenger": 1, "ohne_kamera": 1,
                                                                  "screenshot": 0}
    wa = web.get("/api/no-location", params={"herkunft": "messenger"}).json()
    assert any(m["id"] == state.ids["wa"] for s in wa["serien"] for m in s["medien"])
    media = web.get("/api/no-location/origin-media", params={"herkunft": "ohne_kamera"}).json()["medien"]
    assert [m["id"] for m in media] == [state.ids["meme"]]
    # „kein Ort nötig“: verschwindet aus Liste, Zählung und „alle sicheren“
    web.post("/api/no-location/no-place", json={"ids": [state.ids["meme"], state.ids["wa"]]})
    r = web.get("/api/no-location").json()
    assert r["kein_ort_ausgeblendet"] == 2 and r["herkunft"]["messenger"]["anzahl"] == 0
    loc = web.get("/api/no-location/media", params={"min_confidence": "niedrig"}).json()["medien"]
    assert not {m["id"] for m in loc} & {state.ids["meme"], state.ids["wa"]}
    hidden = {m["id"]: m["grund"] for m in web.get("/api/no-location/hidden").json()["medien"]}
    assert hidden[state.ids["meme"]] == "kein_ort" and hidden[state.ids["shot_jpg"]] == "screenshot"
    # zurückholen: auch ein falsch erkannter Screenshot lässt sich einblenden
    web.post("/api/no-location/no-place", json={"ids": [state.ids["meme"], state.ids["shot_jpg"]], "undo": True})
    r = web.get("/api/no-location").json()
    assert r["kein_ort_ausgeblendet"] == 1 and r["screenshots_ausgeblendet"] == 1
    assert r["herkunft"]["screenshot"]["anzahl"] == 1 and r["herkunft"]["ohne_kamera"]["anzahl"] == 1
    assert web.get("/api/no-location", params={"herkunft": "quatsch"}).status_code == 422


def test_filter_within_place(web, state):
    """Im Ort zählt und filtert die Herkunft nur dort; Vormerken nimmt nur die gefilterte Herkunft."""
    overview = web.get("/api/no-location", params={"overview": True}).json()
    sg = next(o for o in overview["orte"] if "gimignano" in o["key"])
    r = web.get("/api/no-location", params={"ort": sg["key"]}).json()
    counts = {k: v["anzahl"] for k, v in r["herkunft"].items()}
    assert counts["messenger"] == 1 and counts["ohne_kamera"] == 1 and counts["kamera"] >= 1
    assert sum(counts.values()) == r["medien_gefiltert"]  # die Zahlen gehören zu diesem Ort
    only = web.get("/api/no-location", params={"ort": sg["key"], "herkunft": "messenger"}).json()
    members = [m for s in only["serien"] for m in s["medien"]]
    assert [m["id"] for m in members] == [state.ids["wa"]] and only["medien_gefiltert"] == 1
    media = web.get("/api/no-location/origin-media", params={"herkunft": "ohne_kamera", "ort": sg["key"]}).json()["medien"]
    assert [m["id"] for m in media] == [state.ids["meme"]]
    res = web.post("/api/staged/no-location", json={"ort": sg["key"], "herkunft": "messenger", "label": "Test"}).json()
    assert res["vorgemerkt"] == 1
    staged = web.get("/api/staged").json()["eintraege"][0]
    assert staged["daten"]["aenderungen"][0]["asset_id"] == state.ids["wa"]


def box(x, y, w, h, text):
    return {"x1": x, "y1": y, "x2": x + w, "y2": y, "x3": x + w, "y3": y + h, "x4": x, "y4": y + h, "text": text,
            "textScore": 0.9}


def test_text_stats():
    from immich_pflege.textscan import is_document, text_stats

    doc = text_stats([box(0.1, 0.1 + i * 0.05, 0.8, 0.03, "Rechnung Nr. 4711 Betrag") for i in range(10)])
    assert doc["f"] == pytest.approx(0.24, abs=0.001) and is_document(doc) and doc["t"].startswith("Rechnung")
    sign = text_stats([box(0.4, 0.4, 0.1, 0.03, "Ausgang")])  # Schild im Urlaubsfoto
    assert not is_document(sign)
    shaky = text_stats([{**box(0, 0, 1, 1, "xx"), "textScore": 0.1}])  # unsicher: zählt nicht
    assert shaky["f"] == 0 and not is_document(shaky)
    assert not is_document(None)


def test_documents_by_text(web, state, env, http):
    """Foto eines Dokuments mit Kameradaten: über die Texterkennung als „Dokumente & Text“ erkannt."""
    doc = state.add_asset("frank", "IMG_7777.HEIC", "2024-07-16T12:42:00.000Z")  # Apple iPhone, ohne GPS
    state.assets[doc]["_ocr"] = [box(0.1, 0.1 + i * 0.06, 0.8, 0.04, "Mietvertrag Seite 1 Paragraph") for i in range(8)]
    sign = state.add_asset("frank", "IMG_7778.HEIC", "2024-07-16T12:43:00.000Z")
    state.assets[sign]["_ocr"] = [box(0.4, 0.4, 0.1, 0.03, "Ausgang")]
    web.post("/api/scan")
    svc = web.app.state.service
    res = svc.fetch_texts()
    assert res["mit_text"] == 1 and res["fehler"] == 0
    asked = [c[1] for c in state.calls if c[1].endswith("/ocr")]
    assert f"/api/assets/{doc}/ocr" in asked and len(asked) == res["gesamt"]  # nur Bilder ohne Ort
    r = web.get("/api/no-location").json()
    assert r["herkunft"]["dokument"]["anzahl"] == 1
    only = web.get("/api/no-location", params={"herkunft": "dokument"}).json()

    members = [m for s in only["serien"] for m in s["medien"]]
    assert [m["id"] for m in members] == [doc] and members[0]["text"].startswith("Mietvertrag")
    # zweites Mal: alles im Zwischenspeicher, keine neuen Anfragen
    before = len(state.calls)
    assert svc.fetch_texts()["gesamt"] == 0 and len(state.calls) == before


def test_herkunft_types_match():
    """Die API kennt genau die Herkünfte, die location.HERKUNFT kennt."""
    import typing
    from immich_pflege.location import HERKUNFT
    from immich_pflege.web.app import Herkunft
    assert set(typing.get_args(Herkunft)) == set(HERKUNFT)


def test_archived_hidden_and_restorable(web, state):
    """In Immich archivierte Medien ohne Ort sind ausgeblendet – einzeln wieder einblendbar."""
    arch = state.add_asset("frank", "IMG_9999.HEIC", "2024-07-16T12:41:00.000Z", visibility="archive")
    r = web.get("/api/no-location").json()
    assert r["archiviert_ausgeblendet"] == 1
    all_ids = {m["id"] for m in web.get("/api/no-location/origin-media", params={"herkunft": "kamera"}).json()["medien"]}
    assert arch not in all_ids
    hidden = {m["id"]: m["grund"] for m in web.get("/api/no-location/hidden").json()["medien"]}
    assert hidden[arch] == "archiviert"
    web.post("/api/no-location/no-place", json={"ids": [arch], "undo": True})
    r = web.get("/api/no-location").json()
    assert r["archiviert_ausgeblendet"] == 0
    assert arch in {m["id"] for m in web.get("/api/no-location/origin-media", params={"herkunft": "kamera"}).json()["medien"]}


def test_filter_by_user(web, state):
    """Nur Franks oder nur Julias Bilder: Zahlen, Serien, Prüf-Listen und Vormerken."""
    r = web.get("/api/no-location").json()
    assert set(r["benutzer"]) == {"frank", "julia"} and sum(r["benutzer"].values()) == r["medien_gefiltert"]
    julia = web.get("/api/no-location", params={"benutzer": "julia"}).json()
    members = [m for s in julia["serien"] for m in s["medien"]]
    assert members and all(m["benutzer"] == "julia" for m in members)
    assert julia["medien_gefiltert"] == r["benutzer"]["julia"]
    # Herkunft zählt passend zum Benutzer: das WhatsApp-Bild gehört Julia, der Download Frank
    assert julia["herkunft"]["messenger"]["anzahl"] == 1 and julia["herkunft"]["ohne_kamera"]["anzahl"] == 0
    frank = web.get("/api/no-location/origin-media", params={"herkunft": "ohne_kamera", "benutzer": "frank"}).json()
    assert [m["id"] for m in frank["medien"]] == [state.ids["meme"]]
    sure_frank = web.get("/api/no-location/media", params={"min_confidence": "niedrig", "benutzer": "frank"}).json()
    assert sure_frank["medien"] and all(m["benutzer"] == "frank" for m in sure_frank["medien"])
    sg = next(o for o in web.get("/api/no-location", params={"overview": True}).json()["orte"] if "gimignano" in o["key"])
    res = web.post("/api/staged/no-location", json={"ort": sg["key"], "benutzer": "frank", "label": "Test"}).json()
    staged = web.get("/api/staged").json()["eintraege"][0]["daten"]["aenderungen"]
    assert res["vorgemerkt"] == len(staged) and all(ch["owner"] == "frank" for ch in staged)
    assert web.get("/api/no-location", params={"benutzer": "gibtsnicht"}).status_code == 400
