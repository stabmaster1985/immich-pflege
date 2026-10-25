from fastapi.testclient import TestClient

from immich_pflege.imagehash import HashStore, dhash, distance, may_pair, similar_pairs
from immich_pflege.library import scan_library
from immich_pflege.service import Pflege
from immich_pflege.web.app import create_app
from tests.mock_immich import render_thumbnail

from .helpers import asset, library


def test_dhash_robust_against_resize():
    a = dhash(render_thumbnail("motiv-1"))
    small = dhash(render_thumbnail("motiv-1", width=1000))  # verkleinert + stärker komprimiert
    other = dhash(render_thumbnail("motiv-2"))
    assert distance(a, small) <= 6
    assert distance(a, other) > 12


def test_may_pair_rules():
    phone = asset(make="Apple", model="iPhone 15 Pro")
    burst = asset(make="Apple", model="iPhone 15 Pro")
    whatsapp = asset(owner="julia", make=None, model=None)
    same_user_wa = asset(make=None, model=None)
    assert not may_pair(phone, burst)  # Serienbild desselben Handys
    assert may_pair(phone, whatsapp)  # anderer Benutzer
    assert may_pair(phone, same_user_wa)  # Kopie ohne Kameradaten
    assert not may_pair(asset(checksum="x"), asset(checksum="x", owner="julia"))  # identisch: Prüfsumme


def test_similar_pairs_and_store(tmp_path):
    a = asset(make="Apple")
    b = asset(owner="julia", make=None, model=None)
    c = asset(owner="julia")
    store = HashStore(tmp_path / "h.json")
    store.put(a, 0xF0F0F0F0F0F0F0F0)
    store.put(b, 0xF0F0F0F0F0F0F0F1)  # 1 Bit Unterschied
    store.put(c, 0x0F0F0F0F0F0F0F0F)
    store.save()
    again = HashStore(tmp_path / "h.json")
    assert similar_pairs(library(a, b, c), again) == [tuple(sorted((a.id, b.id)))]
    # geänderte Prüfsumme -> Fingerabdruck ungültig
    a.checksum = "neu"
    assert again.get(a) is None and len(again.missing(library(a, b, c))) == 1


def test_whatsapp_copy_found_across_users(settings, http, state):
    settings.dup_image_hash = True
    original = state.add_asset("frank", "IMG_0400.HEIC", "2024-07-18T10:00:00.000Z", image="pizza",
                               lat=43.77, lon=11.25, city="Florenz", country="Italien")
    copy = state.add_asset("julia", "IMG-20240718-WA0003.jpg", "2024-07-18T19:30:00.000Z", image="pizza",
                           make=None, model=None, width=1600, height=1200, size=180_000)
    svc = Pflege(settings, http=http)
    svc.library()
    svc._hash_thread and svc._hash_thread.join(10)  # Einlesen startet die Berechnung im Hintergrund
    status = svc.hash_status()
    assert status["fehlend"] == 0 and status["fehler"] == 0
    groups = [g for g in svc.duplicate_groups() if {original, copy} <= g.asset_ids]
    assert len(groups) == 1
    g = groups[0]
    assert g.sources == {"bildhash"} and g.kind == "sehr_wahrscheinlich"
    assert g.suggested_keep == original  # GPS + höhere Auflösung
    # keine Fehlalarme: die übrigen Demo-Bilder haben eigene Motive
    assert sum(1 for gr in svc.duplicate_groups() if "bildhash" in gr.sources) == 1


def test_fingerprint_endpoint(env, http):
    with TestClient(create_app(env, http=http)) as c:
        assert c.post("/api/fingerprints/start").status_code == 400  # in env abgeschaltet
        assert c.get("/api/duplicates").json()["fingerabdruck"]["aktiv"] is False
