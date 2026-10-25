"""Update-Dienst (updater/pflege-updater.sh) mit echtem git und einem Docker-Ersatz."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "updater" / "pflege-updater.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
# Docker-Ersatz: Images sind Dateien in $FAKE/images, Aufrufe landen in $FAKE/calls
echo "$*" >> "$FAKE/calls"
img() { echo "$FAKE/images/$(echo "$1" | tr ':/' '__')"; }
case "$1" in
  compose) exit 0 ;;
  image)
    case "$2" in
      inspect) [ -f "$(img "$3")" ] ;;
      rm) rm -f "$(img "$3")" ;;
      prune) exit 0 ;;
    esac ;;
  build)
    tag=""; commit=""
    while [ $# -gt 0 ]; do
      case "$1" in -t) tag="$2"; shift ;; --build-arg) case "$2" in GIT_COMMIT=*) commit="${2#GIT_COMMIT=}" ;; esac; shift ;; esac
      shift
    done
    cat > /dev/null
    [ -n "${FAKE_BUILD_FAIL:-}" ] && { echo "build kaputt" >&2; exit 1; }
    echo "$commit" > "$(img "$tag")" ;;
  tag) [ -f "$(img "$2")" ] && cp "$(img "$2")" "$(img "$3")" ;;
  inspect) echo "${FAKE_HEALTH:-healthy}" ;;
esac
"""


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def setup(tmp_path):
    if not shutil.which("git") or not shutil.which("bash"):
        pytest.skip("git/bash fehlt")
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    repo = tmp_path / "immich-pflege"
    fake = tmp_path / "fake"
    (fake / "images").mkdir(parents=True)
    (fake / "bin").mkdir()
    (fake / "bin" / "docker").write_text(FAKE_DOCKER)
    (fake / "bin" / "docker").chmod(0o755)
    (fake / "images" / "immich-pflege_latest").write_text("alt\n")

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    for k, v in (("user.email", "t@example.org"), ("user.name", "Test")):
        git(work, "config", k, v)
    (work / "app.txt").write_text("v1\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "Version 1")
    git(work, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    (repo / "data").mkdir()

    env = {**os.environ, "PATH": f"{fake / 'bin'}:{os.environ['PATH']}", "FAKE": str(fake),
           "PFLEGE_DIR": str(repo), "PFLEGE_HEALTH_WAIT": "4"}

    def run(cmd, **extra):
        return subprocess.run(["bash", str(SCRIPT), cmd], env={**env, **extra}, capture_output=True, text=True)

    def publish(msg):
        (work / "app.txt").write_text(msg + "\n")
        git(work, "commit", "-qam", msg)
        git(work, "push", "-q", "origin", "main")
        return git(work, "rev-parse", "HEAD")

    def status():
        return json.loads((repo / "data" / "updater" / "status.json").read_text())

    def image(tag):
        p = fake / "images" / f"immich-pflege_{tag}"
        return p.read_text().strip() if p.exists() else None

    return dict(run=run, publish=publish, status=status, image=image, repo=repo, work=work, fake=fake)


def test_up_to_date(setup):
    r = setup["run"]("prepare")
    assert r.returncode == 0, r.stderr
    assert setup["status"]()["phase"] == "aktuell"


def test_prepare_then_apply(setup):
    old = git(setup["repo"], "rev-parse", "HEAD")
    new = setup["publish"]('Neue Funktion mit "Anführungszeichen" & \\Backslash')
    r = setup["run"]("prepare")
    assert r.returncode == 0, r.stderr
    st = setup["status"]()
    assert st["phase"] == "bereit" and st["bereit"] == new and st["aktuell"] == old
    assert st["commits"][0]["message"] == 'Neue Funktion mit "Anführungszeichen" & \\Backslash'
    assert setup["image"]("bereit") == new
    assert git(setup["repo"], "rev-parse", "HEAD") == old  # noch nicht umgeschaltet

    r = setup["run"]("apply")
    assert r.returncode == 0, r.stderr
    st = setup["status"]()
    assert st["phase"] == "fertig" and st["aktuell"] == new
    assert git(setup["repo"], "rev-parse", "HEAD") == new
    assert setup["image"]("latest") == new and setup["image"]("vorher") == "alt"


def test_rollback_when_new_version_is_unhealthy(setup):
    old = git(setup["repo"], "rev-parse", "HEAD")
    setup["publish"]("Kaputte Version")
    setup["run"]("prepare")
    r = setup["run"]("apply", FAKE_HEALTH="unhealthy")
    assert r.returncode != 0
    st = setup["status"]()
    assert st["phase"] == "fehler" and "alte Version läuft wieder" in st["meldung"]
    assert git(setup["repo"], "rev-parse", "HEAD") == old
    assert setup["image"]("latest") == "alt"


def test_build_failure_keeps_running_version(setup):
    setup["publish"]("Version 2")
    r = setup["run"]("prepare", FAKE_BUILD_FAIL="1")
    assert r.returncode != 0
    st = setup["status"]()
    assert st["phase"] == "fehler" and "laufende Version bleibt" in st["meldung"]
    assert "build kaputt" in st["log"]
    assert setup["run"]("apply").returncode != 0  # nichts vorbereitet


def test_handle_request_from_app(setup):
    new = setup["publish"]("Version 2")
    req = setup["repo"] / "data" / "updater" / "request.json"
    req.parent.mkdir(parents=True, exist_ok=True)
    req.write_text(json.dumps({"aktion": "vorbereiten"}))
    assert setup["run"]("handle").returncode == 0
    assert not req.exists() and setup["status"]()["phase"] == "bereit"
    req.write_text(json.dumps({"aktion": "umschalten"}))
    assert setup["run"]("handle").returncode == 0
    assert setup["status"]()["phase"] == "fertig" and git(setup["repo"], "rev-parse", "HEAD") == new


@pytest.mark.skipif(os.name != "posix" or os.geteuid() != 0, reason="nur als root (wie der systemd-Dienst)")
def test_apply_refreshes_systemd_units(setup, tmp_path):
    """Nach dem Umschalten übernimmt der Dienst neue systemd-Units selbst – ohne n8n."""
    units = tmp_path / "systemd"
    units.mkdir()
    (setup["fake"] / "bin" / "systemctl").write_text('#!/usr/bin/env bash\necho "systemctl $*" >> "$FAKE/calls"\n')
    (setup["fake"] / "bin" / "systemctl").chmod(0o755)
    shutil.copytree(SCRIPT.parent, setup["work"] / "updater")
    setup["publish"]("Version mit Update-Dienst")
    git(setup["work"], "add", "updater")
    git(setup["work"], "commit", "-qm", "Update-Dienst")
    git(setup["work"], "push", "-q", "origin", "main")
    new = git(setup["work"], "rev-parse", "HEAD")
    assert setup["run"]("prepare").returncode == 0
    r = setup["run"]("apply", PFLEGE_SYSTEMD_DIR=str(units))
    assert r.returncode == 0, r.stderr
    assert setup["status"]()["phase"] == "fertig" and git(setup["repo"], "rev-parse", "HEAD") == new
    service = (units / "immich-pflege-updater.service").read_text()
    assert f"{setup['repo']}/updater/pflege-updater.sh handle" in service
    calls = (setup["fake"] / "calls").read_text()
    assert "systemctl daemon-reload" in calls and "systemctl enable --now" in calls


# ------------------------------------------------------------- App-Seite
def _write_status(data_dir, **kw):
    from datetime import datetime, timezone
    d = data_dir / "updater"
    d.mkdir(parents=True, exist_ok=True)
    base = {"phase": "aktuell", "meldung": "", "aktuell": "a" * 40, "bereit": "", "commits": [],
            "zeit": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "dienst_version": 1}
    (d / "status.json").write_text(json.dumps({**base, **kw}))


def test_app_talks_to_updater(env, http):
    from fastapi.testclient import TestClient

    from immich_pflege.web.app import create_app
    data = Path(env["DATA_DIR"])
    with TestClient(create_app(env, http=http, auto_scan_enabled=False)) as c:
        assert c.get("/api/updater").json()["verfuegbar"] is False
        assert c.post("/api/updater/prepare").status_code == 400

        _write_status(data)
        assert c.get("/api/updater").json()["verfuegbar"] is True
        r = c.post("/api/updater/prepare")
        assert r.status_code == 200
        assert json.loads((data / "updater" / "request.json").read_text())["aktion"] == "vorbereiten"

        assert c.post("/api/updater/apply", json={"bereit": "b" * 40}).status_code == 400  # nichts bereit
        _write_status(data, phase="bereit", bereit="b" * 40, commits=[{"commit": "b" * 40, "message": "Neu"}])
        assert c.get("/api/version").json()["update_available"] is True
        assert c.post("/api/updater/apply", json={"bereit": "c" * 40}).status_code == 400  # andere Version
        r = c.post("/api/updater/apply", json={"bereit": "b" * 40})
        assert r.status_code == 200
        assert json.loads((data / "updater" / "request.json").read_text())["aktion"] == "umschalten"

        _write_status(data, zeit="2020-01-01T00:00:00Z")
        assert c.get("/api/updater").json()["verfuegbar"] is False  # Dienst seit Stunden still
