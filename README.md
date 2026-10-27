<p align="center">
  <img src="assets/mutant.png" alt="A yellow smiley mask with a green tentacle peeking out from behind it" width="440">
</p>

# Mutant

A merge gate for agent-written pull requests that only blocks when it can show you a runnable proof.

## Why I built this

Coding agents now write the implementation and the tests in the same pass. That quietly breaks an assumption most CI pipelines rely on: that the tests were written by someone trying to catch the code being wrong. When one model writes both sides, a green check mostly tells you the code agrees with itself. Line coverage does not rescue you either. A test can execute every line of a function and still assert nothing about the boundary that matters.

Mutation testing is the classic answer to "are my tests any good". You inject small, realistic faults into the code and see whether the suite notices. The idea is decades old, and Google has published work on running it against changed code at review time. In practice it has a reputation for noise. Syntactic mutation operators produce a lot of equivalent or trivially killed mutants, and "your mutation score is 62%" is a weak reason to block anyone's merge.

Mutant takes a narrower and, I think, more defensible position. It never blocks on a score. It blocks on evidence: a concrete test that passes on the PR's code, fails on a realistic planted bug, and was not already in the suite. If that test cannot be produced, the surviving mutant is reported but the merge goes through. The model's opinion is never the evidence. A test run is.

## Architecture

The system is split into a model half and a deterministic half, and that split is the most important design decision in the project.

```
Alan automation (pull request opened / synchronized)
  -> /mutant skill, executed by Alan Code on an open-weight model
       plan     baseline x3, changed-line extraction          mutant.py, no model
       agent    proposes mutants as find/replace edits        open model
       run      apply, test, restore, classify                mutant.py
       agent    writes one candidate proof test per survivor  open model
       prove    3x green on the PR, 2x red on the mutant      mutant.py
       report   Pass / Mixed / Fail + markdown                mutant.py
  -> Alan test report, PR comment, required commit status
```

`mutant.py` is about 270 lines of standard-library Python with zero model calls. The agent's output crosses a trust boundary as two JSON files, and the script treats them exactly like any other untrusted input. Because the script is deterministic, every verdict can be replayed from those two files and the test output, which is what you want from something that sits in front of a merge button.

### The pipeline in detail

plan. Computes `git diff -U0 base...HEAD`, extracts added line ranges from non-test Python files, and runs the suite three times in a clean `git worktree` of HEAD. A red baseline and a flaky baseline are distinct failure modes, and both block with their own message, because every downstream verdict is meaningless if the suite cannot agree with itself.

mutants. The agent proposes edits as `{file, find, replace}` rather than unified diffs. Small models get hunk headers and context lines wrong, and Windows checkouts with `core.autocrlf` make `git apply` reject LF patches. A find/replace contract sidesteps both. `find` must occur exactly once, sit on a line the PR actually changed, and span a single line. Edits to test files, and edits that introduce `import`, `os`, `subprocess`, `eval`, `exec` or `open(`, are rejected before anything runs, so prompt injection hidden in a diff cannot turn into executed code.

run. Each mutant is applied inside a throwaway worktree, never the user's checkout, and restored in a `finally`. The suite runs in its own process group with a timeout of three times the baseline plus ten seconds, and a hang kills the whole group rather than just the parent pytest. `PYTHONDONTWRITEBYTECODE` is set and the mutated file gets a unique mtime, because CPython validates cached bytecode by source size and whole-second mtime, and same-length mutants like `<` to `>` can otherwise load the previous mutant's `.pyc`. Mutants are classified as:

| Status | Meaning | Scored |
|---|---|---|
| killed | the suite failed, confirmed by a second run | yes |
| timeout | the mutant hung the suite | yes, counts as detected |
| survived | the suite stayed green | yes |
| trivial | every test failed, per JUnit XML, so it says nothing about test quality | no |
| inconclusive | the kill did not reproduce, so a flaky failure is never counted as a catch | no |
| equivalent | identical AST to the original, so no behaviour changed | no |
| stillborn | does not parse, or pytest could not collect | no |
| rejected | violated the edit contract or the safety filter | no |

prove. For each survivor the agent writes one candidate test. It is accepted only if it passes three times on the unmutated PR, fails twice on its target mutant, keeps the full suite green, and passes an AST-level import filter. A survivor with an accepted proof test is non-equivalent by construction, which means the gate never needs an LLM to judge equivalence. That removes the least reliable step in most LLM-assisted mutation pipelines.

report. The gate is deliberately asymmetric. Fail means a proven gap, an untrustworthy baseline, or nothing scoreable. Mixed means survivors exist but none could be proven, so they are listed and do not block. Pass means everything scored was caught, or there was nothing to mutate. "Could not verify" is always a Fail, never a silent pass.

## Results

Two independent Alan sessions ran the `/mutant` skill on [pull request #3](https://github.com/brightyorcerf/mutant/pull/3) (`demo/agent-pr` into `demo/base`), both on Alan Code with `deepseek/deepseek-v4.1-flash`. Each invented its own twelve mutants and wrote its own proof tests, and both reached the same verdict.

| Metric | Session 1 | Session 2 |
|---|---|---|
| Mutants proposed / valid | 12 / 12 | 12 / 12 |
| Caught by the PR's own tests | 4 | 4 |
| Survived | 8 | 8 |
| Invalid / equivalent / trivial / rejected | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Proof tests accepted | 8 / 8 | 8 / 8 |
| Gate | Fail, 8 proven gaps | Fail, 8 proven gaps |
| Report | [comment](https://github.com/brightyorcerf/mutant/pull/3#issuecomment-6436189833) | [comment](https://github.com/brightyorcerf/mutant/pull/3#issuecomment-6436190325) |

The agent-written tests caught a third of the realistic bugs. Every survivor came back with a test that passes on the PR and fails on the bug, phrased as a question for the author, for example "free_shipping(50) is False with the mutant and True today. Is a $50 order meant to ship free, or does it only start above $50?" Neither session could read its own token usage, so the reports say cost unknown rather than guess.

An earlier run on the same code, executed locally through Alan's model gateway with usage metadata:

| Metric | Value |
|---|---|
| Mutants proposed / valid | 12 / 12 |
| Caught by the PR's own tests | 3 |
| Survived | 9 |
| Stillborn / equivalent / rejected | 0 / 0 / 0 |
| Proof tests accepted | 9 / 9 |
| Gate | Fail, 9 proven gaps |
| Cost | $0.0100, 9,871 tokens, 2 model calls |

Raw model replies and usage metadata are in `fixtures/recorded/`.

### Hidden-bug benchmark

A mutation score only measures the bugs the model thought of, so I also measured against bugs the model never saw. For each PR, three realistic bugs were written down before Mutant ran. The question is how many of them the PR's tests catch, and how many are caught once Mutant's accepted proof tests are added.

| Case | PR tests | With proof tests | Valid mutants | Cost |
|---|---|---|---|---|
| ledger | 0 / 3 | 3 / 3 | 12 / 12 | $0.0120 |
| slugify | 1 / 3 | 1 / 3 | 12 / 12 | $0.0092 |
| paginate | 0 / 3 | 0 / 3 | 12 / 12 | $0.0083 |
| control (`pypa/packaging` with its real tests) | 2 / 2 scored | 2 / 2 | 12 / 12 | $0.0132 |
| total | 3 / 11 | 6 / 11 | 48 / 48 | $0.0427 |

Two caveats I want to be upfront about. First, the benchmark repositories are not published here yet, so treat this table as a report from one run rather than a reproducible result. Second, slugify and paginate both report Pass while each still leaks two hidden bugs. All twelve model-generated mutants were killed, so there were no survivors and nothing to prove. The model's blind spots become the gate's blind spots. That is the honest weakness of this design, and the benchmark is sized to show it rather than hide it. Ledger is the good case: zero of three hidden bugs caught before, three of three after, because the survivors were real gaps.

## Quickstart

No model and no API key required. The hand-written fixtures exercise the full pipeline; they are stand-ins for model output, not a result.

```
git clone https://github.com/brightyorcerf/mutant && cd mutant
python -m pip install pytest
git worktree add ../mutant-demo demo/agent-pr
python mutant.py plan --repo ../mutant-demo --base demo/base
cp fixtures/handwritten/mutants.json ../mutant-demo/.mutant/ && python mutant.py run   --repo ../mutant-demo
cp fixtures/handwritten/tests.json   ../mutant-demo/.mutant/ && python mutant.py prove --repo ../mutant-demo
python mutant.py report --repo ../mutant-demo --model hand-written --cost '$0'
```

The report exits 1 when the gate fails, so it drops straight into any CI system.

## Running it in Alan

1. Cloud environment: this repository, Python 3.12, and an install script of `python3 -m pip install --break-system-packages pytest` (Ubuntu 24.04 enforces PEP 668).
2. Skill: `skills/mutant/SKILL.md`, added as a team skill named `mutant`. Alan Code on an open-weight model is the model half.
3. Automation: GitHub `pr_opened` and `pr_synchronize` triggers. `pr_opened` alone does not re-fire on new commits, which would leave the gate stale after the author pushes a fix. Instructions are in `docs/automation-instructions.md`.
4. Enforcement: the report goes into an Alan test report and a PR comment, and `scripts/post_status.sh` sets a `mutant` commit status. Alan's GitHub integration may lack the commit-status permission (it returned 403 in my runs); then post the status from a token that has it. Mark that status as required in branch protection to turn the report into an actual merge block.
5. Fallback: `.github/workflows/mutant.yml` runs the deterministic half in GitHub Actions on PRs labelled `mutant`. It never calls a model, refuses fork PRs, and checks out without persisted credentials so the PR's own tests cannot read the job token. Because the mutants in that path come from the PR itself, a green there is not proof. The trusted gate is the Alan automation, where a separate agent writes the mutants.

## Design decisions I would defend in review

No threshold. With around fifteen mutants per PR, one mutant is worth about seven points, and the mutant set changes between runs. A percentage cutoff on that is noise with a config knob attached. Blocking on proof has no number to tune.

No equivalence judge. LLM judges for mutant equivalence are unreliable in both directions, and a wrong "equivalent" verdict silently hides a real gap. Requiring a runnable proof makes equivalence a non-question for anything that blocks.

Proof tests are questions, not commits. A test that kills `>=` to `>` asserts what the PR's code does today. If the agent got the boundary wrong, auto-committing that test would enshrine the bug. So each proof is posted with a question for the author, for example "free_shipping(50) is True today. Is a $50 order meant to ship free?", and never pushed to the PR branch.

Worktrees, not in-place edits. Mutating the working copy means a Ctrl-C or a sandbox timeout can leave a planted bug in your code, and a later commit step will happily ship it. A detached worktree of HEAD makes the user's checkout untouchable by construction.

Cleaned environment. Tests run with every variable matching TOKEN, SECRET, API_KEY, PASSWORD, CREDENTIAL, `GH_*` or `GITHUB_*` stripped, because the PR's own `conftest.py` executes during the run.

## Limits

Python and pytest only. Single-line mutants. It scores the committed HEAD, not the working tree. The project must import from its own working directory, since an editable install pointing elsewhere would test the wrong code. Cost grows with mutants times suite time, and every kill runs twice. Proof tests lock in current behaviour, which is why they are questions. Never run it on pull requests from forks: the PR's code and tests execute during the run.

## Repository layout

```
mutant.py                  the deterministic half: plan, run, prove, report
test_mutant.py             unit tests plus an end-to-end run on the demo branches
skills/mutant/SKILL.md     the model half, as an Alan skill
docs/                      Alan setup, automation instructions, smoke-test notes
scripts/post_status.sh     PR comment plus required commit status
scripts/bench.py           hidden-bug benchmark harness
fixtures/handwritten/      hand-written mutants and proofs for offline runs
fixtures/recorded/         raw replies and usage from the real model run
.github/workflows/         opt-in GitHub Actions fallback
demo/base, demo/agent-pr   branches holding the demo project and its weak agent PR
```

## Tests

```
python -m pytest test_mutant.py
```

Eleven tests covering the edit contract, the safety filters, the gate's decision table, and an end-to-end run against the demo branches that also asserts the working copy is untouched. The end-to-end test skips if the demo branches are not fetched (`git fetch origin demo/base demo/agent-pr`).

## License

MIT
