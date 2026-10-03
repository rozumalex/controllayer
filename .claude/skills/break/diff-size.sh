#!/usr/bin/env bash
# Measure the change on this branch against the main branch: committed,
# staged and unstaged work. Untracked files and lockfiles are left out, so
# git add a new file to count it.
#
#   diff-size.sh          print the size and the limits
#   diff-size.sh --hook   for the PostToolUse hook: when the change is over a
#                         limit, tell Claude to stop and run the break skill
#   diff-size.sh --ack    the user chose to go on: stay quiet until the change
#                         grows by another BREAK_MAX_LINES lines or
#                         BREAK_MAX_FILES files
#
# Set the limits and the main branch with BREAK_MAX_LINES (400),
# BREAK_MAX_FILES (15) and BREAK_MAIN_BRANCH (master).
set -euo pipefail

max_lines=${BREAK_MAX_LINES:-400}
max_files=${BREAK_MAX_FILES:-15}
main=${BREAK_MAIN_BRANCH:-master}

cd "$(git rev-parse --show-toplevel)"

# Prefer the remote branch: the local one may be behind.
if git rev-parse -q --verify "origin/$main" >/dev/null; then
  main=origin/$main
fi
base=$(git merge-base HEAD "$main")

paths=(. ':(exclude)*.lock' ':(exclude)*-lock.yaml' ':(exclude)*-lock.json')

lines=$(git diff --numstat "$base" -- "${paths[@]}" | awk '$1 != "-" { n += $1 + $2 } END { print n + 0 }')
files=$(git diff --name-only "$base" -- "${paths[@]}" | wc -l)
files=$((files + 0))

# The size the user last chose to go on at, per branch. It lives in .git, so
# it is never committed.
branch=$(git rev-parse --abbrev-ref HEAD)
ack_file=$(git rev-parse --git-path "break-ack-${branch//\//-}")

case ${1:-} in
  --ack)
    echo "$lines $files" >"$ack_file"
    echo "Going on at $lines lines in $files files. The next break comes at" \
      "$((lines + max_lines)) lines or $((files + max_files)) files."
    ;;
  --hook)
    read -r ack_lines ack_files 2>/dev/null <"$ack_file" || true
    limit_lines=$((${ack_lines:-0} + max_lines))
    limit_files=$((${ack_files:-0} + max_files))
    if ((lines > limit_lines || files > limit_files)); then
      printf '{"decision": "block", "reason": "%s"}\n' \
        "The change against $main is now $lines lines in $files files, over the limit of $limit_lines lines or $limit_files files. Stop editing and run the break skill before you change anything else."
    fi
    ;;
  "")
    echo "Change against $main: $lines lines in $files files" \
      "(limits: $max_lines lines, $max_files files)"
    ;;
  *)
    echo "Usage: $0 [--hook | --ack]" >&2
    exit 1
    ;;
esac
