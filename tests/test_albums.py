"""Albumvorschläge: Reisen erkennen und mit vorhandenen Alben abgleichen."""

import json

import pytest
from fastapi.testclient import TestClient

from immich_pflege.albums import find_homes, suggest
from immich_pflege.config import Settings
from immich_pflege.service import Pflege
from immich_pflege.web.app import create_app
from tests.mock_immich import album_state

@pytest.fixture
def state():
    return album_state()


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def trip_named(trips, word):
    return next(t for t in trips if word in t["name"])


def test_home_and_trips(env, http):
    svc = Pflege(Settings.load(env), http=http)
    lib = svc.library()
    assert [h.name for h in find_homes(lib.assets.values(), 50)] == ["Hamburg"]
    homes, trips = suggest(lib, 50, 20)
    names = {t.name: t for t in trips}
    assert set(names) == {"Toskana, Juli 2024", "Kopenhagen, September 2024", "Wien, Mai 2024"}
    toskana = names["Toskana, Juli 2024"]
    assert len(toskana.assets) == 31  # inkl. der 6 Kamerafotos ohne GPS
    assert toskana.users == {"frank": 21, "julia": 10}
    assert toskana.status == "ergaenzen" and toskana.target.album["name"] == "Toskana 2024"
    assert names["Kopenhagen, September 2024"].status == "neu"
    assert names["Kopenhagen, September 2024"].users == {"frank": 25}  # Julias Hamburg-Fotos nicht
    assert names["Wien, Mai 2024"].status == "vorhanden"


def test_view_filters(web):
    r = web.get("/api/album-suggestions").json()
    assert r["zuhause"][0]["name"] == "Hamburg"
    assert r["status"] == {"neu": 1, "ergaenzen": 1, "vorhanden": 1} and r["offen"] == 2
    assert [t["name"] for t in r["reisen"]] == ["Kopenhagen, September 2024", "Toskana, Juli 2024"]
    tosk = r["reisen"][1]
    assert tosk["album"]["name"] == "Toskana 2024" and tosk["album"]["besitzer"] == "julia"
    assert tosk["fehlend"] == 26 and len(tosk["beispiele"]) == 8
    done = web.get("/api/album-suggestions", params={"status": "vorhanden"}).json()["reisen"]
    assert done[0]["name"] == "Wien, Mai 2024" and done[0]["album"]["geteilt_mit"] == ["julia"]


def test_stage_and_transfer_extends_and_shares(web, state):
    tid = trip_named(web.get("/api/album-suggestions").json()["reisen"], "Toskana")["id"]
    res = web.post("/api/staged/albums", json={"trips": [{"id": tid}]}).json()
    assert res["vorgemerkt"] == 1
    assert not [c for c in state.calls if c[0] in ("PUT", "POST") and "/albums" in c[1]]  # noch nichts
    assert [t["name"] for t in web.get("/api/album-suggestions").json()["reisen"]] == ["Kopenhagen, September 2024"]
    entry = web.get("/api/staged").json()["eintraege"][0]
    assert entry["typ"] == "album" and entry["daten"]["teilen"] == ["frank"]
    assert "geteilt mit frank" in entry["titel"]

    r = web.post("/api/staged/apply", json={}).json()
    assert r["uebertragen"] == 1, r
    album = next(a for a in state.albums.values() if a["albumName"] == "Toskana 2024")
    assert album["members"] == {state.user_id("frank"): "editor"}  # Julia hat mit Frank geteilt
    assert state.asset_ids_in_album(album["id"]) == set(state.toskana)
    adders = {c[2] for c in state.calls if c[0] == "PUT" and c[1].endswith("/assets")}
    assert adders == {"frank", "julia"}  # jeder fügt seine eigenen Medien hinzu
    after = web.get("/api/album-suggestions", params={"status": "vorhanden"}).json()
    assert {t["name"] for t in after["reisen"]} == {"Wien, Mai 2024", "Toskana, Juli 2024"}


def test_new_album_direct_with_own_name(web, state):
    tid = trip_named(web.get("/api/album-suggestions").json()["reisen"], "Kopenhagen")["id"]
    r = web.post("/api/album-suggestions/apply", json={"trips": [{"id": tid, "name": "Kopenhagen mit Ole"}]}).json()
    assert r["alben"][0]["hinzugefuegt"] == 25
    album = next(a for a in state.albums.values() if a["albumName"] == "Kopenhagen mit Ole")
    assert album["ownerId"] == state.user_id("frank") and not album["members"]


def test_choose_other_album_or_new(web, state):
    tid = trip_named(web.get("/api/album-suggestions").json()["reisen"], "Toskana")["id"]
    web.post("/api/album-suggestions/apply", json={"trips": [{"id": tid, "album": None}]})
    album = next(a for a in state.albums.values() if a["albumName"] == "Toskana, Juli 2024")
    assert album["ownerId"] == state.user_id("frank")  # Frank hat die meisten Medien
    assert album["members"] == {state.user_id("julia"): "editor"}
    assert len(state.asset_ids_in_album(album["id"])) == 31


def test_ignore_and_undo(web):
    tid = trip_named(web.get("/api/album-suggestions").json()["reisen"], "Kopenhagen")["id"]
    web.post("/api/album-suggestions/ignore", json={"trips": [tid]})
    r = web.get("/api/album-suggestions").json()
    assert r["offen"] == 1 and r["ignoriert"] == 1
    hidden = web.get("/api/album-suggestions", params={"ignoriert": True}).json()["reisen"]
    assert [t["id"] for t in hidden] == [tid]
    web.post("/api/album-suggestions/ignore", json={"trips": [tid], "undo": True})
    assert web.get("/api/album-suggestions").json()["offen"] == 2


def test_settings_change_threshold(web):
    assert web.put("/api/settings", json={"album_min_media": 3}).status_code == 200
    names = [t["name"] for t in web.get("/api/album-suggestions").json()["reisen"]]
    assert "Lübeck, August 2024" in names
    assert web.put("/api/settings", json={"album_min_km": 1}).status_code == 422


def test_cli_preview_and_create(env, http, state, monkeypatch):
    from typer.testing import CliRunner

    from immich_pflege import cli

    service = Pflege(Settings.load(env), http=http)
    monkeypatch.setattr(cli, "service_factory", lambda: service)
    runner = CliRunner(env={"COLUMNS": "250"})
    r = runner.invoke(cli.app, ["alben", "--alle"])
    assert r.exit_code == 0, r.output
    assert "Zuhause: Hamburg" in r.output and "„Toskana 2024“ ergänzen (+26)" in r.output and "Wien" in r.output
    data = json.loads(runner.invoke(cli.app, ["alben", "--json"]).stdout)
    tid = next(t["id"] for t in data["reisen"] if t["status"] == "neu")
    r = runner.invoke(cli.app, ["alben", "--anlegen", tid, "--name", "Kopenhagen"])
    assert r.exit_code == 0 and "25 Medien hinzugefügt" in r.output, r.output
    assert any(a["albumName"] == "Kopenhagen" for a in state.albums.values())


def test_rescan_reuses_unchanged_albums(env, http, state):
    svc = Pflege(Settings.load(env), http=http)
    svc.library()

    def album_queries():
        return [c for c in state.calls if c[1] == "/api/search/metadata" and (c[3] or {}).get("albumIds")]

    first = len(album_queries())
    assert first == 3  # Toskana (julia), Wien (frank und julia, geteilt)
    svc.scan()
    assert len(album_queries()) == first  # nichts geändert -> nicht erneut gefragt
    wien = next(a for a in state.albums.values() if a["albumName"] == "Wien")
    extra = state.add_asset("julia", "NEU.JPG", "2024-05-10T20:00:00.000Z")
    state.assets[extra]["_albums"].add(wien["id"])
    lib = svc.scan()
    assert len(album_queries()) == first + 2  # nur Wien, für beide Benutzer
    assert extra in lib.albums[wien["id"]]["medien"]


def test_albums_read_in_background(env, http, state):
    """Einlesen wartet nicht auf die Album-Inhalte; die Vorschläge kommen, sobald sie gelesen sind."""
    svc = Pflege(Settings.load(env), http=http)
    svc.background_albums = True
    lib = svc.library()
    svc._albums_thread.join(10)
    assert lib.albums_ready and {a["name"] for a in lib.albums.values()} == {"Toskana 2024", "Wien"}
    r = svc.albums_view()
    assert r["offen"] == 2 and "laedt" not in r
    # während des Lesens: Hinweis statt falscher „neues Album“-Vorschläge
    lib.albums_ready = False
    svc._albums_thread = None
    assert svc.albums_view() == {"laedt": True, "stand": lib.scanned_at}


def test_manual_home(web):
    home = [{"name": "Oer-Erkenschwick", "breite": 51.64, "laenge": 7.25}, {"name": "Hamburg", "breite": 53.55, "laenge": 9.99}]
    assert web.put("/api/settings", json={"album_home": home}).status_code == 200
    r = web.get("/api/album-suggestions").json()
    assert [z["name"] for z in r["zuhause"]] == ["Oer-Erkenschwick", "Hamburg"] and r["zuhause"][0]["von_hand"]
    assert web.put("/api/settings", json={"album_home": [{"name": "x"}]}).status_code == 422
    web.put("/api/settings", json={"album_home": []})
    assert web.get("/api/album-suggestions").json()["zuhause"][0] == {
        "name": "Hamburg", "tage": 122, "von_hand": False, "breite": 53.55, "laenge": 9.99}


def test_all_media_and_single_selection(web, state):
    tosk = trip_named(web.get("/api/album-suggestions").json()["reisen"], "Toskana")
    media = web.get(f"/api/album-suggestions/{tosk['id']}/media").json()
    assert media["anzahl"] == 31 and len(media["medien"]) == 31
    assert sum(m["im_album"] for m in media["medien"]) == 5  # schon in Julias „Toskana 2024“
    drop = [m["id"] for m in media["medien"] if not m["im_album"]][:3]
    entry = web.post("/api/staged/albums", json={"trips": [{"id": tosk["id"], "ohne": drop}]}).json()
    assert entry["vorgemerkt"] == 1
    staged = web.get("/api/staged").json()["eintraege"][0]
    assert staged["anzahl"] == 23 and staged["daten"]["ohne"] == sorted(drop)
    # zurücknehmen hebt die Abwahl wieder auf
    web.delete(f"/api/staged/{staged['id']}")
    again = trip_named(web.get("/api/album-suggestions").json()["reisen"], "Toskana")
    assert again["anzahl"] == 31
    web.post("/api/staged/albums", json={"trips": [{"id": again["id"], "ohne": drop}]})
    web.post("/api/staged/apply", json={})
    album = next(a for a in state.albums.values() if a["albumName"] == "Toskana 2024")
    inside = state.asset_ids_in_album(album["id"])
    assert len(inside) == 28 and not set(drop) & inside
    done = web.get("/api/album-suggestions", params={"status": "vorhanden"}).json()["reisen"]
    assert any(t["name"].startswith("Toskana") and t["anzahl"] == 28 for t in done)  # abgewählte zählen nicht mehr


def test_new_album_without_some(web, state):
    kop = trip_named(web.get("/api/album-suggestions").json()["reisen"], "Kopenhagen")
    media = web.get(f"/api/album-suggestions/{kop['id']}/media").json()["medien"]
    keep = [m["id"] for m in media[:20]]
    r = web.post("/api/album-suggestions/apply",
                 json={"trips": [{"id": kop["id"], "ohne": [m["id"] for m in media[20:]]}]}).json()
    assert r["alben"][0]["hinzugefuegt"] == 20
    album = next(a for a in state.albums.values() if a["albumName"].startswith("Kopenhagen"))
    assert state.asset_ids_in_album(album["id"]) == set(keep)
    everything = [m["id"] for m in media]
    assert web.post("/api/album-suggestions/apply",
                    json={"trips": [{"id": kop["id"], "ohne": everything}]}).status_code == 400
