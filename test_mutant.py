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


@pytest.mark.parametrize("code", [
    "import importlib\n\ndef test_a():\n    importlib.import_module('o' + 's').system('echo x')\n",   # denylisted import
    "def test_a():\n    getattr(__builtins__, 'ev' + 'al')('1')\n",                                      # getattr + dunder, no import
    "from pathlib import Path\n\ndef test_a():\n    assert 'x' in Path('pricing.py').read_text()\n",      # reads source, proves nothing
])
def test_unsafe_test_blocks_code_execution_escapes(code):
    assert unsafe_test(code) is not None


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


ROOT = Path(__file__).parent


def ref(name):
    """The branch as a local name or origin/<name>, else None."""
    for r in (name, f"origin/{name}"):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", r], cwd=ROOT, capture_output=True).returncode == 0:
            return r


@pytest.mark.skipif(not (ref("demo/base") and ref("demo/agent-pr")), reason="run: git fetch origin demo/base demo/agent-pr")
def test_end_to_end_on_demo_branches_leaves_repo_clean(tmp_path):
    hw, wt = ROOT / "fixtures" / "handwritten", tmp_path / "demo"
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), ref("demo/agent-pr")], cwd=ROOT, check=True, capture_output=True)
    try:
        work = wt / ".mutant"
        work.mkdir()
        (work / "mutants.json").write_bytes((hw / "mutants.json").read_bytes())
        (work / "tests.json").write_bytes((hw / "tests.json").read_bytes())
        status = lambda: subprocess.run(["git", "status", "--short"], cwd=wt, capture_output=True, text=True).stdout
        before = status()
        step = lambda s: subprocess.run([sys.executable, "mutant.py", s, "--repo", str(wt), "--base", ref("demo/base")], cwd=ROOT, capture_output=True, text=True)
        for s in ("plan", "run", "prove"):
            assert step(s).returncode == 0
        r = step("report")
        assert r.returncode == 1 and "MUTANT_STATE=failure" in r.stdout  # proven gaps block
        assert [x["status"] for x in json.loads((work / "results.json").read_text())].count("killed") == 2
        assert status() == before  # mutants never touched the working copy
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=ROOT, capture_output=True)
