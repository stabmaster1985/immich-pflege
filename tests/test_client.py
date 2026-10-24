import pytest

from immich_pflege.client import ImmichClient, ImmichError, chunked
from immich_pflege.library import Library, scan_library


@pytest.mark.parametrize("mode", ["cursor", "page"])
def test_paging_reads_all_pages(state, clients, mode):
    state.paging = mode
    for i in range(2345):
        state.add_asset("frank", f"bulk_{i}.jpg", "2023-01-01T10:00:00.000Z")
    items = list(clients["frank"].search_metadata(withExif=True))
    ids = [a["id"] for a in items]
    assert len(ids) == len(set(ids))
    expected = [a for a in state.assets.values()
                if a["ownerId"] == state.user_id("frank") and not a["isTrashed"]]
    assert len(ids) == len(expected)
    searches = [c for c in state.calls if c[1] == "/api/search/metadata"]
    assert len(searches) == 3  # 1000 + 1000 + Rest
    assert all(c[3]["size"] == 1000 for c in searches)
    key = "cursor" if mode == "cursor" else "page"
    assert key in searches[1][3] and key in searches[2][3]
    assert ("page" if mode == "cursor" else "cursor") not in searches[2][3]


def test_chunked_blocks_of_500():
    blocks = list(chunked([str(i) for i in range(1201)]))
    assert [len(b) for b in blocks] == [500, 500, 201]


def test_bulk_calls_are_chunked(state, clients):
    ids = [state.add_asset("frank", f"x{i}.jpg", "2023-01-01T10:00:00.000Z") for i in range(1100)]
    album = state.add_album("frank", "Test")
    clients["frank"].add_to_album(album, ids)
    puts = [c for c in state.calls if c[0] == "PUT"]
    assert [len(c[3]["ids"]) for c in puts] == [500, 500, 100]
    assert len(state.asset_ids_in_album(album)) == 1100


def test_bad_key_gives_readable_error(http):
    c = ImmichClient("http://immich-server:2283/api", "falsch", "frank", http=http)
    with pytest.raises(ImmichError, match="abgelehnt"):
        c.server_version()


def test_scan_library(state, clients, tmp_path):
    lib = scan_library(clients, "Duplikat-Prüfung")
    names = {a.file_name for a in lib.assets.values()}
    assert "IMG_0101.MOV" not in names  # verstecktes Live-Photo-Video
    assert "alt.jpg" not in names  # Papierkorb
    assert lib.server_version == "3.2.4"
    assert not lib.warnings
    assert {a.owner for a in lib.assets.values()} == {"frank", "julia"}
    in_album = [a for a in lib.assets.values() if a.in_album]
    assert [a.file_name for a in in_album] == ["IMG_0101.HEIC"]
    assert in_album[0].owner == "frank"
    assert len(lib.immich_duplicates) == 1
    ext = [a for a in lib.assets.values() if a.is_external]
    assert len(ext) == 2

    path = tmp_path / "cache.json"
    lib.save(path)
    again = Library.load(path)
    assert again is not None and again.assets.keys() == lib.assets.keys()
    assert again.assets[in_album[0].id].in_album


def test_version_warning(state, clients):
    state.version = (4, 0, 0)
    lib = scan_library(clients, "Duplikat-Prüfung")
    assert lib.warnings and "4.0.0" in lib.warnings[0]


def test_review_album_membership_does_not_count(state, clients):
    aid = next(a["id"] for a in state.assets.values() if a["originalFileName"] == "DSC09812.JPG")
    state.add_album("frank", "Duplikat-Prüfung", [aid])
    lib = scan_library(clients, "Duplikat-Prüfung")
    assert lib.assets[aid].in_review_album
    assert not lib.assets[aid].in_album
