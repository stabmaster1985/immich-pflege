from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from immich_pflege.client import ImmichClient
from immich_pflege.config import Settings
from tests.mock_immich import MockState, create_app, demo_state

API = "http://immich-server:2283/api"


@pytest.fixture
def state() -> MockState:
    return demo_state()


@pytest.fixture
def http(state):
    with TestClient(create_app(state), base_url="http://immich-server:2283") as tc:
        yield tc


@pytest.fixture
def clients(state, http) -> dict[str, ImmichClient]:
    return {u["name"].lower(): ImmichClient(API, key, u["name"].lower(), http=http)
            for key, u in state.users.items()}


@pytest.fixture
def env(tmp_path) -> dict[str, str]:
    """Umgebung wie per .env konfiguriert."""
    return {"DATA_DIR": str(tmp_path / "data"), "IMMICH_URL": "http://immich-server:2283",
            "IMMICH_KEY_FRANK": "key-frank", "IMMICH_KEY_JULIA": "key-julia"}


@pytest.fixture
def settings(env) -> Settings:
    return Settings.load(env)
