#!/bin/sh
set -eu

export QASE_MODE=off
unset QASE_API_TOKEN QASE_TESTOPS_API_TOKEN

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$script_dir/run_hf_smoke_runtime.sh" \
    pytest tests/system_integration --run-smoke -m "smoke and live" -q
