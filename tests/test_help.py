from pathlib import Path

from fastapi.testclient import TestClient

from immich_pflege import albums, duplicates, imagehash, location
from immich_pflege.web.app import HELP, HELP_TOPICS, create_app


def test_help_endpoint(env, http):
    with TestClient(create_app(env, http=http)) as c:
        for topic in HELP_TOPICS:
            r = c.get(f"/api/help/{topic}")
            assert r.status_code == 200 and r.text.startswith("# ")
        assert c.get("/api/help/../config").status_code == 404
        assert c.get("/api/help/gibtsnicht").status_code == 404


def test_help_matches_code():
    """Die Zahlen in den Hilfetexten müssen zu den Konstanten im Code passen."""
    loc = (HELP / "ohne-ort.md").read_text()
    assert location.SURE_DELTA_S == 30 * 60 and "30 Minuten" in loc
    assert location.SAME_PLACE_KM == 1.5 and "1,5 km" in loc
    assert location.BRACKET_MAX_S == 12 * 3600 and "12 Stunden" in loc
    assert location.SERIES_GAP_S == 2 * 3600 and "höchstens **2 Stunden**" in loc
    dup = (HELP / "duplikate.md").read_text()
    assert f"höchstens {imagehash.MAX_DISTANCE} der 64 Bits" in dup
    for _, label, weight in duplicates.WEIGHTS:
        assert f"| {weight} |" in dup, label
    alb = (HELP / "alben.md").read_text()
    assert albums.TRIP_GAP_S == 36 * 3600 and "**36 Stunden**" in alb
    assert albums.EDGE_S == 3 * 3600 and "3 Stunden" in alb
    assert albums.COMPLETE == 0.95 and "95 %" in alb
    assert albums.MATCH == 0.2 and "ab 20 %" in alb
    assert albums.NAME_SHARE == 0.6 and "60 %" in alb
    assert albums.MIN_GPS == 3 and "3 Fotos mit GPS" in alb


def test_readme_links_help():
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    for topic in HELP_TOPICS:
        assert f"immich_pflege/hilfe/{topic}.md" in readme
