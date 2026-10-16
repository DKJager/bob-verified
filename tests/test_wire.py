"""Tests for bobverified.wire (written by the team; Bob writes the implementation)."""
import json
import shlex
import sys

import pytest

from bobverified import wire

PLAN = {
    "title": "Modernize tinyapp",
    "steps": [
        {"id": "step_01", "title": "Pin dependencies", "description": "Pin every dependency.",
         "verify": "python -c 'print(\"hi there\")'"},
        {"id": "step_02", "title": "Port to Python 3.12", "description": "Fix syntax.", "verify": "true"},
    ],
}


def write(path, obj):
    path.write_text(json.dumps(obj))
    return str(path)


@pytest.fixture
def target(tmp_path):
    return write(tmp_path / "target.json", {
        "name": "tiny", "url": "https://example.com/tiny", "commit": "abc123", "license": "MIT",
        "test_command": "true", "start_command": None, "urls": [], "start_wait_s": 3})


def test_load_plan_valid(tmp_path):
    plan = wire.load_plan(write(tmp_path / "plan.json", PLAN))
    assert [s["id"] for s in plan["steps"]] == ["step_01", "step_02"]


@pytest.mark.parametrize("mutate", [
    lambda p: p.update(steps=[]),
    lambda p: p["steps"][0].pop("verify"),
    lambda p: p["steps"][0].update(verify="  "),
    lambda p: p["steps"][0].pop("title"),
    lambda p: p["steps"][1].update(id="step_01"),
    lambda p: p["steps"][0].update(id="Bad Id!"),
    lambda p: p.pop("steps"),
])
def test_load_plan_rejects_bad_plans(tmp_path, mutate):
    plan = json.loads(json.dumps(PLAN))
    mutate(plan)
    with pytest.raises(ValueError):
        wire.load_plan(write(tmp_path / "plan.json", plan))


def test_step_prompt_mentions_the_essentials():
    p = wire.step_prompt(PLAN["steps"][0], 1, 2)
    for needle in ["step_01", "Pin dependencies", "Pin every dependency.", "hi there", "only that step"]:
        assert needle in p


def test_build_tasks_shape_and_gate_command(tmp_path, target):
    ev = tmp_path / "ev"
    cfg = wire.build_tasks(PLAN, target, str(tmp_path / "work"), str(ev), python=sys.executable,
                           pkg_root=str(tmp_path / "pkg"), budget_total=12, max_cost=2.5, max_turns=33,
                           gate_after_task=2, gate_max_spent=6)
    assert cfg["budget_total"] == 12 and cfg["gate_after_task"] == 2 and cfg["gate_max_spent"] == 6
    assert "@" in cfg["author"]
    assert [t["id"] for t in cfg["tasks"]] == ["step_01", "step_02"]
    t = cfg["tasks"][0]
    assert t["mode"] == "agent" and t["max_cost"] == 2.5 and t["max_turns"] == 33
    assert t["retry_on_fail"] is False
    assert "step_01" in t["prompt"]
    assert len(t["accept"]) == 1
    toks = shlex.split(t["accept"][0])
    assert "bobverified.gate" in toks and "verify" in toks
    assert toks[toks.index("--step-id") + 1] == "step_01"
    assert toks[toks.index("--step-cmd") + 1] == PLAN["steps"][0]["verify"]  # quoting survives
    assert toks[toks.index("--evidence") + 1] == str(ev)
    assert toks[toks.index("--config") + 1].endswith("target.json")
    assert any(str(tmp_path / "pkg") in x for x in toks)  # PYTHONPATH reaches the gate


def test_write_run_files(tmp_path, target):
    ev = tmp_path / "ev"
    wire.write_run_files(str(ev), PLAN, target, str(tmp_path / "work"))
    plan = json.loads((ev / "plan.json").read_text())
    assert plan["title"] == "Modernize tinyapp" and len(plan["steps"]) == 2
    assert plan["target"] == {"name": "tiny", "url": "https://example.com/tiny", "commit": "abc123", "license": "MIT"}
    tgt = json.loads((ev / "target.json").read_text())
    assert tgt["workdir"] == str(tmp_path / "work")
    assert tgt["test_command"] == "true"


def test_cli_writes_tasks_and_run_files(tmp_path, target):
    import subprocess
    plan = write(tmp_path / "plan.json", PLAN)
    out = tmp_path / "tasks.json"
    r = subprocess.run([sys.executable, "-m", "bobverified.wire", "--plan", plan, "--target", target,
                        "--workdir", str(tmp_path / "work"), "--evidence", str(tmp_path / "ev"),
                        "--out", str(out), "--budget", "9"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(out.read_text())["budget_total"] == 9
    assert (tmp_path / "ev" / "plan.json").exists() and (tmp_path / "ev" / "target.json").exists()
