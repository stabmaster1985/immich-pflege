"""Selbsttest: alle genutzten Immich-Schnittstellen nur lesend – je Benutzer."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        c.get("/api/duplicates")  # einlesen: Testobjekte
        yield c


def test_selftest_all_green_and_read_only(web, state):
    state.add_person("frank", "Julia", [])
    before = len([c for c in state.calls if c[0] in ("PUT", "DELETE") or (c[0] == "POST" and c[1] != "/api/search/metadata"
                                                                           and c[1] != "/api/search/smart")])
    r = web.post("/api/selftest").json()
    assert set(r["benutzer"]) == {"frank", "julia"}
    frank = r["benutzer"]["frank"]
    bad = [c for c in frank["lesen"] if c["ok"] is False]
    assert not bad, bad
    assert {c["name"] for c in frank["lesen"]} >= {"Vorschaubild", "Original", "Personen", "Speicherplatz", "Texterkennung"}
    assert all(w["ok"] for w in frank["schreiben"]) and frank["rechte_bekannt"] is True
    after = len([c for c in state.calls if c[0] in ("PUT", "DELETE") or (c[0] == "POST" and c[1] != "/api/search/metadata"
                                                                          and c[1] != "/api/search/smart")])
    assert after == before  # nichts verändert
    assert r["mqtt"]["aktiv"] is False


def test_selftest_reports_missing_permission(web, state):
    state.key_permissions["julia"] = ["asset.read"]
    r = web.post("/api/selftest").json()
    julia = r["benutzer"]["julia"]
    thumb = next(c for c in julia["lesen"] if c["name"] == "Vorschaubild")
    assert thumb["ok"] is False and "asset.view" in thumb["detail"]
    assert next(w for w in julia["schreiben"] if w["recht"] == "asset.update")["ok"] is False
    assert r["fehler"] >= 2 and r["benutzer"]["frank"]["fehler"] == 0
