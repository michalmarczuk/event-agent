# Engineering Rules

This document is the canonical behavioral contract for Event Agent changes.
Architecture explains the system; these rules define what implementations and
refactors must preserve.

## Price and Admission Authority

- The LLM must never invent, infer, or reproduce ticket prices.
- Price enrichment must be deterministic and happen only after recommendations
  are selected.
- Browser scraping must run only for final recommendations.
- Missing price data means unknown and must never be interpreted as free
  admission.
- Only explicit provider-authoritative data may set `Admission.is_free=True`.
- A successful scrape replaces existing provider Admission data.
- A failed or unavailable scrape preserves existing Admission data.
- `Admission` remains provider-authoritative throughout discovery,
  recommendation parsing, enrichment, formatting, and delivery.
- Post-selection price enrichment means browser enrichment. Ticketmaster API
  Admission discovered earlier remains provider-owned, is retained in
  `known_event_admissions`, and is injected deterministically after selection.
- Enrichment mutates recommendation objects in place and returns the same list.

## Browser Automation

- Camoufox is the single browser backend. Do not create multi-browser or browser
  provider abstractions without an actual requirement.
- Control Camoufox through the Playwright API.
- Reuse one Camoufox browser and one context for a recommendation batch.
- Create one page per recommendation and close it after that scrape, including
  failure paths.
- A page-level or scraper-level price failure must not fail the daily run.
- Do not add proxy, CAPTCHA, or custom anti-bot behavior without an explicit
  requirement.
- Keep the current five-second wait after navigation. It is a deliberate,
  temporary Ticketmaster render wait and should be replaced only by a proven
  condition-based wait.

## Agent and Enrichment Boundary

- Keep LLM orchestration in `src/agent.py` separate from deterministic price
  enrichment.
- Tools, not model claims, ground event IDs. Only successful tool results may
  make an ID eligible for recommendation.
- Preserve same-run deduplication and filtering of IDs persisted by prior runs.
- Treat `known_event_admissions` as the per-run source of truth for grounded IDs
  and their provider Admission values.
- Reject final recommendations whose event ID is not grounded.
- Do not expose Admission as an LLM-authored recommendation field.
- Successful model-visible search results must omit Admission and all nested
  price fields; provider Admission must remain available to deterministic code.
- Keep tool failures visible to the model as error results, but allow only
  sanitized messages to cross that boundary.

## Delivery and Persistence

- Format Telegram messages deterministically outside the LLM.
- Escape recommendation names, dates, locations, reasons, URLs, and Admission
  notes before inserting them into Telegram HTML.
- Persist only IDs from final recommendations, never every discovered ID.
- Persist those IDs only after successful Telegram delivery.
- Preserve atomic history writes and existing validation semantics.
- Telegram failure must prevent history persistence.

## Failure Isolation

- Ticketmaster price scraping failures must preserve recommendations and allow
  the remaining batch and daily run to continue.
- Failed enrichment must preserve existing Admission information.
- Provider and delivery failures may remain visible, but public error messages
  must be credential-safe.
- Do not weaken malformed-output, unsupported-category, or unknown-event-ID
  validation in the agent.

## Tests

- Prefer observable-behavior tests over implementation-detail tests.
- Unit tests must not make real OpenAI, Ticketmaster, Telegram, or browser calls.
- Tests must run without application secrets.
- Preserve behavioral coverage for:
  - grounded-ID validation and failed-tool non-grounding;
  - same-run and cross-run deduplication;
  - model-visible search results excluding Admission and price data while the
    internal provider Admission reaches the final Recommendation;
  - direct and post-click localized price extraction;
  - scraper browser/context reuse and per-page cleanup;
  - non-fatal scraping failure and Admission preservation;
  - deterministic formatting;
  - Telegram delivery before history persistence;
  - atomic history persistence;
  - credential sanitization in exceptions, logs, and tool outputs.
- Keep live browser and external API checks separate from the default pytest
  suite.

Run the standard validation commands before handoff:

```bash
pytest -q
pip check
git diff --check
```

## Secrets and Runtime State

- Read environment variables only through `src/config.py`.
- Secrets must come from environment variables and must never be hardcoded or
  committed.
- Never include API keys, bot tokens, or credential-bearing URLs in logs,
  exceptions, or model-visible tool outputs.
- When an original request exception may contain a credentialed URL, raise the
  sanitized public exception after leaving the exception handler so the
  original is absent from both `__cause__` and `__context__`.
- Keep `.env` out of Git and Docker build context.
- Treat `data/seen_events.json` as runtime state: do not track it in Git or copy
  it into Docker images.
- Keep Docker images secret-free.

## Simplicity and Change Discipline

- Prefer simple, explicit code over speculative abstractions.
- Add a helper layer only when it is reused or materially improves readability.
- Do not introduce dependency-injection frameworks, provider interfaces,
  browser-backend layers, plugins, or other extensibility mechanisms for
  hypothetical needs.
- Preserve public behavior unless a task explicitly changes it.
- Make focused changes and do not edit unrelated modules.
- Avoid new dependencies unless the current requirement justifies them.
- Add type hints and concise docstrings to public APIs. Comments should explain
  why, not repeat what the code says.

## Deployment Status

Do not claim that the current Docker image is aligned with the Camoufox-only
runtime. The Dockerfile still installs Playwright Chromium and does not execute
`python -m camoufox fetch`. Updating and validating Docker/Hugging Face support
is a separate deployment task.

See [Architecture](architecture.md), [Operations](OPERATIONS.md), and the
repository [README](../README.md) for context.
