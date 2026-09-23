#!/bin/sh
set -eu

export QASE_MODE=off
unset QASE_API_TOKEN QASE_TESTOPS_API_TOKEN

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
cd "$project_root"
exec "$project_root/scripts/support/run_hf_smoke_runtime.sh" \
    pytest tests/system_integration --run-smoke -m "smoke and live" -q
