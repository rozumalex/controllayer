#!/usr/bin/env bash
# PostToolUse hook for Bash: after a git push to a branch with an open pull
# request, tell Claude to update the PR description, so it keeps describing
# the whole branch.
set -euo pipefail

# Match git push only where a command starts: at the beginning of a line or
# after &&, || or ;. A plain substring match would also catch the words
# "git push" in a commit message or a PR body.
python3 -c '
import json, re, sys
command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
sys.exit(0 if re.search(r"(?:^|&&|\|\||;)\s*git\s+push\b", command, re.MULTILINE) else 1)
' || exit 0

pr=$(gh pr view --json url,state --jq 'select(.state == "OPEN") | .url' 2>/dev/null) || exit 0
[[ -n $pr ]] || exit 0

printf '{"decision": "block", "reason": "%s"}\n' \
  "You pushed to a branch with an open pull request: $pr. Update its title and description now, so they describe the whole branch as it is after this push. Follow step 7 of the ship skill."
