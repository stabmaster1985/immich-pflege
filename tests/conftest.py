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
def settings(tmp_path) -> Settings:
    return Settings(
        immich_url="http://immich-server:2283",
        users={"frank": "key-frank", "julia": "key-julia"},
        data_dir=tmp_path / "data",
        config_dir=tmp_path / "config",
        rules_file=tmp_path / "config" / "regeln.yaml",
    )
