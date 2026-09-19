import json

import requests
import yaml

from scripts import sync_qase_cases as qase


_TEST_CASES_YAML = """\
suites:
  - name: Event Discovery
    cases:
      - title: Canceled Ticketmaster events are excluded
        description: Canceled Ticketmaster events are excluded before recommendations.
        preconditions: The response includes dates.status.code=canceled.
        priority: high
        automated: true
        steps:
          - action: Execute event search with a canceled Ticketmaster event.
            expected: Ticketmaster response is processed successfully.
"""


def _response(result, status_code=200):
    response = requests.Response()
    response.status_code = status_code
    response.url = qase.API_BASE_URL
    response._content = json.dumps(result).encode()
    return response


def _text_response(text, status_code):
    response = requests.Response()
    response.status_code = status_code
    response.url = qase.API_BASE_URL
    response._content = text.encode()
    return response


def _list_response(entities, total=None):
    count = len(entities) if total is None else total
    return _response(
        {
            "status": True,
            "result": {
                "total": count,
                "filtered": count,
                "entities": entities,
            },
        }
    )


class FakeSession:
    def __init__(self, handler):
        self.handler = handler
        self.headers = {}
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def request(self, method, url, **kwargs):
        path = url.removeprefix(qase.API_BASE_URL)
        self.calls.append((method, path, kwargs))
        return self.handler(method, path, kwargs)


def _suites():
    return yaml.safe_load(_TEST_CASES_YAML)["suites"]


def _use_test_catalog(monkeypatch, tmp_path):
    cases_file = tmp_path / "qase_cases.yaml"
    cases_file.write_text(_TEST_CASES_YAML, encoding="utf-8")
    monkeypatch.setattr(qase, "CASES_FILE", cases_file)
