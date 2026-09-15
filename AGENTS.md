# Engineering Instructions

## Purpose

This repository is a small Python 3.13 portfolio project for scheduled event
discovery and delivery. The OpenAI agent selects grounded Ticketmaster events;
deterministic code owns price enrichment, Telegram formatting, delivery, and
history persistence.

Read [Architecture](docs/architecture.md) for system behavior and
[Engineering Rules](docs/engineering-rules.md) for the canonical invariants.
[Operations](docs/OPERATIONS.md) contains the deployment runbook.

## Repository Map

- `src/agent.py`: OpenAI Responses API orchestration, tool loop, grounding, and
  recommendation validation.
- `src/tools/registry.py`: OpenAI tool schemas and dispatch.
- `src/tools/ticketmaster.py`: Ticketmaster Discovery API client.
- `src/tools/ticketmaster_price_scraper.py`: Camoufox browser lifecycle and
  visible Ticketmaster price extraction.
- `src/ticketmaster_enrichment.py`: deterministic post-selection price
  enrichment and its failure isolation.
- `src/telegram_formatter.py`: deterministic Telegram HTML.
- `src/telegram_notifier.py`: Telegram transport.
- `src/history.py`: validated, atomic seen-ID persistence.
- `src/config.py`: the only Python application module that reads environment
  variables; deployment wrappers may read their documented infrastructure
  variables.
- `src/daily.py`: composition root and delivery-before-persistence sequencing.
- `src/models.py`: shared domain dataclasses.
- `scripts/run_hf.sh`: Hugging Face-only Tailscale bootstrap and headed process
  startup.

Do not move responsibilities across these boundaries without a concrete need.

## Validation Commands

Run these before handing off a change:

```bash
pytest -q
pip check
git diff --check
```

Unit tests must run without application secrets or real OpenAI, Ticketmaster,
Telegram, or browser calls.

## Non-negotiable Invariants

- The LLM must never invent, infer, or reproduce ticket prices.
- Price enrichment is deterministic and occurs only after recommendations are
  selected.
- Browser scraping runs only for final recommendations.
- Missing price data means unknown, never free admission.
- Successful scraped provider data replaces prior `Admission`; failed or
  unavailable scraping preserves it.
- Retain provider Admission internally, but omit Admission and price fields from
  successful model-visible search results.
- Event IDs must be grounded by successful tool calls.
- Persist only recommended event IDs, and only after successful Telegram
  delivery.
- A price-scraping failure must not fail the daily run.
- Keep agent orchestration separate from deterministic enrichment.

## Browser Rules

- Camoufox is the single browser backend. Do not add a browser-provider layer or
  multi-browser abstraction without an actual requirement.
- Reuse one Camoufox browser and context for a recommendation batch.
- Create one page per recommendation and close it after that scrape.
- Preserve the explicit five-second post-navigation render wait until a proven
  condition-based replacement is implemented.
- Keep proxy support to the optional `SCRAPER_PROXY_URL` passed directly to
  Camoufox. Do not add proxy credentials, provider layers, custom anti-bot, or
  CAPTCHA-handling logic without an explicit task.

## Security and Runtime State

- Read Python application environment variables only through `src/config.py`;
  the HF wrapper may read only its documented Tailscale variables.
- Treat `TAILSCALE_AUTHKEY` as a secret. Never print, commit, bake into an image,
  or pass it as a plain Hugging Face `--env` value.
- Never expose credentials in logs, exceptions, or model-visible tool output.
- Keep `.env` and runtime `data/seen_events.json` out of Git and Docker build
  context.
- Keep Docker images secret-free.

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
- Add type hints and concise docstrings to public APIs. Comments should explain
  why, not restate the code.

## Deployment Rules

- Keep the default container command usable without Tailscale.
- Hugging Face runs `/app/scripts/run_hf.sh`, which owns Tailscale userspace
  networking and then execs the application through Xvfb.
- Keep the SOCKS5 listener bound to `127.0.0.1`; never expose the Raspberry Pi
  or 3proxy to the public internet.
