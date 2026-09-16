# Event Agent

`event-agent` is a scheduled Python 3.13 application that discovers local
Ticketmaster events, lets an OpenAI tool-calling agent select interesting
recommendations grounded by Ticketmaster event ID, enriches only the final
choices with visible ticket prices through Camoufox, and delivers a
deterministically formatted report through Telegram.

The project demonstrates a deliberate AI trust boundary: the LLM selects and
explains events, while event grounding, ticket pricing, message formatting, and
persistence remain deterministic.

## Engineering Highlights

- OpenAI Responses API tool loop with continuation calls
- Strict structured recommendation output
- Tool-grounded event IDs
- Same-run and cross-run deduplication
- Price-free event data in model-visible search results
- Deterministic post-selection price enrichment
- Provider-authoritative `Admission` data
- Deterministic Telegram HTML with escaped recommendation text
- Per-event browser failure isolation
- ECS-compatible JSON application logs on stdout
- Offline automated tests that require no application secrets

## Architecture Flow

```text
Ticketmaster Discovery API
    -> grounded candidate events
    -> OpenAI selects recommendations
    -> Camoufox enriches final Ticketmaster recommendations
       (HF only: SOCKS5 -> Tailscale -> Raspberry Pi exit node)
    -> deterministic Telegram formatting
    -> Telegram delivery
    -> persist recommended IDs after successful delivery
```

The scheduled entry point loads prior history, runs the agent, enriches only
the selected recommendations, sends one report, and saves all final
recommendation IDs only after that delivery succeeds.

## Correctness Guarantees

- Permanent agent instructions prohibit inventing, inferring, estimating,
  mentioning, or reproducing ticket prices.
- Successful search tool output sent to OpenAI contains no `Admission` or price
  fields; only deterministic code populates final `Recommendation.admission`.
- Missing pricing means unknown; it never means free admission.
- A successful scrape replaces prior provider `Admission` data.
- A failed or unavailable scrape preserves existing `Admission` data.
- Only event IDs grounded by successful tool calls may be recommended.
- Price-scraping failure does not fail the daily run.
- History is updated only after Telegram delivery succeeds.

Provider Admission is retained in deterministic state, omitted from
model-visible search results, and injected into recommendations only after model
selection. Model-authored display strings never become pricing authority.

See [Engineering Rules](docs/engineering-rules.md) for the complete normative
contract.

## Quick Start

Create a Python 3.13 virtual environment and install the runtime plus test
dependencies:

```bash
python3.13 -m venv .event-agent-venv
source .event-agent-venv/bin/activate
pip install -r requirements.txt
pip install pytest
python -m camoufox fetch
```

Create local configuration, replace the placeholder values, and run the suite:

```bash
cp .env.example .env
pytest -q
python src/daily.py
```

Camoufox intentionally runs with `headless=False`. Headed execution on Linux
requires a display; on a headless host, run it through Xvfb, for example:

```bash
xvfb-run -a python src/daily.py
```

## Configuration

Python application configuration is read through `src/config.py`. The Hugging
Face runtime wrapper separately reads its documented Tailscale variables.

| Variable | Kind | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Secret | OpenAI API credential |
| `TICKETMASTER_API_KEY` | Secret | Ticketmaster Discovery API credential |
| `TELEGRAM_BOT_TOKEN` | Secret | Telegram bot credential |
| `TELEGRAM_CHAT_ID` | Sensitive | Telegram delivery destination |
| `MODEL` | Configuration | OpenAI model used by the agent |
| `ELASTIC_OTLP_ENDPOINT` | Optional configuration | Elastic Managed OTLP base endpoint; direct export is enabled only with `ELASTIC_API_KEY` |
| `ELASTIC_API_KEY` | Optional secret | Elastic API key; direct export is enabled only with `ELASTIC_OTLP_ENDPOINT` |
| `EVENT_BASE_LOCATION_NAME` | Configuration | Human-readable search base |
| `EVENT_BASE_GEOPOINT` | Configuration | Ticketmaster geohash for the search base |
| `EVENT_SEARCH_RADIUS_KM` | Configuration | Positive search radius in kilometers |
| `SCRAPER_PROXY_URL` | Optional configuration | Camoufox proxy URL; unset for direct local access and normally set by the HF wrapper |
| `TAILSCALE_AUTHKEY` | Secret | Authenticates the ephemeral HF Job with the tailnet; read only by `scripts/run_hf.sh` |
| `TAILSCALE_EXIT_NODE` | Configuration | Tailscale IP or name of the Raspberry Pi exit node; read only by `scripts/run_hf.sh` |

The [.env.example](.env.example) template contains placeholders only. Real values
belong in an ignored `.env` file or the runtime secret store.

## Testing Strategy

Unit tests do not call real OpenAI, Ticketmaster, Telegram, or browser services.
External API and live-browser validation are separate, explicit activities.

| Area | Main behavior covered |
| --- | --- |
| Agent | Responses API continuation, tool errors, grounding, deduplication, model-visible price isolation, admission authority |
| Ticketmaster | Request construction, response mapping, credential-safe failures |
| Price scraper | Polish/English UI, consent, direct and post-click prices, blocked/failure paths, lifecycle reuse |
| Enrichment | Final-only scraping, admission preservation, malformed URLs, failure continuation |
| Daily flow | Agent → enrichment → formatter → Telegram → persistence ordering |
| Telegram/history | Deterministic HTML, safe delivery failures, validation, atomic persistence |

Run the complete offline suite with:

```bash
pytest -q
```

## Logging

Python application logs are emitted to stdout as one ECS-compatible JSON object
per record. Every record includes `service.name=event-agent` and
`service.environment=production`. When both `ELASTIC_OTLP_ENDPOINT` and
`ELASTIC_API_KEY` are configured, the same Python log records are additionally
batch-exported directly to Elastic Managed OTLP over HTTP. The application
appends `/v1/logs` to the normalized base endpoint. With neither value, logging
remains stdout-only; partial configuration emits a credential-free warning and
does not enable export.

`ELASTIC_OTLP_ENDPOINT` is non-secret configuration, while `ELASTIC_API_KEY` is
a secret. This integration exports logs only. An OpenTelemetry Collector,
auto-instrumentation, metrics, and traces are intentionally not enabled.

## Intentional Limitations

- Ticketmaster is currently the only event provider.
- Browser extraction depends on Ticketmaster's rendered UI.
- Camoufox currently waits five seconds after navigation for Ticketmaster to
  render. This explicit temporary wait may later be replaced by a proven
  condition-based wait.
- Camoufox is the only browser backend; there are no speculative multi-provider
  or multi-browser abstractions.

## Docker and Deployment Status

GitHub Actions runs tests and publishes the Docker image to GHCR; Hugging Face
Jobs is the intended scheduler, with `/app/data` mounted as persistent storage.

The image contains the Camoufox payload, its Linux runtime dependencies,
Tailscale, Xvfb, and tini. Its default command remains a direct local run through
Xvfb. On Hugging Face, `/app/scripts/run_hf.sh` joins the tailnet in userspace
mode and exposes `socks5://127.0.0.1:1055` to Camoufox through
`SCRAPER_PROXY_URL`. Ticketmaster then sees the Raspberry Pi/home-network egress
IP. See the [operations runbook](docs/OPERATIONS.md) for the exact command and
security requirements.

## Project Structure

```text
.
├── .github/workflows/build-image.yml
├── data/                         # runtime history mount; only .gitkeep is tracked
├── docs/
│   ├── architecture.md
│   ├── engineering-rules.md
│   └── OPERATIONS.md
├── scripts/
│   └── run_hf.sh              # Hugging Face Tailscale bootstrap
├── src/
│   ├── agent.py                 # LLM orchestration and grounding
│   ├── config.py                # environment configuration
│   ├── daily.py                 # scheduled composition root
│   ├── history.py               # seen-event persistence
│   ├── logging_config.py        # ECS JSON logging configuration
│   ├── models.py                # shared dataclasses
│   ├── telegram_formatter.py    # deterministic Telegram HTML
│   ├── telegram_notifier.py     # Telegram transport
│   ├── ticketmaster_enrichment.py
│   └── tools/
│       ├── registry.py          # tool schemas and dispatch
│       ├── ticketmaster.py      # Discovery API client
│       └── ticketmaster_price_scraper.py
├── tests/
├── .env.example
├── AGENTS.md
├── Dockerfile
└── requirements.txt
```

## Documentation

- [Architecture](docs/architecture.md)
- [Engineering Rules](docs/engineering-rules.md)
- [Operations](docs/OPERATIONS.md)
- [Coding-agent instructions](AGENTS.md)
