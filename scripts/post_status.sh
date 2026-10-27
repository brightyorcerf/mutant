#!/usr/bin/env bash
# usage: scripts/post_status.sh <pr-number> <report.md> <success|failure>
# Comments the report on the PR and sets a commit status "mutant". Mark that status as required in the branch rules
# to make it a real merge block. Needs `gh` with a token that can write statuses; unverified inside Alan's sandbox.
set -euo pipefail
pr="$1"; report="$2"; state="$3"
sha="$(gh pr view "$pr" --json headRefOid -q .headRefOid)"
gh pr comment "$pr" --body-file "$report"
gh api "repos/{owner}/{repo}/statuses/$sha" -f state="$state" -f context=mutant \
  -f description="$(head -n1 "$report" | cut -c1-140)"
