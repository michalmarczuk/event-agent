# Testing Strategy

Event Agent uses several test levels so that fast checks of individual
components, in-process collaboration checks, production-container behavior, and
live external-service checks each have an appropriate execution environment.
The separation keeps normal CI deterministic while preserving a small set of
high-value black-box and live checks.

## Test Levels

| ISTQB level | Location | Test object and dependencies | Execution | Examples |
| --- | --- | --- | --- | --- |
| Component Testing | `tests/component/` | Individual application components and deterministic helpers; dependencies are mocked or faked. | GitHub runner and local pytest. | Ticketmaster response mapping, price parsing, Telegram formatting, history validation. |
| Component Integration Testing | `tests/component_integration/` | Collaboration between application components while external boundaries remain mocked or faked. | GitHub runner and local pytest. | Daily delivery-before-persistence ordering, enrichment with the formatter, ECS/OTLP logging lifecycle. |
| System Testing | `tests/system/` | The exact `event-agent` production image, treated as a black box. | Local Docker orchestration and GitHub Actions. | Happy path, Telegram failure, no events, seen-event filtering, canceled-event filtering, OpenAI failure, multiple candidates. |
| System Integration Testing | `tests/system_integration/` | Live connectivity to external systems through the test runtime. | Explicit Hugging Face smoke run. | Ticketmaster Discovery API, Ticketmaster reached through Camoufox, Telegram `getMe`, Elastic OTLP ingestion. |

Component and Component Integration Testing together currently contain 183
tests. System Testing contains seven black-box scenarios. System Integration
Testing contains four live smoke checks.

## Test Purpose and Execution Markers

A test level answers *what scope is being tested*. A marker describes a selected
purpose or execution characteristic; it is not a test level.

| Marker | Meaning | Current use |
| --- | --- | --- |
| `regression` | Stable local regression subset. | 23 selected Component or Component Integration tests. |
| `smoke` | Fast availability check for a critical external integration. | The four System Integration checks. |
| `live` | Calls a real external service rather than a mock or fake. | The same four System Integration checks. |

Qase is not a pytest level or marker. `@qase.id(...)` provides only
traceability from a representative pytest scenario to a Qase case.

## Execution Model

```mermaid
flowchart TB
    component["Component Testing\ntests/component"] --> runner["GitHub runner\npytest"]
    component_integration["Component Integration Testing\ntests/component_integration"] --> runner
    runner --> allure["Allure\n183 results"]

    system["System Testing\ntests/system"] --> sut["event-agent\nproduction container"]
    fake["event-agent-tests\nfake external services"] --> sut
    sut --> artifacts["Exit code · ECS logs\nrequest journal · /app/data"]
    artifacts --> assertions["event-agent-tests\nblack-box assertions"]
    assertions --> allure
    assertions --> qase_local["Local Qase report"]
    qase_local --> qase["Qase\n7 System cases"]

    system_integration["System Integration Testing\nsmoke + live"] --> hf["Hugging Face\nreal external services"]
    hf --> qase_live["Qase\n4 live cases"]
```

Component and Component Integration tests run directly on the GitHub runner.
The source-free `event-agent-tests` image contains pytest, Qase and Allure
tooling, `tests/system/`, `tests/system_integration/`, and the required test
support modules; it deliberately does not contain `/app/src`. The separate
`event-agent` image is the production system under test.

## System Testing Architecture

System Testing does not import or patch application code. The host orchestrates
two images on a private Docker network; the assertion container itself has no
network access.

```mermaid
flowchart LR
    fake["event-agent-tests\nfake external services"] --> network["Private Docker network"]
    network --> sut["event-agent\nproduction container"]
    sut --> artifacts["Artifacts\nexit code · ECS logs · journal · data"]
    artifacts --> assertions["event-agent-tests\nassertions (--network none)"]
```

The seven deterministic scenarios cover:

1. successful delivery and persistence;
2. Telegram failure without history persistence;
3. explicit no-events notification;
4. filtering an already seen event;
5. canceled-event filtering;
6. OpenAI failure without partial delivery or history; and
7. persistence of only the delivered recommendation from multiple candidates.

## Reporting and Traceability

```mermaid
flowchart TB
    ci["Component + Component Integration Tests\n183 results"] --> allure["Allure report\nGitHub Pages"]
    system["System Tests\n7 results"] --> allure
    system --> local["Local Qase JSON report"]
    local --> publish["Publish System Results to Qase\nnon-blocking"]
    publish --> qase["Qase System cases\nIDs 28–34"]
    hf["HF System Integration\n4 live smoke tests"] --> qase_live["Qase System Integration\nIDs 24–27"]
```

Allure is the technical report for every automated test executed by GitHub CI:
183 Component and Component Integration results plus seven System results, for
190 results in the final report. System Integration live smoke checks are not
run in GitHub CI and are therefore not added to that report; their execution
details remain in Hugging Face logs.

Qase is the high-level QA traceability layer. System Tests generate their local
Qase report during the same network-isolated pytest execution that creates
Allure results. The GitHub runner later imports that saved report, so Qase does
not require a second execution. Qase publication is intentionally non-blocking
and does not gate Allure or GitHub Pages deployment.

The active Qase catalog is:

- System Integration: IDs 24–27 for the four live smoke checks.
- System: IDs 28–34 for the seven black-box System scenarios.
- IDs 1–23: retained as `Deprecated` historical cases; they have no active
  pytest traceability.

## Running Tests Locally

Activate the repository virtual environment first:

```bash
source .event-agent-venv/bin/activate
```

Run a single local level or the CI-equivalent local selection:

```bash
pytest -q tests/component
pytest -q tests/component_integration
pytest -q tests/component tests/component_integration
```

Run the retained local regression subset:

```bash
pytest -m regression -q
```

Run black-box System Tests. Docker builds both local images unless the script is
configured to use pre-built images:

```bash
./scripts/run_system_tests.sh
```

Collect the live System Integration suite without calling external services:

```bash
pytest --collect-only -q tests/system_integration
```

Run the four live smoke checks only with intentional opt-in and the required
runtime configuration:

```bash
pytest --run-smoke -m "smoke and live" -q tests/system_integration
```

For the supported routed live execution, use the Hugging Face runtime commands
in [Operations](OPERATIONS.md#docker).
