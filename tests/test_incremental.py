"""Einlesen nur der Änderungen."""

from datetime import datetime, timedelta, timezone

from immich_pflege.config import Settings
from immich_pflege.service import Pflege
from tests.mock_immich import now_iso


def searches(state, start):
    return [c[3] or {} for c in state.calls[start:] if c[1] == "/api/search/metadata"]


def test_only_changes_are_fetched(env, http, state):
    svc = Pflege(Settings.load(env), http=http)
    lib = svc.library()
    assert not lib.incremental and lib.full_scan_at == lib.scanned_at
    total = len(lib.assets)
    # Änderungen in Immich: neues Foto, eines in den Papierkorb, eines bekommt einen Ort, eines ins Album
    new = state.add_asset("frank", "NEU.HEIC", "2024-08-01T10:00:00.000Z")
    gone = next(a for a in lib.assets.values() if a.file_name == "IMG_0200 2.JPG").id
    state.assets[gone].update(isTrashed=True, _trashedAt=now_iso(), updatedAt=now_iso())
    moved = next(a for a in lib.assets.values() if a.file_name == "DSC10000.JPG").id
    state.assets[moved]["exifInfo"].update(latitude=43.46, longitude=11.04, city="San Gimignano")
    state.assets[moved]["updatedAt"] = now_iso()
    album = next(iter(state.albums))
    state.assets[new]["_albums"].add(album)
    start = len(state.calls)
    lib2 = svc.scan()
    assert lib2.incremental and lib2.full_scan_at == lib.full_scan_at
    assert len(lib2.assets) == total  # +1 neu, -1 Papierkorb
    assert new in lib2.assets and gone not in lib2.assets
    assert lib2.assets[moved].city == "San Gimignano"
    assert lib2.assets[new].in_album  # aus den gelesenen Alben
    calls = searches(state, start)
    assert all("updatedAfter" in c or "trashedAfter" in c or "albumIds" in c for c in calls)
    assert not any(c.get("isNotInAlbum") for c in calls)
    # vollständig auf Wunsch
    start = len(state.calls)
    lib3 = svc.scan(full=True)
    assert not lib3.incremental and any(c.get("isNotInAlbum") for c in searches(state, start))
    assert set(lib3.assets) == set(lib2.assets)


def test_weekly_full_scan(env, http, state):
    svc = Pflege(Settings.load(env), http=http)
    lib = svc.library()
    lib.full_scan_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    assert not svc.scan().incremental  # eine Woche her -> vollständig
    assert svc.scan().incremental
