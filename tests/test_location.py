from immich_pflege.library import scan_library
from immich_pflege.location import (GpsIndex, analyze, apply_locations, format_delta, group_by_day,
                                    is_screenshot, km)

from .helpers import asset, library

EXT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SIENA = (43.3188, 11.3308)
FLORENZ = (43.7696, 11.2558)


def gps(owner="frank", utc="2024-07-16T10:00:00Z", at=SIENA, city="Siena"):
    return asset(owner=owner, utc=utc, latitude=at[0], longitude=at[1], city=city, country="Italien")


def test_km():
    assert 50 < km(*SIENA, *FLORENZ) < 51


def test_screenshot_detection():
    assert is_screenshot(asset(name="Screenshot 2024-07-20 at 10.00.png", make=None, model=None))
    assert is_screenshot(asset(name="Bildschirmfoto 2024-07-20.png"))
    assert is_screenshot(asset(name="IMG_4711.PNG", make=None, model=None))  # iPhone-Screenshot
    assert is_screenshot(asset(name="RPReplay_Final1690000000.MP4", type="VIDEO"))
    assert not is_screenshot(asset(name="IMG_4711.PNG", make="Apple", model="iPhone 15 Pro"))
    assert not is_screenshot(asset(name="IMG_4711.HEIC", make=None, model=None))


def test_screenshots_are_skipped():
    shot = asset(name="Screenshot 1.png", utc="2024-07-16T10:05:00Z", make=None, model=None)
    photo = asset(utc="2024-07-16T10:06:00Z")
    lib = library(gps(), shot, photo)
    an = analyze(lib, 2, False)
    assert [c.asset.id for c in an.candidates] == [photo.id] and an.screenshots == 1
    assert len(analyze(lib, 2, False, skip_screenshots=False).candidates) == 2


def test_confidence_levels():
    src = gps(utc="2024-07-16T10:00:00Z")
    idx = GpsIndex([src])
    near = idx.suggest(asset(utc="2024-07-16T10:20:00Z"), 2)
    assert near.confidence == "hoch" and "20 min vorher bei frank" in near.reason
    far = idx.suggest(asset(utc="2024-07-16T11:30:00Z"), 2)
    assert far.confidence == "mittel"
    assert idx.suggest(asset(utc="2024-07-16T12:30:00Z"), 2) is None


def test_neighbors_agree_or_disagree():
    before = gps(owner="julia", utc="2024-07-16T10:00:00Z", city="Vorher")
    after_same = gps(utc="2024-07-16T11:40:00Z", at=(43.3190, 11.3310), city="Nachher")
    s = GpsIndex([before, after_same]).suggest(asset(utc="2024-07-16T10:50:00Z"), 2)
    assert s.confidence == "hoch" and "derselbe Ort" in s.reason and s.source is before
    after_other = gps(utc="2024-07-16T11:40:00Z", at=FLORENZ, city="Florenz")
    s = GpsIndex([before, after_other]).suggest(asset(utc="2024-07-16T10:50:00Z"), 2)
    assert s.confidence == "mittel" and "verschiedene Orte" in s.reason


def test_between_two_photos_at_same_place():
    morning = gps(utc="2024-07-16T07:00:00Z")
    evening = gps(utc="2024-07-16T18:00:00Z", at=(43.3195, 11.3300))
    target = asset(utc="2024-07-16T12:00:00Z")  # 5 h bzw. 6 h entfernt – außerhalb ±2 h
    s = GpsIndex([morning, evening]).suggest(target, 2)
    assert s.confidence == "niedrig" and s.method == "zwischen" and "selben Ort" in s.reason
    # verschiedene Orte -> kein Vorschlag
    assert GpsIndex([morning, gps(utc="2024-07-16T18:00:00Z", at=FLORENZ)]).suggest(target, 2) is None


def test_uses_utc_not_local_time():
    src = asset(local="2024-07-16T12:00:00Z", utc="2024-07-16T10:00:00Z", latitude=1.0, longitude=1.0)
    target = asset(local="2024-07-16T12:00:00Z", utc="2024-07-16T16:00:00Z")
    assert GpsIndex([src]).suggest(target, 2) is None


def test_series_inherit_place():
    src = gps(utc="2024-07-16T10:00:00Z")
    # Kamera-Serie: erstes Foto nah am GPS-Foto, die weiteren im Abstand < 2 h, aber außerhalb des Fensters
    cam = [asset(utc=f"2024-07-16T{h}:00:00Z", make="SONY", model="ILCE-7M4") for h in ("10", "11", "12", "13", "14")]
    an = analyze(library(src, *cam), 2, False)
    assert len(an.series) == 1
    series = an.series[0].to_dict()
    assert series["anzahl"] == 5 and series["mit_vorschlag"] == 5 and series["vorschlag"]["ort"] == "Siena, Italien"
    by = {c.asset.id: c.suggestion for c in an.candidates}
    assert by[cam[0].id].confidence == "hoch" and by[cam[0].id].method == "naechstes"
    assert by[cam[4].id].method == "serie" and by[cam[4].id].confidence == "mittel"
    assert "aus derselben Serie" in by[cam[4].id].reason
    assert series["sicherheit"] == "mittel"


def test_series_split_and_conflicting_places():
    a = asset(utc="2024-07-16T10:00:00Z")
    b = asset(utc="2024-07-16T13:00:00Z")  # 3 h später -> neue Serie
    assert len(analyze(library(a, b), 2, False).series) == 2
    # zwei Orte in einer Serie -> keine Vererbung
    s1, s2 = gps(utc="2024-07-16T10:00:00Z"), gps(utc="2024-07-16T11:30:00Z", at=FLORENZ, city="Florenz")
    x = asset(utc="2024-07-16T10:05:00Z")
    y = asset(utc="2024-07-16T11:25:00Z")
    lonely = asset(utc="2024-07-16T10:50:00Z")
    an = analyze(library(s1, s2, x, y, lonely), 0.5, False)
    ser = an.series[0]
    assert ser.several_places and ser.suggestion is None
    assert an.by_id[lonely.id].suggestion is None


def test_external_locked_and_day_grouping():
    src = gps(utc="2024-07-16T10:00:00Z")
    a = asset(utc="2024-07-16T10:10:00Z")
    b = asset(utc="2024-07-17T10:10:00Z")
    ext = asset(utc="2024-07-16T10:20:00Z", library_id=EXT)
    an = analyze(library(src, a, b, ext), 2, include_external=False)
    assert not an.by_id[ext.id].editable and an.by_id[a.id].editable
    days = group_by_day(an.candidates)
    assert [d["datum"] for d in days] == ["2024-07-17", "2024-07-16"]
    assert analyze(library(src, a, b, ext), 2, include_external=True).by_id[ext.id].editable


def test_format_delta():
    assert format_delta(30) == "30 s"
    assert format_delta(5 * 60) == "5 min"
    assert format_delta(95 * 60) == "1 h 35 min"
    assert format_delta(-7200) == "2 h"


def test_against_mock(state, clients):
    lib = scan_library(clients, "Duplikat-Prüfung")
    an = analyze(lib, 2, False)
    assert an.screenshots == 1 and len(an.candidates) == 7
    by_name = {c.asset.file_name: c for c in an.candidates if c.asset.library_id is None}
    assert by_name["DSC10000.JPG"].suggestion.place == "San Gimignano, Italien"
    assert by_name["DSC10000.JPG"].suggestion.confidence == "hoch"
    assert by_name["DSC10001.JPG"].suggestion.confidence == "mittel"
    assert by_name["DSC10002.JPG"].suggestion is None

    # alle mit hoher Sicherheit übernehmen
    res = apply_locations(lib, clients, None, 2, False, min_confidence="hoch")
    assert res["aktualisiert"] == 2  # DSC10000 + IMG_0200 2.JPG
    puts = [c for c in state.calls if c[:2] == ("PUT", "/api/assets")]
    assert {c[2] for c in puts} == {"frank", "julia"}
    assert lib.assets[by_name["DSC10000.JPG"].asset.id].has_gps


def test_manual_place(state, clients):
    lib = scan_library(clients, "Duplikat-Prüfung")
    ids = [a.id for a in lib.assets.values() if a.file_name == "DSC09812.JPG"]  # Upload + extern
    res = apply_locations(lib, clients, ids, 2, False, manual=(43.4642, 11.0413, "San Gimignano"))
    assert res["aktualisiert"] == 1
    assert res["uebersprungen"][0]["grund"].startswith("externe Bibliothek")
    upload = next(lib.assets[i] for i in ids if not lib.assets[i].is_external)
    assert upload.has_gps and upload.city == "San Gimignano"
