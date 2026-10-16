"""The dashboard ships with deployment files (written by the team)."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def read(rel):
    return (ROOT / rel).read_text()


def test_dockerfile_runs_the_dashboard():
    d = read("deploy/Dockerfile")
    assert re.search(r"^FROM python:3\.12", d, re.M)
    assert "EXPOSE 8080" in d
    assert "bobverified.dashboard" in d
    assert "0.0.0.0" in d


def test_systemd_unit_runs_the_dashboard():
    u = read("deploy/bob-verified-dashboard.service")
    assert "[Service]" in u and "ExecStart=" in u and "bobverified.dashboard" in u


def test_deploy_notes_mention_the_essentials():
    t = read("deploy/DEPLOY.md")
    for needle in ["8080", "--run", "reverify", "TARGET_VENV"]:
        assert needle in t


def test_no_secrets_in_deploy_files():
    for rel in ["deploy/Dockerfile", "deploy/bob-verified-dashboard.service", "deploy/DEPLOY.md"]:
        assert "BOB_API_KEY=" not in read(rel)
