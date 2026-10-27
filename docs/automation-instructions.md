# Automation: PR opened or updated -> Mutant

Paste this into **Automations -> New automation**.

**Name:** Mutant gate

**Triggers (all GitHub, one repository):**
- Pull Request Opened (`pr_opened`)
- Pull Request Synchronised (`pr_synchronize`) — so a new commit on the PR re-runs the gate
- Push to Branch (`push`) — optional; only if you also want bare branch pushes checked

**Agent:** Alan Code, open model (`deepseek/deepseek-v4.1-flash` or `minimax/minimax-m3.1-flash` on this team).
**Runs on:** the team cloud environment.
**Visibility:** Team (or Personal).

**Instructions (paste verbatim):**

```
Run the /mutant skill on this pull request, on the PR's head branch, with BASE set to the PR's target branch.

Do not edit the PR's code, do not commit, and do not push. Do not merge.

When `python mutant.py report` prints its report:
1. Paste it unchanged into a test report for this run (result Fail/Mixed/Pass from ALAN_RESULT).
2. Post it on the PR with: bash scripts/post_status.sh <PR number> .mutant/report.md <MUTANT_STATE>.

If any command fails, put its exact error text in the report instead of guessing. Report the model name and this
run's token cost.
```

**Notes**
- `pr_opened` alone does not cover later commits; `pr_synchronize` does.
- The `mutant` commit status only blocks a merge if you mark it **Required** in GitHub branch protection.
- Same-repository branches only. Never enable this on fork PRs.
