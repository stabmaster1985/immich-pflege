import time

import pytest
from fastapi.testclient import TestClient

from immich_pflege.web import auth
from immich_pflege.web.app import create_app


@pytest.fixture
def app_env(env):
    return {**env, "WEB_USER": "frank", "WEB_PASSWORD": "geheim123"}


@pytest.fixture
def web(app_env, http):
    with TestClient(create_app(app_env, http=http), base_url="https://pflege.local") as c:
        yield c


def login(c, pw="geheim123", remember=True):
    return c.post("/api/login", json={"benutzer": "frank", "passwort": pw, "angemeldet_bleiben": remember})


def test_browser_is_redirected_to_login_page(web):
    r = web.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login?next=/"
    page = web.get("/login")
    assert page.status_code == 200 and "Angemeldet bleiben" in page.text
    assert web.get("/static/app.css").status_code == 200  # Login-Seite braucht das Stylesheet
    # Fetch aus der Oberfläche: 401 ohne Basic-Challenge (kein Browser-Popup)
    r = web.get("/api/status", headers={"x-requested-with": "pflege"})
    assert r.status_code == 401 and r.json()["anmeldung"] and "www-authenticate" not in r.headers


def test_login_sets_long_lived_cookie(web):
    r = login(web)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "pflege_sitzung=" in cookie and "HttpOnly" in cookie and "Max-Age=7776000" in cookie
    assert "Secure" in cookie and "SameSite=lax" in cookie
    assert web.get("/api/status?server=false").status_code == 200
    assert web.get("/login", follow_redirects=False).status_code == 303  # schon angemeldet


def test_session_cookie_without_remember(web):
    r = login(web, remember=False)
    assert "Max-Age" not in r.headers["set-cookie"]
    assert web.get("/api/status?server=false").status_code == 200


def test_wrong_password_and_lockout(web, monkeypatch):
    monkeypatch.setattr("immich_pflege.web.app.asyncio.sleep", _no_sleep)
    for _ in range(auth.MAX_FAILS):
        r = login(web, pw="falsch")
        assert r.status_code == 401 and "falsch" in r.json()["fehler"]
    r = login(web)  # auch das richtige Passwort ist jetzt kurz gesperrt
    assert r.status_code == 429 and "warten" in r.json()["fehler"]


async def _no_sleep(_):
    return None


def test_logout(web):
    login(web)
    web.post("/api/logout")
    assert web.get("/api/status?server=false").status_code == 401


def test_tampered_or_expired_cookie(web, app_env):
    login(web)
    value = web.cookies.get("pflege_sitzung")
    web.cookies.clear()
    web.cookies.set("pflege_sitzung", value[:-2] + "xx", domain="pflege.local")
    assert web.get("/api/status?server=false").status_code == 401

    sessions = auth.Sessions(web.app.state.service.settings.data_dir)
    settings = web.app.state.service.settings
    expired, _ = sessions.issue(settings, True)
    real_time = time.time
    try:
        auth.time.time = lambda: real_time() + auth.LONG_S + 10
        assert sessions.check(expired, settings) is None
    finally:
        auth.time.time = real_time


def test_password_change_logs_out_everyone(env, http, tmp_path):
    with TestClient(create_app(env, http=http)) as c:
        c.put("/api/settings", json={"web_user": "frank", "web_password": "geheim123"})
        other = TestClient(c.app)
        login(other)
        assert other.get("/api/status?server=false").status_code == 200
        c.put("/api/settings", json={"web_password": "neues-pw-456"})
        assert other.get("/api/status?server=false").status_code == 401  # alte Sitzung ungültig
        assert c.get("/api/status?server=false").status_code == 200  # wer ändert, bleibt drin


def test_basic_auth_still_works_for_n8n(web):
    assert web.get("/api/status?server=false", auth=("frank", "geheim123")).status_code == 200
    r = web.get("/api/status?server=false", auth=("frank", "falsch"))
    assert r.status_code == 401 and "Basic" in r.headers["www-authenticate"]


def test_session_key_survives_restart(app_env, http):
    with TestClient(create_app(app_env, http=http)) as a:
        login(a)
        cookie = a.cookies.get("pflege_sitzung")
    with TestClient(create_app(app_env, http=http)) as b:
        b.cookies.set("pflege_sitzung", cookie)
        assert b.get("/api/status?server=false").status_code == 200


def test_app_install_files_open_without_login(web):
    """„Als App installieren“: Manifest, Symbole und Service Worker lädt der Browser ohne Sitzung."""
    m = web.get("/static/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["display"] == "standalone"
    for icon in m.json()["icons"]:
        r = web.get("/static/" + icon["src"])
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    sw = web.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    page = web.get("/login").text
    assert "manifest.webmanifest" in page and "apple-touch-icon" in page
