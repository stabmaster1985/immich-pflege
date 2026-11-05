"""Kennzahlen per MQTT an Home Assistant – mit Discovery, also ohne YAML in Home Assistant.

Optional und standardmäßig aus (MQTT_ENABLED). Läuft als Hintergrund-Task im Lifespan der App:
verbindet mit Backoff (5 s bis 5 min) neu, Fehler werden nur geloggt – ein fehlender Broker
blockiert nie die App.

Topics (``<base>`` = MQTT_BASE_TOPIC, Standard immich_pflege):
- ``<base>/status``: online/offline (retained, Last Will)
- ``<base>/state``: Kennzahlen als JSON (retained) – nach Einlesen, Vormerken, Übertragen, Rückgängig
  und alle MQTT_PUBLISH_INTERVAL Sekunden
- ``<base>/cmd/scan``: Knopf „Neu scannen“ (wie POST /api/scan)
- ``<prefix>/<komponente>/immich_pflege/<objekt>/config``: Discovery (retained), neu gesendet beim
  Verbinden und wenn Home Assistant ``<prefix>/status`` = online meldet

Bewusst nicht per MQTT: Übernehmen, Löschen, Taggen – das bleibt in der Oberfläche mit Vorschau.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import Settings

log = logging.getLogger(__name__)

NODE = "immich_pflege"  # fest: Gerät und unique_ids in Home Assistant
BACKOFF_S = (5, 300)  # erster und längster Abstand zwischen Verbindungsversuchen
DEBOUNCE_S = 2.0  # mehrere Änderungen kurz hintereinander = eine Nachricht
MB = 1024 * 1024


# ------------------------------------------------------------------ Zustand
def _local(iso: str | None, tz: str) -> str | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")
    except (ValueError, KeyError):
        return iso


def build_state(svc, version: str, update_available: bool) -> dict[str, Any]:
    """Kennzahlen aus denselben Funktionen wie Dashboard, Menüzähler und Vorgemerkt (keine eigene Rechnung).
    Was gerade nicht bekannt ist (z. B. Alben werden noch gelesen), steht als null."""
    s: Settings = svc.settings
    state: dict[str, Any] = {"status": "ok", "version": version, "update_verfuegbar": update_available,
                             "immich_erreichbar": False}
    if not svc.clients:
        return {**state, "status": "nicht_eingerichtet"}
    try:
        next(iter(svc.clients.values())).server_version()
        state["immich_erreichbar"] = True
    except Exception as exc:  # noqa: BLE001 – Zustand trotzdem melden
        log.debug("MQTT: Immich nicht erreichbar: %s", exc)
        state["status"] = "immich_nicht_erreichbar"
    staged = svc.staging.summary()
    last_change = max((e.get("zeit") for e in svc.history.entries if e.get("zeit")), default=None)
    state.update(vorgemerkt=staged["anzahl"], papierkorb=staged["papierkorb"],
                 letzte_aenderung=_local(last_change, s.timezone))
    lib = svc.cached_library()
    if lib is None:
        return {**state, "status": "noch_nicht_eingelesen" if state["status"] == "ok" else state["status"]}

    def safe(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 – ein Wert fehlt, der Rest kommt trotzdem
            log.warning("MQTT: Wert nicht ermittelbar: %s", exc)
            return None

    dup = safe(svc.duplicate_savings)
    loc = safe(lambda: svc.no_location_view(overview=True))
    state.update(
        medien_gesamt=len(lib.assets),
        duplikate_gruppen=dup[0] if dup else None,
        duplikate_einsparung_mb=round(dup[1] / MB, 1) if dup else None,
        ohne_ort=loc["medien"] if loc else None,
        ohne_ort_vorschlaege=loc["mit_vorschlag"] if loc else None,
        aufraeum_kandidaten=safe(lambda: svc.cleanup_view(limit=0)["gesamt"]),
        album_vorschlaege=None if svc.albums_pending() else safe(lambda: svc.albums_view(limit=0)["offen"]),
        tag_vorschlaege=safe(lambda: len(svc.suggestions_view()["vorschlaege"])),
        letzter_scan=_local(lib.scanned_at, s.timezone),
    )
    return state


# ---------------------------------------------------------------- Discovery
SENSORS: list[tuple[str, str, str, dict[str, Any]]] = [
    # (Komponente, Objekt, Name, Zusätze)
    ("sensor", "duplikate_gruppen", "Duplikate",
     {"icon": "mdi:content-duplicate", "state_class": "measurement", "attribute": "duplikate_einsparung_mb"}),
    ("sensor", "duplikate_einsparung_mb", "Duplikate Einsparung",
     {"unit_of_measurement": "MB", "device_class": "data_size", "state_class": "measurement", "icon": "mdi:harddisk"}),
    ("sensor", "ohne_ort", "Fotos ohne Ort",
     {"icon": "mdi:map-marker-question", "state_class": "measurement", "attribute": "ohne_ort_vorschlaege"}),
    ("sensor", "aufraeum_kandidaten", "Aufräum-Kandidaten", {"icon": "mdi:broom", "state_class": "measurement"}),
    ("sensor", "album_vorschlaege", "Album-Vorschläge", {"icon": "mdi:image-album", "state_class": "measurement"}),
    ("sensor", "tag_vorschlaege", "Tag-Vorschläge", {"icon": "mdi:tag-multiple", "state_class": "measurement"}),
    ("sensor", "vorgemerkt", "Vorgemerkt", {"icon": "mdi:playlist-check", "state_class": "measurement",
                                           "attribute": "papierkorb"}),
    ("sensor", "medien_gesamt", "Medien gesamt",
     {"icon": "mdi:image-multiple", "state_class": "measurement", "entity_category": "diagnostic"}),
    ("sensor", "letzter_scan", "Letzter Scan", {"device_class": "timestamp", "entity_category": "diagnostic"}),
    ("sensor", "version", "Version", {"icon": "mdi:tag-outline", "entity_category": "diagnostic"}),
    ("binary_sensor", "immich_erreichbar", "Immich erreichbar",
     {"device_class": "connectivity", "entity_category": "diagnostic", "bool": True}),
    ("binary_sensor", "update_verfuegbar", "Update verfügbar", {"device_class": "update", "bool": True}),
]


def topics(s: Settings) -> dict[str, str]:
    base = s.mqtt_base_topic
    return {"status": f"{base}/status", "state": f"{base}/state", "cmd": f"{base}/cmd/#",
            "scan": f"{base}/cmd/scan", "ha_status": f"{s.mqtt_discovery_prefix}/status"}


def discovery(s: Settings, version: str) -> list[tuple[str, dict[str, Any]]]:
    """(Topic, Payload) je Entität – Gerät „Immich-Pflege“ mit Sensoren, Binärsensoren und Scan-Knopf."""
    t = topics(s)
    device = {"identifiers": [NODE], "name": "Immich-Pflege", "manufacturer": "stabmaster1985",
              "model": "Immich-Pflege", "sw_version": version}
    if s.public_url:
        device["configuration_url"] = s.public_url
    common = {"availability_topic": t["status"], "payload_available": "online", "payload_not_available": "offline",
              "device": device, "origin": {"name": "Immich-Pflege", "sw_version": version},
              "has_entity_name": True}
    out = []
    for component, obj, name, extra in SENSORS:
        extra = dict(extra)
        cfg: dict[str, Any] = {**common, "name": name, "unique_id": f"{NODE}_{obj}", "object_id": f"{NODE}_{obj}",
                               "state_topic": t["state"]}
        if extra.pop("bool", False):
            cfg["value_template"] = f"{{{{ 'ON' if value_json.{obj} else 'OFF' }}}}"
        else:
            cfg["value_template"] = f"{{{{ value_json.{obj} }}}}"
        attribute = extra.pop("attribute", None)
        if attribute:
            cfg["json_attributes_topic"] = t["state"]
            cfg["json_attributes_template"] = f'{{{{ {{"{attribute}": value_json.{attribute}}} | tojson }}}}'
        cfg.update(extra)
        out.append((f"{s.mqtt_discovery_prefix}/{component}/{NODE}/{obj}/config", cfg))
    out.append((f"{s.mqtt_discovery_prefix}/button/{NODE}/scan/config",
                {**common, "name": "Neu scannen", "unique_id": f"{NODE}_scan", "object_id": f"{NODE}_scan",
                 "command_topic": t["scan"], "payload_press": "PRESS", "icon": "mdi:refresh"}))
    return out


# ------------------------------------------------------------------- Brücke
class MqttBridge:
    """Hält die Verbindung zum Broker. ``trigger()`` (aus jedem Thread) schickt den Zustand bald neu."""

    def __init__(self, get_service: Callable[[], Any], get_version: Callable[[], tuple[str, bool]],
                 start_scan: Callable[[], bool]):
        self._get_service = get_service
        self._get_version = get_version
        self._start_scan = start_scan
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._event: asyncio.Event | None = None
        self._client = None
        self.connected = False
        self.error: str | None = None
        self.last_sent: str | None = None

    # ---------------------------------------------------------- Steuerung
    def start(self) -> None:
        """Im laufenden Event-Loop (Lifespan) starten – nur wenn eingeschaltet und ein Broker eingetragen ist."""
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()
        s = self._get_service().settings
        if s.mqtt_enabled and s.mqtt_host:
            self._task = self._loop.create_task(self._run(), name="mqtt")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        client = self._client
        if client is not None:  # sauber abmelden: „offline“ statt auf den Last Will zu warten
            try:
                await asyncio.wait_for(client.publish(topics(self._get_service().settings)["status"], "offline",
                                                      qos=1, retain=True), 2)
            except Exception:  # noqa: BLE001
                pass
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self.connected = False

    def restart(self) -> None:
        """Nach geänderten Einstellungen (aus einem beliebigen Thread)."""
        if self._loop is None:
            return

        async def again():
            await self.stop()
            self.error = None
            self.start()
        asyncio.run_coroutine_threadsafe(again(), self._loop)

    def trigger(self) -> None:
        """Zustand bald neu senden (thread-sicher; ohne Verbindung passiert nichts)."""
        if self._loop is not None and self._event is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._event.set)

    def info(self) -> dict[str, Any]:
        s = self._get_service().settings
        return {"aktiv": bool(s.mqtt_enabled and s.mqtt_host), "verbunden": self.connected, "fehler": self.error,
                "zuletzt_gesendet": self.last_sent, "broker": f"{s.mqtt_host}:{s.mqtt_port}" if s.mqtt_host else None,
                "topic": topics(s)["state"]}

    # ---------------------------------------------------------- Ablauf
    async def _run(self) -> None:
        try:
            import aiomqtt
        except ImportError:
            self.error = "Python-Paket aiomqtt fehlt (pip install aiomqtt)"
            log.error("MQTT: %s", self.error)
            return

        backoff = BACKOFF_S[0]
        while True:
            s = self._get_service().settings
            t = topics(s)
            try:
                async with aiomqtt.Client(
                        hostname=s.mqtt_host, port=s.mqtt_port, username=s.mqtt_user or None,
                        password=s.mqtt_password or None, identifier=f"immich-pflege-{s.mqtt_base_topic}",
                        will=aiomqtt.Will(t["status"], "offline", qos=1, retain=True), keepalive=60,
                        timeout=10) as client:
                    self._client, self.connected, self.error, backoff = client, True, None, BACKOFF_S[0]
                    log.info("MQTT verbunden mit %s:%s", s.mqtt_host, s.mqtt_port)
                    await client.publish(t["status"], "online", qos=1, retain=True)
                    await self._send_discovery(client)
                    await client.subscribe(t["cmd"])
                    await client.subscribe(t["ha_status"])
                    await self._send_state(client)
                    listen = asyncio.create_task(self._listen(client))
                    periodic = asyncio.create_task(self._periodic(client))
                    try:
                        done, _ = await asyncio.wait({listen, periodic}, return_when=asyncio.FIRST_EXCEPTION)
                        for task in done:
                            task.result()  # Fehler weiterreichen -> neu verbinden
                    finally:
                        listen.cancel()
                        periodic.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 – Broker weg, falsches Passwort …: später noch einmal
                self.error = str(exc) or exc.__class__.__name__
                log.warning("MQTT (%s:%s): %s – neuer Versuch in %d s", s.mqtt_host, s.mqtt_port, self.error, backoff)
            finally:
                self._client, self.connected = None, False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_S[1])

    async def _send_discovery(self, client) -> None:
        version, _ = self._get_version()
        for topic, payload in discovery(self._get_service().settings, version):
            await client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)

    async def _send_state(self, client) -> None:
        version, update = self._get_version()
        state = await asyncio.to_thread(build_state, self._get_service(), version, update)
        await client.publish(topics(self._get_service().settings)["state"], json.dumps(state, ensure_ascii=False),
                             qos=1, retain=True)
        self.last_sent = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async def _periodic(self, client) -> None:
        while True:
            interval = self._get_service().settings.mqtt_publish_interval
            try:
                await asyncio.wait_for(self._event.wait(), timeout=interval)
                await asyncio.sleep(DEBOUNCE_S)  # weitere Änderungen abwarten
            except TimeoutError:
                pass
            self._event.clear()
            await self._send_state(client)

    async def _listen(self, client) -> None:
        async for message in client.messages:
            await self.handle(client, str(message.topic), bytes(message.payload or b""))

    async def handle(self, client, topic: str, payload: bytes) -> None:
        t = topics(self._get_service().settings)
        if topic == t["scan"]:
            started = await asyncio.to_thread(self._start_scan)
            log.info("MQTT: Neu scannen %s", "gestartet" if started else "übersprungen (läuft schon / nicht eingerichtet)")
        elif topic == t["ha_status"] and payload.strip().lower() == b"online":
            log.info("MQTT: Home Assistant ist (wieder) da – Discovery neu senden")
            await self._send_discovery(client)
            await self._send_state(client)
