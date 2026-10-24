import json

import pytest
from typer.testing import CliRunner

from immich_pflege import cli
from immich_pflege.service import Pflege

runner = CliRunner(env={"COLUMNS": "250"})


@pytest.fixture
def svc(settings, http, monkeypatch):
    service = Pflege(settings, http=http)
    monkeypatch.setattr(cli, "service_factory", lambda: service)
    return service


def run(*args):
    return runner.invoke(cli.app, list(args))


def test_version(svc):
    r = run("version")
    assert r.exit_code == 0, r.output
    assert "3.2.4" in r.output and "frank" in r.output


def test_duplicates_preview_is_default(svc, state):
    r = run("duplikate", "--json")
    assert r.exit_code == 0, r.output
    data = json.loads(r.stdout)
    assert data["gesamt"] == 3
    assert not any(c[0] in ("PUT", "DELETE", "POST") and c[1] != "/api/search/metadata" for c in state.calls)


def test_duplicates_table_and_csv(svc):
    r = run("duplikate")
    assert r.exit_code == 0, r.output
    assert "★" in r.output and "DSC09812.JPG" in r.output
    r = run("duplikate", "--csv")
    lines = r.stdout.strip().splitlines()
    assert lines[0].startswith("gruppe,behalten,quellen,id,benutzer")
    assert len(lines) == 1 + 6


def test_trash_needs_yes_without_tty(svc, state):
    r = run("duplikate", "--papierkorb")
    assert r.exit_code == 1
    assert not any(c[0] == "DELETE" for c in state.calls)
    r = run("duplikate", "--papierkorb", "--ja", "--json")
    assert r.exit_code == 0, r.output
    res = json.loads(r.stdout)
    assert res["ergebnis"]["papierkorb"] == 2


def test_keep_override(svc, state):
    view = json.loads(run("duplikate", "--json").stdout)
    g = next(g for g in view["gruppen"] if "name_zeit" in g["quellen"])
    upload = next(m for m in g["medien"] if not m["extern"])
    ext = next(m for m in g["medien"] if m["extern"])
    r = run("duplikate", "--gruppe", g["id"], "--behalten", f"{g['id']}={upload['id']}",
            "--papierkorb", "--ja", "--json")
    assert r.exit_code == 0, r.output
    steps = json.loads(r.stdout)["schritte"]
    assert steps == [{"id": ext["id"], "benutzer": "frank", "dateiname": "DSC09812.JPG",
                      "aktion": "album", "grund": "externe Bibliothek – nie in den Papierkorb"}]


def test_no_location_and_apply(svc, state):
    r = run("ohne-ort")
    assert r.exit_code == 0, r.output
    assert "San Gimignano" in r.output
    r = run("ohne-ort", "--datum", "2024-07-16", "--ort-uebernehmen", "--json")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["aktualisiert"] == 3  # 2× Sony + Julias IMG_0200 2.JPG


def test_tags_broken_rules(svc, settings):
    settings.rules_file.parent.mkdir(parents=True)
    settings.rules_file.write_text("regeln:\n  - name: x\n    tag: A\n    typ: bild\n")
    r = run("tags")
    assert r.exit_code == 1
    assert "'typ' muss 'foto' oder 'video' sein" in r.output


def test_tags_preview_and_apply(svc, settings):
    settings.rules_file.parent.mkdir(parents=True)
    settings.rules_file.write_text("regeln:\n  - name: Sony\n    tag: Kamera/Sony\n    hersteller: sony\n")
    r = run("tags")
    assert r.exit_code == 0, r.output
    assert "Sony" in r.output
    r = run("tags", "--anwenden", "--json")
    assert json.loads(r.stdout)["getaggt"] == 6
    r = run("tags", "--json")
    assert json.loads(r.stdout)["regeln"][0]["neu"] == 0


def test_config_error(monkeypatch):
    monkeypatch.setattr(cli, "service_factory", lambda: Pflege(__import__("immich_pflege.config", fromlist=["x"]).Settings.from_env({})))
    r = run("version")
    assert r.exit_code == 2 and "IMMICH_URL" in r.output
