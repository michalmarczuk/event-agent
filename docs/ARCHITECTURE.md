# Architecture

## System Overview

The application is a scheduled Python event discovery agent. GitHub Actions runs tests, builds the Docker image, and publishes it to GHCR. A Hugging Face scheduled Job runs that image, with secrets injected at runtime and `/app/data` backed by a Hugging Face Storage Bucket.

The container starts `src/daily.py`. The entry point loads event history, runs the agent through the OpenAI Responses API, allows the model to call Ticketmaster tools, parses structured recommendations, formats and sends the report to Telegram, then persists the updated event history.

```mermaid
flowchart LR
    G[GitHub] --> C[CI tests]
    C --> B[Docker build]
    B --> R[GHCR]
    R --> J[Hugging Face Scheduled Job]
    J --> D[daily.py]
    D --> A[run_agent]
    A --> O[OpenAI Responses API]
    O --> T[Ticketmaster tools]
    T --> F[Filter and deduplicate]
    F --> O
    O --> P[Final response]
    P --> TG[Telegram]
    TG --> H[Persist history]
    H --> S[Hugging Face Storage Bucket]
```

## High-Level Flow

```text
GitHub
  -> CI tests
  -> Docker build
  -> GHCR

Hugging Face Scheduled Job
  -> Docker container
  -> daily.py
  -> run_agent()
  -> OpenAI
  -> tool calls
  -> Ticketmaster
  -> filtering/deduplication
  -> final response
  -> Telegram
  -> persist history
```

`daily.py` saves history only after Telegram delivery succeeds. A Telegram failure therefore prevents the current run's event IDs from being marked as delivered.

## Module Responsibilities

- `src/daily.py`: Application entry point. Configures logging, loads history, runs the agent, prints the report, sends Telegram, and saves history.
- `src/agent.py`: OpenAI conversation orchestration and runtime dependency wiring. It creates service clients and runs the function-call loop, but does not implement Ticketmaster or define tool schemas.
- `src/config.py`: Loads and validates required environment variables into the frozen `Settings` dataclass.
- `src/models.py`: Defines `Event` and `EventDetails` dataclasses.
- `src/history.py`: Loads, validates, filters, and atomically saves seen event IDs in `data/seen_events.json`.
- `src/telegram_notifier.py`: Sends a message through the Telegram Bot API.
- `src/tools/registry.py`: Defines the OpenAI tool schemas, creates handlers, and dispatches tool calls.
- `src/tools/ticketmaster.py`: Implements Ticketmaster HTTP requests and maps responses to event dataclasses.

## Agent Loop

1. `run_agent()` loads `Settings`, creates a `TicketmasterClient` with the configured `SearchLocation`, creates tool handlers and definitions, and sends the initial user request to the OpenAI Responses API.
2. The response is inspected for `function_call` items.
3. Each call's JSON arguments are parsed and dispatched through the tool registry.
4. `search_events` results are filtered and serialized. Tool failures become error payloads returned to the model.
5. Results are sent back as `function_call_output` items in a follow-up Responses API request.
6. The loop repeats until the model response contains no function calls.
7. The final model response is structured JSON containing at most seven recommendations. Each recommendation includes an event ID from tool results. `run_agent()` parses it into `Recommendation` objects and returns only the recommended event IDs for persistence; discovered IDs remain internal to the run.

`daily.py` passes recommendations to `telegram_formatter.py`, which owns deterministic Telegram HTML formatting and HTML escaping. The model does not generate Telegram HTML or Markdown.

## Event Deduplication

`search_events` queries Ticketmaster around the configured base location using its `geoPoint` and radius. The base location is configuration, not an LLM tool argument.

`seen_event_ids` contains IDs loaded from previous scheduled runs. It prevents events already delivered in an earlier run from being sent again.

`discovered_event_ids` starts empty for each agent run. After each successful `search_events` call, results are filtered against:

```python
seen_event_ids | discovered_event_ids
```

This prevents duplicates both across scheduled runs and between multiple searches in the same run. Only remaining events are sent to the model, and their IDs are added to the internal `discovered_event_ids` set. The model's selected recommendation IDs are exposed as `recommended_event_ids` and are the only IDs persisted. `get_event_details` results are not filtered.

## Configuration Flow

`config.load_settings()` calls `load_dotenv()` and reads the required environment variables into `Settings`, including a `SearchLocation` with the base location name, Ticketmaster geohash, and search radius. Runtime secrets are injected by the execution environment. The agent passes the Ticketmaster API key and location configuration to `TicketmasterClient`; location configuration values are not LLM tool arguments.

No secrets are copied into or stored in the Docker image.

## Persistence

The container's `/app/data` directory is mounted from a Hugging Face Storage Bucket. `history.py` uses `data/seen_events.json` as the history file.

- Missing history starts as an empty set.
- Valid history is a JSON list of string event IDs.
- Saves write a sorted list to a temporary file and atomically replace the target.
- `daily.py` saves the union of prior and newly discovered IDs only after successful Telegram delivery.

## Testing Architecture

Unit tests mock the OpenAI client and Responses API, mock Ticketmaster HTTP requests, and isolate Telegram delivery. They do not make real external API calls and run without application secrets. Tests cover the agent loop, tool dispatch, filtering across and within runs, configuration validation, history persistence, and daily delivery ordering.

## Design Principles

- Keep modules small and responsibility-focused.
- Use dependency injection at external-service boundaries where useful.
- Keep external integrations isolated from orchestration.
- Prefer standard-library mechanisms and small functions.
- Avoid unnecessary frameworks and abstractions.
