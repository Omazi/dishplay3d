#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TASK_ROOT="$PWD"
TASK_NAME=dishplay-reconstruction
case "${1:-status}" in
  start)
    test -f .data/worker.env || { echo 'Missing .data/worker.env; configure the private database connection first.'; exit 1; }
    test "$(stat -c %a .data/worker.env)" = 600 || { echo 'Set .data/worker.env permissions to 600.'; exit 1; }
    docker image inspect dishplay-reconstruction:1 >/dev/null
    mkdir -p .data/worker
    chmod 700 .data/worker
    if docker container inspect "$TASK_NAME" >/dev/null 2>&1; then
      docker start "$TASK_NAME"
    else
      docker run -d --name "$TASK_NAME" --restart unless-stopped --init \
        --cpus 1 --memory 2g --memory-swap 2g --pids-limit 256 \
        --cap-drop ALL --security-opt no-new-privileges --read-only \
        --tmpfs /tmp:rw,noexec,nosuid,size=128m \
        --user "$(id -u):$(id -g)" --env-file .data/worker.env \
        -e NODE_OPTIONS=--max-old-space-size=256 -e WORKER_MAX_IMAGES=40 \
        -e WORKER_MEMORY_MIB=1536 -e WORKER_DATA_DIR=/project/.data/worker \
        -e WORKER_PYTHON=/usr/bin/python3 -e WORKER_JOB_SECONDS=3600 \
        -v "$(command -v node):/usr/bin/node:ro" \
        -v "$TASK_ROOT/node_modules:/project/node_modules:ro" \
        -v "$TASK_ROOT/src/lib:/project/src/lib:ro" \
        -v "$TASK_ROOT/scripts/worker.ts:/project/scripts/worker.ts:ro" \
        -v "$TASK_ROOT/migrations:/project/migrations:ro" \
        -v "$TASK_ROOT/worker:/project/worker:ro" \
        -v "$TASK_ROOT/.data/worker:/project/.data/worker:rw" \
        -w /project --entrypoint /usr/bin/node dishplay-reconstruction:1 --import tsx scripts/worker.ts
    fi
    ;;
  stop) docker stop --time 20 "$TASK_NAME" ;;
  status) docker ps -a --filter "name=^/${TASK_NAME}$" --format '{{.Names}}: {{.Status}}';;
  logs) docker logs --tail 50 "$TASK_NAME" ;;
  *) echo 'Usage: bash scripts/local-worker.sh start|stop|status|logs'; exit 1 ;;
esac
