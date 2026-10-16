"""The demo target configuration is well formed and pinned (written by the team)."""
import json
import pathlib
import re

from bobverified import gate

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_simple_api_target_is_pinned_and_loadable():
    path = ROOT / "targets" / "simple_api.json"
    raw = json.loads(path.read_text())
    assert re.fullmatch(r"[0-9a-f]{40}", raw["commit"])
    assert raw["url"].startswith("https://github.com/")
    assert raw["license"] == "MIT"
    cfg = gate.load_config(str(path))
    assert cfg["urls"] and cfg["start_command"]
    assert "TARGET_VENV" in cfg["test_command"]  # the interpreter lives outside the target tree
