#!/bin/sh
set -eu

if [ -z "${QASE_API_TOKEN:-}" ]; then
    echo "QASE_API_TOKEN is required for Qase MOSiR smoke reporting." >&2
    exit 2
fi

case_id=39
exec python -m scripts.qase_mosir_smoke_reporter \
    --case-id "$case_id" \
    --title "Event Agent - MOSiR Live Smoke" \
    --probe /app/scripts/run_hf_mosir_live_smoke.sh
