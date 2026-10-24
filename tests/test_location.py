from immich_pflege.library import scan_library
from immich_pflege.location import GpsIndex, apply_locations, find_candidates, format_delta, group_by_day

from .helpers import asset, library

EXT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def gps(owner="frank", utc="2024-07-16T10:00:00Z", city="Siena"):
    return asset(owner=owner, utc=utc, local=utc, latitude=43.3, longitude=11.3, city=city,
                 country="Italien")


def test_nearest_within_window_across_users():
    before = gps(owner="julia", utc="2024-07-16T10:00:00Z", city="Vorher")
    after = gps(owner="frank", utc="2024-07-16T10:50:00Z", city="Nachher")
    target = asset(utc="2024-07-16T10:30:00Z")
    s = GpsIndex([before, after, target]).nearest(target, 2)
    assert s.source.id == after.id and s.delta_s == 20 * 60
    assert s.to_dict()["ort"] == "Nachher, Italien"


def test_window_limits():
    src = gps(utc="2024-07-16T10:00:00Z")
    inside = asset(utc="2024-07-16T11:59:00Z")
    outside = asset(utc="2024-07-16T12:01:00Z")
    idx = GpsIndex([src])
    assert idx.nearest(inside, 2) is not None
    assert idx.nearest(outside, 2) is None
    assert idx.nearest(outside, 3) is not None


def test_uses_utc_not_local_time():
    # Gleiche Ortszeit, aber unterschiedliche Zeitzonen -> 6 h echte Differenz
    src = asset(local="2024-07-16T12:00:00Z", utc="2024-07-16T10:00:00Z", latitude=1.0, longitude=1.0)
    target = asset(local="2024-07-16T12:00:00Z", utc="2024-07-16T16:00:00Z")
    assert GpsIndex([src]).nearest(target, 2) is None


def test_candidates_grouped_by_day_and_external_locked():
    src = gps(utc="2024-07-16T10:00:00Z")
    a = asset(utc="2024-07-16T10:10:00Z")
    b = asset(utc="2024-07-17T10:10:00Z")
    ext = asset(utc="2024-07-16T10:20:00Z", library_id=EXT)
    lib = library(src, a, b, ext)
    cands = find_candidates(lib, 2, include_external=False)
    assert {c.asset.id for c in cands} == {a.id, b.id, ext.id}
    by_id = {c.asset.id: c for c in cands}
    assert not by_id[ext.id].editable and by_id[a.id].editable
    assert by_id[b.id].suggestion is None
    days = group_by_day(cands)
    assert [d["datum"] for d in days] == ["2024-07-17", "2024-07-16"]
    assert days[1]["anzahl"] == 2 and days[1]["mit_vorschlag"] == 2
    assert find_candidates(lib, 2, include_external=True)[1].editable


def test_format_delta():
    assert format_delta(30) == "30 s"
    assert format_delta(5 * 60) == "5 min"
    assert format_delta(95 * 60) == "1 h 35 min"
    assert format_delta(-7200) == "2 h"


def test_apply_against_mock(state, clients):
    lib = scan_library(clients, "Duplikat-Prüfung")
    cands = find_candidates(lib, 2, include_external=False)
    by_name = {c.asset.file_name: c for c in cands}
    assert by_name["DSC10000.JPG"].suggestion.to_dict()["ort"] == "San Gimignano, Italien"
    assert by_name["DSC10000.JPG"].suggestion.source.owner == "julia"
    assert by_name["DSC10002.JPG"].suggestion is None  # 3,5 h entfernt

    ids = [by_name[n].asset.id for n in ("DSC10000.JPG", "DSC10001.JPG", "DSC10002.JPG", "DSC20000.JPG")]
    res = apply_locations(lib, clients, ids, 2, include_external=False)
    assert res["aktualisiert"] == 2
    reasons = sorted(s["grund"] for s in res["uebersprungen"])
    assert reasons[0].startswith("externe") and reasons[1].startswith("kein Foto")

    puts = [c for c in state.calls if c[:2] == ("PUT", "/api/assets")]
    assert len(puts) == 1 and puts[0][2] == "frank"
    assert sorted(puts[0][3]["ids"]) == sorted(ids[:2])
    assert puts[0][3]["latitude"] == 43.4642
    assert lib.assets[ids[0]].has_gps
