#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  printf 'Web 用環境がありません。先に %s/setup.sh を実行してください。\n' "$APP_DIR" >&2
  exit 1
fi
cd -- "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" -B -m studio.main "$@"
