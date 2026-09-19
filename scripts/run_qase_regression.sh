#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${QASE_API_TOKEN:-}" ]]; then
  echo "QASE_API_TOKEN is required for Qase regression reporting." >&2
  exit 2
fi

run_title="Event Agent - Offline Regression"
if short_commit="$(git rev-parse --short HEAD 2>/dev/null)" && [[ -n "${short_commit}" ]]; then
  run_title="${run_title} - ${short_commit}"
fi

export QASE_MODE="testops"
export QASE_TESTOPS_API_TOKEN="${QASE_API_TOKEN}"
export QASE_TESTOPS_PROJECT="EA"
export QASE_TESTOPS_RUN_TITLE="${run_title}"
export QASE_TESTOPS_RUN_COMPLETE="true"
export QASE_TESTOPS_RUN_TAGS="offline,regression"
export QASE_TESTOPS_SHOW_PUBLIC_REPORT_LINK="false"

exec pytest -m "qase and not smoke" -q
