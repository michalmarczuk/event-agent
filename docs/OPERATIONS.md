# Operations

## Local Development

Use Python 3.13 and a virtual environment:

```bash
python3.13 -m venv .event-agent-venv
source .event-agent-venv/bin/activate
pip install -r requirements-test.txt
```

The default offline pytest suite needs neither application secrets nor a
downloaded browser:

```bash
pytest -q
```

Run only the offline tests linked to the Qase catalog without publishing:

```bash
pytest -m "qase and not smoke" -q
```

Publish the 23 linked offline regression cases manually outside CI with:

```bash
scripts/run_qase_regression.sh
```

The runner requires `QASE_API_TOKEN` in the environment and maps it to the
reporter's credential variable without printing it. Qase reporting remains off
for normal pytest commands. The four linked live smoke cases are separate and
are never selected by this offline reporting command.

On pushes to `main` and manual CI dispatches, the `qase-regression` job invokes
the same wrapper automatically after the primary test gate passes.

Offline regression and live smoke results are published as separate Qase runs.
The case synchronizer manages catalog definitions only; it does not publish
pytest execution results.

Generate the same latest-only Allure report locally after installing the
official Allure CLI:

```bash
pytest -q --alluredir=allure-results --clean-alluredir
allure generate allure-results --clean -o allure-report
```

The unified CI workflow runs the full offline suite once for its quality gate
and latest-only GitHub Pages report. A separate job reruns only the 23 linked
offline cases for Qase reporting. It does not retain Allure history or run the
opt-in live smoke tests.

For a live daily run, install the Camoufox browser payload and create local
configuration from the sanitized template:

```bash
python -m camoufox fetch
cp .env.example .env
# Replace required application placeholders; Tailscale is optional locally.
python src/daily.py
```

Camoufox currently runs with `headless=False`. On headless Linux, provide a
virtual display:

```bash
xvfb-run -a python src/daily.py
```

## Environment Variables

`src/config.py` validates these variables at runtime:

- `OPENAI_API_KEY`: OpenAI API credential.
- `TICKETMASTER_API_KEY`: Ticketmaster API credential.
- `TELEGRAM_BOT_TOKEN`: Telegram bot credential.
- `TELEGRAM_CHAT_ID`: Telegram destination.
- `MODEL`: OpenAI model name.
- `ELASTIC_OTLP_ENDPOINT`: Optional, non-secret Elastic Managed OTLP base
  endpoint. Direct log export is enabled only when `ELASTIC_API_KEY` is also
  set.
- `ELASTIC_API_KEY`: Optional secret for direct Elastic OTLP log export. Export
  is enabled only when `ELASTIC_OTLP_ENDPOINT` is also set.
- `EVENT_BASE_LOCATION_NAME`: Configured base location name, currently `Tychy`.
- `EVENT_BASE_GEOPOINT`: Precomputed Ticketmaster geohash for the base location.
- `EVENT_SEARCH_RADIUS_KM`: Positive Ticketmaster search radius in kilometers,
  currently `50`.
- `SCRAPER_PROXY_URL`: Optional Camoufox proxy server. Leave it unset for direct
  local access; `scripts/run_hf.sh` sets it internally to the local Tailscale
  SOCKS5 endpoint.

The Hugging Face wrapper reads two deployment variables directly:

- `TAILSCALE_AUTHKEY`: secret used to authenticate the ephemeral HF Job node.
- `TAILSCALE_EXIT_NODE`: non-secret Tailscale IP or name of the Raspberry Pi
  exit node, for example `100.89.86.79`.

Use secret values only through the local `.env` file or the deployment
environment. Never place real values in documentation, source code,
Dockerfiles, image layers, or command history.

## Application Logging

Python application log records are written to stdout as one ECS-compatible JSON
object per line. Records include stable `service.name=event-agent` and
`service.environment=production` metadata. When both
`ELASTIC_OTLP_ENDPOINT` and `ELASTIC_API_KEY` are present, the same Python log
records are additionally batch-exported directly over OTLP/HTTP to Elastic
Managed OTLP at the normalized base endpoint plus `/v1/logs`. With neither
value, logging remains stdout-only. Supplying only one value leaves OTLP export
disabled and produces a credential-free warning.

Treat `ELASTIC_OTLP_ENDPOINT` as non-secret configuration and
`ELASTIC_API_KEY` as a secret. For Hugging Face Jobs, pass the endpoint with
`--env ELASTIC_OTLP_ENDPOINT=...` and the API key with `-s ELASTIC_API_KEY`, or
omit both to disable export. There is no OpenTelemetry Collector or
auto-instrumentation; metrics and traces are intentionally not enabled.
Tailscale and runtime-wrapper output remains unchanged and is not formatted or
exported by the Python logging configuration.

## Docker

The Dockerfile has two final runtime targets built from the same base. Both
include the pinned Camoufox browser payload and its Linux dependencies,
Tailscale binaries, Xvfb, and tini. Neither installs a separate Playwright
Chromium browser payload; Playwright remains a Python dependency because
Camoufox uses its API.

- `production` is the default and final target. It contains application runtime
  files but does not copy `tests/` or install pytest.
- `test-runtime` additionally installs pytest and copies `tests/`, `pytest.ini`,
  and the repository scripts required by live smoke checks.

Build the image locally:

```bash
docker build -t event-agent:local .
```

Build the separate smoke-test runtime when preparing an opt-in Hugging Face
diagnostic job:

```bash
docker build --target test-runtime -t event-agent:test-runtime .
```

Its default command is `/app/scripts/run_hf_smoke.sh`. The wrapper establishes
the same Tailscale userspace SOCKS5 route as production, exports
`SCRAPER_PROXY_URL`, runs `pytest --run-smoke -m smoke -q` through Xvfb, and
then cleans up `tailscaled`. It returns pytest's exit code. The smoke job checks
Ticketmaster API connectivity, Telegram bot authentication without sending a
message, Camoufox browser connectivity, and Elastic OTLP ingestion. It does not
run the daily agent pipeline or modify event history.

GitHub Actions publishes `production` to `ghcr.io/michalmarczuk/event-agent`
and `test-runtime` separately to
`ghcr.io/michalmarczuk/event-agent-tests`. Use the test package for the
Hugging Face diagnostic job; it does not replace the production tags.

Run the four live smoke checks on Hugging Face without Qase reporting:

```bash
hf jobs run \
  --name event-agent-live-smoke \
  --flavor cpu-basic \
  --env TAILSCALE_EXIT_NODE="$TAILSCALE_EXIT_NODE" \
  --env ELASTIC_OTLP_ENDPOINT="$ELASTIC_OTLP_ENDPOINT" \
  -s TAILSCALE_AUTHKEY \
  -s TICKETMASTER_API_KEY \
  -s TELEGRAM_BOT_TOKEN \
  -s ELASTIC_API_KEY \
  ghcr.io/michalmarczuk/event-agent-tests:latest \
  /app/scripts/run_hf_smoke.sh
```

Publish the same four live checks as a separate Qase run by adding the Qase
token secret and selecting the dedicated entry point:

```bash
hf jobs run \
  --name event-agent-live-smoke-qase \
  --flavor cpu-basic \
  --env TAILSCALE_EXIT_NODE="$TAILSCALE_EXIT_NODE" \
  --env ELASTIC_OTLP_ENDPOINT="$ELASTIC_OTLP_ENDPOINT" \
  -s TAILSCALE_AUTHKEY \
  -s TICKETMASTER_API_KEY \
  -s TELEGRAM_BOT_TOKEN \
  -s ELASTIC_API_KEY \
  -s QASE_API_TOKEN \
  ghcr.io/michalmarczuk/event-agent-tests:latest \
  /app/scripts/run_hf_qase_smoke.sh
```

`run_hf_smoke.sh` explicitly keeps Qase disabled. The dedicated Qase runner
selects only `qase and smoke`, maps the token without printing it, and reuses
the same Tailscale, SOCKS5, Xvfb, cleanup, and exit-code lifecycle. Supply every
listed service setting and confirm `4 passed, 0 skipped`; missing service
credentials can intentionally skip their corresponding smoke checks. Prefer
an immutable `sha-<commit-sha>` image tag for repeatable diagnostics.

Run it with runtime secrets and persistent history:

```bash
docker run --rm \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  event-agent:local
```

This direct Docker command uses the default
`xvfb-run -a python src/daily.py` command and does not require Tailscale. The
image entry point is `tini -g --`; Hugging Face overrides only the command with
`/app/scripts/run_hf.sh`, which starts its own single Xvfb wrapper after network
setup.

The Docker image contains no secrets. Credentials are injected at runtime with
`--env-file` or the hosting platform's secret mechanism.

Mount `/app/data` to persistent storage. Without that mount, `seen_events.json` is lost when the container is removed and events may be delivered again on a later run.

## GitHub Actions, Allure, and GHCR

One `CI` workflow runs on pushes to `main` and on manual dispatch, so GitHub
shows the pipeline as one workflow run with this dependency graph:

```text
tests + Allure results
├── build and publish production image (passing tests only)
├── build and publish test-runtime image (passing tests only)
├── publish 23 linked offline results to Qase (passing tests only)
└── generate Allure report -> deploy GitHub Pages (even after pytest failure)
```

The tests job uploads `allure-results` before restoring pytest's exit code. A
failed suite therefore skips both image builds, remains visible as a failed CI
run, skips Qase publication, and still allows the report and Pages deployment
to complete. The Qase job uses the existing safe regression wrapper and only
reports the 23 linked non-smoke tests. Docker, Qase, Allure-generation, or Pages
failures also leave the same CI run failed.

The two independently cleaned GHCR packages are:

```text
ghcr.io/michalmarczuk/event-agent:latest
ghcr.io/michalmarczuk/event-agent:sha-<commit-sha>
ghcr.io/michalmarczuk/event-agent-tests:latest
ghcr.io/michalmarczuk/event-agent-tests:sha-<commit-sha>
```

GitHub Actions uses `GITHUB_TOKEN` for GHCR authentication and GitHub's Pages
permissions for deployment. Application secrets are not provided to CI;
`QASE_API_TOKEN` is exposed only to the Qase regression step. The primary suite
keeps Qase reporting off, and browser doubles keep application dependencies
offline. The Qase job contacts only Qase TestOps to publish its results; live
smoke tests remain opt-in. The image build fetches and verifies the Camoufox
payload, but a successful build still does not prove live Ticketmaster
rendering or exit-node connectivity.

Configure `QASE_API_TOKEN` as a GitHub Actions repository secret. It is not
passed to either Docker build and is never included in an image.

## Hugging Face Jobs

Hugging Face Jobs is the intended production runtime and scheduler. The image's
default command runs directly through Xvfb, while an HF Job overrides that
command with `/app/scripts/run_hf.sh`. The wrapper:

1. requires `TAILSCALE_AUTHKEY` and `TAILSCALE_EXIT_NODE`;
2. starts `tailscaled` with userspace networking and a SOCKS5 listener bound to
   `127.0.0.1:1055`;
3. authenticates the ephemeral node and selects the Raspberry Pi exit node;
4. exports `SCRAPER_PROXY_URL=socks5://127.0.0.1:1055`;
5. executes the headed Camoufox application through Xvfb.

Camoufox alone receives this proxy setting, so Ticketmaster browser traffic
leaves through the Raspberry Pi and its home-network public IP. The remaining
Python HTTP clients are not redirected through the SOCKS5 endpoint.

Before invoking the CLI, export the five secret values and the non-secret
configuration values in the local shell. A manual run is:

```bash
hf jobs run \
  --name event-agent-tailscale-smoke \
  --flavor cpu-basic \
  --env MODEL="$MODEL" \
  --env EVENT_BASE_LOCATION_NAME="$EVENT_BASE_LOCATION_NAME" \
  --env EVENT_BASE_GEOPOINT="$EVENT_BASE_GEOPOINT" \
  --env EVENT_SEARCH_RADIUS_KM="$EVENT_SEARCH_RADIUS_KM" \
  --env TAILSCALE_EXIT_NODE="$TAILSCALE_EXIT_NODE" \
  -s OPENAI_API_KEY \
  -s TICKETMASTER_API_KEY \
  -s TELEGRAM_BOT_TOKEN \
  -s TELEGRAM_CHAT_ID \
  -s TAILSCALE_AUTHKEY \
  --volume hf://buckets/mmarczuk/event-agent-data:/app/data \
  ghcr.io/michalmarczuk/event-agent:latest \
  /app/scripts/run_hf.sh
```

With bare `-s NAME`, the Hugging Face CLI reads the value from the invoking
shell and submits it as an encrypted Job secret. Do not use
`--env TAILSCALE_AUTHKEY=...` or place any secret value directly in the command.
Prefer the immutable `sha-<commit-sha>` image tag after CI publishes this
change.

The Raspberry Pi needs only its outbound Tailscale connection and approved exit
node route. Do not expose the Raspberry Pi or 3proxy to the public internet;
this runtime does not require a public listener on either one.

## Hugging Face Scheduled Job

The current production cadence is:

```text
15 8 * * * UTC
```

Cron is interpreted in UTC. This runs at `09:15` Poland time during CET (winter) and `10:15` Poland time during CEST (summer). The schedule is therefore not a fixed local-clock time across daylight-saving transitions.

Typical scheduled-job commands:

```bash
# List scheduled jobs
hf jobs scheduled list

# Trigger a scheduled job manually
hf jobs scheduled trigger SCHEDULED_JOB_ID

# Delete a scheduled job
hf jobs scheduled delete SCHEDULED_JOB_ID

# Create or recreate it with the current image and runtime configuration
hf jobs scheduled run "15 8 * * *" \
  --name event-agent \
  --flavor cpu-basic \
  --env MODEL=YOUR_MODEL_NAME \
  --env EVENT_BASE_LOCATION_NAME=Tychy \
  --env EVENT_BASE_GEOPOINT=YOUR_TYCHY_GEOHASH \
  --env EVENT_SEARCH_RADIUS_KM=50 \
  --env TAILSCALE_EXIT_NODE=100.89.86.79 \
  -s OPENAI_API_KEY \
  -s TICKETMASTER_API_KEY \
  -s TELEGRAM_BOT_TOKEN \
  -s TELEGRAM_CHAT_ID \
  -s TAILSCALE_AUTHKEY \
  --volume hf://buckets/mmarczuk/event-agent-data:/app/data \
  ghcr.io/michalmarczuk/event-agent:latest \
  /app/scripts/run_hf.sh
```

If a command is unavailable, update the Hugging Face CLI before changing the deployment:

```bash
hf version
pip install --upgrade huggingface_hub
```

## Persistent History

The production bucket is `mmarczuk/event-agent-data`, mounted at:

```text
/app/data
```

The application stores:

```text
/app/data/seen_events.json
```

Each run loads the JSON list of seen event IDs. IDs from final recommendations
are merged with the existing set and saved atomically only after Telegram
delivery succeeds. A failed Telegram delivery leaves history unchanged so the
events can be retried.

## Troubleshooting

### Missing runtime secrets

The unified CI workflow does not need application secrets. Verify
`OPENAI_API_KEY`, `TICKETMASTER_API_KEY`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, and `TAILSCALE_AUTHKEY` are present in the shell invoking
the Hugging Face CLI. `MODEL` and `TAILSCALE_EXIT_NODE` must also be supplied as
non-secret environment configuration.

### Tailscale bootstrap fails

`scripts/run_hf.sh` deliberately exits before Python starts if the auth key or
exit-node setting is missing, `tailscaled` cannot start, or `tailscale up`
fails. Check that the key is reusable, ephemeral, pre-approved when required,
and authorized to use `autogroup:internet`; check that `proxy-pi` is online and
approved as an exit node. Do not print the auth key while troubleshooting.

The SOCKS5 listener must remain container-local at `127.0.0.1:1055`. Do not
open a public port on the Raspberry Pi or expose 3proxy; neither is required by
this design.

### GitHub Actions schedule unreliability

GitHub Actions is CI and image publishing, not the production scheduler. Use Hugging Face Scheduled Jobs for production execution. Check Actions logs only for test or image-build failures.

### Wrong local Python environment

A test run may use the system Python instead of the project virtual environment and report `No module named openai`. Activate `.event-agent-venv` and run:

```bash
source .event-agent-venv/bin/activate
pytest -q
```

### Absolute local paths in tests

Tests must derive paths from `Path(__file__)`, not from a developer's checkout path. Replace hard-coded local paths with project-relative resolution before relying on CI results.

### Hugging Face CLI lacks scheduled commands

Check the installed version with `hf version`. Upgrade `huggingface_hub` if `hf jobs scheduled ...` commands are missing.

### `--name` or namespace errors

Confirm the Hugging Face account and namespace are correct, and authenticate the CLI with the intended account. Inspect the exact command help for the installed CLI version:

```bash
hf jobs scheduled --help
hf jobs run --help
```

### Missing persistent volume

If `/app/data` is not mounted, history is container-local and disappears when the job ends. Recreate or update the job with:

```text
hf://buckets/mmarczuk/event-agent-data:/app/data
```

### Inspect `/app/data` from a Hugging Face job

Run a temporary diagnostic job using the same volume:

```bash
hf jobs run \
  --flavor cpu-basic \
  --volume hf://buckets/mmarczuk/event-agent-data:/app/data \
  python:3.13-slim \
  python -c 'from pathlib import Path; print(list(Path("/app/data").iterdir()))'
```

Inspect the job logs, then remove the diagnostic job if it was created as a named or persistent job.

## Recovery Procedures

### Manually trigger production

```bash
hf jobs scheduled trigger SCHEDULED_JOB_ID
```

Use the scheduled-job ID returned by `hf jobs scheduled list`.

### Inspect logs

List recent jobs and inspect the failed job through the Hugging Face CLI:

```bash
hf jobs list
hf jobs logs JOB_ID
```

Check for missing configuration, Telegram delivery failures, Ticketmaster errors, and whether `/app/data` is mounted.

### Reset history intentionally

Only do this when repeated delivery is acceptable. Back up or remove `seen_events.json` from the persistent bucket, or run a temporary job with the mounted bucket to replace it with an empty list:

```bash
python -c 'from pathlib import Path; Path("/app/data/seen_events.json").write_text("[]\n")'
```

Run that command only inside a job with the production bucket mounted.

### Rebuild and publish after code changes

Push changes to `main` or manually dispatch the CI workflow. Passing tests
build and publish both image packages:

```text
ghcr.io/michalmarczuk/event-agent:latest
ghcr.io/michalmarczuk/event-agent:sha-<commit-sha>
ghcr.io/michalmarczuk/event-agent-tests:latest
ghcr.io/michalmarczuk/event-agent-tests:sha-<commit-sha>
```

Update the Hugging Face Job to the desired tag, normally `latest` for the current production image or a SHA tag for a reproducible deployment.

## Deployment Responsibility

- GitHub Actions: offline tests, automated offline Qase reporting, latest-only
  Allure Pages publication, and Docker image builds.
- GHCR: Docker image registry.
- Hugging Face Jobs: production runtime and scheduler.
- Hugging Face Storage Bucket: persistent event history.
