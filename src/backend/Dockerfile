# Build stage: install the dependencies into a virtual environment with uv.
FROM python:3.14-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

# Keep the virtual environment outside /app, so the dev bind mount of the
# source code does not hide it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install the dependencies first, so this layer is cached until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# Dev stage: adds the dev dependencies and reloads on code changes. Compose
# mounts the source code into /app.
FROM build AS dev

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

EXPOSE 8000

CMD ["newrelic-admin", "run-program", "fastapi", "dev", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]

# Runtime stage: only Python, the virtual environment and the app code.
FROM python:3.14-slim-bookworm AS runtime

RUN useradd --system --uid 1000 --no-create-home app

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
# The app reads its title, description and version from pyproject.toml.
COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY app ./app

ENV PATH="/opt/venv/bin:$PATH"

USER app

EXPOSE 8000

# newrelic-admin starts the New Relic agent before the app imports anything,
# and does nothing while NEW_RELIC_LICENSE_KEY is empty.
CMD ["newrelic-admin", "run-program", "fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
