#!/bin/sh
set -eu

if [ -z "${QASE_API_TOKEN:-}" ]; then
    echo "QASE_API_TOKEN is required for Qase smoke reporting." >&2
    exit 2
fi

run_title="Event Agent - Live Smoke"
if short_commit=$(git rev-parse --short HEAD 2>/dev/null) && [ -n "$short_commit" ]; then
    run_title="$run_title - $short_commit"
fi

export QASE_MODE=testops
export QASE_TESTOPS_API_TOKEN="$QASE_API_TOKEN"
unset QASE_API_TOKEN
export QASE_TESTOPS_PROJECT=EA
export QASE_TESTOPS_RUN_TITLE="$run_title"
export QASE_TESTOPS_RUN_COMPLETE=true
export QASE_TESTOPS_RUN_TAGS=live,smoke,hf
export QASE_TESTOPS_SHOW_PUBLIC_REPORT_LINK=false

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
cd "$project_root"
exec "$project_root/scripts/support/run_hf_smoke_runtime.sh" \
    pytest tests/system_integration --run-smoke -m "smoke and live" -q
