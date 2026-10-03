# AI control layer

A control layer between AI agents and their tools: a pipeline of guards that inspects every tool call and result.

## TODO

- [ ] `src/frontend/public/favicon.svg`: replace the Vite logo with your own icon.
- [ ] Sentry: create a project on [sentry.io](https://sentry.io/) and set `SENTRY_DSN` and `VITE_SENTRY_DSN`, see [Environment variables](#environment-variables). Leave them empty to keep Sentry off.
- [ ] New Relic: create an account on [newrelic.com](https://newrelic.com/), copy an ingest license key and set `NEW_RELIC_LICENSE_KEY`, see [Environment variables](#environment-variables). For the deploy, add it as the GitHub Actions secret `NEW_RELIC_LICENSE_KEY`. Leave it empty to keep New Relic off.
- [ ] Set up the [deploy](#deploy) to DigitalOcean:
  - [ ] Create a DigitalOcean [personal access token](https://cloud.digitalocean.com/account/api/tokens) with full access.
  - [ ] Install the [DigitalOcean GitHub app](https://github.com/apps/digitalocean) on the repository.
  - [ ] In the repository settings on GitHub, under **Secrets and variables → Actions**, add the secret `DIGITALOCEAN_ACCESS_TOKEN` with the token, and the variable `DIGITALOCEAN_APP_NAME` with a name for the app.
  - [ ] Push to `main`, or run the Main workflow from the Actions tab, and open the URL from the deploy job's log.
  - [ ] When the hackathon ends, run the Destroy workflow, so the app stops costing money.
- [ ] Delete this TODO section.

## Backend

FastAPI app in `src/backend`, managed with [uv](https://docs.astral.sh/uv/).

The backend uses Postgres through async SQLAlchemy and asyncpg, with [Alembic](https://alembic.sqlalchemy.org/) for migrations. It reads `DATABASE_URL` from the environment or from `src/backend/.env`, and connects to the Compose database on `localhost:5432` by default.

The usual way to run it is in Docker, see [Docker](#docker). To run it on the host instead:

```sh
docker compose up -d db          # from the repo root: start Postgres
cd src/backend
uv sync
uv run alembic upgrade head      # apply the migrations
uv run fastapi dev app/main.py   # http://localhost:8000/api/health, docs at /api/docs
uv run alembic revision --autogenerate -m "describe the change"   # after you change a model
uv run pytest
uv run ruff check . && uv run ruff format .
uv run ty check
```

### Background tasks

[Celery](https://docs.celeryq.dev/) runs background and scheduled tasks, with Redis as the broker. The `worker` service runs the worker and the beat scheduler in one process, so run only one copy of it: each scheduler sends every scheduled task again.

- Put tasks in `app/tasks/<name>.py` with the `@celery_app.task` decorator from `app.worker`, and add the module to `include` in `app/worker.py`.
- Send a task from an endpoint with `task.delay(...)`.
- Schedule a task in `celery_app.conf.beat_schedule` in `app/worker.py` with `crontab(...)`, for example `crontab(hour=3, minute=0)`. `app/tasks/ping.py` is an example that runs every minute. Beat keeps the last run times in a file that is lost when the container is recreated. A crontab runs at its clock time anyway, while a fixed interval starts counting again on every deploy, so prefer crontab.
- Keep a task under 60 seconds. On a deploy, the worker stops taking new tasks and waits up to 60 seconds for the running ones to finish. A task that runs longer is killed and runs again from the start, so write tasks that are safe to run twice.

To run it on the host: `uv run celery -A app.worker worker --beat --loglevel INFO`, with Redis running (`docker compose up -d redis`).

### MCP gateway

The control layer gives agents the tools of every registered MCP server, and runs each call and result through its guards. The gateway runs inside the API and has no URL of its own: the chat calls it for the signed-in user, whose clearance decides what the guards let through.

- **Servers** are managed on the Configuration page at `/config`, or at `/api/mcp-servers`. Whoever manages them decides which tools every agent gets, and for now that is anyone: access control comes with the users.
- **Keep the servers behind it internal.** An agent that can reach an MCP server directly goes around the guards. Run each one without a public port in Compose and without a public route on DigitalOcean, so only the API reaches it.

#### Bank MCP server

`app/servers/bank.py` is an example tool set to put behind the gateway: the Golden Socks core banking system over the data that `./dev seed` loads. It has no guards of its own. It checks the business rules a bank would, such as no payments from a frozen account, and returns whole rows, restricted fields included. Everything else is left to the control layer once the server is registered.

| Tool                                   | Does                                                                |
| -------------------------------------- | ------------------------------------------------------------------- |
| `search_clients`, `get_client`         | Find clients; one client's profile with their accounts              |
| `get_account`                          | An account and its balance available for payments                   |
| `list_transactions`, `list_trades`     | A client's or an account's transactions or trades, newest first     |
| `search_research`                      | Research reports by symbol, sector or title                         |
| `initiate_payment`                     | Send money out of an account; it waits as `PENDING` for payment ops |
| `flag_transaction`                     | Raise an AML alert; a pending payment is held                       |
| `restrict_account`, `lift_restriction` | Freeze an account for a risk review or legal hold, or open it again |
| `book_trade`, `cancel_trade`           | Book a client trade; cancel one that has not settled                |
| `update_client_contact`                | Change a client's named contact, email or phone                     |
| `add_client_note`                      | Add a dated note to a client's relationship notes                   |

Research, the data catalog, the identity profiles and the staff are read only. The tools carry MCP annotations: read only, write, or destructive for the ones that move money or freeze an account.

The API serves it at `/api/bank/mcp` and takes `Authorization: Bearer $BANK_MCP_TOKEN`; in Compose, the token is `dev-bank`. Only the gateway holds the token, so agents reach the tools only through the guards. Register it on the Configuration page, with the URL `http://localhost:8000/api/bank/mcp` and the authorization header `Bearer dev-bank`, or:

```sh
curl -X POST localhost:8000/api/mcp-servers -H "Content-Type: application/json" \
  -d '{"name": "bank", "url": "http://localhost:8000/api/bank/mcp", "auth_header": "Bearer dev-bank"}'
```

Its tools then reach agents as `bank__search_clients` and so on.

### Attack signatures

The `attack_signatures` guard blocks the patterns of known exploits on AI systems in every prompt, tool call and tool result: code execution, unsafe deserialization such as pickle and PyYAML tags, model files and code from untrusted repositories, template injection, cloud metadata SSRF and path traversal. Each signature cites the CVEs or write-ups it comes from.

The signatures live outside the code, in a JSON feed that a security team can maintain: `src/backend/app/control/signatures.json` by default, or any file or URL in `CONTROL_SIGNATURE_FEED`. The guard reads a file again when it changes, and a URL every `CONTROL_SIGNATURE_REFRESH` seconds, so an edit applies to the next message without a restart. If a new version is broken, the last good one stays, and a signature with a broken pattern is left out on its own.

```json
{
  "version": "2026-10-03.1",
  "signatures": [
    {
      "id": "CL-DESER-004",
      "name": "PyYAML tag that builds Python objects",
      "category": "deserialization",
      "severity": 0.95,
      "pattern": "!!python/(?:object|name|module)",
      "references": ["CVE-2017-18342", "CVE-2020-1747"],
      "enabled": true
    }
  ]
}
```

A match blocks when its `severity` reaches `CONTROL_SIGNATURE_THRESHOLD`, `0.7` by default. A lower match is only logged, as `CL-SUPPLY-002` is for a pickle model file from a model hub. Set `enabled` to `false` to turn one signature off. The audit log holds the IDs of the signatures matched, never the text.

## Frontend

React app in `src/frontend`, built with [Vite](https://vite.dev/), [Tailwind CSS](https://tailwindcss.com/) and [shadcn/ui](https://ui.shadcn.com/), managed with [pnpm](https://pnpm.io/).

The usual way to run it is in Docker, see [Docker](#docker). To run it on the host instead:

```sh
cd src/frontend
pnpm install
pnpm dev     # http://localhost:5173
pnpm build
pnpm typecheck
pnpm lint
pnpm format
```

## Docker

`docker-compose.yml` runs the whole stack for development. The backend and frontend containers run from the source code in `src/`, so every change you save applies at once: the backend reloads and the frontend updates in the browser.

| Service   | What it runs                                                   | URL                   |
| --------- | -------------------------------------------------------------- | --------------------- |
| `app`     | Frontend: the Vite dev server with hot reload                  | http://localhost:3000 |
| `api`     | Backend: `fastapi dev`, which reloads on every change          | http://localhost:8000 |
| `worker`  | Backend: Celery worker and beat scheduler, reloads on change   |                       |
| `migrate` | Applies the migrations, then exits. `api` starts after it ends |                       |
| `db`      | Postgres 18                                                    | `localhost:5432`      |
| `redis`   | Redis 8, the Celery broker                                     | `localhost:6379`      |

Manage the stack with the `./dev` script in the repo root. Every command except `lint` runs in the Docker containers. A command uses the running container when the stack is up, and a temporary one when it is down. Run `./dev help` for the full list.

| Command                          | What it does                                                                                                  |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| `./dev up [service...]`          | Build and start the stack, or only the given services                                                         |
| `./dev down`                     | Stop the stack; the database data stays                                                                       |
| `./dev restart [service...]`     | Rebuild and restart the stack, or only the given services                                                     |
| `./dev logs [service...]`        | Follow the logs                                                                                               |
| `./dev ps`                       | Show the status of every service                                                                              |
| `./dev destroy [-y]`             | Stop the stack and delete the database data and built images; asks first unless `-y`                          |
| `./dev shell [service]`          | Open a bash shell in a service, `api` by default                                                              |
| `./dev python`                   | Open a Python shell in the backend; `await` works at the prompt                                               |
| `./dev ngrok`                    | Share the app on a public HTTPS URL through ngrok; needs `NGROK_AUTHTOKEN`                                    |
| `./dev psql`                     | Open psql in the database                                                                                     |
| `./dev migrate [revision]`       | Apply the migrations, up to `head` by default                                                                 |
| `./dev makemigrations <message>` | Create a migration from the model changes                                                                     |
| `./dev checkmigrations`          | Check that the migrations apply to a fresh database and cover every model change                              |
| `./dev seed [--url URL] [-y]`    | Load the Golden Socks bank data; asks first unless `-y` when the URL is not local                             |
| `./dev lint [hook]`              | Run every pre-commit hook on the host, or only the given one. Needs the [pre-commit setup](#pre-commit-hooks) |
| `./dev test [pytest args...]`    | Run the backend tests; paths are relative to `src/backend`                                                    |

Extra arguments go straight to the tool:

```sh
./dev test tests/test_health.py::test_health   # one test
./dev test -k health -x                        # tests that match "health"; stop at the first failure
./dev logs api                                 # only the backend logs
./dev makemigrations "add posts table"
```

`./dev seed` replaces the rows of the `bank_` tables, and the bank's staff in `users` (emails at `goldensocks.com`), with the Golden Socks bank data in `src/backend/scripts/bank_data`: clients, accounts, trades, payments, research and staff, made up but consistent with each other, and the sensitivity of every field. `scripts/generate_bank_data.py` writes the files; change it and run `uv run python -m scripts.generate_bank_data` in `src/backend` to regenerate them. It leaves other users and tables alone, so you can run it again. Apply the migrations first. Every deploy to DigitalOcean seeds production too, right after the migrations, so it starts from the same rows. To seed it by hand, pass its URL: `./dev seed --url "postgresql://..."`.

The database data lives in the `db-data` volume, so it stays between `down` and `up`. Only `./dev destroy` deletes it.

Every backend route lives under `/api`, for example `/api/health` and the docs at `/api/docs`. The frontend passes requests under `/api/` to the backend unchanged, so the frontend can call `fetch("/api/health")`.

After you add a dependency, rebuild the images with `./dev up`. After you add a migration, apply it with `./dev migrate`.

To change the ports or the database credentials, see [Environment variables](#environment-variables).

### Production images

Both Dockerfiles use multi-stage builds. A `dev` stage is for Compose, and the last stage, the default one, is for production:

- Backend: a small image with Python, the virtual environment without dev dependencies, and the app code. It runs `fastapi run` under `newrelic-admin run-program`, which starts the New Relic agent, as a non-root user. Run `alembic upgrade head` in the same image to apply the migrations, `python -m scripts.seed -y` to load the bank data, and `newrelic-admin run-program celery -A app.worker worker --beat` to run the worker.
- Frontend: no image. The frontend deploys as static HTML, JS and CSS files. The last stage holds only the built files, so Docker can copy them out to `src/frontend/dist`. Running `pnpm build` locally gives the same files.

```sh
docker build -t api src/backend
docker build --output src/frontend/dist src/frontend
```

Vite puts `VITE_*` variables into the built files, so pass the frontend's Sentry DSN at build time: `docker build --build-arg VITE_SENTRY_DSN=https://... --output src/frontend/dist src/frontend`.

The static host must send requests under `/api/` to the backend unchanged, the way the Vite dev server does. See [Deploy](#deploy) for how this repo does it.

## Environment variables

Every variable has a default, so the project runs without any setup.

| Variable                      | Read by                    | Default                                                     | What it sets                                                                                       |
| ----------------------------- | -------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `APP_PORT`                    | Compose                    | `3000`                                                      | Host port for the frontend                                                                         |
| `API_PORT`                    | Compose                    | `8000`                                                      | Host port for the backend                                                                          |
| `DB_PORT`                     | Compose                    | `5432`                                                      | Host port for Postgres                                                                             |
| `REDIS_PORT`                  | Compose                    | `6379`                                                      | Host port for Redis                                                                                |
| `NGROK_AUTHTOKEN`             | Compose                    |                                                             | ngrok authtoken for `./dev ngrok`, from https://dashboard.ngrok.com                                |
| `POSTGRES_USER`               | Compose                    | `postgres`                                                  | Database user                                                                                      |
| `POSTGRES_PASSWORD`           | Compose                    | `postgres`                                                  | Database password                                                                                  |
| `POSTGRES_DB`                 | Compose                    | `app`                                                       | Database name                                                                                      |
| `DATABASE_URL`                | Backend                    | `postgresql+asyncpg://postgres:postgres@localhost:5432/app` | Database connection. It must use the `postgresql+asyncpg://` driver                                |
| `REDIS_URL`                   | Backend                    | `redis://localhost:6379/0`                                  | Redis that Celery sends the tasks through                                                          |
| `API_PREFIX`                  | Backend                    | `/api`                                                      | Path prefix for every backend route                                                                |
| `API_URL`                     | Frontend (Vite dev server) | `http://localhost:8000`                                     | Backend that the dev server sends `/api/` requests to                                              |
| `SENTRY_DSN`                  | Backend, Compose           | empty, Sentry off                                           | [Sentry](https://sentry.io/) project that the API and the worker send errors and traces to         |
| `SENTRY_ENVIRONMENT`          | Backend                    | `development`                                               | Environment name on the Sentry events                                                              |
| `SENTRY_TRACES_SAMPLE_RATE`   | Backend                    | `1.0`                                                       | Share of the requests and tasks that send a trace, from `0.0` to `1.0`                             |
| `VITE_SENTRY_DSN`             | Frontend (build), Compose  | empty, Sentry off                                           | Sentry project that the browser sends errors and traces to                                         |
| `VITE_SENTRY_ENVIRONMENT`     | Frontend (build)           | the Vite mode, `production` in the Docker build             | Environment name on the browser's Sentry events                                                    |
| `NEW_RELIC_LICENSE_KEY`       | New Relic agent, Compose   | empty, New Relic off                                        | [New Relic](https://newrelic.com/) ingest license key that the API and the worker report with      |
| `NEW_RELIC_APP_NAME`          | New Relic agent, Compose   | `backend` in Compose                                        | App name in New Relic APM; the deploy sets it to the DigitalOcean app name                         |
| `BANK_MCP_TOKEN`              | Backend, Compose           | `dev-bank` in Compose, else empty: server closed            | Bearer token for the bank MCP server at `/api/bank/mcp`. A repository secret in production         |
| `CONTROL_SIGNATURE_FEED`      | Backend                    | empty, the bundled `app/control/signatures.json`            | File path or http(s) URL of the attack signature feed, see [Attack signatures](#attack-signatures) |
| `CONTROL_SIGNATURE_REFRESH`   | Backend                    | `30`                                                        | Seconds between two fetches of a feed URL. A file is read again when it changes                    |
| `CONTROL_SIGNATURE_THRESHOLD` | Backend                    | `0.7`                                                       | Severity from which a signature match blocks; a lower one is only logged                           |

Where to set them:

- **Compose:** in your shell, or in a `.env` file next to `docker-compose.yml`, for example `API_PORT=8010 docker compose up --build`. Compose builds `DATABASE_URL` from the `POSTGRES_*` variables, and sets `REDIS_URL` to the `redis` service and `API_URL` to the `api` service, so you do not set those three yourself.
- **Backend outside Docker:** in your shell, or in `src/backend/.env`. The New Relic agent reads only the shell, not `.env`.
- **Frontend outside Docker:** in your shell, for example `API_URL=http://localhost:8010 pnpm dev`.

## Pre-commit hooks

[pre-commit](https://pre-commit.com/) runs these checks on every commit:

- Backend: ruff (lint and format) and ty (types).
- Migrations: the migrations must have a single head, and every model change must have a migration. The second check applies the migrations to a throwaway database on the Postgres in `DATABASE_URL`, so start the Compose database first (`./dev up db`) or point `DATABASE_URL` at your own Postgres. In CI, the job runs Postgres as a service container.
- Frontend: tsc (types), oxlint (lint) and Prettier (format).
- Whole repo: basic file checks from [pre-commit-hooks](https://github.com/pre-commit/pre-commit-hooks), such as trailing whitespace, valid YAML, JSON and TOML, merge-conflict markers, large files and private keys. GitHub workflow files are checked against their schema.

The backend and frontend hooks use the tools installed in each project, so install the backend and frontend dependencies first. Then set up the hooks once:

```sh
uv tool install pre-commit   # install the pre-commit command, once per machine
pre-commit install           # set up the git hook, once per clone
pre-commit run --all-files   # run all hooks by hand
```

## Claude Code skills

`.claude/skills` holds project skills for [Claude Code](https://code.claude.com/docs/en/skills). Claude runs a skill when it fits the task, or you run it with `/<name>`.

- `break`: stops Claude and makes it check in with you when the branch gets too big, drifts from what you asked for, or grows in scope. It reports what was asked, what is done and what is off track, and recommends a plan: split the work, trim it or go on. After every edit, a hook in `.claude/settings.json` runs `.claude/skills/break/diff-size.sh`, which measures the change against `main`, and tells Claude to run the skill when the change passes 400 lines or 15 files. Set other limits with `BREAK_MAX_LINES` and `BREAK_MAX_FILES`, for example in the `env` of `.claude/settings.local.json`.
- `ship`: takes finished work to an open pull request: checks the size with `break`, runs `./dev lint`, `./dev test` and the frontend build, commits, pushes, opens the PR or updates its description, and watches CI. Run it with `/ship`; Claude never runs it on its own, because it pushes. After every `git push` to a branch with an open PR, a hook runs `.claude/hooks/pr-description.sh`, which tells Claude to update the PR description, so it keeps describing the whole branch.
- `judge`: checks the work against the hackathon's documents in `local/rules`, such as the rules, the participant guide and the task description, as PDF, Markdown, text or screenshots. It keeps a digest of the facts with their sources in `local/.judge-cache`, and on every run reads again only the files that changed, so it follows changed tasks, times and criteria without reading every document each time. `/judge --fresh` rebuilds the digest. It reports the time left to each deadline and when to stop feature work, a one-line problem statement, how well the work fits the task with MoSCoW, a mock jury score on an anchored rubric with the real weights, a cold read and a pre-mortem of the submission, and the next steps ranked with ICE. It only reports and changes nothing. `local/` is gitignored, so the documents stay out of the repo.
- `sync`: merges the latest `main` into your branch and fixes what breaks: it resolves conflicts, regenerates lockfiles instead of merging them by hand, generates the branch's migration again on top of main's when both added one, rebuilds the stack or applies migrations when they changed, and runs the checks. It never pushes. `ship` runs it first when the branch is behind `main`.

## CI

GitHub Actions runs these workflows from `.github/workflows`:

- `pr.yml`: runs on every pull request. A new push to the PR cancels the run for the older commit.
- `main.yml`: runs on every push to `main`, and by hand from the Actions tab. Runs wait in a queue and never overlap. When several pushes wait, only the newest one runs. After the checks pass, it [deploys](#deploy).
- `destroy.yml`: runs by hand only, and deletes the deployed app and its databases.

`pr.yml` and `main.yml` call `checks.yml`, which runs all pre-commit hooks, the backend tests and the frontend build. Add steps that only one event needs to that event's workflow.

## Deploy

`main` deploys to [DigitalOcean App Platform](https://docs.digitalocean.com/products/app-platform/). The whole stack lives in one DigitalOcean app, described in `.do/app.yaml`:

| Component | What it runs                                                         | Monthly price, billed per second |
| --------- | -------------------------------------------------------------------- | -------------------------------- |
| `web`     | The frontend's static files, built with `pnpm build`                 | free                             |
| `api`     | The backend image, at `/api`                                         | $5                               |
| `worker`  | The backend image, with `celery -A app.worker worker --beat`         | $5                               |
| `migrate` | `alembic upgrade head`, before every deploy                          | per run                          |
| `db`      | A managed Postgres cluster, `<app name>-db`, created on first deploy | $15                              |
| `redis`   | A managed Valkey cluster, `<app name>-valkey`, the Celery broker     | $15                              |

That is about $40 a month, or about $1.30 a day. The app gets a URL like `https://<app name>-xxxxx.ondigitalocean.app`, where `/` serves the frontend and `/api/*` goes to the backend unchanged.

Set it up once:

1. In DigitalOcean, create a [personal access token](https://cloud.digitalocean.com/account/api/tokens) with full access.
2. Give DigitalOcean access to the repository: install the [DigitalOcean GitHub app](https://github.com/apps/digitalocean) on it.
3. In the repository settings on GitHub, under **Secrets and variables → Actions**, add the secret `DIGITALOCEAN_ACCESS_TOKEN` with the token, and the variable `DIGITALOCEAN_APP_NAME` with a name for the app: lowercase letters, digits and dashes, at most 29 characters.
4. Push to `main`, or run the Main workflow from the Actions tab. The first run creates the database clusters, which takes about five minutes, and then the app. The URL is in the deploy job's log and in the DigitalOcean console.

Without the `DIGITALOCEAN_APP_NAME` variable, `main.yml` skips the deploy.

For the [bank MCP server](#bank-mcp-server), also add the secret `BANK_MCP_TOKEN` there. Without it, the server refuses every request.

To send errors to [Sentry](https://sentry.io/), also add the variables `SENTRY_DSN` and `VITE_SENTRY_DSN` there. The deploy passes them to the backend and to the frontend build, with the environment `production`. Without them, Sentry stays off.

When you are done, run the Destroy workflow from the Actions tab and type the app name. It deletes the app and the database clusters with all their data, so they stop costing money. The next deploy creates them again, with an empty database.

To change the stack, edit `.do/app.yaml`, for example the instance sizes or an environment variable, and push. Each deploy applies the whole file. Changes you make in the DigitalOcean console are lost on the next deploy.
