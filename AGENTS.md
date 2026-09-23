# Engineering Instructions

## Purpose

This repository is a small Python 3.13 portfolio project for scheduled event
discovery and delivery. Ticketmaster and MOSiR Tychy feed one normalized
catalog; the OpenAI agent selects grounded events, while deterministic code
owns identity, price enrichment, Telegram formatting, delivery, and history.

Read [Architecture](docs/architecture.md) for system behavior and
[Engineering Rules](docs/engineering-rules.md) for the canonical invariants.
[Operations](docs/OPERATIONS.md) contains the deployment runbook.

## Repository Map

- `src/agent/runner.py`: OpenAI Responses API orchestration, tool loop, grounding, and
  recommendation validation.
- `src/agent/tools/registry.py`: OpenAI tool schemas and dispatch.
- `src/integrations/ticketmaster/client.py`: Ticketmaster Discovery API client.
- `src/integrations/ticketmaster/price_scraper.py`: Camoufox browser lifecycle and
  visible Ticketmaster price extraction.
- `src/integrations/ticketmaster/enrichment.py`: deterministic post-selection price
  enrichment and its failure isolation.
- `src/integrations/telegram/formatter.py`: deterministic Telegram HTML.
- `src/integrations/telegram/notifier.py`: Telegram transport.
- `src/persistence/history.py`: validated, atomic seen-ID persistence.
- `src/observability/logging.py`: root ECS JSON stdout logging, stable service
  metadata, and optional direct OTLP log-export lifecycle.
- `src/config.py`: the only Python application module that reads environment
  variables; deployment wrappers may read their documented infrastructure
  variables.
- `src/app/daily.py`: application entrypoint and delivery-before-persistence sequencing.
- `src/events/models.py`: shared provider-neutral event dataclasses.
- `scripts/runtime/run_hf_production.sh`: Hugging Face Tailscale bootstrap and
  headed production process startup.
- `scripts/system/run_system_tests.sh`: black-box System Test driver.
- `scripts/system_integration/run_hf_smoke.sh`: source-free pytest live smoke
  runner; `scripts/system_integration/run_hf_smoke_qase.sh` enables Qase.
- `python -m scripts.admin.sync_qase_cases`: manual Qase catalog administration.

Do not move responsibilities across these boundaries without a concrete need.

## Validation Commands

Run these before handing off a change:

```bash
pytest -q
pip check
git diff --check
```

Component tests must run without application secrets and must not make real
network calls, including OpenAI, Ticketmaster, Telegram, or browser calls.

## Engineering Contracts

The detailed behavioral, security, testing, and persistence contracts are
canonical in [Engineering Rules](docs/engineering-rules.md). Preserve them when
changing code; in particular, keep agent orchestration separate from
deterministic enrichment, protect provider-owned pricing, and preserve
delivery-before-persistence ordering.

## Browser Rules

Camoufox is the only browser backend. Follow the lifecycle, readiness, proxy,
and failure-isolation rules in [Engineering Rules](docs/engineering-rules.md);
do not introduce another browser/provider abstraction without an explicit
requirement.

## Security and Runtime State

Follow the canonical secret, environment, telemetry, and runtime-state rules in
[Engineering Rules](docs/engineering-rules.md). Never expose credentials in
logs, exceptions, model-visible output, Git, or Docker images.

## Change Discipline

- Preserve public behavior unless a task explicitly changes it.
- Prefer simple, explicit code over speculative abstractions.
- Add helper layers only when they materially improve readability or are reused.
- Do not introduce frameworks, provider interfaces, plugins, or dependencies for
  hypothetical future needs.
- Prefer observable-behavior tests over implementation-detail tests.
- Preserve coverage for grounding, deduplication, model-visible price isolation,
  admission authority, scraper reuse/page cleanup, failure isolation, delivery
  ordering, persistence, and credential sanitization.
- Keep changes focused; do not modify unrelated modules.
- Inspect only files relevant to the task and their direct dependencies; avoid
  repository-wide scans unless necessary.
- Do not commit changes unless explicitly requested.
- Add type hints and concise docstrings to public APIs. Comments should explain
  why, not restate the code.

## Deployment Rules

- Keep the default container command usable without Tailscale.
- Hugging Face runs `/app/scripts/runtime/run_hf_production.sh`, which owns Tailscale userspace
  networking and then runs the application through Xvfb while retaining wrapper
  lifecycle cleanup.
- Keep the SOCKS5 listener bound to `127.0.0.1`; never expose the Raspberry Pi
  or 3proxy to the public internet.

## Handoff Output

After completing a task, report only:

1. changed files
2. what changed
3. tests and validation executed with results
4. unresolved issues

Keep explanations concise.
