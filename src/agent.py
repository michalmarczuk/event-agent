import json
import logging
from dataclasses import asdict, dataclass, is_dataclass

from openai import OpenAI

try:
    from .config import load_settings
    from .history import filter_unseen_events
    from .tools.registry import (
        create_tool_handlers,
        execute_tool,
        get_tool_definitions,
    )
    from .tools.ticketmaster import TicketmasterClient
    from .models import Event, Recommendation
except ImportError:  # pragma: no cover - supports script execution
    from config import load_settings
    from history import filter_unseen_events
    from tools.registry import create_tool_handlers, execute_tool, get_tool_definitions
    from tools.ticketmaster import TicketmasterClient
    from models import Event, Recommendation


AGENT_INSTRUCTIONS = """
You are an event discovery agent.

Your job is to find interesting events for the user.

Use available tools when you need real event data.
Never invent events.
Prefer upcoming events.
The search_events tool searches for events around the user's configured home location.

Prefer:
- live music and concerts
- local cultural events
- unusual, distinctive, or niche events
- festivals
- interesting city or community events
- events worth travelling a short distance for

Avoid recommending:
- sports
- generic mass events unless they are genuinely distinctive
- repetitive versions of very similar events

When comparing multiple events, select the most interesting ones
Prioritize uniqueness and local interest.
Prefer variety in the final recommendations.
Briefly explain why each selected event may be interesting.
Return only the requested JSON structure. Do not return HTML or Markdown.
"""

logger = logging.getLogger(__name__)

RECOMMENDATION_CATEGORIES = (
    "music",
    "culture",
    "live_performance",
    "art",
    "local",
    "unusual",
)

RESPONSE_FORMAT = {
    "format": {
        "type": "json_schema",
        "name": "event_recommendations",
        "schema": {
            "type": "object",
            "properties": {
                "recommendations": {
                    "type": "array",
                    "maxItems": 7,
                    "items": {
                        "type": "object",
                        "properties": {
                            "event_id": {"type": "string"},
                            "name": {"type": "string"},
                            "category": {
                                "type": "string",
                                "enum": list(RECOMMENDATION_CATEGORIES),
                            },
                            "date": {"type": ["string", "null"]},
                            "time": {"type": ["string", "null"]},
                            "city": {"type": ["string", "null"]},
                            "venue": {"type": ["string", "null"]},
                            "reason": {"type": "string"},
                            "url": {"type": ["string", "null"]},
                        },
                        "required": [
                            "event_id",
                            "name",
                            "category",
                            "date",
                            "time",
                            "city",
                            "venue",
                            "reason",
                            "url",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["recommendations"],
            "additionalProperties": False,
        },
        "strict": True,
    }
}


@dataclass
class AgentRunResult:
    recommendations: list[Recommendation]
    recommended_event_ids: set[str]


def _get_function_calls(response):
    return [
        item for item in response.output
        if item.type == "function_call"
    ]


def _serialize_tool_result(result):
    if isinstance(result, list):
        return [
            asdict(item) if is_dataclass(item) else item
            for item in result
        ]
    if is_dataclass(result):
        return asdict(result)
    return result


def _parse_recommendations(
    output_text: str,
    discovered_event_ids: set[str],
    discovered_events: dict[str, Event] | None = None,
) -> list[Recommendation]:
    discovered_events = discovered_events or {}
    payload = json.loads(output_text)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("recommendations"), list
    ):
        raise ValueError("Agent response must contain a recommendations list")

    recommendations = payload["recommendations"]
    if len(recommendations) > 7:
        raise ValueError("The agent returned more than 7 recommendations")

    parsed = []
    for recommendation in recommendations:
        if recommendation.get("event_id") not in discovered_event_ids:
            raise ValueError("Agent response contains an unknown event ID")
        if recommendation.get("category") not in RECOMMENDATION_CATEGORIES:
            raise ValueError("Agent response contains an unsupported category")
        source_event = discovered_events.get(recommendation["event_id"])
        source_admission = source_event.admission if source_event else None
        parsed.append(
            Recommendation(
                **(recommendation | {"admission": source_admission})
            )
        )
    return parsed


def _build_function_call_output(tool_call, result):
    return {
        "type": "function_call_output",
        "call_id": tool_call.call_id,
        "output": json.dumps(result),
    }


def _execute_tool_call(
    tool_handlers,
    tool_call,
    seen_event_ids,
    discovered_event_ids,
    discovered_events,
):
    arguments = json.loads(tool_call.arguments)
    try:
        result = execute_tool(tool_handlers, tool_call.name, arguments)
    except Exception as exception:
        logger.warning("Tool execution failed tool=%s", tool_call.name)
        return {
            "error": True,
            "message": str(exception),
        }

    if tool_call.name == "search_events" and isinstance(result, list):
        returned_count = len(result)
        result = filter_unseen_events(
            result,
            seen_event_ids | discovered_event_ids,
        )
        logger.info(
            "search_events returned=%d unseen=%d",
            returned_count,
            len(result),
        )
        discovered_event_ids.update(event.id for event in result)
        discovered_events.update({event.id: event for event in result})
    elif tool_call.name == "get_event_details":
        discovered_event_ids.add(arguments["event_id"])

    return _serialize_tool_result(result)


def run_agent(
    user_input: str,
    seen_event_ids: set[str] | None = None,
) -> AgentRunResult:
    """Run the agent conversation and return recommendations and their event IDs."""
    settings = load_settings()
    ticketmaster_client = TicketmasterClient(
        settings.ticketmaster_api_key,
        settings.search_location,
    )
    tool_handlers = create_tool_handlers(ticketmaster_client)
    tool_definitions = get_tool_definitions()
    client = OpenAI(api_key=settings.openai_api_key)
    seen_event_ids = set(seen_event_ids or ())
    discovered_event_ids = set()
    discovered_events = {}

    response = client.responses.create(
        model=settings.model,
        instructions=AGENT_INSTRUCTIONS,
        input=user_input,
        tools=tool_definitions,
        text=RESPONSE_FORMAT,
    )

    while tool_calls := _get_function_calls(response):
        outputs = []
        for tool_call in tool_calls:
            result = _execute_tool_call(
                tool_handlers,
                tool_call,
                seen_event_ids,
                discovered_event_ids,
                discovered_events,
            )
            outputs.append(_build_function_call_output(tool_call, result))

        response = client.responses.create(
            model=settings.model,
            instructions=AGENT_INSTRUCTIONS,
            previous_response_id=response.id,
            input=outputs,
            tools=tool_definitions,
            text=RESPONSE_FORMAT,
        )

    recommendations = _parse_recommendations(
        response.output_text,
        discovered_event_ids,
        discovered_events,
    )
    return AgentRunResult(
        recommendations=recommendations,
        recommended_event_ids={recommendation.event_id for recommendation in recommendations},
    )


if __name__ == "__main__":
    result = run_agent(
        "Co ciekawego w Tychach, Katowicach i Gliwicach przez najbliższe 30 dni?"
    )
    print(json.dumps([asdict(recommendation) for recommendation in result.recommendations]))
