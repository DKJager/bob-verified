"""Tests for scripts/fetch_target.sh (written by the team; Bob writes the script)."""
import json
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch_target.sh"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def upstream(tmp_path):
    up = tmp_path / "upstream"
    up.mkdir()
    git(up, "init", "-q", "-b", "main")
    git(up, "config", "user.email", "u@example.com")
    git(up, "config", "user.name", "U")
    (up / "app.py").write_text("v = 1\n")
    git(up, "add", "-A")
    git(up, "commit", "-q", "-m", "first")
    first = git(up, "rev-parse", "HEAD")
    (up / "app.py").write_text("v = 2\n")
    git(up, "commit", "-q", "-am", "second")
    return up, first


def write_target(tmp_path, url, commit):
    t = tmp_path / "target.json"
    t.write_text(json.dumps({"name": "tiny", "url": str(url), "commit": commit, "license": "MIT",
                             "test_command": "true"}))
    return t


def fetch(target, dest):
    return subprocess.run(["bash", str(SCRIPT), str(target), str(dest)], capture_output=True, text=True)


def test_fetch_clones_at_pinned_commit(tmp_path, upstream):
    up, first = upstream
    dest = tmp_path / "work" / "tiny"
    r = fetch(write_target(tmp_path, up, first), dest)
    assert r.returncode == 0, r.stdout + r.stderr
    assert git(dest, "rev-parse", "HEAD") == first
    assert (dest / "app.py").read_text() == "v = 1\n"
    assert first in r.stdout


def test_fetch_is_idempotent_and_resets_changes(tmp_path, upstream):
    up, first = upstream
    dest = tmp_path / "work" / "tiny"
    target = write_target(tmp_path, up, first)
    assert fetch(target, dest).returncode == 0
    (dest / "app.py").write_text("tampered\n")
    (dest / "junk.txt").write_text("x")
    r = fetch(target, dest)
    assert r.returncode == 0, r.stderr
    assert (dest / "app.py").read_text() == "v = 1\n"
    assert not (dest / "junk.txt").exists()


def test_fetch_fails_on_unknown_commit(tmp_path, upstream):
    up, _ = upstream
    r = fetch(write_target(tmp_path, up, "0" * 40), tmp_path / "work" / "tiny")
    assert r.returncode != 0


def test_fetch_refuses_destination_inside_this_repository(tmp_path, upstream):
    up, first = upstream
    r = fetch(write_target(tmp_path, up, first), ROOT / "work" / "tiny")
    assert r.returncode == 2
    assert not (ROOT / "work" / "tiny").exists()


def test_fetch_sets_a_commit_identity_for_the_runner(tmp_path, upstream):
    up, first = upstream
    dest = tmp_path / "work" / "tiny"
    assert fetch(write_target(tmp_path, up, first), dest).returncode == 0
    assert git(dest, "config", "user.name") != ""
    assert git(dest, "config", "user.email") != ""
    assert git(dest, "rev-parse", "--abbrev-ref", "HEAD") == "modernize"
