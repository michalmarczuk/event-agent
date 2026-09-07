from collections.abc import Callable

from .ticketmaster import TicketmasterClient


_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "search_events",
        "description": "Znajduje wydarzenia w podanym mieście.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Miasto, np. Tychy",
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "Liczba dni do przodu od bieżącego czasu.",
                }
            },
            "required": ["city", "days_ahead"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_event_details",
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
    return _TOOL_DEFINITIONS


def create_tool_handlers(
    ticketmaster_client: TicketmasterClient,
) -> dict[str, Callable[..., object]]:
    return {
        "search_events": ticketmaster_client.search_events,
        "get_event_details": ticketmaster_client.get_event_details,
    }


def execute_tool(
    tool_handlers: dict[str, Callable[..., object]],
    tool_name: str,
    arguments: dict,
):
    try:
        tool_function = tool_handlers[tool_name]
    except KeyError as error:
        raise ValueError(f"Unknown tool: {tool_name}") from error

    return tool_function(**arguments)
