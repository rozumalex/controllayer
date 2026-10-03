---
name: sync
description: Bring the latest master into the current branch and fix what breaks, such as merge conflicts, two Alembic heads, changed dependencies and new migrations. Use it when the user types /sync, when master has moved on since the branch started (for example after a teammate's PR was merged), or before shipping a branch that is behind master.
---

# Sync

In a hackathon, master moves fast. Bring it into the branch early and often, so conflicts stay small. Sync never pushes: the ship skill does that.

## 1. Check what is new

```sh
git fetch origin
git log --oneline HEAD..origin/master
```

If nothing is new, tell the user the branch is up to date and stop.

## 2. Put away unfinished work

If `git status --short` shows changes, stash them, new files too:

```sh
git stash push -u -m sync
```

## 3. Merge master

```sh
git merge origin/master --no-edit
```

Merge, don't rebase. A merge needs no force push, so it is safe when a teammate has pushed to the branch too. PRs are squash-merged, so the merge commit never reaches master.

## 4. Resolve conflicts

List the files with conflicts:

```sh
git diff --name-only --diff-filter=U
```

For each file, find out what each side meant: read both sides, and the commits that changed it on master (`git log --oneline HEAD..origin/master -- <file>`). Keep both intents. Don't take one side of a whole file just to get past the conflict.

- **Lockfiles:** take master's version, then regenerate it from the merged manifest:

  ```sh
  git checkout --theirs src/backend/uv.lock && docker compose run --rm --no-deps api uv lock
  git checkout --theirs src/frontend/pnpm-lock.yaml && docker compose run --rm --no-deps app pnpm install
  ```

- **Migrations:** never edit a migration file. Two branches that each add a migration don't conflict as files, but leave two Alembic heads. Step 5 fixes that by generating this branch's migrations again.
- **When you can't tell what is right,** for example both sides changed the same logic in different ways: stop and ask the user. Show both versions and say what each one does.

Then mark the files resolved and finish the merge:

```sh
git add <files>
git commit --no-edit
```

## 5. Regenerate the branch's migrations

```sh
docker compose run --rm migrate alembic heads
```

If it lists more than one head, master and this branch both added migrations. Don't join them with `alembic merge heads`: master's history stays a single line. Instead, delete this branch's migrations and generate them again on top of master's newest one. The branch isn't merged yet, so nobody else has applied its migrations.

1. Find the branch's own migrations, and the revision they start from:

   ```sh
   own=$(git diff --name-only --diff-filter=A origin/master...HEAD -- src/backend/migrations/versions)
   grep -H "^down_revision" $own
   ```

   The start is the `down_revision` of the oldest one: the revision that isn't one of the branch's own.

2. If the dev database has the branch's migrations applied (`docker compose run --rm migrate alembic current` shows one of them), downgrade it to the start first. The files must still exist to undo them:

   ```sh
   docker compose run --rm migrate alembic downgrade <start>
   ```

3. Delete the branch's migrations, apply master's, and generate one migration from the models:

   ```sh
   git rm $own
   ./dev migrate
   ./dev makemigrations "<what the branch changes, such as add user phone>"
   ```

4. Check the new file: its `down_revision` is master's newest revision, and it holds only this branch's model changes. If it's wrong, for example a renamed column shows up as a drop and an add, stop and tell the user. Don't fix it by hand.

5. Apply it and commit:

   ```sh
   ./dev migrate
   git add src/backend/migrations/versions
   git commit -m "Generate the migration again on top of master"
   ```

## 6. Bring back unfinished work

If you stashed in step 2:

```sh
git stash pop
```

Resolve any conflicts the same way as in step 4. Then run `git stash drop` once they're resolved, because a pop with conflicts keeps the stash.

## 7. Update the running stack

See what the merge brought in:

```sh
git diff --name-only ORIG_HEAD HEAD
```

- `uv.lock`, `pnpm-lock.yaml`, a `Dockerfile` or `docker-compose.yml` changed: rebuild with `./dev up`.
- Files in `src/backend/migrations/versions` changed: apply them with `./dev migrate`.

## 8. Run the checks

```sh
docker compose up -d --wait db
./dev lint
./dev test
```

If a check fails because of the merge, fix it and commit the fix. If the fix needs a real decision, stop and tell the user.

## 9. Report

Tell the user:

- How many commits came in from master, and their subjects.
- Each conflict, and how you resolved it.
- Whether you generated the branch's migrations again, rebuilt the stack or applied migrations.
- The check results.
