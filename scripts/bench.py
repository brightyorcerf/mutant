#!/usr/bin/env python3
"""Benchmark against hidden bugs. For each case, plant bugs the agent never saw and report how many the PR's own
tests catch, then how many are caught once Mutant's accepted proof tests are added.

  python scripts/bench.py cases.json
cases.json: [{"name": "...", "repo": "path", "base": "main", "hidden": "path/to/hidden.json"}]
hidden.json uses the same {file, find, replace, bug} contract as mutants.json. Run the agent (plan/run/prove) first so
<repo>/.mutant/proofs.json exists. Hidden bugs must be written BEFORE the agent runs, and never shown to it.
"""
import json, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mutant import run_all  # noqa: E402

CAUGHT, SCORED = ("killed", "timeout"), ("killed", "timeout", "survived")


def count(rows):
    return sum(r["status"] in CAUGHT for r in rows), sum(r["status"] in SCORED for r in rows)


def main():
    table = ["| case | hidden bugs caught by the PR's tests | with Mutant's proof tests | seconds |", "|---|---|---|---|"]
    for c in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")):
        repo, t0 = Path(c["repo"]).resolve(), time.time()
        subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "mutant.py"), "plan", "--repo", str(repo), "--base", c.get("base", "main")], check=True, capture_output=True)
        plan = json.loads((repo / ".mutant" / "plan.json").read_text(encoding="utf-8"))
        hidden = json.loads(Path(c["hidden"]).read_text(encoding="utf-8"))
        pf = repo / ".mutant" / "proofs.json"
        proofs = json.loads(pf.read_text(encoding="utf-8")) if pf.exists() else []
        extra = {f"test_mutant_proof_{p['mutant']}.py": p["code"] for p in proofs if p["proven"]}
        before, after = count(run_all(repo, plan, hidden)), count(run_all(repo, plan, hidden, extra))
        table.append(f"| {c['name']} | {before[0]}/{before[1]} | {after[0]}/{after[1]} | {time.time() - t0:.0f} |")
    print("\n".join(table))


if __name__ == "__main__":
    main()
