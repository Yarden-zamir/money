# Frontend first: its output is static and gets copied into the runtime image, so one
# container serves the API and the app from a single origin.
FROM node:26-alpine AS web

WORKDIR /web
RUN corepack enable
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
# invalidate the install.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --extra server

COPY src/ ./src/
COPY --from=web /web/dist ./web/dist
RUN uv sync --frozen --no-editable --extra server

# git needs an identity for the fallback path; real commits override both with the acting
# user's name and email.
RUN git config --system user.name "money" \
    && git config --system user.email "money@yarden-zamir.com" \
    && git config --system --add safe.directory '*'

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS --unix-socket "${KITSHN_DEFAULT_SOCKET}" http://localhost/healthz || exit 1

# Uvicorn binds the Unix socket itself and chmods it to 0666, so Caddy on the host can reach
# it with no socat sidecar and no published port.
CMD ["sh", "-c", "exec uvicorn money.api.app:app --uds \"${KITSHN_DEFAULT_SOCKET}\" --proxy-headers --forwarded-allow-ips='*'"]
