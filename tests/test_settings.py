import json

import pytest
from fastapi.testclient import TestClient

from immich_pflege.config import ConfigError, Settings, update_settings, verify_password
from immich_pflege.web.app import create_app


def test_defaults_without_anything(tmp_path):
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    assert not s.configured and s.immich_url == ""
    assert s.rules_file == tmp_path / "regeln.yaml" and s.locked == set()


def test_env_wins_and_locks(tmp_path):
    (tmp_path / "einstellungen.json").write_text(json.dumps(
        {"immich_url": "http://gespeichert:2283", "location_max_hours": 5, "users": {"otto": "k"}}))
    s = Settings.load({"DATA_DIR": str(tmp_path), "LOCATION_MAX_HOURS": "1,5"})
    assert s.immich_url == "http://gespeichert:2283" and s.users == {"otto": "k"}
    assert s.location_max_hours == 1.5 and s.locked == {"location_max_hours"}
    with pytest.raises(ConfigError, match=".env"):
        update_settings(s, {"location_max_hours": 3})


def test_update_validates_and_keeps_keys(tmp_path):
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    update_settings(s, {"immich_url": "http://immich-server:2283/api/", "benutzer": [
        {"name": "Frank", "key": "aaaa-bbbb-cccc"}, {"name": "julia", "key": "dddd-eeee-ffff"}]})
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    assert s.immich_url == "http://immich-server:2283" and s.users["frank"] == "aaaa-bbbb-cccc"
    # Key leer lassen = behalten, Umbenennen per "alt", nicht genannte werden entfernt
    update_settings(s, {"benutzer": [{"name": "franky", "alt": "frank"}]})
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    assert s.users == {"franky": "aaaa-bbbb-cccc"}
    with pytest.raises(ConfigError) as exc:
        update_settings(s, {"immich_url": "immich", "location_max_hours": "0",
                            "benutzer": [{"name": "Ä"}, {"name": "neu"}]})
    msg = str(exc.value)
    assert "http://" in msg and "48" in msg and "ungültig" in msg and "fehlt der API-Key" in msg
    assert Settings.load({"DATA_DIR": str(tmp_path)}).users == {"franky": "aaaa-bbbb-cccc"}  # nichts gespeichert


def test_password_is_hashed(tmp_path):
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    update_settings(s, {"web_user": "frank", "web_password": "geheim123"})
    raw = (tmp_path / "einstellungen.json").read_text()
    assert "geheim123" not in raw
    s = Settings.load({"DATA_DIR": str(tmp_path)})
    assert s.auth_enabled and s.check_login("frank", "geheim123") and not s.check_login("frank", "x")
    assert verify_password("geheim123", s.web_password_hash)
    with pytest.raises(ConfigError, match="6 Zeichen"):
        update_settings(s, {"web_password": "kurz"})
    update_settings(s, {"web_user": ""})
    assert not Settings.load({"DATA_DIR": str(tmp_path)}).auth_enabled


@pytest.fixture
def fresh(tmp_path, http):
    env = {"DATA_DIR": str(tmp_path / "data")}
    with TestClient(create_app(env, http=http)) as c:
        yield c


def test_setup_flow_via_gui(fresh, state):
    r = fresh.post("/api/settings/test", json={"benutzer": [{"name": "frank", "key": "key-frank"}]})
    assert r.status_code == 400 and "Adresse" in r.json()["fehler"]
    st = fresh.get("/api/status").json()
    assert st["eingerichtet"] is False and "server" not in st
    r = fresh.get("/api/duplicates")
    assert r.status_code == 409 and r.json()["einrichtung"] is True

    body = {"immich_url": "http://immich-server:2283",
            "benutzer": [{"name": "frank", "key": "key-frank"}, {"name": "julia", "key": "falsch"}]}
    test = fresh.post("/api/settings/test", json=body).json()
    assert test["version"] == "3.2.4"
    assert test["schluessel"]["frank"]["ok"] and not test["schluessel"]["julia"]["ok"]

    body["benutzer"][1]["key"] = "key-julia"
    r = fresh.put("/api/settings", json=body)
    assert r.status_code == 200, r.text
    pub = r.json()
    assert pub["eingerichtet"] and pub["benutzer"][0] == {"name": "frank", "key_gesetzt": True, "key_ende": "rank"}
    assert "key-frank" not in r.text and "key-frank" not in fresh.get("/api/settings").text
    assert fresh.get("/api/duplicates").json()["gesamt"] == 3

    # Test mit gespeicherten Keys (Key leer = gespeicherten verwenden)
    test = fresh.post("/api/settings/test", json={"benutzer": [{"name": "julia"}]}).json()
    assert test["schluessel"]["julia"]["ok"]

    r = fresh.put("/api/settings", json={"location_max_hours": "abc"})
    assert r.status_code == 422 and "Zahl" in r.json()["details"][0]


def test_login_via_gui(fresh):
    r = fresh.put("/api/settings", json={"web_user": "frank", "web_password": "geheim123"})
    assert r.json()["login_geaendert"] is True
    assert fresh.get("/api/settings").status_code == 200  # wer den Login setzt, bleibt angemeldet
    fresh.cookies.clear()
    assert fresh.get("/api/settings").status_code == 401
    assert fresh.get("/api/settings", auth=("frank", "geheim123")).status_code == 200
    assert fresh.get("/healthz").status_code == 200


def test_rules_editor_api(fresh):
    fresh.put("/api/settings", json={"immich_url": "http://immich-server:2283",
                                     "benutzer": [{"name": "frank", "key": "key-frank"}]})
    assert fresh.get("/api/rules").json()["regeln"] == []
    ex = fresh.get("/api/rules/example").json()["regeln"]
    r = fresh.put("/api/rules", json={"regeln": ex[:2]})
    assert r.status_code == 200 and len(r.json()["regeln"]) == 2
    r = fresh.put("/api/rules", json={"regeln": [{"name": "x", "tag": "A", "benutzer": "julia", "typ": "foto"}]})
    assert r.status_code == 422 and "unbekannte(r) Benutzer julia" in r.json()["details"][0]
    r = fresh.put("/api/rules", json={"yaml": "regeln:\n  - name: roh\n    tag: B\n    typ: video\n"})
    assert r.json()["regeln"] == [{"name": "roh", "tag": "B", "typ": "video"}]


def test_empty_env_values_from_compose_do_not_lock(tmp_path):
    # docker-compose reicht nicht gesetzte Variablen als leere Strings durch
    keys = ("IMMICH_URL", "REVIEW_ALBUM", "LOCATION_MAX_HOURS", "LOCATION_INCLUDE_EXTERNAL", "WEB_USER",
            "WEB_PASSWORD", "UPDATE_CHECK", "UPDATE_WEBHOOK_URL", "UPDATE_WEBHOOK_SECRET")
    s = Settings.load({"DATA_DIR": str(tmp_path), **{k: "" for k in keys}})
    assert s.locked == set() and not s.auth_enabled and s.update_check


def test_compose_file_works_with_older_compose():
    import yaml
    from pathlib import Path
    compose = yaml.safe_load((Path(__file__).parent.parent / "docker-compose.yml").read_text())
    svc = compose["services"]["immich-pflege"]
    # env_file mit "required: false" kennt Compose erst ab 2.24 – Fehler auf dem Docker-Server
    assert "env_file" not in svc
    assert "networks" not in compose  # Immich läuft auf eigenem LXC, kein gemeinsames Docker-Netz
