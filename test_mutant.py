import json, subprocess, sys
from pathlib import Path

import pytest

import mutant
from mutant import check_mutant, decide, unsafe_test

SRC = "def f(t):\n    return t >= 50\n\n\ndef g(t):\n    return t >= 51\n"
RANGES = {"a.py": [[2, 2]]}


@pytest.fixture
def root(tmp_path):
    (tmp_path / "a.py").write_bytes(SRC.encode())  # bytes: write_text would turn \n into \r\n on Windows
    return tmp_path


def m(**kw):
    return {"file": "a.py", "find": "return t >= 50", "replace": "return t > 50", **kw}


def test_valid_edit_applies_once(root):
    status, new, line, _ = check_mutant(m(), RANGES, root)
    assert status is None and line == 2 and new == SRC.replace("t >= 50", "t > 50").encode()


@pytest.mark.parametrize("edit,why", [
    ({"find": "t >="}, "exactly once"),                      # appears twice
    ({"find": "return t >= 51"}, "changed"),                 # unchanged line (g)
    ({"find": "return t >= 50\n\n\ndef g"}, "one line"),
    ({"file": "tests/test_a.py"}, "changed non-test"),
    ({"replace": "return __import__('os').x"}, "dangerous"),
    ({"replace": "return open('x')"}, "dangerous"),
])
def test_bad_edits_are_rejected(root, edit, why):
    status, new, _, reason = check_mutant(m(**edit), RANGES, root)
    assert status == "rejected" and why in reason and new is None


def test_syntax_error_is_stillborn_and_noop_is_equivalent(root):
    assert check_mutant(m(replace="return t >="), RANGES, root)[0] == "stillborn"
    assert check_mutant(m(replace="return t  >=  50"), RANGES, root)[0] == "equivalent"


def test_unsafe_test_code():
    assert unsafe_test("from pricing import f\n\ndef test_a():\n    assert f(1)\n") is None
    assert "dangerous" in unsafe_test("import os\n")
    assert "eval" in unsafe_test("def test_a():\n    eval('1')\n")


def plan(state):
    return {"state": state}


def row(status):
    return {"status": status}


def test_gate_blocks_only_on_proof_or_when_blind():
    proof = [{"proven": True}]
    assert decide(plan("red"), [], [])[:2] == ("Fail", "failure")
    assert decide(plan("flaky"), [], [])[:2] == ("Fail", "failure")
    assert decide(plan("nothing"), [], [])[:2] == ("Pass", "success")
    assert decide(plan("ok"), [], [])[:2] == ("Fail", "failure")  # never ran = not a pass
    assert decide(plan("ok"), [row("stillborn")], [])[:2] == ("Fail", "failure")  # nothing scoreable
    assert decide(plan("ok"), [row("survived")], proof)[:2] == ("Fail", "failure")
    assert decide(plan("ok"), [row("survived"), row("killed")], [])[:2] == ("Mixed", "success")
    assert decide(plan("ok"), [row("killed"), row("timeout")], [])[:2] == ("Pass", "success")


DEMO = Path(__file__).parent / "demo"


@pytest.mark.skipif(not (DEMO / ".git").exists(), reason="demo repo not present")
def test_end_to_end_on_demo_leaves_repo_clean():
    hw = Path(__file__).parent / "fixtures" / "handwritten"
    work = DEMO / ".mutant"
    work.mkdir(exist_ok=True)
    (work / "mutants.json").write_text((hw / "mutants.json").read_text())
    (work / "tests.json").write_text((hw / "tests.json").read_text())
    before = subprocess.run(["git", "status", "--short"], cwd=DEMO, capture_output=True, text=True).stdout
    for step in ("plan", "run", "prove"):
        assert subprocess.run([sys.executable, "mutant.py", step, "--repo", "demo"], cwd=DEMO.parent, capture_output=True).returncode == 0
    r = subprocess.run([sys.executable, "mutant.py", "report", "--repo", "demo"], cwd=DEMO.parent, capture_output=True, text=True)
    assert r.returncode == 1 and "MUTANT_STATE=failure" in r.stdout  # proven gaps block
    results = json.loads((work / "results.json").read_text())
    assert [x["status"] for x in results].count("killed") == 2
    assert subprocess.run(["git", "status", "--short"], cwd=DEMO, capture_output=True, text=True).stdout == before
    assert "mutant-" not in subprocess.run(["git", "worktree", "list"], cwd=DEMO, capture_output=True, text=True).stdout
