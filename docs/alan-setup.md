# Running Mutant in Alan

Verified against `docs.tryalan.ai` and the live Alan catalogue on 2026-10-27. Anything still unverified is marked.

## 1. Cloud environment
Settings -> your team -> **Cloud Environment** (`/teams/{teamId}/settings/managed-cloud`).

- Add the repository (the team must first link it under **Settings -> Integrations**), pin the branch.
- Install script: `bash .alan/setup.sh` (Python 3.12 + `pip install pytest` + the repo's deps).
- The image is built from the environment; a new session starts from that image with the code cloned.
- **Verified:** the docs say a cloud session starts a fresh computer with the code cloned. **Not verified:** the exact
  image contents, whether `gh` is present, or whether `origin/main` exists. `mutant.py` tries `main` then `origin/main`
  and exits if neither is found, so add `git fetch origin <base>` if your runs fail there.

## 2. Skill
A skill is a folder with `SKILL.md` (`name`, `description`, instructions) plus any reference files. This repo already
matches that shape. Add `skills/mutant/SKILL.md` as a team skill named `mutant` (Skills -> Create manually, or
`create_skill`).

## 3. Automation
Create an automation (Alan -> Automations -> New). **Runs need a cloud environment.**

- **Triggers (verified names):** GitHub `pr_opened` (Pull Request Opened) and `pr_synchronize` (Pull Request
  Synchronised) so a fix commit re-runs the gate. Optionally add `push` (Push to Branch). Same-repo branches only.
- **Agent:** Alan Code on an open model. On this team's gateway only `deepseek/deepseek-v4.1-flash` and
  `minimax/minimax-m3.1-flash` are enabled; other ids return `403 This model is disabled for the team`.
- **Instructions:** see `docs/automation-instructions.md` (paste the block verbatim).

## 4. Make it block
In GitHub: Settings -> Branches -> require the status check `mutant`. Alan test reports alone do not block a merge.

## 5. Facts and open items
1. **`pr_opened` does not fire on new commits.** Use `pr_synchronize` (or `push`). Verified in the trigger catalogue.
2. **Test reports:** an agent can create one (`create_test_report` with title/content/status). Nothing enforces that the
   pasted text is unchanged; the instruction asks, the model may still paraphrase.
3. **Cost:** Settings -> Team -> Usage shows tokens by model and member, and the last 14/30/90 days. There is no
   per-run dollar line in the UI; the model response carries `usage.cost` (this run: $0.0100 for 9,871 tokens).
4. **Timeout / limits:** a run ends `Timed out`; a run is `Skipped` when the previous run is still going, the team hit
   its cloud-run limit, or the org can't start cloud work. Cloud budget exhaustion pauses running sandboxes after a
   grace period.
5. **GitHub writes:** verified on the local machine, not in a sandbox. `scripts/post_status.sh 1 report.md failure` on
   `tejaanshglido/mutant-smoke` posted a PR comment and a `mutant` commit status (combined state `failure`). Inside an
   Alan sandbox this is still unverified: no cloud machine existed and the GitHub App was not installed. See
   `docs/smoke-test.md`.
6. **Never run on fork PRs.** The PR's code and tests execute during the run.
