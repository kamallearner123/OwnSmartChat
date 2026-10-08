#!/usr/bin/env bash
set -e

cd "$(dirname "${BASH_SOURCE[0]}")"

python3 manage.py migrate
exec python3 manage.py runserver "${HOST:-0.0.0.0}:${PORT:-8001}"
