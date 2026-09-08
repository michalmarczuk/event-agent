# Engineering Instructions

## Project

This repository contains a Python 3.13 event discovery agent. It uses the OpenAI Responses API, Ticketmaster tools, and Telegram delivery. The application runs on a schedule through Hugging Face Jobs. GitHub Actions builds the Docker image and publishes it to GHCR.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/OPERATIONS.md](docs/OPERATIONS.md) for detailed documentation.

## Architecture

- `src/agent.py`: LLM orchestration and runtime dependency wiring; it does not implement Ticketmaster or define tools.
- `src/tools/registry.py`: OpenAI tool definitions and dispatch.
- `src/tools/ticketmaster.py`: Ticketmaster integration.
- `src/config.py`: Environment configuration and validation.
- `src/history.py`: Seen-event persistence.
- `src/telegram_notifier.py`: Telegram delivery.
- `src/daily.py`: Application entry point.

Do not move responsibilities across these boundaries without a clear reason.

## Coding Rules

- Target Python 3.13.
- Add type hints to public functions.
- Add concise docstrings to public APIs.
- Comments should explain why, not obvious code.
- Prefer small functions and avoid unnecessary abstractions or frameworks.
- Read environment variables only through `src/config.py`.
- Never hardcode secrets.

## Testing Rules

- Use `pytest`.
- Unit tests must not call OpenAI, Ticketmaster, or Telegram.
- Tests must run without application secrets.
- Preserve regression coverage for seen-event filtering.
- Run the full test suite after changes.

## Change Discipline

- Preserve public behavior unless explicitly requested otherwise.
- Prefer small, focused refactors.
- Do not modify unrelated files.
- Avoid new dependencies unless justified.

## Runtime Rules

- Docker images must remain secret-free.
- Persistent history is stored in `/app/data` through the Hugging Face Storage Bucket.
- GitHub Actions is for CI and image builds, not production scheduling.
