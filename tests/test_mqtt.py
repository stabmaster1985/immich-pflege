"""Home Assistant per MQTT: Zustand und Discovery ohne Broker, Start ohne/mit nicht erreichbarem Broker."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from immich_pflege.config import Settings
from immich_pflege.mqtt import MqttBridge, build_state, discovery, topics
from immich_pflege.web.app import create_app


@pytest.fixture
def web(env, http):
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        yield c


def test_state_uses_same_numbers_as_the_app(web):
    svc = web.app.state.service
    web.get("/api/duplicates")  # einlesen
    state = build_state(svc, "1.2.3", False)
    counts = web.get("/api/nav-counts").json()
    assert state["status"] == "ok" and state["immich_erreichbar"] is True and state["version"] == "1.2.3"
    assert state["medien_gesamt"] == web.get("/api/dashboard").json()["gesamt"]["medien"]
    assert state["duplikate_gruppen"] == counts["dup"] and state["duplikate_einsparung_mb"] >= 0
    assert state["ohne_ort_vorschlaege"] == counts["ort"] and state["ohne_ort"] >= state["ohne_ort_vorschlaege"]
    assert state["tag_vorschlaege"] == counts["tags"] and state["vorgemerkt"] == 0
    assert state["letzter_scan"].endswith(("+01:00", "+02:00"))  # Ortszeit mit Versatz
    gid = web.get("/api/duplicates").json()["gruppen"][0]["id"]
    web.post("/api/staged/duplicates", json={"action": "album", "groups": [{"id": gid}]})
    after = build_state(svc, "1.2.3", True)
    assert after["vorgemerkt"] == 1 and after["update_verfuegbar"] is True
    assert after["duplikate_gruppen"] == state["duplikate_gruppen"] - 1


def test_state_without_configuration(tmp_path):
    svc = type("S", (), {"settings": Settings(data_dir=tmp_path), "clients": {}})()
    assert build_state(svc, "1", False)["status"] == "nicht_eingerichtet"


def test_discovery_payloads(tmp_path):
    s = Settings(data_dir=tmp_path, public_url="http://192.168.0.114:2222")
    items = dict(discovery(s, "1.2.3"))
    assert "homeassistant/sensor/immich_pflege/duplikate_gruppen/config" in items
    assert "homeassistant/button/immich_pflege/scan/config" in items
    dup = items["homeassistant/sensor/immich_pflege/duplikate_gruppen/config"]
    assert dup["unique_id"] == "immich_pflege_duplikate_gruppen" and dup["state_topic"] == "immich_pflege/state"
    assert dup["availability_topic"] == "immich_pflege/status" and dup["icon"] == "mdi:content-duplicate"
    assert dup["device"] == {"identifiers": ["immich_pflege"], "name": "Immich-Pflege", "manufacturer": "stabmaster1985",
                             "model": "Immich-Pflege", "sw_version": "1.2.3",
                             "configuration_url": "http://192.168.0.114:2222"}
    assert "duplikate_einsparung_mb" in dup["json_attributes_template"]
    mb = items["homeassistant/sensor/immich_pflege/duplikate_einsparung_mb/config"]
    assert mb["unit_of_measurement"] == "MB" and mb["device_class"] == "data_size"
    scan = items["homeassistant/sensor/immich_pflege/letzter_scan/config"]
    assert scan["device_class"] == "timestamp" and scan["entity_category"] == "diagnostic"
    online = items["homeassistant/binary_sensor/immich_pflege/immich_erreichbar/config"]
    assert online["device_class"] == "connectivity" and "'ON' if value_json.immich_erreichbar" in online["value_template"]
    assert items["homeassistant/binary_sensor/immich_pflege/update_verfuegbar/config"]["device_class"] == "update"
    button = items["homeassistant/button/immich_pflege/scan/config"]
    assert button["command_topic"] == "immich_pflege/cmd/scan" and "state_topic" not in button
    # eigene Topics
    s2 = Settings(data_dir=tmp_path, mqtt_base_topic="pflege", mqtt_discovery_prefix="ha")
    assert topics(s2)["state"] == "pflege/state"
    assert all(t.startswith("ha/") for t, _ in discovery(s2, "1")) and "configuration_url" not in discovery(s2, "1")[0][1]["device"]


def test_disabled_starts_no_client(web):
    assert web.app.state.mqtt._task is None
    assert web.get("/api/mqtt").json()["aktiv"] is False


def test_unreachable_broker_does_not_block(env, http):
    env = {**env, "MQTT_ENABLED": "true", "MQTT_HOST": "127.0.0.1", "MQTT_PORT": "1"}
    started = time.monotonic()
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        assert c.get("/healthz").json()["ok"] is True
        for _ in range(50):
            info = c.get("/api/mqtt").json()
            if info["fehler"]:
                break
            time.sleep(0.1)
        assert info["aktiv"] is True and info["verbunden"] is False and info["fehler"]
        assert c.post("/api/mqtt/publish").status_code == 200  # ohne Verbindung harmlos
    assert time.monotonic() - started < 10


def test_scan_button_and_ha_restart(tmp_path):
    sent, scans = [], []

    class FakeClient:
        async def publish(self, topic, payload, qos=0, retain=False):
            sent.append(topic)

    svc = type("S", (), {"settings": Settings(data_dir=tmp_path), "clients": {}})()
    bridge = MqttBridge(lambda: svc, lambda: ("1", False), lambda: scans.append(1) or True)

    async def go():
        await bridge.handle(FakeClient(), "immich_pflege/cmd/scan", b"PRESS")
        await bridge.handle(FakeClient(), "homeassistant/status", b"online")
        await bridge.handle(FakeClient(), "homeassistant/status", b"offline")
    asyncio.run(go())
    assert scans == [1]
    assert "immich_pflege/state" in sent and sum(t.endswith("/config") for t in sent) == len(discovery(svc.settings, "1"))


def test_settings_roundtrip(web):
    r = web.put("/api/settings", json={"mqtt_enabled": False, "mqtt_host": "mqtt://192.168.0.102", "mqtt_port": 1884,
                                        "mqtt_user": "ha", "mqtt_password": "geheim", "public_url": "http://192.168.0.114:2222"})
    assert r.status_code == 200, r.text
    d = web.get("/api/settings").json()
    assert d["mqtt_host"] == "192.168.0.102" and d["mqtt_port"] == 1884 and d["mqtt_password_gesetzt"] is True
    assert "geheim" not in web.get("/api/settings").text  # Passwort geht nie an den Browser
    assert web.put("/api/settings", json={"mqtt_base_topic": "a/#"}).status_code in (400, 422)
    assert web.put("/api/settings", json={"mqtt_publish_interval": 5}).status_code in (400, 422)
