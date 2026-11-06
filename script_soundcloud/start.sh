#!/usr/bin/env bash
# Démarre le daemon Docker (WSL) puis slskd.
set -e
cd "$(dirname "$0")"

if ! docker info >/dev/null 2>&1; then
    echo "Démarrage du daemon Docker..."
    nohup dockerd > /tmp/dockerd.log 2>&1 &
    for _ in $(seq 1 20); do
        docker info >/dev/null 2>&1 && break
        sleep 1
    done
fi

docker compose up -d
echo "slskd : http://localhost:5030"
