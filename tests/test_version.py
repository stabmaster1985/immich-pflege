import json

import httpx
import pytest
from fastapi.testclient import TestClient

from immich_pflege.gitinfo import read_git_version
from immich_pflege.version import Version
from immich_pflege.web.app import create_app

OLD = "a" * 40
NEW = "b" * 40


def github(status="ahead", latest=NEW, calls=None):
    def handler(request: httpx.Request):
        if calls is not None:
            calls.append(request)
        path = request.url.path
        if path.endswith("/commits/main"):
            return httpx.Response(200, json={"sha": latest, "commit": {
                "message": "Neu\n\nDetails", "committer": {"date": "2026-10-24T20:00:00Z"}}})
        if "/compare/" in path:
            return httpx.Response(200, json={"status": status, "ahead_by": 2, "commits": [
                {"sha": "c1", "commit": {"message": "Erster", "committer": {"date": "x"}}},
                {"sha": latest, "commit": {"message": "Neu", "committer": {"date": "y"}}}]})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def vfile(tmp_path):
    f = tmp_path / "version.json"
    f.write_text(json.dumps({"commit": OLD, "branch": "main", "updated_at": None}))
    return f


def test_read_git_version(tmp_path):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text(OLD + "\n")
    (git / "logs").mkdir()
    (git / "logs" / "HEAD").write_text(f"0 {OLD} Frank <f@x> 1729800000 +0200\tpull\n")
    v = read_git_version(tmp_path)
    assert v["commit"] == OLD and v["branch"] == "main" and v["updated_at"].startswith("2024-10-24")
    # gepackte Refs
    (git / "refs" / "heads" / "main").unlink()
    (git / "packed-refs").write_text(f"# pack-refs\n{NEW} refs/heads/main\n")
    assert read_git_version(tmp_path)["commit"] == NEW


def test_update_available(vfile):
    calls = []
    v = Version("stabmaster1985/immich-pflege", http=github(calls=calls), files=(vfile,))
    v.refresh()
    info = v.get()
    assert v.update_available and info["behind"] == 2
    assert [c["message"] for c in info["commits"]] == ["Neu", "Erster"]
    v.refresh()  # innerhalb einer Stunde keine neue Anfrage
    assert len(calls) == 2


def test_current_and_errors(vfile, tmp_path):
    v = Version("x/y", http=github(latest=OLD), files=(vfile,))
    v.refresh()
    assert v.get()["status"] == "current" and not v.update_available
    v = Version("x/y", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                files=(vfile,))
    v.refresh()
    assert "privates Repo" in v.get()["error"] and not v.update_available
    off = Version("x/y", enabled=False, files=(vfile,))
    off.refresh()
    assert off.get()["enabled"] is False and "status" not in off.get()


def test_update_button_calls_n8n(env, http, vfile):
    posted = []

    def handler(request):
        posted.append(request)
        return httpx.Response(202)
    ext = httpx.Client(transport=httpx.MockTransport(handler))
    v = Version("x/y", http=github(), files=(vfile,))
    with TestClient(create_app(env, http=http, ext_http=ext, version=v)) as c:
        r = c.post("/api/version/update")
        assert r.status_code == 400 and "Webhook" in r.json()["fehler"]
        c.put("/api/settings", json={"update_webhook_url": "http://n8n:5678/webhook/immich-pflege-update",
                                    "update_webhook_secret": "geheim"})
        info = c.post("/api/version/check").json()
        assert info["update_available"] and info["update_moeglich"]
        r = c.post("/api/version/update")
        assert r.json()["ok"] is True
        assert posted[0].headers["X-Update-Key"] == "geheim"
        assert json.loads(posted[0].content) == {"typ": "update", "von": OLD, "auf": NEW}
        pub = c.get("/api/settings").json()
        assert pub["update_webhook_secret_gesetzt"] and "geheim" not in json.dumps(pub)


def test_update_webhook_down(env, http, vfile):
    ext = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    v = Version("x/y", enabled=False, files=(vfile,))
    with TestClient(create_app({**env, "UPDATE_WEBHOOK_URL": "http://n8n/webhook/x"}, http=http,
                               ext_http=ext, version=v)) as c:
        r = c.post("/api/version/update")
        assert r.status_code == 502 and "abgelehnt" in r.json()["fehler"]


def test_update_without_auth(env, http, vfile):
    posted = []

    def handler(request):
        posted.append(request)
        return httpx.Response(200)
    ext = httpx.Client(transport=httpx.MockTransport(handler))
    v = Version("x/y", enabled=False, files=(vfile,))
    with TestClient(create_app(env, http=http, ext_http=ext, version=v)) as c:
        r = c.put("/api/settings", json={"update_webhook_url": "http://n8n:5678/webhook/immich-pflege-update",
                                         "update_webhook_header": "", "update_webhook_secret": "alt"})
        assert r.status_code == 200, r.text
        pub = r.json()
        assert pub["update_webhook_header"] == "" and not pub["update_webhook_secret_gesetzt"]
        # bleibt nach erneutem Laden leer (nicht wieder X-Update-Key)
        assert c.get("/api/settings").json()["update_webhook_header"] == ""
        assert c.post("/api/version/update").json()["ok"] is True
        assert "x-update-key" not in {k.lower() for k in posted[0].headers}
        # Auth wieder einschalten
        c.put("/api/settings", json={"update_webhook_header": "X-Update-Key", "update_webhook_secret": "neu"})
        c.post("/api/version/update")
        assert posted[1].headers["X-Update-Key"] == "neu"
