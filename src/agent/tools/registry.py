from collections.abc import Callable
from functools import partial

from src.events.catalog import EventCatalog
from src.integrations.ticketmaster.client import TicketmasterClient

SEARCH_EVENTS_TOOL = "search_events"
GET_EVENT_DETAILS_TOOL = "get_event_details"


_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": SEARCH_EVENTS_TOOL,
        "description": "Znajduje wydarzenia w pobliżu skonfigurowanej lokalizacji.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Liczba dni do przodu od bieżącego czasu.",
                }
            },
            "required": ["days_ahead"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": GET_EVENT_DETAILS_TOOL,
        "description": "Pobiera szczegółowe informacje o konkretnym wydarzeniu.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string"
                }
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def get_tool_definitions() -> list[dict]:
    """Return the OpenAI tool definitions exposed by the agent."""
    return _TOOL_DEFINITIONS


def create_tool_handlers(
    ticketmaster_client: TicketmasterClient,
    event_catalog: EventCatalog | None = None,
    city: str | None = None,
) -> dict[str, Callable[..., object]]:
    """Bind tool names to configured discovery and Ticketmaster detail handlers."""
    search_events = ticketmaster_client.search_events
    if event_catalog is not None:
        if city is None:
            raise ValueError("An event catalog requires a configured city")
        search_events = partial(event_catalog.search_events, city)
    return {
        SEARCH_EVENTS_TOOL: search_events,
        GET_EVENT_DETAILS_TOOL: ticketmaster_client.get_event_details,
    }


def execute_tool(
    tool_handlers: dict[str, Callable[..., object]],
    tool_name: str,
    arguments: dict,
) -> object:
    """Execute a registered tool with the supplied keyword arguments."""
    try:
        tool_function = tool_handlers[tool_name]
    except KeyError as error:
        raise ValueError(f"Unknown tool: {tool_name}") from error

    return tool_function(**arguments)
