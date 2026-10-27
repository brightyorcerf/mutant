#!/usr/bin/env python3
"""Mutant: a merge gate that only blocks with runnable proof. No model calls in this file.

An agent (see skills/mutant/SKILL.md) writes mutants.json and tests.json. This script checks them:
  plan    baseline x3 on the PR's committed HEAD + changed lines   -> .mutant/plan.json
  run     apply each mutant in a throwaway worktree, run the tests -> .mutant/results.json
  prove   a survivor blocks only if a test passes on the PR and fails on the bug -> .mutant/proofs.json
  report  markdown + the gate state (exit 1 = block)

Python + pytest. Scores the committed HEAD, never uncommitted edits. The PR's own code and tests execute here,
so never run it on pull requests from forks.
"""
import argparse, ast, contextlib, json, os, re, shlex, shutil, signal, subprocess, sys, tempfile, time
import xml.etree.ElementTree as ET
from pathlib import Path

TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test|conftest)\.py$|(^|/)tests?/")
SECRET = re.compile(r"TOKEN|SECRET|PASSWORD|CREDENTIAL|API_?KEY|^GH_|^GITHUB_", re.I)
ENV = {**{k: v for k, v in os.environ.items() if not SECRET.search(k)}, "PYTHONDONTWRITEBYTECODE": "1"}
# a "mutant" or test that adds any of these is rejected: model output must never become arbitrary code
UNSAFE = re.compile(r"\b(import|os|subprocess|socket|shutil|ctypes|pickle|__import__)\b|\b(eval|exec|open)\s*\(")
BAD_MODULES = {"os", "subprocess", "socket", "shutil", "ctypes", "pickle", "urllib", "requests"}


def log(s):
    print(s, file=sys.stderr, flush=True)


def kill_tree(p):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)


def run_cmd(cmd, cwd, timeout):
    """(exit code | 'timeout', output). A hang kills the whole process group, not just pytest."""
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=ENV, **kw)
    try:
        out = p.communicate(timeout=timeout)[0]
        return p.returncode, out
    except subprocess.TimeoutExpired:
        kill_tree(p)
        p.communicate()
        return "timeout", ""


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@contextlib.contextmanager
def worktree(repo):
    """Clean checkout of HEAD: mutants never touch the user's working copy, and every run starts fresh."""
    tmp = tempfile.mkdtemp(prefix="mutant-")
    wt = Path(tmp) / "w"
    git(repo, "worktree", "add", "--detach", str(wt), "HEAD")
    try:
        yield wt
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


def resolve_base(repo, base):
    for b in (base, f"origin/{base}"):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", b], cwd=repo, capture_output=True).returncode == 0:
            return b
    sys.exit(f"base branch '{base}' not found (also tried origin/{base}); fetch it first")


def changed_ranges(repo, base):
    """{path: [(first, last)]} of added lines in non-test .py files."""
    path, res = None, {}
    for line in git(repo, "diff", "-U0", "--no-color", f"{base}...HEAD").splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and path and path.endswith(".py") and not TEST_FILE.search(path):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, n = int(m[1]), int(m[2] if m[2] is not None else 1)
            if n:
                res.setdefault(path, []).append([start, start + n - 1])
    return res


def is_pytest(cmd):
    return "pytest" in " ".join(cmd)


def check_mutant(m, ranges, root):
    """-> (status, mutated bytes, line). status None means runnable; the contract is {file, find, replace}."""
    if not isinstance(m, dict) or not all(isinstance(m.get(k), str) for k in ("file", "find", "replace")):
        return "rejected", None, 0, "needs string fields file, find, replace"
    file, find, rep = m["file"], m["find"], m["replace"]
    if file not in ranges:
        return "rejected", None, 0, "not a changed non-test .py file"
    text = (root / file).read_bytes().decode("utf-8")
    if not find or text.count(find) != 1:
        return "rejected", None, 0, "find must appear exactly once in the file"
    if "\n" in find.strip("\r\n"):
        return "rejected", None, 0, "edit spans more than one line"
    line = text.count("\n", 0, text.index(find)) + 1
    if not any(a <= line <= b for a, b in ranges[file]):
        return "rejected", None, line, "not on a line the PR changed"
    if sum(1 for _ in UNSAFE.finditer(rep)) > sum(1 for _ in UNSAFE.finditer(find)):
        return "rejected", None, line, "adds an import or a dangerous call"
    new = text.replace(find, rep, 1)
    try:
        same = ast.dump(ast.parse(text.lstrip("﻿"))) == ast.dump(ast.parse(new.lstrip("﻿")))
    except SyntaxError:
        return "stillborn", None, line, "does not parse"
    return ("equivalent", None, line, "same syntax tree") if same else (None, new.encode(), line, "")


def run_mutant(wt, cmd, row, new, timeout, tmp):
    path = wt / row["file"]
    orig, st = path.read_bytes(), path.stat()
    xml = Path(tmp) / f"m{row['id']}.xml"
    try:
        path.write_bytes(new)
        os.utime(path, (time.time() + row["id"], time.time() + row["id"]))  # mtime never matches a cached .pyc
        rc, _ = run_cmd(cmd + ([f"--junitxml={xml}"] if is_pytest(cmd) else []), wt, timeout)
        confirm = run_cmd(cmd, wt, timeout)[0] if rc == 1 else None  # a flaky failure must not count as a kill
    finally:
        path.write_bytes(orig)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    if rc == 0:
        return "survived"
    if rc == "timeout":
        return "timeout"
    if rc != 1:
        return "stillborn"  # exit 2/4/5: tests didn't collect or run, which is not a catch
    if confirm != 1:
        return "inconclusive"
    try:  # a mutant that fails every test (import-level breakage) proves nothing about test quality
        cases = list(ET.parse(xml).getroot().iter("testcase"))
        bad = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
        if len(cases) >= 3 and len(bad) == len(cases):
            return "trivial"
    except (ET.ParseError, OSError):
        pass
    return "killed"


def run_all(repo, plan, mutants, extra=None):
    """Rows with a status per mutant. `extra` = {filename: code} test files added on top (used by the benchmark)."""
    cmd, timeout, rows = plan["cmd"], int(3 * plan["baseline_s"] + 10), []
    with worktree(repo) as wt, tempfile.TemporaryDirectory() as tmp:
        for name, code in (extra or {}).items():
            write_test(wt, name, code)
        for i, m in enumerate(mutants, 1):
            status, new, line, why = check_mutant(m, plan["ranges"], wt)
            row = {"id": i, "line": line, "why": why, **{k: (m.get(k, "") if isinstance(m, dict) else "") for k in ("file", "find", "replace", "bug", "effect")}}
            row["status"] = status or run_mutant(wt, cmd, row, new, timeout, tmp)
            rows.append(row)
            log(f"[{i:>2}/{len(mutants)}] {row['file']}:{line} {row['bug'] or row['find'][:30]}: {row['status']}")
    return rows


def write_test(wt, name, code):
    (wt / "tests" if (wt / "tests").is_dir() else wt).joinpath(name).write_text(code, encoding="utf-8")


def unsafe_test(code):
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"syntax error: {e.msg}"
    for n in ast.walk(tree):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else []
        if any(m.split(".")[0] in BAD_MODULES for m in mods):
            return "imports a dangerous module"
    body = "\n".join(l for l in code.splitlines() if not re.match(r"\s*(import|from)\s", l))
    return "calls eval/exec/open" if UNSAFE.search(body) else None


def prove_one(wt, cmd, timeout, row, code, mid):
    name = f"test_mutant_proof_{mid}.py"
    if why := unsafe_test(code):
        return why
    write_test(wt, name, code)
    rel = ("tests/" if (wt / "tests").is_dir() else "") + name
    try:
        if any(run_cmd(cmd + [rel], wt, timeout)[0] != 0 for _ in range(3)):
            return "does not pass 3 times on the PR's own code"
        _, new, _, _ = check_mutant(row, {row["file"]: [[row["line"], row["line"]]]}, wt)
        path = wt / row["file"]
        orig = path.read_bytes()
        try:
            path.write_bytes(new)
            if any(run_cmd(cmd + [rel], wt, timeout)[0] != 1 for _ in range(2)):
                return "does not fail on the planted bug"
        finally:
            path.write_bytes(orig)
        return None if run_cmd(cmd, wt, timeout * 3)[0] == 0 else "breaks the full suite"
    finally:
        (wt / "tests" / name if (wt / "tests").is_dir() else wt / name).unlink(missing_ok=True)


def decide(plan, rows, proofs):
    """-> (Alan test-report result, commit status, why). When in doubt, block."""
    if plan["state"] in ("red", "flaky"):
        return "Fail", "failure", f"baseline is {plan['state']}: the suite can't be trusted, nothing was scored"
    if plan["state"] == "nothing":
        return "Pass", "success", "nothing to mutate: the PR changes no non-test Python lines"
    scored = [r for r in rows if r["status"] in ("killed", "survived", "timeout")]
    if not scored:
        return "Fail", "failure", "couldn't verify: no mutant could be scored"
    proven = [p for p in proofs if p["proven"]]
    if proven:
        return "Fail", "failure", f"{len(proven)} proven gap(s): tests pass on the PR but miss a bug that a runnable test catches"
    open_ = [r for r in rows if r["status"] == "survived"]
    if open_:
        return "Mixed", "success", f"{len(open_)} survivor(s) without a proof test: listed, not blocking"
    return "Pass", "success", f"all {len(scored)} scored bugs were caught"


def render(plan, rows, proofs, result, why, model, cost):
    count = lambda s: sum(r["status"] == s for r in rows)
    byid = {r["id"]: r for r in rows}
    out = [f"### 🧬 Mutant: {result.upper()}, {why}", "",
           f"Agent model: **{model}** · cost: **{cost}** · {len(rows)} mutants: {count('killed')} caught, {count('timeout')} hung (caught), "
           f"{count('survived')} survived · not scored: {count('stillborn')} invalid, {count('equivalent')} equivalent, "
           f"{count('trivial')} trivial, {count('inconclusive')} flaky, {count('rejected')} rejected", ""]
    proven = [p for p in proofs if p["proven"]]
    if proven:
        out += ["#### Proven gaps (each has a runnable proof test)"]
        for p in proven:
            r = byid[p["mutant"]]
            out += ["", f"**{r['bug'] or r['find']}** `{r['file']}:{r['line']}`: `{r['find'].strip()}` → `{r['replace'].strip()}`",
                    f"> {p.get('question') or r['effect']}", "```python", p["code"].strip(), "```"]
    proof_ids = {p["mutant"] for p in proven}
    unproven = [r for r in rows if r["status"] == "survived" and r["id"] not in proof_ids]
    if unproven:
        out += ["", "#### Survivors without proof (not blocking)"]
        out += [f"- `{r['file']}:{r['line']}` {r['bug'] or r['find']}: {r['effect']}" for r in unproven]
    refused = [p for p in proofs if not p["proven"]]
    if refused:
        out += ["", "#### Proof tests that were refused"] + [f"- mutant {p['mutant']}: {p['reason']}" for p in refused]
    out += ["", "_Proof tests lock in what the PR's code does today. They are questions for the author, not commits._"]
    return "\n".join(out)


def load(work, name, default=None):
    f = work / name
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "run", "prove", "report"])
    ap.add_argument("--repo", default="."); ap.add_argument("--base", default="main")
    ap.add_argument("--work", help="state folder (default <repo>/.mutant)")
    ap.add_argument("--test", help="test command (default: python -m pytest -q)")
    ap.add_argument("--mutants", help="mutants.json (default <work>/mutants.json)")
    ap.add_argument("--tests", help="tests.json (default <work>/tests.json)")
    ap.add_argument("--model", default="unknown"); ap.add_argument("--cost", default="unknown")
    ap.add_argument("--md", help="write the report here too")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    repo = Path(a.repo).resolve()
    work = Path(a.work) if a.work else repo / ".mutant"
    work.mkdir(exist_ok=True)
    (work / ".gitignore").write_text("*\n")
    save = lambda name, obj: (work / name).write_text(json.dumps(obj, indent=1), encoding="utf-8")

    if a.cmd == "plan":
        cmd = shlex.split(a.test) if a.test else [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
        base = resolve_base(repo, a.base)
        plan = {"base": base, "head": git(repo, "rev-parse", "HEAD").strip(), "cmd": cmd, "ranges": changed_ranges(repo, base), "state": "nothing", "baseline_s": 1}
        if plan["ranges"]:
            with worktree(repo) as wt:
                rcs, secs = [], 0
                for _ in range(3):  # 3 runs: a test that fails 5% of the time shows up here
                    t0 = time.time(); rc, out = run_cmd(cmd, wt, 600); rcs.append(rc); secs = max(secs, time.time() - t0)
            plan.update(baseline_s=round(secs, 2), state="ok" if set(rcs) == {0} else "red" if 0 not in rcs else "flaky")
            if plan["state"] != "ok":
                log(out[-800:])
        save("plan.json", plan)
        print(f"plan: {plan['state']} · changed: {json.dumps(plan['ranges'])} · baseline {plan['baseline_s']}s")
        sys.exit(0 if plan["state"] in ("ok", "nothing") else 1)

    plan = load(work, "plan.json") or sys.exit("run `plan` first")
    if a.cmd == "run":
        if plan["state"] != "ok":
            sys.exit(f"plan state is '{plan['state']}': nothing to run")
        rows = run_all(repo, plan, json.loads(Path(a.mutants or work / "mutants.json").read_text(encoding="utf-8")))
        save("results.json", rows)
        print(f"run: " + ", ".join(f"{s}={sum(r['status'] == s for r in rows)}" for s in sorted({r['status'] for r in rows})))
    elif a.cmd == "prove":
        rows = {r["id"]: r for r in load(work, "results.json", [])}
        proofs = []
        with worktree(repo) as wt:
            for t in json.loads(Path(a.tests or work / "tests.json").read_text(encoding="utf-8")):
                mid, row = t.get("mutant"), rows.get(t.get("mutant"))
                why = "not a surviving mutant" if not row or row["status"] != "survived" else \
                    prove_one(wt, plan["cmd"], int(3 * plan["baseline_s"] + 10), row, str(t.get("code", "")), mid)
                proofs.append({"mutant": mid, "proven": why is None, "reason": why or "ok", "question": t.get("question", ""), "code": str(t.get("code", ""))})
                log(f"proof for mutant {mid}: {'PROVEN' if why is None else 'refused: ' + why}")
        save("proofs.json", proofs)
        print(f"prove: {sum(p['proven'] for p in proofs)}/{len(proofs)} proof tests accepted")
    else:
        rows, proofs = load(work, "results.json", []), load(work, "proofs.json", [])
        result, state, why = decide(plan, rows, proofs)
        text = render(plan, rows, proofs, result, why, a.model, a.cost)
        print(text)
        if a.md:
            Path(a.md).write_text(text + "\n", encoding="utf-8")
        print(f"\nALAN_RESULT={result}\nMUTANT_STATE={state}")
        sys.exit(1 if state == "failure" else 0)


if __name__ == "__main__":
    main()
