"""Opt-in ingestion check for Elastic Managed OTLP/HTTP."""

import os
import time

import pytest
import requests
from dotenv import load_dotenv
from qase.pytest import qase


def _logs_endpoint(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/v1/logs"):
        return base
    return f"{base}/v1/logs"


@qase.id(27)
@pytest.mark.smoke
@pytest.mark.live
def test_elastic_accepts_otlp_log() -> None:
    """Send one minimal structured log without exposing exporter credentials."""
    load_dotenv()
    endpoint = os.getenv("ELASTIC_OTLP_ENDPOINT")
    api_key = os.getenv("ELASTIC_API_KEY")
    if not endpoint or not api_key:
        pytest.skip("ELASTIC_OTLP_ENDPOINT and ELASTIC_API_KEY are not configured")

    payload = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "event-agent"},
                        },
                        {
                            "key": "deployment.environment.name",
                            "value": {"stringValue": "smoke"},
                        },
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": "event-agent-smoke"},
                        "logRecords": [
                            {
                                "timeUnixNano": str(time.time_ns()),
                                "severityNumber": 9,
                                "severityText": "INFO",
                                "body": {
                                    "stringValue": "event-agent Elastic smoke test"
                                },
                                "attributes": [
                                    {
                                        "key": "event.action",
                                        "value": {
                                            "stringValue": "elastic_smoke_test"
                                        },
                                    },
                                    {
                                        "key": "event.outcome",
                                        "value": {"stringValue": "success"},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    try:
        response = requests.post(
            _logs_endpoint(endpoint),
            headers={
                "Authorization": f"ApiKey {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException as error:
        raise AssertionError(
            f"Elastic OTLP smoke failed ({type(error).__name__})"
        ) from None

    if not 200 <= response.status_code < 300:
        raise AssertionError(
            f"Elastic OTLP smoke failed (HTTP {response.status_code})"
        )
