# 0001. Build the hackathon template as one repo with a fixed stack

- Status: Accepted
- Date: 2026-10-03

## Context

This repo is a template for hackathons. A small team creates a new repository from it and has about a day or two to build a working product, show it on a public URL and hand it to a jury. That shapes every choice:

- The first hour must go to the product, not to setup. A fresh clone has to run with one command and no accounts or secrets.
- Several people, and AI coding agents such as Claude Code, change the code at the same time, so the code must follow one style that tools check, and branches must stay small.
- The jury looks at a live app, so `master` must always deploy, and deploying must take no manual steps.
- The money runs out when the hackathon ends, so the hosting must cost little and be easy to delete.

The decisions below were made one pull request at a time (#2 to #13). This record collects them in one place. Later ADRs record changes to them.

## Decision

We keep the whole product in one repo with a fixed, boring stack, run it in Docker for development, and deploy `master` to one DigitalOcean app.

**Layout.** One repo: the backend in `src/backend`, the frontend in `src/frontend`, the dev stack in `docker-compose.yml`, the deploy in `.do/app.yaml` and `.github/workflows`, and the decisions in `docs/adr`. A feature that touches the API and the UI is one branch and one pull request.

**Backend.** Python 3.14 and [FastAPI](https://fastapi.tiangolo.com/), managed with [uv](https://docs.astral.sh/uv/).

- Async all the way: `async def` endpoints, SQLAlchemy's async API and the asyncpg driver.
- Postgres for the data, with Alembic migrations that always come from `./dev makemigrations`, never by hand.
- Every route lives under `/api`, including the docs at `/api/docs`.
- Settings come from environment variables through pydantic-settings, and every one has a default.
- Background and scheduled work runs in [Celery](https://docs.celeryq.dev/) with Redis as the broker. The worker and the beat scheduler share one process, and schedules use `crontab`, because the beat state is lost on every deploy.

**Frontend.** React and TypeScript on [Vite](https://vite.dev/), styled with Tailwind CSS v4 and [shadcn/ui](https://ui.shadcn.com/), managed with pnpm. It builds to static files and calls the backend at the same origin under `/api/`, so there is no CORS to set up.

**Development.** `docker-compose.yml` runs the whole stack: `db`, `redis`, `migrate`, `api`, `worker` and `app`. The containers mount the source code and reload on every change. The `./dev` script wraps every command, so nobody needs Python, Node or Postgres on the host, only Docker and pre-commit.

**Quality.** pre-commit runs the same checks on every commit and in CI: ruff and ty on the backend, two migration checks, tsc, oxlint and Prettier on the frontend, and basic file checks. CI also runs the backend tests and the frontend build. Tests use the given / when / then structure.

**Deploy.** Every push to `master` that passes the checks deploys to [DigitalOcean App Platform](https://docs.digitalocean.com/products/app-platform/), as one app described in `.do/app.yaml`: the static frontend, the API, the worker, a migrate job, and managed Postgres and Valkey. It costs about $40 a month, billed per second, and the Destroy workflow deletes all of it.

**Monitoring.** [Sentry](https://sentry.io/) for errors on the backend and in the browser, and [New Relic](https://newrelic.com/) APM for the backend. Both stay off until their keys are set, so they never block a fresh clone.

**Working with AI agents.** `AGENTS.md` (and `CLAUDE.md`, a symlink to it) gives agents the rules of the repo. Project skills in `.claude/skills` keep the team's process: `break` stops a branch that grows past about 400 lines or 15 files, `ship` takes work to a pull request and keeps its description current, `sync` brings in `master`, and `judge` checks the work against the hackathon's rules in `local/rules`.

## Alternatives

- **Separate repos for the backend and the frontend.** Every feature would need two pull requests that must merge in the right order, and the dev stack and the deploy would have to join them again.
- **A full-stack JavaScript framework, such as Next.js.** One language, but the Python side is where data and AI libraries live, and FastAPI gives typed request models and API docs for free.
- **Sync Django.** It brings an admin panel and an ORM with migrations, but much of it goes unused in a hackathon, and slow calls to external APIs, such as LLMs, would block a worker.
- **Running the tools on the host.** Faster to start for one person, but every teammate needs the same Python, Node and Postgres versions, and "works on my machine" costs hours.
- **A PaaS with a free tier, such as Render or Railway, or a VPS.** Free tiers sleep or limit the database, and a VPS needs someone to run it. App Platform runs the whole stack from one spec file with a managed database, and its price is low for a few days.

## Consequences

- A new team runs `./dev up` and has the whole stack with hot reload. The TODO in `README.md` lists what to rename and which accounts to set up.
- Everyone, people and agents alike, writes code the same way, and the hooks catch the rest before review.
- `master` is always the version the jury sees, so a broken merge shows at once. Keep `master` green.
- The stack is fixed on purpose. Adding a service, a framework or a hosting provider is a new decision: write an ADR for it.
- The deploy costs money while it runs. Run the Destroy workflow when the hackathon ends.
- Some limits come with the choices: run only one worker, because each beat sends every scheduled task again; keep each task under 60 seconds and safe to run twice, because a deploy kills longer ones; and set `VITE_*` variables at build time, because Vite puts them into the built files.
