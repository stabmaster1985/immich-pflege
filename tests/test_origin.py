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
    assert {k: v["anzahl"] for k, v in r["herkunft"].items()} == {"kamera": 7, "messenger": 1, "ohne_kamera": 1,
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
