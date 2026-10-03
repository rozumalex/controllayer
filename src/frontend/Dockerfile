# Dependencies stage: install the dependencies with pnpm.
FROM node:24-slim AS deps

ENV PNPM_HOME=/pnpm \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0
ENV PATH="$PNPM_HOME:$PATH"

# Corepack installs the pnpm version set in the packageManager field.
RUN corepack enable

WORKDIR /app

# Install the dependencies first, so this layer is cached until the lockfile changes.
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# Dev stage: the Vite dev server with hot reload. Compose mounts the source
# code into /app.
FROM deps AS dev

EXPOSE 5173

CMD ["pnpm", "dev", "--host", "0.0.0.0"]

# Build stage: build the static files.
FROM deps AS build

# Vite puts these into the built files, so pass them with --build-arg.
ARG VITE_SENTRY_DSN \
    VITE_SENTRY_ENVIRONMENT=production

COPY . .
RUN pnpm build

# Export stage: only the built files, to copy out with
# `docker build --output dist src/frontend`.
FROM scratch AS dist

COPY --from=build /app/dist /
