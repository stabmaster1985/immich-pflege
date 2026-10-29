from pathlib import Path

from fastapi.testclient import TestClient

from immich_pflege import albumcare, albums, cleanup, folders, duplicates, imagehash, location, stacking, suggestions, timefix
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
    assert folders.MIN_MEDIA == 5 and "mindestens **5 Medien**" in alb and folders.COMPLETE == 0.95 and "**95 %**" in alb
    cln = (HELP / "aufraeumen.md").read_text()
    assert cleanup.BIG_VIDEO_MB == 300 and "**300 MB**" in cln
    assert cleanup.LIVE_MAX_S == 3.5 and "3,5 s" in cln and cleanup.LIVE_DELTA_S == 2
    assert cleanup.BURST_GAP_S == 2 and "**2 Sekunden**" in cln and cleanup.BURST_MAX_DIST == 12
    assert cleanup.DARK_MAX == 25 and "**25**" in cln and cleanup.BLUR_MAX == 3.0 and "**3**" in cln
    assert timefix.STEP_MIN == 30 and timefix.MAX_OFFSET_MIN == 12 * 60 and "±12 Stunden" in cln
    assert timefix.MATCH_MIN == 10 and "10 Minuten" in cln and timefix.MIN_SHARE == 0.5
    assert stacking.PAIR_GAP_S == stacking.BURST_GAP_S == 2 and "höchstens 2 Sekunden" in cln
    assert stacking.SIMILAR_GAP_S == 60 and "höchstens 60 Sekunden" in cln
    assert albumcare.OVERLAP == 0.9 and "**90 %**" in cln and albumcare.MINI_MAX == 2 and "1–2 Medien" in cln
    tags = (HELP / "tags.md").read_text()
    assert suggestions.MIN_COUNTRY == 10 and "ab 10 Fotos" in tags and suggestions.MIN_CAMERA == 30 and "ab 30 Medien" in tags
    # die Oberfläche holt für die Prüf-Ansicht standardmäßig 400 KI-Treffer je Benutzer, wählbar bis SMART_MAX
    app_js = (Path(__file__).parent.parent / "immich_pflege/web/static/app.js").read_text(encoding="utf-8")
    assert "const SMART_REVIEW = 400;" in app_js and "Standard 400" in tags
    assert suggestions.SMART_MAX == 5000 and "200 bis 5.000" in tags
    assert all(name in tags for name, _, _ in suggestions.BEGRIFFE)


def test_readme_links_help():
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    for topic in HELP_TOPICS:
        assert f"immich_pflege/hilfe/{topic}.md" in readme
