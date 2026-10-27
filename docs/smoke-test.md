# Smoke test (2026-10-27)

Goal: prove the path **PR -> gate -> PR comment + commit status + Alan test report**, using a fake gate.

## Repo and PR
- Public repo: https://github.com/tejaanshglido/mutant-smoke
- PR #1: https://github.com/tejaanshglido/mutant-smoke/pull/1 (`pr/failing-test` -> `main`)
- Head sha: `a1f12fcab60a5a32f9c82d2917fe09571c2a658d`

## What ran (real)
- `py -m pytest -q` on the PR head: **1 failed, 1 passed** (the PR deliberately asserts `add(2, 2) == 5`).
- `bash scripts/post_status.sh 1 report.md failure`:
  - PR comment: https://github.com/tejaanshglido/mutant-smoke/pull/1#issuecomment-6434953145
  - commit status: `context=mutant`, `state=failure`; combined commit state `failure`.
- Alan test report: `92c53483-2a66-423e-a617-16f6119096cc`, result **Fail**, content passed unchanged.
  https://app.tryalan.ai/teams/cfaa22bc-9d40-49f8-8b2c-dc5747a2e887/docs?artifactId=92c53483-2a66-423e-a617-16f6119096cc

## What did NOT run, and why
- The **Alan automation run**. After GitHub was authorized, `add_team_repository("tejaanshglido/mutant-smoke")` returned
  `environment_unavailable`: "This conversation's cloud environment cannot take repositories."
- `list_cloud_machines` is `[]`; `get_cloud_machine({})` says an id is required; `test_environment_build({})` says
  "only available on a conversation bound to a cloud machine".
- `list_repositories(scope="connectable")` still returns `github_app_not_installed` for the organization.
- Therefore there is no sandbox `gh auth status`, no sandbox status write, and no screenshots of a live run yet. The
  local `gh` path above is real; the sandbox path is not exercised.

The automation (`Mutant gate`, `e738c74c-1e45-49fb-84ed-335eee5e6cb9`) and the skill (`mutant`,
`135679f1-804b-4a70-899b-68ea6fcfd8a2`) are installed but the automation is disabled until the App is connected and a
cloud environment exists.

## Commands
```
gh repo create mutant-smoke --public --source=. --remote=origin --push
gh pr create --title "Add a deliberately failing regression test" --base main --head pr/failing-test
py -m pytest -q                                  # 1 failed, 1 passed
bash scripts/post_status.sh 1 report.md failure   # comment + status
gh api repos/tejaanshglido/mutant-smoke/commits/<sha>/status
```
