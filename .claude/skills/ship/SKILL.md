---
name: ship
description: Take finished work from the working tree to an open pull request in one go. It checks the size, runs the same checks as CI, commits, pushes, opens the PR or updates its description, and watches CI. Use it when the user types /ship.
disable-model-invocation: true
---

# Ship

The user typed `/ship`, so they want this work committed, pushed and in a PR. Do every step without asking, unless a step below says to stop.

## 1. Check the branch

```sh
git branch --show-current
git status --short
```

- On `main`, create a branch first: `git switch -c <type>/<short-name>`, for example `feat/user-login` or `fix/health-timeout`. Never commit to `main`.
- Read every untracked file name. Stop and ask about anything that looks like a secret, a local config or a build artifact, such as `.env`, `*.pem`, `dist/` or a database dump.

## 2. Check the size

```sh
.claude/skills/break/diff-size.sh
```

If the change is over the limit and the user hasn't chosen to go on, stop and run the break skill instead of shipping.

## 3. Bring in main

If `git fetch origin && git log --oneline HEAD..origin/main` shows new commits, run the sync skill first, so CI tests the branch as it will merge.

## 4. Run the checks

Run what CI runs. The migration hook needs Postgres on `localhost`, so start it first:

```sh
docker compose up -d --wait db
./dev lint
./dev test
docker compose run --rm --no-deps app pnpm build   # only when src/frontend changed
```

Fix what fails, and run the checks again until they pass. Formatters fix files on their own, so just run them again. If a fix needs a real change to the code, such as a failing test or a type error with no clear cause, stop and tell the user. Never ship red, and never skip a hook with `--no-verify`.

## 5. Commit

Read the whole diff before you commit. Remove debug prints, commented-out code and leftover TODOs that the change added.

Stage files by path, not with `git add -A`. Write the message the way `git log` shows in this repo:

- An imperative subject under about 70 characters, such as "Add user login endpoint".
- A body that says what changed and why, for a reviewer who hasn't seen the conversation.

Make one commit per logical change. Most ship runs need one.

## 6. Push

```sh
git push -u origin HEAD
```

## 7. Open the PR, or update it

Check for an open PR on this branch:

```sh
gh pr view --json number,url,title,body,baseRefName
```

**No PR yet:** open one with `gh pr create`. The base is `main`, unless this branch is stacked on another open PR's branch: then the base is that branch.

**A PR is open:** update its description, every time you push. The description must describe the whole branch as it is now, not the first commit and not this push. Read it from `git log <base>..HEAD` and `git diff <base>...HEAD`, not from memory. Keep what still holds from the current description, such as screenshots, linked issues, notes a teammate wrote and test plan items already checked, and rewrite the rest. Don't add an "Updates" log at the bottom. Change the title too if it no longer fits.

```sh
gh pr edit --title "<title>" --body-file <file>
```

Write the description in this shape:

```markdown
## Summary

<what the branch changes and why, as a short paragraph or a list of the main changes>

## Test plan

- [x] <checks you ran, such as ./dev lint and ./dev test>
- [ ] <what a reviewer should try by hand>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## 8. Watch CI

```sh
gh pr checks --watch
```

If it says no checks are reported, the CI run hasn't attached to the PR yet. Wait about 10 seconds and run it again, up to a few times, before you report that the PR has no CI.

If a check fails, read the log with `gh run view <run-id> --log-failed`, fix the cause, and ship again from step 4.

## 9. Report

Give the user the PR link, the commits you pushed, and the CI result.
