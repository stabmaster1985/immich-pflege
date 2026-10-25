"""Alben aufräumen: doppelt, fast gleich, leer, mini."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web.app import create_app
from tests.mock_immich import MockState


def care_state() -> MockState:
    s = MockState()
    s.add_user("frank", "key-frank")
    s.add_user("julia", "key-julia")
    f = [s.add_asset("frank", f"F{i}.HEIC", f"2024-07-1{i}T10:00:00.000Z") for i in range(6)]
    j = [s.add_asset("julia", f"J{i}.HEIC", f"2024-07-1{i}T11:00:00.000Z") for i in range(5)]
    s.ids = {"f": f, "j": j}
    s.ids["frank_tosk"] = s.add_album("frank", "Toskana 2024", f[:4])
    s.ids["julia_tosk"] = s.add_album("julia", "toskana  2024", j[:3])  # gleicher Name, andere Schreibweise
    s.ids["gross"] = s.add_album("frank", "Sommer", f)
    s.ids["teil"] = s.add_album("frank", "Sommer Best of", f[:5])
    s.ids["leer"] = s.add_album("julia", "Neues Album")
    s.ids["mini"] = s.add_album("julia", "Test", j[3:4])
    return s


@pytest.fixture
def state():
    return care_state()


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def by_art(r):
    return {it["art"]: it for it in r["eintraege"]}


def test_finds_issues(web, state):
    r = web.get("/api/album-care").json()
    items = by_art(r)
    assert {a["name"] for a in items["doppelt"]["alben"]} == {"Toskana 2024", "toskana  2024"}
    assert {a["name"] for a in items["ueberlappend"]["alben"]} == {"Sommer", "Sommer Best of"}
    assert items["ueberlappend"]["ziel"] == state.ids["gross"]
    assert items["leer"]["alben"][0]["name"] == "Neues Album"
    assert items["mini"]["alben"][0]["name"] == "Test"
    assert r["arten"]["doppelt"]["anzahl"] == 1


def test_merge_across_users_and_undo(web, state):
    item = by_art(web.get("/api/album-care").json())["doppelt"]
    web.post("/api/staged/album-care", json={"id": item["id"], "aktion": "zusammenfuehren", "ziel": state.ids["frank_tosk"]})
    entry = web.get("/api/staged").json()["eintraege"][0]
    assert entry["typ"] == "albenpflege" and "geteilt mit julia" in entry["titel"]
    assert "doppelt" not in by_art(web.get("/api/album-care").json())
    web.post("/api/staged/apply", json={})
    target = state.albums[state.ids["frank_tosk"]]
    assert target["members"] == {state.user_id("julia"): "editor"}
    assert state.asset_ids_in_album(target["id"]) == set(state.ids["f"][:4] + state.ids["j"][:3])
    assert state.ids["julia_tosk"] not in state.albums  # zusammengeführt und gelöscht
    e = web.get("/api/history").json()["eintraege"][0]
    assert web.post(f"/api/history/{e['id']}/undo").json()["fehler"] == []
    assert state.asset_ids_in_album(target["id"]) == set(state.ids["f"][:4]) and target["members"] == {}
    restored = [a for a in state.albums.values() if a["albumName"] == "toskana  2024"]
    assert len(restored) == 1 and restored[0]["ownerId"] == state.user_id("julia")
    assert state.asset_ids_in_album(restored[0]["id"]) == set(state.ids["j"][:3])


def test_delete_empty_and_keep(web, state):
    items = by_art(web.get("/api/album-care").json())
    web.post("/api/staged/album-care", json={"id": items["leer"]["id"], "aktion": "loeschen"})
    web.post("/api/cleanup/keep", json={"ids": [items["mini"]["id"]]})
    after = by_art(web.get("/api/album-care").json())
    assert "leer" not in after and "mini" not in after
    web.post("/api/staged/apply", json={})
    assert state.ids["leer"] not in state.albums
    assert web.post("/api/staged/album-care", json={"id": items["leer"]["id"], "aktion": "zusammenfuehren"}).status_code == 400



@pytest.mark.parametrize("timeline_ok", [True, False])
def test_album_with_partner_photos_is_not_empty(web, state, monkeypatch, timeline_ok):
    """Franks Album, nicht geteilt, nur mit Julias Fotos (über die Partnerfreigabe hineingelegt):
    nie „leer“ – auch nicht, wenn sich der Inhalt nicht lesen lässt (Immichs Zählung zählt mit)."""
    from immich_pflege.client import ImmichClient, ImmichError

    if not timeline_ok:
        def broken(self, album_id):
            raise ImmichError("kaputt")
        monkeypatch.setattr(ImmichClient, "album_timeline_ids", broken)
    album = state.add_album("frank", "Julias Garten", state.ids["j"][:4])
    items = web.get("/api/album-care").json()["eintraege"]
    garten = [it for it in items if any(a["id"] == album for a in it["alben"])]
    assert all(it["art"] not in ("leer", "mini") for it in garten)
