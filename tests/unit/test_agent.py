import json

import pytest

import src.agent as agent
from src.models import Admission, Recommendation
from tests.support.agent_support import _BASE_RECOMMENDATION


def test_parse_recommendations_returns_recommendation_model():
    payload = _BASE_RECOMMENDATION | {
        "event_id": "event-1",
        "category": "culture",
        "date": "2026-09-10",
        "time": "19:00",
        "venue": "Town Hall",
        "reason": "A local concert.",
        "url": "https://example.test/concert",
    }

    recommendations = agent._parse_recommendations(
        json.dumps({"recommendations": [payload]}),
        {"event-1": None},
    )

    assert isinstance(recommendations[0], Recommendation)
    assert recommendations[0].name == "Concert"
    assert recommendations[0].category == "culture"
    assert recommendations[0].date == "2026-09-10"


@pytest.mark.parametrize(
    "admission",
    [Admission(False, 40, 60, "PLN"), None],
)
def test_parse_recommendations_uses_source_admission(admission):
    recommendations = agent._parse_recommendations(
        json.dumps(
            {
                "recommendations": [
                    _BASE_RECOMMENDATION | {"event_id": "event-1"}
                ]
            }
        ),
        {"event-1": admission},
    )

    assert recommendations[0].admission == admission


def test_parse_recommendations_rejects_more_than_seven():
    recommendation = _BASE_RECOMMENDATION | {"event_id": "event-1"}

    with pytest.raises(ValueError, match="more than 7"):
        agent._parse_recommendations(
            json.dumps({"recommendations": [recommendation] * 8}),
            {"event-1": None},
        )
