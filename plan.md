# Mutant: plan (v2, after review)

> **A merge gate that only blocks with runnable proof.**
> An Alan agent on an open model plants realistic bugs in a PR's changed lines. If the PR's tests stay green,
> Mutant produces a **proof test**: it passes on the PR's code, fails on the planted bug, and isn't already in the
> suite. No proof, no block. The model's opinion is never the evidence.

**Timeline (Oct 27, IST, extended):** 16:00 code freeze, repo final. 16:00-19:30 record the 1-2 min demo. 19:30 Alan's launch post goes live on X: quote it with the demo. 20:00 submission form opens (email + Discord #announcement). 22:00 final deadline. Submit by 21:00, not 21:55.
**Submit:** quote-post of Alan's launch post with the 1-2 min demo (what it does, how it works, how Alan was used), public GitHub repo with a good README, the submission form with the repo and X post links.
**Rules:** solo, open source, Alan + open models. Alan must be in the demo, not around it.

## Status (Oct 27, afternoon IST)

| Item | State |
|---|---|
| `mutant.py` plan / run / prove / report, all safety rules | Done. 11 tests green |
| `/mutant` skill on an open model in Alan | Done. Two sessions on PR #3, deepseek-v4.1-flash: 12 mutants, 4 caught, 8 survived, 8/8 proofs, Fail, same verdict both times |
| PR comment + Alan test report | Done, by the Alan agent |
| Required `mutant` commit status | Done, but posted with the owner's `gh`: Alan's integration token gets 403 on statuses (answers open question 3) |
| Automation on PR opened / synchronize | Configured. Cloud builds fail at `fetch: BUILD` for any fresh commit (Alan platform issue), so the on-camera run is a local Alan session |
| Benchmark | Done once (3/11 hidden bugs caught by PR tests, 6/11 with proofs). Spread over 3 runs: cut |
| Proof rule 4 (not a duplicate) | Holds by construction: the mutant survived every existing test |
| Reproducible gate (cache mutants.json by diff hash) | Cut. Two independent runs already agreed; changing the skill before the demo costs more than it saves |
| README, LICENSE, logo | Done |
| Second-agent review of the repo | Left: fixes pushed before the 16:00 freeze |
| Demo video (1-2 min) | Left: record 16:00-19:30 |
| Quote Alan's launch post with the demo | Left: at 19:30 |
| Submission form | Left: opens 20:00, submit by 21:00 |

## What changed from v1, and why

| v1 | v2 | Why |
|---|---|---|
| Pitch: "mutation testing for agent PRs" | Pitch: **proof-gated merge** | Mutation testing with model-written mutants exists (Google's diff-level mutation testing, Meta's ACH, open-source Mutahunter). Per the review, a founder could say "so it's Mutahunter inside Alan?". The contract is the defensible part, not the mechanism. Verify these three before quoting them. |
| `mutant.py` calls the model | **An Alan agent calls the model; `mutant.py` has no model calls** | Otherwise Alan only starts a script and a 15-line GitHub Action does the same. The agent (Alan Code on an open model: Kimi / GLM / Qwen) writes `mutants.json` and `tests.py`; the script checks them. |
| Block when score < threshold | **Block only on a proven gap, or when verification couldn't run** | With ~15 mutants one mutant is ~7 points and the set changes per run, so a percentage cutoff is noise. Proof has no number to tune. |
| Equivalence judged by a second model call | **Deleted** | A wrong "equivalent" verdict hides real gaps. A survivor with a proof test is non-equivalent by definition. A survivor with none after 2 tries is "unproven" and doesn't block. |
| Benchmark: seeded weak PRs, before -> after | **Hidden bugs** | Same model writing mutants and tests aimed at them makes "after" near 100% regardless. See Benchmark. |
| Alan at build steps 6-7 | **Alan first, end to end** | If Alan fails late, the submission breaks the rules. |

## Architecture

```
Alan automation (GitHub: PR opened + push to branch)
  -> Alan agent (open model) runs the /mutant skill:
       1. python mutant.py plan      -> changed ranges, baseline time, flaky check   (no model)
       2. agent writes mutants.json  [{file, find, replace, bug, effect}]
       3. python mutant.py run       -> apply, test, restore, classify               (no model)
       4. agent writes tests.json    for each survivor
       5. python mutant.py prove     -> check each test (see Proof rules)            (no model)
       6. python mutant.py report    -> report text; agent pastes it UNCHANGED into the Alan test report
       7. commit status "mutant" = success | failure (via gh api), PR comment
```

The script is deterministic and safe to run with hand-written JSON, so it can be developed and tested today without a model.

### Status mapping
- **Fail:** a proven gap, a red or flaky baseline, or a script error (when in doubt, block).
- **Mixed:** only unproven survivors or timeouts.
- **Pass:** no gaps, or nothing to mutate (the report says which).

### Proof rules (a proof test counts only if all hold)
1. Passes **3x** on the unmutated PR code.
2. **Fails** on its target mutant (kill confirmed by re-running only the failing test).
3. Touches only test files; the full suite stays green with it added.
4. Not a duplicate of an existing test.
5. Posted as a **question about intended behavior** ("price(100) returns 90 now; is that intended?"), never pushed to the PR branch. A test that kills `>=` -> `>` asserts what the PR's code does today; if the agent got the boundary wrong, an auto-pushed test would lock the bug in.

## Safety rules for the script

- **Edit contract `{file, find, replace}`:** `find` must appear exactly once; apply with `str.replace(find, replace, 1)`; build the displayed diff with `difflib`. (Already true in spirit: v1 already replaces single lines instead of applying diffs.)
- **Changed lines only, enforced:** reject any edit that doesn't overlap a `+` line in `git diff -U0`, touches a test file, or spans more than ~1 line.
- **Reject dangerous edits:** adding `import`, `os.`, `subprocess`, `eval`, `exec`, `open(`. Prompt injection from the diff must not become executed code.
- **Run in a throwaway copy** (`git worktree add $TMP HEAD`), restore the original text in a `finally`. Before any commit, `git diff --name-only` must list only test files.
- **`PYTHONDONTWRITEBYTECODE=1`** on every run, plus fresh worktree: same-length mutants (`<` -> `>`) can otherwise load the previous mutant's cached `.pyc`. (v1 already sets this and bumps mtime; the worktree makes it airtight. Not reproduced, only reasoned.)
- **Stillborn:** `py_compile` first. Exit 0 = survived, 1 = killed, anything else = stillborn. Record the exception per kill (`--junitxml`); a mutant that fails every test is "trivial" and left out of the count. If nothing is scoreable, report "couldn't verify" (never divide by zero, never pass).
- **Timeouts:** per mutant 3x baseline + 10 s; start tests in a new process group and kill the group (`os.killpg`). Timeout is its own category, counted as detected.
- **Flaky:** baseline red = block; baseline flaky (re-run 3x) = block with its own message. A kill during the mutant run is confirmed by re-running only the failing tests; unconfirmed kills are "inconclusive" and never counted.
- **Reproducible gate:** cache `mutants.json` keyed by a hash of the diff, so the gate doesn't flip on the same commit. Report the spread over 3 fresh runs in the benchmark.
- **Secrets:** run tests with a cleaned environment (no tokens). Test command comes from the automation settings, never from the PR. Trigger only on same-repo branches. Say "never run on fork PRs" in the README.
- **Platform:** Linux only (`os.killpg`). Develop in the Alan sandbox or WSL. `python` isn't on PATH on this laptop, only `py`.

## What already exists (in this folder)

- `mutant.py`: working loop with the model calls inside it, replay mode (`MUTANT_REPLAY`) reading hand-written mutants/tests, baseline x2, hang = caught, unparseable discarded, survivor retry, fix pass with tests verified on the original code, markdown report. **Refactor into the `plan / run / prove / report` subcommands above**: replay mode is essentially the new input path.
- `demo/`: repo with `agent/shipping-and-bulk`, weak tests. `fixtures/replay/`: **hand-written, not model output**. Never present the 2/12 -> 12/12 from them as a result.
- `test_mutant.py`: 4 checks for the edit contract. Extend it for each new rule.

## Build order (Alan first)

Hours are relative to now; the deadline is 20:00 IST today. Stop coding at deadline - 2h.

| When | Do | Done when |
|---|---|---|
| Hour 0 | Post the open Alan questions on Discord (below). Alan's team may be offline for the afternoon IST, so every question needs an answer in the first ~6 hours | Questions posted |
| Hours 0-3 | **Alan end to end first:** cloud environment with Python; an automation on PR opened runs `pytest`, writes a hard-coded test report, sets a commit status | A PR open triggers a run you can see; status shows on the PR |
| Hours 3-6 | Refactor `mutant.py` into subcommands, hardened per Safety rules; test with hand-written `mutants.json` | `py -m pytest test_mutant.py` green; demo repo scored without any model |
| Hours 6-8 | `/mutant` skill: the open-model agent writes `mutants.json` and `tests.json`, runs the commands | A real run produces real mutants |
| Sleep | | |
| Hours 12-14 | Proof tests and their checks | Proof rules enforced |
| Hours 14-16 | Test report, PR comment, status; benchmark | One table of real numbers |
| Hours 16-18 | Record a real run; README | Uncut recording linked |
| Hours 18-20 | Buffer. Stop coding | |
| Last 1h | Edit video, post, submit | Posted before the deadline |

**Cut, in this order:** one Alan task per survivor, Slack trigger, extra tweets, a second repo for the benchmark. Never cut the Alan-first step or the final hour.

## Open Alan questions (ask on Discord in hour 0; docs summaries don't answer them)

1. Can a PR-triggered automation run an agent on an **open model** in a cloud sandbox with Python and the PR's code checked out? **If not, Alan isn't in the demo. This kills the project; test first.**
2. Does "PR opened" also fire on new commits? (Reviewer says it doesn't. Add the "push to branch" trigger.)
3. Do the sandbox's GitHub credentials allow `gh api repos/{o}/{r}/statuses/$SHA`? (A required commit status is the real merge block. Test reports don't block merges by themselves.)
4. Can the agent create a test report (via `alan-test-feature` or similar), and can the skill force it to paste text unchanged?
5. Do credits pay for the model use, and does the usage page show cost per run (for the cost-per-PR number)?
6. What happens on timeout or when the team hits its cloud-run limit? A skipped run on camera means no demo.
7. Is the base branch available in the sandbox (`origin/main`), or must the script fetch it / use `gh pr diff`?

## Benchmark (honest version)

- A real Alan agent writes the PRs. Don't hand-write weak tests.
- For each PR, write 2-3 realistic **hidden bugs** *before* running Mutant; never show them to the model.
- Headline: "the agent's tests caught X of N hidden bugs; with Mutant's proof tests, Y of N". Plus: false alarms on a **control** (a real library's code and its real tests, not tests you wrote), share of mutants valid / stillborn / trivial, spread over 3 runs, seconds and cost per PR.
- Use a **different open-model family** for Mutant than the one that wrote the PR, so they don't share blind spots.
- If a number is bad, show it and say why.

## Demo (about 90 s)

0-10 s hook: a green agent PR, then Mutant's red comment: "your tests miss this bug", with the proof test.
10-30 s problem: agents write the code and the tests; green is not proof.
30-70 s a real, recorded run: Alan automation -> agent -> mutants -> survivor -> proof test -> status goes red -> the agent repairs.
70-90 s real numbers, the model name and cost on screen, repo link.
**De-risk:** record the real run well before the deadline and freeze `mutants.json` for it. Say whatever numbers that run produced.

## Tweets

1. Announcement (posted or about to be). The two-panel image with real pytest output; no numbers.
2. After Alan runs end to end: a short clip of the PR triggering the run.
3. Final: demo video + real benchmark numbers + repo link.

## README must say

How to install in two minutes (import the skill; create the automation: trigger PR opened + push, instruction `/mutant`). The proof contract. Limits: Python + pytest, Linux only, single-line mutants, tests lock in current behavior, cost grows with mutants x suite time. Never run on fork PRs. LICENSE (MIT).

## Known unknowns

- Alan claims above come from summaries of docs.tryalan.ai pages, not from running Alan. Fork-PR handling and the sandbox's GitHub permissions are undocumented.
- The prior-art claims (Google, Meta ACH numbers, Mutahunter) come from the review; open the sources before quoting any figure.
- The stale `.pyc` problem is reasoned, not reproduced.
