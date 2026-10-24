# relic5. On Linux (white) the hub runs in Docker; on a Mac everything runs natively (uv run relic5 ...).
set dotenv-load := false

default:
    @just --list

# tests (any machine)
test:
    uv run pytest -q

# Linux: build the image with this user's uid/gid
build:
    UID=$(id -u) GID=$(id -g) docker compose build

# Linux: start the hub (restart: unless-stopped), then wait for the healthcheck
up: build
    UID=$(id -u) GID=$(id -g) docker compose up -d serve
    @for i in $(seq 1 30); do s=$(docker inspect -f '{{"{{"}}.State.Health.Status{{"}}"}}' $(docker compose ps -q serve)); [ "$s" = healthy ] && { echo "serve healthy"; exit 0; }; sleep 2; done; echo "serve not healthy" >&2; exit 1

down:
    docker compose down

logs:
    docker compose logs -f --tail=100 serve

# month manifests + BM25 tables (Linux: in the image; Mac: native)
index:
    if [ "$(uname)" = Linux ]; then docker compose run --rm index; else uv run relic5 index; fi

# what the hub says about itself, from this machine
status:
    curl -s http://white.follow-rankine.ts.net:8795/api/status | python3 -m json.tool | head -60

# push this machine's parts (Mac native; white uses RELIC5_HUB=local)
push:
    bin/relic5-push
