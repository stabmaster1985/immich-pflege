"""Alben aus Ordnern der externen Bibliothek."""

import pytest
from fastapi.testclient import TestClient

from immich_pflege.folders import folder_name
from immich_pflege.web.app import create_app
from tests.mock_immich import MockState


def ext(s, owner, folder, n, start=0):
    return [s.add_asset(owner, f"DSC{start + i:04d}.JPG", f"2019-07-{10 + i % 9:02d}T10:00:00.000Z", library=True,
                        make="SONY", model="ILCE-7M4", path=f"{folder}/DSC{start + i:04d}.JPG") for i in range(n)]


def folder_state() -> MockState:
    s = MockState()
    s.add_user("frank", "key-frank")
    s.add_user("julia", "key-julia")
    s.ids = {"tosk": ext(s, "frank", "/mnt/fotos/2019 Toskana", 6),
             "hochzeit": ext(s, "frank", "/mnt/fotos/Hochzeit", 5, 100),
             "klein": ext(s, "frank", "/mnt/fotos/Einzeln", 2, 200)}
    s.ids["album"] = s.add_album("frank", "Hochzeit", s.ids["hochzeit"][:2])
    s.add_asset("frank", "IMG_0001.HEIC", "2024-01-01T10:00:00.000Z")  # Upload, kein Ordner-Album
    return s


@pytest.fixture
def state():
    return folder_state()


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def test_names():
    assert folder_name("/mnt/fotos/2019 Toskana") == "2019 Toskana"
    assert folder_name("/mnt/fotos/Toskana/2019") == "Toskana 2019"
    assert folder_name("/mnt/sd/DCIM/100MSDCF") == "100MSDCF"
    assert folder_name("/mnt/fotos") == "fotos"  # Einhängepunkt gehört nicht in den Namen


def test_proposals(web):
    r = web.get("/api/folder-albums").json()
    by = {p["ordner"]: p for p in r["ordner"]}
    assert set(by) == {"/mnt/fotos/2019 Toskana", "/mnt/fotos/Hochzeit"}  # zu kleine Ordner nicht
    assert by["/mnt/fotos/2019 Toskana"]["status"] == "neu" and by["/mnt/fotos/2019 Toskana"]["name"] == "2019 Toskana"
    assert by["/mnt/fotos/Hochzeit"]["status"] == "ergaenzen" and by["/mnt/fotos/Hochzeit"]["fehlend"] == 3


def test_create_with_sync_then_new_files_follow(web, state):
    tosk = next(p for p in web.get("/api/folder-albums").json()["ordner"] if p["status"] == "neu")
    web.post("/api/staged/folder-albums", json={"ordner": [{"id": tosk["id"], "name": "Toskana 2019", "sync": True}]})
    assert web.get("/api/staged").json()["nach_typ"]["album"] == 1
    web.post("/api/staged/apply", json={})
    album = next(a for a in state.albums.values() if a["albumName"] == "Toskana 2019")
    assert state.asset_ids_in_album(album["id"]) == set(state.ids["tosk"])
    synced = web.get("/api/folder-albums", params={"status": "abgeglichen"}).json()["ordner"]
    assert synced[0]["album"]["name"] == "Toskana 2019"
    new = ext(state, "frank", "/mnt/fotos/2019 Toskana", 2, 300)
    web.post("/api/scan", json={})
    assert state.asset_ids_in_album(album["id"]) == set(state.ids["tosk"] + new)  # automatisch nachgezogen
    e = web.get("/api/history").json()["eintraege"][0]
    assert e["quelle"] == "automatisch" and e["anzahl"] == 2 and "Ordner-Abgleich" in e["titel"]
    web.post(f"/api/history/{e['id']}/undo")
    assert state.asset_ids_in_album(album["id"]) == set(state.ids["tosk"])


def test_extend_existing(web, state):
    hz = next(p for p in web.get("/api/folder-albums").json()["ordner"] if p["status"] == "ergaenzen")
    web.post("/api/staged/folder-albums", json={"ordner": [{"id": hz["id"]}]})
    web.post("/api/staged/apply", json={})
    assert state.asset_ids_in_album(state.ids["album"]) == set(state.ids["hochzeit"])
    assert web.get("/api/folder-albums").json()["ordner"] == [
        p for p in web.get("/api/folder-albums").json()["ordner"] if p["status"] == "neu"]


def test_review_and_exclude_also_for_sync(web, state):
    tosk = next(p for p in web.get("/api/folder-albums").json()["ordner"] if p["status"] == "neu")
    media = web.get(f"/api/folder-albums/{tosk['id']}/media").json()["medien"]
    assert {m["id"] for m in media} == set(state.ids["tosk"])
    off = state.ids["tosk"][:2]
    web.post("/api/staged/folder-albums", json={"ordner": [{"id": tosk["id"], "sync": True, "ohne": off}]})
    assert "2 abgewählt" in web.get("/api/staged").json()["eintraege"][0]["titel"]
    web.post("/api/staged/apply", json={})
    album = next(a for a in state.albums.values() if a["albumName"] == "2019 Toskana")
    assert state.asset_ids_in_album(album["id"]) == set(state.ids["tosk"][2:])
    new = ext(state, "frank", "/mnt/fotos/2019 Toskana", 1, 300)
    web.post("/api/scan", json={})  # Abgleich: Neue kommen dazu, Abgewählte nicht
    assert state.asset_ids_in_album(album["id"]) == set(state.ids["tosk"][2:] + new)
    hz = next(p for p in web.get("/api/folder-albums").json()["ordner"] if p["status"] == "ergaenzen")
    missing = web.get(f"/api/folder-albums/{hz['id']}/media", params={"album": state.ids["album"]}).json()["medien"]
    assert {m["id"] for m in missing} == set(state.ids["hochzeit"][2:])  # was schon im Album liegt, fehlt
    assert web.get("/api/folder-albums/ogibtsnicht/media").status_code == 400
