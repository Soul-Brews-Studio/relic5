# relic5 hub image (Linux). Macs run relic5 natively; this is for white and, later, gb300's embed workers.
# Python, DuckDB and LanceDB are pinned (pyproject.toml + uv.lock). Runs as a non-root user whose uid/gid match the
# owner of the mounted data root, so files written to ~/relic5 stay nat's.
FROM python:3.12.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /usr/local/bin/uv
ARG UID=1001
ARG GID=1001
RUN groupadd -g ${GID} relic && useradd -u ${UID} -g ${GID} -m -s /usr/sbin/nologin relic \
 && apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN chown relic:relic /app
USER relic
# Dependencies first, in their own layer: a code change rebuilds only the small layers below. No `chown -R` after the
# install (it copied the whole venv into a new layer on every deploy: ~10 x several hundred MB of build cache on white,
# 2026-10-24); files are owned by relic as they are written.
ENV UV_NO_CACHE=1
COPY --chown=relic:relic pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=relic:relic src ./src
RUN uv sync --frozen --no-dev
ENV PATH=/app/.venv/bin:$PATH RELIC5_ROOT=/data RELIC5_TOKENS=/config/tokens RELIC5_TOKENS_JSON=/config/tokens.json HOME=/home/relic
EXPOSE 8795
CMD ["relic5", "serve", "--root", "/data", "--host", "127.0.0.1,100.103.52.67", "--port", "8795"]
