# AGENTS.md

Instructions for AI coding agents working in this repo. `CLAUDE.md` is a symlink to this file.

## Backend (`src/backend`)

FastAPI app managed with uv. Run its commands in Docker with the `./dev` script from the repo root (see [Docker](#docker)):

```sh
./dev test                                   # all tests
./dev test tests/test_health.py::test_health # one test
./dev lint                                   # every pre-commit hook, on the host
./dev python                                 # Python shell in the backend, await works
```

- `src/backend` is the sources root and `app` is a package, so imports look like `from app.api.endpoints import health`.
- Put endpoints in `app/api/endpoints/<name>.py` as an `APIRouter`, and include it in the router in `app/api/router.py`. That router adds the `/api` prefix, so every route, including the docs, lives under `/api`.
- Put request and response models in `app/core/schema/<name>.py`.
- The app reads its title, description and version from `pyproject.toml`. Do not hardcode them.
- Write async code: endpoints are `async def`, and the database is reached through SQLAlchemy's async API with the asyncpg driver. Do not add blocking I/O to a request path.
- Settings come from environment variables (or `src/backend/.env`) through `app/core/config.py`.
- Get a database session with the `get_session` dependency from `app/db/session.py`.
- Put SQLAlchemy models in `app/db/models/<name>.py`, and import each one in `app/db/models/__init__.py` so Alembic can see it.
- Put Celery tasks in `app/tasks/<name>.py` with `@celery_app.task` from `app.worker`, and add the module to `include` in `app/worker.py`. Schedule them in `beat_schedule` there with `crontab(...)`, not a fixed interval, because the beat state is lost when the container is recreated. Tasks are sync functions; to reach the database from one, run async code with `asyncio.run`.
- After you change a model, create a migration, check the generated file, then apply it:

  ```sh
  ./dev makemigrations "add posts table"
  ./dev migrate
  ```

- If main and your branch both added a migration, pre-commit fails with more than one head. Don't join the heads with a merge migration. Generate your branch's migration again on top of main's: downgrade the dev database below your migration, delete it, run `./dev migrate`, then `./dev makemigrations`. In Claude Code, the `sync` skill does this.
- Every migration must come from `./dev makemigrations`. Never write a migration file by hand, and never edit a generated one. To change a migration, change the model and generate it again. If the generated file is wrong, for example a renamed column shows up as a drop and an add, stop and tell the user. Do not fix it by hand.

## Tests

Every test must use the given / when / then structure, marked with comments:

```python
def test_health(client: TestClient) -> None:
    # given
    url = "/api/health"

    # when
    response = client.get(url)

    # then
    assert response.status_code == 200
```

- `# given`: set up the inputs and state.
- `# when`: do the one action under test.
- `# then`: assert the results.

When the action and the check fit in one line, use `# when / then` instead of separate `# when` and `# then` sections:

```python
def test_redoc(client: TestClient) -> None:
    # given
    url = "/api/redoc"

    # when / then
    assert client.get(url).status_code == 200
```

## Frontend (`src/frontend`)

React + TypeScript app on Vite, styled with Tailwind CSS v4 and shadcn/ui, managed with pnpm. Run commands from `src/frontend`:

```sh
pnpm dev                        # dev server at http://localhost:5173
pnpm build                      # type-check and build
pnpm typecheck                  # tsc only
pnpm lint                       # oxlint, fails on warnings
pnpm format                     # prettier
pnpm dlx shadcn@latest add card # add a shadcn component
```

- Import from `src` with the `@/` alias, for example `import { Button } from "@/components/ui/button"`.
- Add shadcn components with the CLI. Do not write them by hand. The CLI puts them in `src/components/ui`, and lint skips that folder.
- Use `cn` from `@/lib/utils` to merge class names.
- Follow the shadcn code style: double quotes and no semicolons. Prettier applies it, and also sorts Tailwind classes.

## Docker

`docker-compose.yml` in the repo root is the development stack: `db` (Postgres), `redis` (the Celery broker), `migrate` (applies the migrations, then exits), `api` (backend), `worker` (Celery worker and beat in one process) and `app` (frontend). `api`, `worker` and `app` mount the source code from `src/` and reload on every change, so do not rebuild the images after a code change. Rebuild only after you change the dependencies.

Manage it with the `./dev` script in the repo root. Every command except `lint` runs in the containers, so use it instead of running uv, pnpm or pytest on the host. `lint` runs pre-commit on the host, the same hooks as the git commit hook and CI. Run `./dev help` for the full list.

```sh
./dev up          # build and start; app at http://localhost:3000, api at http://localhost:8000
./dev logs api    # follow the backend logs
./dev test -k x   # extra arguments go to pytest
./dev lint        # every pre-commit hook
./dev psql        # psql in the database
```

When you add a command to `./dev`, add it to its `usage` text and to the command table in `README.md`.

Both Dockerfiles use multi-stage builds, and Compose builds the `dev` stage. In the backend, the last stage is the production image: keep it small and do not add dev tools to it. The frontend deploys as static files, so its last stage holds only the built `dist` files.

## Pre-commit hooks

`.pre-commit-config.yaml` runs ruff and ty on the backend, two migration checks (a single Alembic head, and no model change without a migration), tsc, oxlint and Prettier on the frontend, and basic file checks on the whole repo. CI runs the same hooks, plus the backend tests and the frontend build. Before you commit, run all hooks and fix any failures:

```sh
pre-commit run --all-files
```

## Scope

Keep each branch to one task, so it gets reviewed and merged fast. Stop and check in with the user when the change against `main` grows past about 400 lines or 15 files (lockfiles not counted), when the work drifts from what the user asked for, or when the scope grows, for example with fixes found along the way or features nobody asked for. Claude Code does this with the `break` skill in `.claude/skills/break`. After every edit, a hook in `.claude/settings.json` measures the change and tells Claude to run the skill when it is over the limit.

## Pull requests

Every time you push to a branch with an open pull request, update the PR title and description, so they describe the whole branch as it is after the push. Read it from the commits and the diff against the base branch, not from memory. Keep what still holds, such as screenshots, linked issues and notes from teammates, and rewrite the rest. Don't add a log of updates. In Claude Code, the `ship` skill does this, and a hook in `.claude/settings.json` reminds Claude after every `git push`.
