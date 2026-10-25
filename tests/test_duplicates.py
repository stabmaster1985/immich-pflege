from immich_pflege.duplicates import UnionFind, execute_steps, find_groups, plan_group
from immich_pflege.library import ImmichDuplicate, scan_library

from .helpers import asset, library

EXT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def test_union_find_merges_overlaps():
    uf = UnionFind()
    uf.union_all(["a", "b"])
    uf.union_all(["c", "d"])
    uf.union_all(["b", "c"])
    uf.find("e")
    groups = sorted(sorted(g) for g in uf.groups().values())
    assert groups == [["a", "b", "c", "d"], ["e"]]


def test_overlapping_sources_become_one_group():
    a = asset(checksum="X")
    b = asset(owner="julia", checksum="X")  # gleiche Prüfsumme, anderer Benutzer
    c = asset(name=b.file_name, local=b.local_date_time, library_id=EXT)  # Name + Zeit wie b
    d = asset()  # Immich-Duplikat zu c
    e = asset()  # einzeln
    lib = library(a, b, c, d, e, duplicates=[
        ImmichDuplicate("frank", "dup1", [c.id, d.id], [d.id])])
    groups = find_groups(lib)
    assert len(groups) == 1
    g = groups[0]
    assert {x.id for x in g.assets} == {a.id, b.id, c.id, d.id}
    assert g.sources == {"immich", "pruefsumme", "name_zeit"}
    assert g.users == {"frank", "julia"}
    assert g.id == find_groups(lib)[0].id  # stabile Gruppen-ID


def test_filename_match_is_case_insensitive_but_needs_same_time():
    a = asset(name="IMG_1.JPG", local="2024-01-01T10:00:00.000Z")
    b = asset(name="img_1.jpg", local="2024-01-01T10:00:00.000Z")
    c = asset(name="IMG_1.JPG", local="2024-01-01T10:00:01.000Z")
    groups = find_groups(library(a, b, c))
    assert len(groups) == 1 and {x.id for x in groups[0].assets} == {a.id, b.id}


def test_score_order():
    # Jede Stufe schlägt alle niedrigeren zusammen
    fav = asset(checksum="S", favorite=True, width=100, height=100)
    rest = asset(checksum="S", in_album=True, latitude=1.0, longitude=1.0, library_id=EXT)
    g = find_groups(library(fav, rest))[0]
    assert g.suggested_keep == fav.id

    alb = asset(checksum="T", in_album=True)
    gps = asset(checksum="T", latitude=48.1, longitude=11.5, library_id=EXT, width=8000, height=6000)
    assert find_groups(library(alb, gps))[0].suggested_keep == alb.id

    gps2 = asset(checksum="U", latitude=48.1, longitude=11.5)
    sug = asset(checksum="U", library_id=EXT, width=8000, height=6000)
    lib = library(gps2, sug, duplicates=[ImmichDuplicate("frank", "d", [gps2.id, sug.id], [sug.id])])
    assert find_groups(lib)[0].suggested_keep == gps2.id

    sug2 = asset(checksum="V")
    ext = asset(checksum="V", library_id=EXT, width=8000, height=6000)
    lib = library(sug2, ext, duplicates=[ImmichDuplicate("frank", "d", [sug2.id, ext.id], [sug2.id])])
    assert find_groups(lib)[0].suggested_keep == sug2.id

    up = asset(checksum="W", width=8000, height=6000)
    ext2 = asset(checksum="W", library_id=EXT, width=100, height=100)
    assert find_groups(library(up, ext2))[0].suggested_keep == ext2.id

    small = asset(checksum="Y", width=100, height=100)
    big = asset(checksum="Y", width=200, height=200)
    g = find_groups(library(small, big))[0]
    assert g.suggested_keep == big.id
    assert g.scores[big.id].reasons == ["höchste Auflösung"]


def test_ignore_gps_zero_zero():
    a = asset(checksum="Z", latitude=0.0, longitude=0.0, width=10, height=10)
    b = asset(checksum="Z")
    assert find_groups(library(a, b))[0].suggested_keep == b.id


def test_plan_trash_rules():
    keep = asset(checksum="P", favorite=True)
    same_user = asset(checksum="P")
    ext = asset(checksum="P", library_id=EXT)
    other_user = asset(owner="julia", checksum="P")
    done = asset(checksum="P", in_review_album=True)
    g = find_groups(library(keep, same_user, ext, other_user, done))[0]
    steps = {s.asset.id: s for s in plan_group(g, keep.id, "papierkorb")}
    assert keep.id not in steps
    assert steps[same_user.id].action == "papierkorb"
    assert steps[ext.id].action == "album"
    assert steps[other_user.id].action == "album"
    assert steps[done.id].action == "papierkorb"  # gleicher Benutzer, Upload

    steps = {s.asset.id: s for s in plan_group(g, keep.id, "album")}
    assert {s.action for s in steps.values()} == {"album", "keine"}
    assert steps[done.id].action == "keine"


def test_plan_keep_override():
    a = asset(checksum="Q", favorite=True)
    b = asset(checksum="Q")
    g = find_groups(library(a, b))[0]
    steps = plan_group(g, b.id, "papierkorb")
    assert [(s.asset.id, s.action) for s in steps] == [(a.id, "papierkorb")]


def test_execute_against_mock(state, clients):
    lib = scan_library(clients, "Duplikat-Prüfung")
    groups = find_groups(lib)
    assert len(groups) == 3
    by_name = {g.assets[0].file_name: g for g in groups}

    shared = by_name["IMG_0101.HEIC"]
    keeper = shared.asset(shared.suggested_keep)
    assert keeper.owner == "julia" and keeper.favorite  # Favorit schlägt "im Album"

    sony = by_name["DSC09812.JPG"]
    assert sony.asset(sony.suggested_keep).is_external
    assert sony.sources == {"name_zeit"}

    steps = []
    for g in groups:
        steps += plan_group(g, g.suggested_keep, "papierkorb")
    res = execute_steps(lib, clients, steps, "Duplikat-Prüfung")
    assert res["fehler"] == []
    assert res["papierkorb"] == 2  # Sony-Upload und Julias kleinere Kopie
    assert res["album"] == 1  # Franks Kopie: anderer Benutzer -> nur Prüf-Album

    # Album wurde für frank angelegt
    created = [c for c in state.calls if c[:2] == ("POST", "/api/albums")]
    assert [c[2] for c in created] == ["frank"]
    trashed = {a["originalFileName"] for a in state.assets.values() if a["isTrashed"]}
    assert trashed == {"alt.jpg", "DSC09812.JPG", "IMG_0200 2.JPG"}
    ext = [a for a in state.assets.values() if a["libraryId"]]
    assert not any(a["isTrashed"] for a in ext)
    # Lokaler Stand ist aktualisiert
    assert len(find_groups(lib)) == 1 and find_groups(lib)[0].done()


def test_group_kinds():
    same = [asset(checksum="K"), asset(owner="julia", checksum="K")]
    assert find_groups(library(*same))[0].kind == "identisch"
    a = asset(name="IMG_1.JPG", local="2024-01-01T10:00:00Z")
    b = asset(name="IMG_1.JPG", local="2024-01-01T10:00:00Z", library_id=EXT)
    assert find_groups(library(a, b))[0].kind == "sehr_wahrscheinlich"
    c, d = asset(), asset()
    lib = library(c, d, duplicates=[ImmichDuplicate("frank", "x", [c.id, d.id], [c.id])])
    g = find_groups(lib)[0]
    assert g.kind == "aehnlich" and g.to_dict()["art_text"] == "ähnlich"
    assert g.month == "2024-07"


def test_ignore_list(tmp_path):
    from immich_pflege.duplicates import IgnoreList
    a, b, c = asset(checksum="I"), asset(checksum="I"), asset(checksum="I")
    path = tmp_path / "ign.json"
    ign = IgnoreList(path)
    g = find_groups(library(a, b))[0]
    ign.add(g.asset_ids)
    assert IgnoreList(path).contains(g)
    # Eine Kopie verschwindet -> bleibt ausgeblendet; neue Kopie -> taucht wieder auf
    assert IgnoreList(path).contains(find_groups(library(a, b))[0])
    assert not IgnoreList(path).contains(find_groups(library(a, b, c))[0])
    ign.remove(g.asset_ids)
    assert not IgnoreList(path).contains(g)
