---
name: break
description: Stop and check in with the user before the work gets out of hand. Use it when the diff against master is too big (the PostToolUse hook tells you so), when the work drifts away from what the user asked for, or when the scope grows, for example you start fixing things you found along the way, touch areas the request never mentioned, or the task turns into several tasks. Also use it when the user types /break.
---

# Break

In a hackathon, small branches get reviewed and merged fast, and a big one blocks the team. Stop, show the user where the work stands, and let them decide what happens next.

## 1. Stop editing

Make no more changes to files until the user answers. Finish the sentence you are writing, not the feature.

## 2. Measure the change

```sh
.claude/skills/break/diff-size.sh
git diff --stat "$(git merge-base HEAD origin/master)"
git status --short
```

## 3. Compare it to the request

State the original request in one line. Take it from the conversation, the branch name or the PR. Then sort every changed file into one of three groups:

- **Needed:** the request can't work without it.
- **Found along the way:** refactors, fixes and cleanups in code the request didn't need to touch.
- **New scope:** features or behavior nobody asked for.

## 4. Report

Keep it short, in this shape:

```
Break: <why: too big, drifted or scope grew>, <N lines in M files>

Asked:     <the request in one line>
Done:      <what of it works now>
Left:      <what of it is still missing>
Off track: <files or changes found along the way or in new scope, or "nothing">

Recommendation: <one plan>
```

Pick one recommendation from these, or a mix:

- **Split:** commit the needed part on this branch, and move the rest to a new branch for a follow-up PR.
- **Trim:** revert the changes that are off track.
- **Go on:** the change is big but all of it is needed, and splitting it would leave something broken.

## 5. Wait for the user

Ask which plan to follow, and do nothing until they answer. Don't revert, stash or move code on your own.

Then follow their choice:

- **Split:** stash the off-track files with `git stash push -- <paths>`, commit the rest, then create the follow-up branch from this one and run `git stash pop` there.
- **Trim:** revert each off-track file with `git restore --source "$(git merge-base HEAD origin/master)" -- <path>`, and delete the new files. List the files first and get a yes, because this throws work away.
- **Go on:** run `.claude/skills/break/diff-size.sh --ack`, so the hook stays quiet until the change grows by another full limit.
