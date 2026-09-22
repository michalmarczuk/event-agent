import json
import logging
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from openai import OpenAI

try:
    from .config import Settings, load_settings
    from .event_catalog import EventCatalog
    from .event_identity import parse_event_id
    from .history import filter_unseen_events
    from .models import Admission, Recommendation
    from .sources.mosir_tychy import MosirTychySource
    from .sources.ticketmaster import TicketmasterSource
    from .tools.registry import (
        GET_EVENT_DETAILS_TOOL,
        SEARCH_EVENTS_TOOL,
        create_tool_handlers,
        execute_tool,
        get_tool_definitions,
    )
    from .tools.ticketmaster import TicketmasterClient
except ImportError:  # pragma: no cover - supports script execution
    from config import Settings, load_settings
    from event_catalog import EventCatalog
    from event_identity import parse_event_id
    from history import filter_unseen_events
    from models import Admission, Recommendation
    from sources.mosir_tychy import MosirTychySource
    from sources.ticketmaster import TicketmasterSource
    from tools.registry import (
        GET_EVENT_DETAILS_TOOL,
        SEARCH_EVENTS_TOOL,
        create_tool_handlers,
        execute_tool,
        get_tool_definitions,
    )
    from tools.ticketmaster import TicketmasterClient


AGENT_INSTRUCTIONS = """
You are an event discovery agent.

Your job is to find interesting events for the user.

Use available tools when you need real event data.
Never invent events.
Never mention, invent, infer, estimate, or reproduce ticket prices.
Pricing is handled by deterministic code after you select recommendations.
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

_MAX_RECOMMENDATIONS = 7

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
                    "maxItems": _MAX_RECOMMENDATIONS,
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
    discovery_failed: bool


@dataclass(frozen=True)
class _GroundedEvent:
    source: str
    source_event_id: str
    url: str | None
    admission: Admission | None


@dataclass
class _GroundingStore:
    """Own provider-authoritative event data for one agent conversation.

    The model may choose a grounded event ID and write editorial fields, but
    source identity, canonical URL, and admission always come from this store.
    """

    _events: dict[str, _GroundedEvent]

    def __init__(
        self,
        events: dict[str, _GroundedEvent] | None = None,
    ) -> None:
        self._events = dict(events or {})

    @property
    def event_ids(self) -> set[str]:
        """Return IDs already made eligible during this run."""
        return set(self._events)

    def register_search_events(self, events: list[Any]) -> None:
        """Ground normalized events returned by a successful search tool call."""
        for event in events:
            self._events[event.id] = _GroundedEvent(
                source=event.source,
                source_event_id=event.source_event_id,
                url=event.url,
                admission=event.admission,
            )

    def update_details(
        self,
        event_id: str,
        source: str,
        source_event_id: str,
        details: Any,
    ) -> None:
        """Preserve known provider metadata while accepting a details URL."""
        existing = self._events.get(event_id)
        self._events[event_id] = _GroundedEvent(
            source=existing.source if existing is not None else source,
            source_event_id=(
                existing.source_event_id
                if existing is not None
                else source_event_id
            ),
            admission=existing.admission if existing is not None else None,
            url=getattr(details, "url", None)
            or (existing.url if existing is not None else None),
        )

    def require(self, event_id: str) -> _GroundedEvent:
        """Return a grounded event or reject an LLM-invented ID."""
        try:
            return self._events[event_id]
        except KeyError as error:
            raise ValueError("Agent response contains an unknown event ID") from error


@dataclass(frozen=True)
class _ToolCallArguments:
    """Provider-ready arguments plus optional global details identity."""

    provider_arguments: dict[str, Any]
    event_id: str | None = None
    source: str | None = None
    source_event_id: str | None = None


@dataclass(frozen=True)
class _ToolExecutionResult:
    """Internal outcome of one tool call before OpenAI output serialization."""

    output: object
    success: bool
    discovery_failed: bool = False


@dataclass(frozen=True)
class _AgentDependencies:
    """Configured collaborators required by one agent conversation."""

    client: OpenAI
    model: str
    tool_handlers: dict[str, Any]
    tool_definitions: list[dict]


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
    grounding: _GroundingStore,
) -> list[Recommendation]:
    """Validate LLM selections and hydrate them with provider-owned metadata."""
    payload = json.loads(output_text)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("recommendations"), list
    ):
        raise ValueError("Agent response must contain a recommendations list")

    recommendations = payload["recommendations"]
    if len(recommendations) > _MAX_RECOMMENDATIONS:
        raise ValueError(
            f"The agent returned more than {_MAX_RECOMMENDATIONS} recommendations"
        )

    parsed = []
    for recommendation in recommendations:
        event_id = recommendation.get("event_id")
        grounded_event = grounding.require(event_id)
        if recommendation.get("category") not in RECOMMENDATION_CATEGORIES:
            raise ValueError("Agent response contains an unsupported category")
        # Hydrate provider-owned fields after validation; model output is not
        # authoritative for source identity, URL, or admission.
        parsed.append(
            Recommendation(
                **(
                    recommendation
                    | {
                        "source": grounded_event.source,
                        "admission": grounded_event.admission,
                        "url": grounded_event.url,
                    }
                )
            )
        )
    return parsed


def _build_function_call_output(tool_call, result):
    return {
        "type": "function_call_output",
        "call_id": tool_call.call_id,
        "output": json.dumps(result),
    }


def _parse_tool_arguments(tool_call) -> dict[str, Any]:
    """Decode the raw LLM arguments without changing malformed-input semantics."""
    return json.loads(tool_call.arguments)


def _prepare_tool_call_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    seen_event_ids: set[str],
    grounding: _GroundingStore,
) -> _ToolCallArguments:
    """Convert model arguments into the provider-specific call contract."""
    if tool_name == SEARCH_EVENTS_TOOL:
        return _ToolCallArguments(
            provider_arguments=arguments | {
                "seen_event_ids": seen_event_ids | grounding.event_ids
            }
        )
    if tool_name != GET_EVENT_DETAILS_TOOL:
        return _ToolCallArguments(provider_arguments=arguments)

    source, source_event_id = parse_event_id(arguments["event_id"])
    if source != "ticketmaster":
        raise ValueError(f"Unsupported event source: {source}")
    return _ToolCallArguments(
        provider_arguments=arguments | {"event_id": source_event_id},
        event_id=arguments["event_id"],
        source=source,
        source_event_id=source_event_id,
    )


def _model_visible_search_events(
    result: object,
    seen_event_ids: set[str],
    grounding: _GroundingStore,
) -> object:
    """Filter, ground, and remove private Admission data from search output."""
    if not isinstance(result, list):
        return _serialize_tool_result(result)

    returned_count = len(result)
    events = filter_unseen_events(
        result,
        seen_event_ids | grounding.event_ids,
    )[:10]
    logger.info(
        "search_events returned=%d unseen=%d",
        returned_count,
        len(events),
    )
    grounding.register_search_events(events)
    model_visible_events = _serialize_tool_result(events)
    for event_data in model_visible_events:
        event_data.pop("admission", None)
    return model_visible_events


def _process_successful_tool_result(
    tool_name: str,
    prepared_arguments: _ToolCallArguments,
    result: object,
    seen_event_ids: set[str],
    grounding: _GroundingStore,
) -> object:
    """Apply deterministic post-tool behavior before returning model output."""
    if tool_name == SEARCH_EVENTS_TOOL:
        return _model_visible_search_events(result, seen_event_ids, grounding)
    if tool_name == GET_EVENT_DETAILS_TOOL:
        grounding.update_details(
            prepared_arguments.event_id,
            prepared_arguments.source,
            prepared_arguments.source_event_id,
            result,
        )
    return _serialize_tool_result(result)


def _tool_failure(tool_name: str, error: Exception) -> _ToolExecutionResult:
    """Return the credential-safe failure shape exposed to the model."""
    logger.warning("Tool execution failed tool=%s", tool_name)
    return _ToolExecutionResult(
        output={"error": True, "message": str(error)},
        success=False,
        discovery_failed=tool_name == SEARCH_EVENTS_TOOL,
    )


def _execute_tool_call(
    tool_handlers,
    tool_call,
    seen_event_ids,
    grounding: _GroundingStore,
) -> _ToolExecutionResult:
    """Execute one tool call and return its typed internal outcome."""
    arguments = _parse_tool_arguments(tool_call)
    try:
        prepared_arguments = _prepare_tool_call_arguments(
            tool_call.name,
            arguments,
            seen_event_ids,
            grounding,
        )
        result = execute_tool(
            tool_handlers,
            tool_call.name,
            prepared_arguments.provider_arguments,
        )
    except Exception as exception:
        return _tool_failure(tool_call.name, exception)

    return _ToolExecutionResult(
        output=_process_successful_tool_result(
            tool_call.name,
            prepared_arguments,
            result,
            seen_event_ids,
            grounding,
        ),
        success=True,
    )


def build_agent_dependencies(settings: Settings) -> _AgentDependencies:
    """Compose the production collaborators for one agent conversation.

    Keeping construction here makes the runtime boundary explicit while the
    conversation loop remains focused on tool calls and response handling.
    """
    ticketmaster_client = TicketmasterClient(
        settings.ticketmaster_api_key,
        settings.search_location,
        api_base_url=settings.ticketmaster_api_base_url,
    )
    event_catalog = EventCatalog(
        [
            TicketmasterSource(ticketmaster_client),
            MosirTychySource(settings.mosir_tychy_base_url),
        ]
    )
    return _AgentDependencies(
        client=OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        ),
        model=settings.model,
        tool_handlers=create_tool_handlers(
            ticketmaster_client,
            event_catalog,
            settings.search_location.name,
        ),
        tool_definitions=get_tool_definitions(),
    )


def run_agent(
    user_input: str,
    seen_event_ids: set[str] | None = None,
) -> AgentRunResult:
    """Run one function-calling conversation and return grounded recommendations.

    Tool failures remain recoverable for the model loop, while the discovery
    failure latch is preserved for the caller's delivery/persistence decision.
    """
    settings = load_settings()
    dependencies = build_agent_dependencies(settings)
    seen_event_ids = set(seen_event_ids or ())
    grounding = _GroundingStore()
    discovery_failed = False

    response = dependencies.client.responses.create(
        model=dependencies.model,
        instructions=AGENT_INSTRUCTIONS,
        input=user_input,
        tools=dependencies.tool_definitions,
        text=RESPONSE_FORMAT,
    )

    while tool_calls := _get_function_calls(response):
        outputs = []
        for tool_call in tool_calls:
            result = _execute_tool_call(
                dependencies.tool_handlers,
                tool_call,
                seen_event_ids,
                grounding,
            )
            discovery_failed = discovery_failed or result.discovery_failed
            outputs.append(
                _build_function_call_output(tool_call, result.output)
            )

        response = dependencies.client.responses.create(
            model=dependencies.model,
            instructions=AGENT_INSTRUCTIONS,
            previous_response_id=response.id,
            input=outputs,
            tools=dependencies.tool_definitions,
            text=RESPONSE_FORMAT,
        )

    recommendations = _parse_recommendations(
        response.output_text,
        grounding,
    )
    return AgentRunResult(
        recommendations=recommendations,
        recommended_event_ids={recommendation.event_id for recommendation in recommendations},
        discovery_failed=discovery_failed,
    )


if __name__ == "__main__":
    result = run_agent(
        "Co ciekawego w Tychach, Katowicach i Gliwicach przez najbliższe 30 dni?"
    )
    print(json.dumps([asdict(recommendation) for recommendation in result.recommendations]))
