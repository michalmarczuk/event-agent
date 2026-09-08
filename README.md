# Event Agent

Python AI agent for discovering local events through natural-language requests. It uses the OpenAI Responses API and tool calling to query Ticketmaster, returns event details, delivers the final report through Telegram, and runs on a schedule with Hugging Face Jobs.

## Key Capabilities

- Natural-language event search
- Multi-step OpenAI tool calling
- Event details lookup
- Cross-run and same-run event deduplication
- Persistent seen-event history
- Dockerized runtime
- Automated CI and GHCR image builds

## Architecture

```text
Hugging Face Scheduled Job
	-> Docker image from GHCR
	-> Python agent
	-> OpenAI Responses API
	-> Ticketmaster tools
	-> filtering/deduplication
	-> Telegram
	-> persistent history
```

## Tech Stack

- Python 3.13
- OpenAI Responses API
- Ticketmaster Discovery API
- Telegram Bot API
- pytest
- Docker
- GitHub Actions
- GitHub Container Registry (GHCR)
- Hugging Face Jobs
- Hugging Face Storage Buckets

## Local Setup

```bash
python3.13 -m venv .event-agent-venv
source .event-agent-venv/bin/activate
pip install -r requirements.txt pytest
touch .env  # add the required variables listed below
python -m pytest -q
python src/daily.py
```

The local `.env` must define the required variables below. Never commit secret values.

## Environment Variables

- `OPENAI_API_KEY`
- `TICKETMASTER_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `MODEL`

## Testing

The pytest suite mocks OpenAI, Ticketmaster HTTP, and Telegram interactions. Tests require no real external API calls or application secrets.

```bash
python -m pytest -q
```

## Deployment

GitHub Actions runs tests on pushes to `main`, builds the Docker image, and publishes it to GHCR:

```text
ghcr.io/michalmarczuk/event-agent:latest
ghcr.io/michalmarczuk/event-agent:sha-<commit-sha>
```

Hugging Face Jobs runs the GHCR image as the production scheduled job. Runtime secrets are injected by Hugging Face, and event history is persisted through the `mmarczuk/event-agent-data` Storage Bucket mounted at `/app/data`.

## Project Structure

```text
.
├── .github/workflows/build-image.yml
├── data/
├── docs/
│   ├── ARCHITECTURE.md
│   └── OPERATIONS.md
├── src/
│   ├── agent.py
│   ├── config.py
│   ├── daily.py
│   ├── history.py
│   ├── models.py
│   ├── telegram_notifier.py
│   └── tools/
│       ├── registry.py
│       └── ticketmaster.py
├── tests/
├── Dockerfile
├── AGENTS.md
└── requirements.txt
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Operations](docs/OPERATIONS.md)
- [Agent instructions](AGENTS.md)
