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
    @for i in $(seq 1 30); do s=$(docker inspect -f '{{"{{"}}.State.Health.Status{{"}}"}}' $(docker compose ps -q serve)); [ "$s" = healthy ] && { echo "serve healthy"; just prune-old; exit 0; }; sleep 2; done; echo "serve not healthy" >&2; exit 1

# Remove the relic5 images an earlier build left untagged (each `just up` leaves one, ~0.9 GB: 31 had piled up on
# white by 2026-10-24). Only dangling images whose command is `relic5 serve`; docker refuses one a container still uses.
prune-old:
    @n=0; for id in $(docker images -f dangling=true -q); do case "$(docker image inspect -f '{{"{{"}}json .Config.Cmd{{"}}"}}' $id 2>/dev/null)" in *'"relic5","serve"'*) docker rmi $id >/dev/null 2>&1 && n=$((n+1));; esac; done; echo "removed $n old relic5 image(s)"

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

# Rebuild the web UI (web/, React + Tailwind) into src/relic5/web; commit the result so white needs no Node.
web:
    cd web && bun install --frozen-lockfile && bun run build

# The UI with hot reload, its /api proxied to a hub (default white).
web-dev hub="http://white.follow-rankine.ts.net:8795":
    cd web && RELIC5_DEV_HUB={{hub}} bun run dev
