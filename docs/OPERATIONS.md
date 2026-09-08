# Operations

## Local Development

Use Python 3.13 and a virtual environment:

```bash
python3.13 -m venv .event-agent-venv
source .event-agent-venv/bin/activate
pip install -r requirements.txt pytest
```

Create `.env` locally with the required variables. Do not commit it:

```text
OPENAI_API_KEY=
TICKETMASTER_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
MODEL=
```

Run tests and the daily application:

```bash
python -m pytest -q
python src/daily.py
```

## Required Environment Variables

`src/config.py` validates these variables at runtime:

- `OPENAI_API_KEY`: OpenAI API credential.
- `TICKETMASTER_API_KEY`: Ticketmaster API credential.
- `TELEGRAM_BOT_TOKEN`: Telegram bot credential.
- `TELEGRAM_CHAT_ID`: Telegram destination.
- `MODEL`: OpenAI model name.

Use secret values only through the local `.env` file or the deployment environment. Never place real values in documentation, source code, Dockerfiles, or image layers.

## Docker

Build the image locally:

```bash
docker build -t event-agent:local .
```

Run it with runtime secrets and persistent history:

```bash
docker run --rm \
  --env-file .env \
  -v "$PWD/data:/app/data" \
  event-agent:local
```

The Docker image contains application code and dependencies, but no secrets. Credentials are injected at runtime with `--env-file` or the hosting platform's secret mechanism.

Mount `/app/data` to persistent storage. Without that mount, `seen_events.json` is lost when the container is removed and events may be delivered again on a later run.

## GitHub Actions and GHCR

The build workflow runs on pushes to `main` and on manual dispatch. It installs dependencies, runs pytest, builds the Docker image, and pushes it to:

```text
ghcr.io/michalmarczuk/event-agent
```

Published tags are:

```text
latest
sha-<commit-sha>
```

GitHub Actions uses `GITHUB_TOKEN` for GHCR authentication. Application secrets are not needed to build or test the image.

## Hugging Face Jobs

Hugging Face Jobs is the production runtime and scheduler. A manual run uses the GHCR image, the `cpu-basic` flavor, runtime secrets, the model environment variable, and the persistent bucket mount:

```bash
hf jobs run \
  --flavor cpu-basic \
  --env MODEL=YOUR_MODEL_NAME \
  -s OPENAI_API_KEY \
  -s TICKETMASTER_API_KEY \
  -s TELEGRAM_BOT_TOKEN \
  -s TELEGRAM_CHAT_ID \
  --volume hf://buckets/mmarczuk/event-agent-data:/app/data \
  ghcr.io/michalmarczuk/event-agent:latest \
  python src/daily.py
```

The `-s` values refer to secrets configured in the Hugging Face account. Do not put secret values directly in shell history or commands.

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
  -s OPENAI_API_KEY \
  -s TICKETMASTER_API_KEY \
  -s TELEGRAM_BOT_TOKEN \
  -s TELEGRAM_CHAT_ID \
  --volume hf://buckets/mmarczuk/event-agent-data:/app/data \
  ghcr.io/michalmarczuk/event-agent:latest \
  python src/daily.py
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

Each run loads the JSON list of seen event IDs. New IDs are merged with the existing set and saved atomically only after Telegram delivery succeeds. A failed Telegram delivery leaves history unchanged so the events can be retried.

## Troubleshooting

### Missing GitHub secrets

The build workflow does not need application secrets. Verify `OPENAI_API_KEY`, `TICKETMASTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` are configured in the Hugging Face runtime instead. `MODEL` must also be supplied as an environment variable.

### GitHub Actions schedule unreliability

GitHub Actions is CI and image publishing, not the production scheduler. Use Hugging Face Scheduled Jobs for production execution. Check Actions logs only for test or image-build failures.

### Wrong local Python environment

A test run may use the system Python instead of the project virtual environment and report `No module named openai`. Activate `.event-agent-venv` and run:

```bash
source .event-agent-venv/bin/activate
python -m pytest -q
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
hf jobs scheduled run event-agent
```

Use the scheduled-job name returned by `hf jobs scheduled list` if it differs.

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

Push changes to `main` or manually dispatch the build workflow. It runs tests, builds the image, and publishes both tags:

```text
ghcr.io/michalmarczuk/event-agent:latest
ghcr.io/michalmarczuk/event-agent:sha-<commit-sha>
```

Update the Hugging Face Job to the desired tag, normally `latest` for the current production image or a SHA tag for a reproducible deployment.

## Deployment Responsibility

- GitHub Actions: CI tests and Docker image builds.
- GHCR: Docker image registry.
- Hugging Face Jobs: production runtime and scheduler.
- Hugging Face Storage Bucket: persistent event history.
