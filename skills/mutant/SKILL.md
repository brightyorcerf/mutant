---
name: mutant
description: Check whether a pull request's tests can fail. Plants realistic bugs on the PR's changed lines, runs the PR's tests against each, and blocks only when a runnable proof test shows a real gap. Use on every agent-written PR.
---

# /mutant

You are the model half of Mutant. `mutant.py` does all checking and has no model calls: it never trusts your opinion,
only the JSON you write and the test results it observes. Never edit the PR's code, never commit, never push, and never
change the numbers it prints.

Run from the repo root, on the PR's branch (HEAD is what gets scored). `BASE` is the PR's target branch (usually `main`).
On Windows use `py` wherever this says `python`.

## 1. Plan
```
python mutant.py plan --base BASE
```
- If it prints `red` or `flaky`, STOP. Skip to step 6 (the baseline can't be trusted).
- If it prints `nothing`, skip to step 6.
- Otherwise it lists the changed files and line ranges. Read those files and the existing tests.

## 2. Write `.mutant/mutants.json` (about 12 bugs)
A JSON array of `{"file", "find", "replace", "bug", "effect"}`:
- `file`: a changed non-test `.py` file.
- `find`: text that appears **exactly once** in that file, on **one line** the PR changed. Copy it verbatim from the
  file, including indentation. There is no line-number field; the line is derived from `find`.
- `replace`: the buggy text. Same length is not required.
- `bug`: a 4-word name. `effect`: one sentence on how behaviour changes.
- Realistic bugs only: off-by-one, wrong boundary or comparison, swapped arguments, dropped None/empty check,
  inverted condition, wrong constant. At least one per changed function.
- Never add imports, `os`, `subprocess`, `eval`, `exec`, `open(`. Never edit tests.
- **Write raw JSON only.** No markdown fence and no prose: `mutant.py` calls `json.loads` on the file and crashes on a
  ` ```json ` block. If your reply came back fenced, strip the fence before writing the file.

## 3. Run
```
python mutant.py run
```

## 4. Write `.mutant/tests.json` for each survivor
A JSON array of `{"mutant": <id>, "question": "...", "code": "..."}`:
- `code` is a complete pytest file (imports included) with ONE test that passes on the PR's code today and fails on
  that mutant. Assert boundaries and edge inputs, not implementation details. No mocks of the code under test.
- `question` is a one-line question for the PR's author: "free_shipping(50) is True today. Is a $50 order meant to
  ship free?" The test records current behaviour; the author decides if it is correct.
- Use a different approach from the existing tests. Only write tests for ids that survived.
- Write raw JSON, as in step 2.

## 5. Prove
```
python mutant.py prove
```
Refused tests are listed with a reason. You may fix and re-run once.

## 6. Report
```
python mutant.py report --base BASE --model "<the model you are running as>" --cost "<tokens or $ for this run>" --md .mutant/report.md
```
- Paste the printed report **unchanged** into the Alan test report. `ALAN_RESULT=Fail|Mixed|Pass` is the result.
- Post it: `bash scripts/post_status.sh <PR number> .mutant/report.md <MUTANT_STATE>`.
- If any step errored, put the exact error text in the report. Do not guess a result.

## Guardrails
- Same-repository branches only. Never run on a pull request from a fork: the PR's code and tests execute.
- The test command comes from the automation, never from the PR.
- Report the model name and the cost of this run. If you cannot read the cost, say so.
