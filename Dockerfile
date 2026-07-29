# Frontend first: its output is static and gets copied into the runtime image, so one
# container serves the API and the app from a single origin.
FROM node:26-alpine AS web

WORKDIR /web
# Node 26 no longer ships corepack, so it is installed explicitly. Going through corepack
# rather than `npm i -g pnpm@x` keeps the pnpm version coming from the `packageManager` field
# in web/package.json, which is the same source CI uses.
RUN npm install -g corepack@latest && corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm run build


FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS runtime

# git is a runtime dependency, not a build one: the store shells out to it for every read and
# write. curl is only here for the container healthcheck over the Unix socket.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

# Dependencies resolve from the lockfile in their own layer so application edits do not
# invalidate the install. README.md comes too: pyproject declares it as the project readme,
# so the build backend needs it present to produce metadata.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra server

COPY src/ ./src/
COPY --from=web /web/dist ./web/dist
RUN uv sync --frozen --no-editable --extra server

# The frontend is served from here. It must be explicit: the package is installed
# non-editable, so nothing in site-packages is relative to this directory.
ENV WEB_DIST=/app/web/dist

# No git identity is configured here on purpose. The store runs git with GIT_CONFIG_NOSYSTEM
# and GIT_CONFIG_GLOBAL unset, so anything written to /etc/gitconfig would be ignored, and
# every commit passes its author and committer explicitly instead.

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS --unix-socket "${KITSHN_DEFAULT_SOCKET}" http://localhost/healthz || exit 1

# Uvicorn binds the Unix socket itself and chmods it to 0666, so Caddy on the host can reach
# it with no socat sidecar and no published port.
CMD ["sh", "-c", "exec uvicorn money.api.app:app --uds \"${KITSHN_DEFAULT_SOCKET}\" --proxy-headers --forwarded-allow-ips='*'"]
