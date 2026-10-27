# Mutant

**A merge gate that only blocks with runnable proof.**

Agents write the code and the tests, so a green CI proves little. Mutant has an agent plant realistic bugs on the
lines a PR changed. If the PR's tests stay green, Mutant asks for a **proof test**: it passes on the PR's code, fails on
the planted bug, and wasn't in the suite. A proven gap blocks the merge. A model's guess never does.

```
Alan automation (PR opened / updated)
  -> /mutant skill, run by Alan Code on an open model
       plan    baseline x3, changed lines          (mutant.py, no model)
       agent   writes mutants.json                 (open model)
       run     apply, test, restore, classify      (mutant.py)
       agent   writes a proof test per survivor    (open model)
       prove   3x green on the PR, red on the bug  (mutant.py)
       report  markdown + Fail / Mixed / Pass      (mutant.py)  -> Alan test report, PR comment, commit status
```

`mutant.py` is ~300 lines, standard library only, and contains **no model calls**, so every verdict is reproducible
from the JSON and the test output.

## 60-second quickstart
```
git clone https://github.com/brightyorcerf/mutant-demo demo   # the demo PR lives in its own repo
python -m pip install pytest
python -m pytest test_mutant.py -q
python mutant.py plan --repo demo --base main
```

That checks the harness. To see a full scored report offline, replay the hand-written fixture (it is **not** a model
result — it only exercises the pipeline):
```
cp fixtures/handwritten/mutants.json demo/.mutant/ && python mutant.py run --repo demo
cp fixtures/handwritten/tests.json   demo/.mutant/ && python mutant.py prove --repo demo
python mutant.py report --repo demo --model "hand-written" --cost '$0' --md demo/.mutant/report.md
```

## Real result
One real run on `demo/` (`agent/shipping-and-bulk` vs `main`), model `deepseek/deepseek-v4.1-flash`:

| | |
|---|---|
| Mutants proposed / valid | 12 / 12 |
| Caught by the PR's tests | **3** |
| Survived | **9** |
| Stillborn / equivalent / rejected | 0 / 0 / 0 |
| Proof tests accepted | **9 / 9** |
| Gate | **FAIL** (9 proven gaps) |
| Cost | **$0.0100** · 9,871 tokens · 2 calls |

The PR's tests caught 3 of 12 planted bugs (25%). Every survivor came back with a proof test that passes on the PR and
fails on the bug. Raw replies are in `fixtures/recorded/`; this number is from the real endpoint, not fixtures.

## How Alan runs it
1. **Cloud environment** — the repo, Python 3.12, `pytest`, and the repo's deps installed in the image.
2. **Skill** — `skills/mutant/SKILL.md` added as a team skill named `mutant`. Alan Code is the model half.
3. **Automation** — GitHub `pr_opened` **and** `pr_synchronize` (new commits do not re-fire `pr_opened`), optionally
   `push`. Instructions: `docs/automation-instructions.md`.
4. **Evidence** — the report is pasted into an Alan test report and posted to the PR; `scripts/post_status.sh` sets a
   `mutant` commit status, which becomes a real merge block when marked **Required** in branch protection.
5. **Fallback** — `.github/workflows/mutant.yml` runs the deterministic half in GitHub Actions and comments the report.
   It does not call a model: the two JSON files must come from the skill. It refuses fork PRs and holds no keys.

Model availability is team-scoped: on this team's gateway only `deepseek/deepseek-v4.1-flash` and
`minimax/minimax-m3.1-flash` are enabled. Other ids return `403 This model is disabled for the team`.

## Benchmark (real model, real numbers)
**Not reproducible from this repo yet:** the four benchmark repos (`bench/`) are not published, and no timestamp
proves the hidden bugs were written first. Treat this table as a report from one run, not a verified result.

Four PRs, three written the way an AI coding agent normally writes code + tests, plus a control from a real library
(`pypa/packaging`'s `utils.py` and its own tests). Three hidden bugs per PR were written **before** Mutant ran and never
shown to the model.

| case | PR tests caught | with Mutant proofs | valid mutants | stillborn | equivalent | false alarms | seconds | cost |
|---|---|---|---|---|---|---|---|---|
| ledger | 0 / 3 | **3 / 3** | 12 / 12 | 0% | 0% | 0 | 69 | $0.0120 |
| slugify | 1 / 3 | 1 / 3 | 12 / 12 | 0% | 0% | 0 | 48 | $0.0092 |
| paginate | 0 / 3 | 0 / 3 | 12 / 12 | 0% | 0% | 0 | 55 | $0.0083 |
| control (`packaging`) | 2 / 2 scored* | 2 / 2 | 12 / 12 | 0% | 0% | 0 | 60 | $0.0132 |
| **total** | **3 / 11** | **6 / 11** | 48 / 48 | 0% | 0% | 0 | — | **$0.0427** |

\*The third control bug was rejected by `plan` (`not on a line the PR changed`), so only 2 were scored.

**Where it is bad, and why.** `slugify` and `paginate` both report **Pass** while each still leaks two hidden bugs. All
12 model mutants were killed by the existing tests, so there were no survivors and no proof tests — a high mutation
score says "the bugs I thought of were caught", not "the tests are strong". The model's blind spots become the gate's
blind spots. That is the honest weakness of this design, and the benchmark is sized to show it.

The `ledger` result is the good case: 0/3 hidden bugs caught before, 3/3 after, because the survivors were real gaps.

## Limits
- **Python + pytest only.** Single-line mutants. Scores committed `HEAD`, not your working tree.
- **Mutation score is not coverage.** A survivor is only useful if the model planted a bug that matters; a clean sweep
  can still miss anything the model did not think of.
- **Proof tests lock in current behaviour.** They are posted as questions, never committed: a wrong boundary would
  otherwise be enshrined as a test.
- **Cost grows with mutants x suite time** (each kill is run twice). This benchmark: ~$0.01–0.013 per PR, 48–69 s.
- **Never run on fork PRs.** The PR's code and tests execute during the run.
- The control's real suite needed `hypothesis`, `pretend`, and `tomli_w`; the run was bounded to the suite covering the
  changed function.

## Tests
`python -m pytest test_mutant.py` (includes an end-to-end run on `demo/`).

MIT licensed.
