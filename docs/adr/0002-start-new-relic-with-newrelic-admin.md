# 0002. Start New Relic with newrelic-admin

- Status: Accepted
- Date: 2026-10-03

## Context

The API and the Celery worker send traces, errors and metrics to [New Relic](https://newrelic.com/) APM. The Python agent has to start before it can instrument anything, and there are two ways to start it:

- In the app code: call `newrelic.agent.initialize()` at the top of `app/main.py` and `app/worker.py`.
- With the launcher: run the process as `newrelic-admin run-program <command>`.

The first version of this branch started the agent in the app code, from `init_new_relic()` in `app/core/new_relic.py`, next to `init_sentry()`. It worked, but it needed its own settings in `app/core/config.py`, its own tests, and a call in each entry point that had to stay above the other imports.

New Relic must also stay optional: the project has to run with no setup, so the agent must do nothing while `NEW_RELIC_LICENSE_KEY` is empty.

## Decision

We start the New Relic agent with `newrelic-admin run-program`, and the app code does not know about it.

- The `dev` and `runtime` stages in `src/backend/Dockerfile` run `newrelic-admin run-program fastapi ...`.
- The `worker` service in `docker-compose.yml` and the `worker` in `.do/app.yaml` run `newrelic-admin run-program celery ...`.
- The agent reads its settings from `NEW_RELIC_*` environment variables only. Compose passes `NEW_RELIC_LICENSE_KEY` and sets `NEW_RELIC_APP_NAME` to `backend`. The deploy sets the license key from a GitHub Actions secret and the app name to the DigitalOcean app name.

## Alternatives

- **Start the agent in the app code.** The agent starts after Python has imported some modules, so instrumentation depends on import order, and a new entry point that forgets the call is not monitored. It also adds settings, a module and tests that only wrap the agent's own setup.
- **A `newrelic.ini` file.** It duplicates what the environment variables already set, and it would need a different file, or overrides, for development and production.

## Consequences

- The agent starts before the app imports anything, the way New Relic recommends, so FastAPI, Celery, SQLAlchemy and Redis are instrumented without any code.
- New Relic is off until `NEW_RELIC_LICENSE_KEY` is set. With an empty key, `newrelic-admin` just runs the command.
- Every new backend process that should report to New Relic needs `newrelic-admin run-program` in front of its command. A command without it runs fine but sends nothing.
- The agent does not read `src/backend/.env`. Outside Docker, set the `NEW_RELIC_*` variables in the shell.
- There are no tests for the New Relic setup, because there is no app code for it. Check it by hand: set a license key, run `./dev up`, and look for the app in New Relic APM.
