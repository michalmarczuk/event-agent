#!/bin/sh
set -eu

export QASE_MODE=off
unset QASE_API_TOKEN QASE_TESTOPS_API_TOKEN

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
production_image=${EVENT_AGENT_SYSTEM_PRODUCTION_IMAGE:-${EVENT_AGENT_SYSTEM_IMAGE:-event-agent:system-test}}
test_image=${EVENT_AGENT_SYSTEM_TEST_IMAGE:-event-agent-tests:system-test}
run_id="event-agent-system-$$"
network_name="$run_id"
fake_container="$run_id-fake"
sut_container="$run_id-sut"
assertions_container="$run_id-assertions"
runtime_dir=$(mktemp -d /tmp/event-agent-system.XXXXXX)
artifacts_dir="$runtime_dir/artifacts"
data_dir="$runtime_dir/data"
allure_results_dir=${EVENT_AGENT_SYSTEM_ALLURE_DIR:-$project_root/allure-results/system}

mkdir -p "$artifacts_dir" "$data_dir"
chmod 0777 "$data_dir"

cleanup() {
    docker rm -f "$assertions_container" >/dev/null 2>&1 || true
    docker rm -f "$sut_container" >/dev/null 2>&1 || true
    docker rm -f "$fake_container" >/dev/null 2>&1 || true
    docker network rm "$network_name" >/dev/null 2>&1 || true
    rm -rf "$runtime_dir"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ "${EVENT_AGENT_SYSTEM_SKIP_BUILD:-}" != "1" ]; then
    echo "Building production image: $production_image"
    docker build \
        --target production \
        --tag "$production_image" \
        "$project_root"

    echo "Building test image: $test_image"
    docker build \
        --target test-runtime \
        --tag "$test_image" \
        "$project_root"
fi

docker run --rm \
    --network none \
    --entrypoint /bin/sh \
    "$test_image" \
    -c 'test ! -e /app/src && test -f /app/tests/support/fake_external_services.py && test -f /app/tests/system/test_daily_black_box.py'

docker network create --internal "$network_name" >/dev/null

echo "Starting fake services from test image: $test_image"
docker run --detach \
    --name "$fake_container" \
    --network "$network_name" \
    --network-alias fake-services \
    --entrypoint python \
    "$test_image" \
    -m tests.support.fake_external_services \
    --host 0.0.0.0 \
    --port 8080 \
    --scenario happy_path >/dev/null

attempt=0
until docker exec "$fake_container" python -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1).read()' \
    >/dev/null 2>&1; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 20 ]; then
        echo "Fake external services failed to become ready" >&2
        docker logs "$fake_container" >&2 || true
        exit 1
    fi
    sleep 1
done

echo "Starting production application from: $production_image"
set +e
docker run \
    --name "$sut_container" \
    --network "$network_name" \
    --volume "$data_dir:/app/data" \
    --env OPENAI_API_KEY=system-test-openai-key \
    --env OPENAI_BASE_URL=http://fake-services:8080/openai/v1 \
    --env TICKETMASTER_API_KEY=system-test-ticketmaster-key \
    --env TICKETMASTER_API_BASE_URL=http://fake-services:8080/ticketmaster/discovery/v2 \
    --env TELEGRAM_BOT_TOKEN=system-test-telegram-token \
    --env TELEGRAM_CHAT_ID=system-test-chat-id \
    --env TELEGRAM_API_BASE_URL=http://fake-services:8080/telegram \
    --env MODEL=fake-model \
    --env EVENT_BASE_LOCATION_NAME=Tychy \
    --env EVENT_BASE_GEOPOINT=u2y0test \
    --env EVENT_SEARCH_RADIUS_KM=50 \
    --env ELASTIC_OTLP_ENDPOINT= \
    --env ELASTIC_API_KEY= \
    --env SCRAPER_PROXY_URL= \
    "$production_image" \
    >"$artifacts_dir/stdout.log" \
    2>"$artifacts_dir/stderr.log"
sut_exit_code=$?
set -e
printf '%s\n' "$sut_exit_code" >"$artifacts_dir/exit_code.txt"
docker exec "$fake_container" python -c \
    'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/__journal", timeout=5).read().decode())' \
    >"$artifacts_dir/journal.json"

echo "Running black-box assertions from test image: $test_image"
# Keep Allure results outside runtime_dir so cleanup preserves failed-test reports.
mkdir -p "$allure_results_dir"
allure_results_dir=$(CDPATH= cd -- "$allure_results_dir" && pwd)
docker run --rm \
    --name "$assertions_container" \
    --network none \
    --volume "$artifacts_dir:/artifacts:ro" \
    --volume "$data_dir:/data:ro" \
    --volume "$allure_results_dir:/allure-results" \
    --env EVENT_AGENT_SYSTEM_ARTIFACTS_DIR=/artifacts \
    --env EVENT_AGENT_SYSTEM_DATA_DIR=/data \
    --env QASE_MODE=off \
    "$test_image" \
    pytest -q tests/system/test_daily_black_box.py \
        --alluredir=/allure-results --clean-alluredir
