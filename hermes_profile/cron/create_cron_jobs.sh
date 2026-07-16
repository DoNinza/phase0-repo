#!/usr/bin/env bash
# create_cron_jobs.py의 얇은 wrapper (tradermonty 사례와 동일한 패턴).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 "${ROOT_DIR}/cron/create_cron_jobs.py" "$@"
