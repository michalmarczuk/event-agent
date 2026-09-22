import json
from dataclasses import asdict
from unittest.mock import patch

import pytest

import src.agent as agent
from src.config import SearchLocation, Settings
from src.models import Admission, Event, EventDetails, Recommendation
from tests.support.agent_support import (
    _BASE_RECOMMENDATION,
    TEST_SETTINGS,
    _final_response,
    _run_with_tool_results,
    _tool_response,
)


def test_run_agent_hides_prices_from_model_and_preserves_source_admission():
    admission = Admission(
        False,
        40.25,
        60.75,
        "TEST-CURRENCY",
        "provider-price-note",
    )
    event = Event(
        "ticketmaster:event-1",
        "Concert",
        None,
        "Tychy",
        None,
        "https://www.ticketmaster.pl/event/canonical",
        "ticketmaster",
        "event-1",
        admission,
    )
    first_response = _tool_response(
        "response-1",
        "search_events",
        "call-1",
        days_ahead=30,
    )

    result, create, execute_tool_mock = _run_with_tool_results(
        [first_response, _final_response("ticketmaster:event-1")],
        [[event]],
    )

    execute_tool_mock.assert_called_once()
    assert execute_tool_mock.call_args.args[1:] == (
        "search_events",
        {"days_ahead": 30, "seen_event_ids": set()},
    )
    assert create.call_count == 2
    for response_call in create.call_args_list:
        assert response_call.kwargs["instructions"] == agent.AGENT_INSTRUCTIONS
        assert response_call.kwargs["tools"] == agent.get_tool_definitions()
        assert response_call.kwargs["text"] == agent.RESPONSE_FORMAT

    continuation_call = create.call_args_list[1]
    assert continuation_call.kwargs["model"] == TEST_SETTINGS.model
    assert continuation_call.kwargs["previous_response_id"] == first_response.id
    model_visible_output = continuation_call.kwargs["input"][0]["output"]
    tool_output = json.loads(model_visible_output)
    expected_event = asdict(event)
    del expected_event["admission"]
    assert tool_output == [expected_event]
    for hidden_value in (
        "admission",
        "is_free",
        "price_min",
        "price_max",
        "currency",
        "note",
        "40.25",
        "60.75",
        "TEST-CURRENCY",
        "provider-price-note",
    ):
        assert hidden_value not in model_visible_output

    recommendation = result.recommendations[0]
    assert isinstance(recommendation, Recommendation)
    assert recommendation.event_id == "ticketmaster:event-1"
    assert recommendation.admission == admission
    assert recommendation.url == event.url


def test_run_agent_passes_configured_base_urls_to_api_clients():
    settings = Settings(
        openai_api_key="openai-test-key",
        ticketmaster_api_key="ticketmaster-test-key",
        telegram_bot_token="telegram-test-token",
        telegram_chat_id="telegram-test-chat",
        model="test-model",
        search_location=SearchLocation("Tychy", "u2y0test", 50),
        openai_base_url="http://fake-services:8080/openai/v1",
        ticketmaster_api_base_url=(
            "http://fake-services:8080/ticketmaster/discovery/v2"
        ),
    )

    with (
        patch.object(agent, "load_settings", return_value=settings),
        patch.object(agent, "TicketmasterClient") as ticketmaster_client,
        patch.object(agent, "OpenAI") as openai,
    ):
        openai.return_value.responses.create.return_value = _final_response()
        agent.run_agent("Find events")

    ticketmaster_client.assert_called_once_with(
        "ticketmaster-test-key",
        settings.search_location,
        api_base_url="http://fake-services:8080/ticketmaster/discovery/v2",
    )
    openai.assert_called_once_with(
        api_key="openai-test-key",
        base_url="http://fake-services:8080/openai/v1",
    )


def test_run_agent_returns_tool_error_to_model_and_continues():
    result, create, _ = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _final_response(),
        ],
        [RuntimeError("Ticketmaster unavailable")],
    )

    assert create.call_count == 2
    assert create.call_args_list[1].kwargs["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": json.dumps(
                {"error": True, "message": "Ticketmaster unavailable"}
            ),
        }
    ]
    assert result.recommendations == []
    assert result.recommended_event_ids == set()
    assert result.discovery_failed is True


def test_model_visible_search_caps_oversized_tool_result_after_filtering():
    tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    events = [
        Event(
            f"ticketmaster:{event_id}",
            event_id,
            None,
            None,
            None,
            None,
            "ticketmaster",
            event_id,
        )
        for event_id in ["seen", *(f"new-{index}" for index in range(12))]
    ]
    grounding = agent._GroundingStore()

    with patch.object(agent, "execute_tool", return_value=events):
        execution = agent._execute_tool_call(
            {},
            tool_call,
            seen_event_ids={"ticketmaster:seen"},
            grounding=grounding,
        )

    assert execution.success is True
    assert [event["id"] for event in execution.output] == [
        f"ticketmaster:new-{index}" for index in range(10)
    ]
    assert grounding.event_ids == {
        f"ticketmaster:new-{index}" for index in range(10)
    }


def test_run_agent_rejects_unknown_recommendation_id():
    with pytest.raises(ValueError, match="unknown event ID"):
        _run_with_tool_results([_final_response("unknown")], [])


def test_tool_execution_preserves_malformed_argument_failure_semantics():
    malformed_tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    malformed_tool_call.arguments = "{"

    with pytest.raises(json.JSONDecodeError):
        agent._execute_tool_call(
            {},
            malformed_tool_call,
            seen_event_ids=set(),
            grounding=agent._GroundingStore(),
        )


def test_tool_execution_preserves_non_event_tool_output():
    tool_call = _tool_response(
        "response-1", "other_tool", "call-1", value="test"
    ).output[0]

    execution = agent._execute_tool_call(
        {"other_tool": lambda value: {"value": value}},
        tool_call,
        seen_event_ids=set(),
        grounding=agent._GroundingStore(),
    )

    assert execution.success is True
    assert execution.output == {"value": "test"}


def test_search_tool_preserves_non_list_result_without_grounding():
    tool_call = _tool_response(
        "response-1", "search_events", "call-1", days_ahead=30
    ).output[0]
    grounding = agent._GroundingStore()

    execution = agent._execute_tool_call(
        {"search_events": lambda days_ahead, seen_event_ids: {"error": "test"}},
        tool_call,
        seen_event_ids=set(),
        grounding=grounding,
    )

    assert execution.success is True
    assert execution.output == {"error": "test"}
    assert grounding.event_ids == set()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "recommendations list"),
        (
            {"recommendations": [_BASE_RECOMMENDATION | {"event_id": "event-1", "category": "unsupported"}]},
            "unsupported category",
        ),
    ],
)
def test_parse_recommendations_rejects_invalid_model_contract(payload, message):
    grounding = agent._GroundingStore(
        {"event-1": agent._GroundedEvent("ticketmaster", "event-1", None, None)}
    )

    with pytest.raises(ValueError, match=message):
        agent._parse_recommendations(json.dumps(payload), grounding)


def test_run_agent_allows_event_returned_by_get_event_details():
    result, _, _ = _run_with_tool_results(
        [
            _tool_response(
                "response-1",
                "get_event_details",
                "call-1",
                event_id="ticketmaster:event-1",
            ),
            _final_response("ticketmaster:event-1"),
        ],
        [
            EventDetails(
                "Concert",
                None,
                None,
                None,
                "Tychy",
                "https://www.ticketmaster.pl/event/details",
            )
        ],
    )

    assert result.recommended_event_ids == {"ticketmaster:event-1"}
    assert result.recommendations[0].source == "ticketmaster"
    assert result.recommendations[0].admission is None
    assert result.recommendations[0].url == (
        "https://www.ticketmaster.pl/event/details"
    )


def test_get_event_details_routes_namespaced_id_to_ticketmaster_provider():
    tool_call = _tool_response(
        "response-1",
        "get_event_details",
        "call-1",
        event_id="ticketmaster:abc123",
    ).output[0]
    calls = []

    def get_event_details(event_id):
        calls.append(event_id)
        return EventDetails(None, None, None, None, None, None)

    grounding = agent._GroundingStore()
    execution = agent._execute_tool_call(
        {"get_event_details": get_event_details},
        tool_call,
        seen_event_ids=set(),
        grounding=grounding,
    )

    assert calls == ["abc123"]
    assert execution.success is True
    assert grounding.require("ticketmaster:abc123") == agent._GroundedEvent(
        "ticketmaster", "abc123", None, None
    )


def test_get_event_details_preserves_grounded_source_identity_and_admission():
    event_id = "ticketmaster:abc123"
    existing_admission = Admission(False, 40, 60, "PLN")
    grounding = agent._GroundingStore({
        event_id: agent._GroundedEvent(
            "ticketmaster",
            "abc123",
            "https://www.ticketmaster.pl/event/search",
            existing_admission,
        )
    })
    tool_call = _tool_response(
        "response-1", "get_event_details", "call-1", event_id=event_id
    ).output[0]

    execution = agent._execute_tool_call(
        {
            "get_event_details": lambda event_id: EventDetails(
                None,
                None,
                None,
                None,
                None,
                "https://www.ticketmaster.pl/event/details",
            )
        },
        tool_call,
        seen_event_ids=set(),
        grounding=grounding,
    )

    assert execution.success is True
    assert grounding.require(event_id) == agent._GroundedEvent(
        "ticketmaster",
        "abc123",
        "https://www.ticketmaster.pl/event/details",
        existing_admission,
    )


@pytest.mark.parametrize("event_id", ["abc123", "mosir_tychy:abc123"])
def test_get_event_details_rejects_malformed_or_unsupported_global_id(event_id):
    tool_call = _tool_response(
        "response-1",
        "get_event_details",
        "call-1",
        event_id=event_id,
    ).output[0]

    execution = agent._execute_tool_call(
        {}, tool_call, seen_event_ids=set(), grounding=agent._GroundingStore()
    )

    assert execution.success is False
    assert execution.output["error"] is True


@pytest.mark.parametrize(
    ("details_url", "expected_url"),
    [
        (
            "https://www.ticketmaster.pl/event/details",
            "https://www.ticketmaster.pl/event/details",
        ),
        (
            None,
            "https://www.ticketmaster.pl/event/search",
        ),
    ],
)
def test_run_agent_get_event_details_preserves_search_admission_and_url(
    details_url,
    expected_url,
):
    admission = Admission(False, 40, 60, "PLN")
    event = Event(
        "ticketmaster:event-1",
        "Concert",
        None,
        "Tychy",
        None,
        "https://www.ticketmaster.pl/event/search",
        "ticketmaster",
        "event-1",
        admission,
    )

    result, _, _ = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _tool_response(
                "response-2",
                "get_event_details",
                "call-2",
                event_id="ticketmaster:event-1",
            ),
            _final_response("ticketmaster:event-1"),
        ],
        [
            [event],
            EventDetails(
                "Concert",
                None,
                None,
                None,
                "Tychy",
                details_url,
            ),
        ],
    )

    assert result.recommendations[0].admission == admission
    assert result.recommendations[0].url == expected_url


def test_run_agent_failed_tool_call_does_not_ground_event_id():
    with pytest.raises(ValueError, match="unknown event ID"):
        _run_with_tool_results(
            [
                _tool_response(
                    "response-1",
                    "get_event_details",
                    "call-1",
                    event_id="ticketmaster:event-1",
                ),
                _final_response("ticketmaster:event-1"),
            ],
            [RuntimeError("Ticketmaster unavailable")],
        )


def test_run_agent_filters_seen_and_same_run_events():
    seen_event = Event(
        "ticketmaster:seen", "Already seen", None, None, None, None,
        "ticketmaster", "seen",
    )
    new_event = Event(
        "ticketmaster:new", "New event", None, None, None, None,
        "ticketmaster", "new",
    )
    latest_event = Event(
        "ticketmaster:latest", "Latest event", None, None, None, None,
        "ticketmaster", "latest",
    )

    result, create, execute_tool_mock = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _tool_response("response-2", "search_events", "call-2", days_ahead=30),
            _final_response(),
        ],
        [
            [seen_event, new_event],
            [new_event, latest_event],
        ],
        seen_event_ids={"ticketmaster:seen"},
    )

    first_output = json.loads(create.call_args_list[1].kwargs["input"][0]["output"])
    second_output = json.loads(create.call_args_list[2].kwargs["input"][0]["output"])
    expected_new_event = asdict(new_event)
    expected_latest_event = asdict(latest_event)
    del expected_new_event["admission"]
    del expected_latest_event["admission"]
    assert first_output == [expected_new_event]
    assert second_output == [expected_latest_event]
    assert execute_tool_mock.call_args_list[0].args[2]["seen_event_ids"] == {
        "ticketmaster:seen"
    }
    assert execute_tool_mock.call_args_list[1].args[2]["seen_event_ids"] == {
        "ticketmaster:seen", "ticketmaster:new"
    }
    assert result.recommendations == []
    assert result.recommended_event_ids == set()
    assert result.discovery_failed is False


def test_run_agent_returns_only_recommended_event_ids():
    events = [
        Event("ticketmaster:event-1", "First event", None, "Tychy", None, None, "ticketmaster", "event-1"),
        Event("ticketmaster:event-2", "Second event", None, "Tychy", None, None, "ticketmaster", "event-2"),
        Event("ticketmaster:event-3", "Third event", None, "Tychy", None, None, "ticketmaster", "event-3"),
    ]

    result, _, _ = _run_with_tool_results(
        [
            _tool_response("response-1", "search_events", "call-1", days_ahead=30),
            _final_response("ticketmaster:event-1", "ticketmaster:event-2"),
        ],
        [events],
    )

    assert result.recommended_event_ids == {
        "ticketmaster:event-1", "ticketmaster:event-2"
    }
    assert not hasattr(result, "discovered_event_ids")


def test_parse_recommendations_returns_recommendation_model():
    payload = _BASE_RECOMMENDATION | {
        "event_id": "ticketmaster:event-1",
        "category": "culture",
        "date": "2026-09-10",
        "time": "19:00",
        "venue": "Town Hall",
        "reason": "A local concert.",
    }

    recommendations = agent._parse_recommendations(
        json.dumps({"recommendations": [payload]}),
        agent._GroundingStore({
            "ticketmaster:event-1": agent._GroundedEvent(
                "ticketmaster",
                "event-1",
                "https://example.test/event-1",
                None,
            )
        }),
    )

    assert isinstance(recommendations[0], Recommendation)
    assert recommendations[0].name == "Concert"
    assert recommendations[0].category == "culture"
    assert recommendations[0].date == "2026-09-10"
    assert recommendations[0].source == "ticketmaster"
    assert recommendations[0].url == "https://example.test/event-1"


def test_recommendation_response_schema_excludes_provider_metadata():
    properties = agent.RESPONSE_FORMAT["format"]["schema"]["properties"]
    recommendation = properties["recommendations"]["items"]

    assert "url" not in recommendation["properties"]
    assert "url" not in recommendation["required"]
    assert "source" not in recommendation["properties"]
    assert "source" not in recommendation["required"]


def test_parse_recommendations_uses_grounded_source_over_model_value():
    recommendations = agent._parse_recommendations(
        json.dumps(
            {
                "recommendations": [
                    _BASE_RECOMMENDATION
                    | {
                        "event_id": "ticketmaster:event-1",
                        "source": "mosir_tychy",
                    }
                ]
            }
        ),
        agent._GroundingStore({
            "ticketmaster:event-1": agent._GroundedEvent(
                "ticketmaster", "event-1", None, None
            )
        }),
    )

    assert recommendations[0].source == "ticketmaster"


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
        agent._GroundingStore({
            "event-1": agent._GroundedEvent(
                "ticketmaster", "event-1", None, admission
            )
        }),
    )

    assert recommendations[0].admission == admission


def test_parse_recommendations_rejects_more_than_seven():
    recommendation = _BASE_RECOMMENDATION | {"event_id": "event-1"}

    with pytest.raises(ValueError, match="more than 7"):
        agent._parse_recommendations(
            json.dumps({"recommendations": [recommendation] * 8}),
            agent._GroundingStore({
                "event-1": agent._GroundedEvent(
                    "ticketmaster", "event-1", None, None
                )
            }),
        )
