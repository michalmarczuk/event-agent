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
except ImportError:  # pragma: no cover - supports script execution
    from config import load_settings
    from history import filter_unseen_events
    from tools.registry import create_tool_handlers, execute_tool, get_tool_definitions
    from tools.ticketmaster import TicketmasterClient


AGENT_INSTRUCTIONS = """
You are an event discovery agent.

Your job is to find interesting events for the user.

Use available tools when you need real event data.
Never invent events.
Prefer upcoming events.
When comparing multiple events, select the most interesting ones
and briefly explain why.
"""

logger = logging.getLogger(__name__)


@dataclass
class AgentRunResult:
    text: str
    discovered_event_ids: set[str]


def _get_function_calls(response):
    return [
        item for item in response.output
        if item.type == "function_call"
    ]


def _parse_tool_arguments(tool_call):
    return json.loads(tool_call.arguments)


def _serialize_tool_result(result):
    if isinstance(result, list):
        return [
            asdict(item) if is_dataclass(item) else item
            for item in result
        ]
    if is_dataclass(result):
        return asdict(result)
    return result


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
):
    arguments = _parse_tool_arguments(tool_call)
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
            "search_events city=%s returned=%d unseen=%d",
            arguments["city"],
            returned_count,
            len(result),
        )
        discovered_event_ids.update(event.id for event in result)

    return _serialize_tool_result(result)


def _continue_conversation(
    client,
    model,
    response,
    outputs,
    tool_definitions,
):
    return client.responses.create(
        model=model,
        instructions=AGENT_INSTRUCTIONS,
        previous_response_id=response.id,
        input=outputs,
        tools=tool_definitions,
    )


def run_agent(
    user_input: str,
    seen_event_ids: set[str] | None = None,
) -> AgentRunResult:
    """Run the agent conversation and return its text and new event IDs."""
    settings = load_settings()
    ticketmaster_client = TicketmasterClient(settings.ticketmaster_api_key)
    tool_handlers = create_tool_handlers(ticketmaster_client)
    tool_definitions = get_tool_definitions()
    client = OpenAI(api_key=settings.openai_api_key)
    seen_event_ids = set(seen_event_ids or set())
    discovered_event_ids = set()

    response = client.responses.create(
        model=settings.model,
        instructions=AGENT_INSTRUCTIONS,
        input=user_input,
        tools=tool_definitions,
    )

    while tool_calls := _get_function_calls(response):
        outputs = []
        for tool_call in tool_calls:
            result = _execute_tool_call(
                tool_handlers,
                tool_call,
                seen_event_ids,
                discovered_event_ids,
            )
            outputs.append(_build_function_call_output(tool_call, result))

        response = _continue_conversation(
            client,
            settings.model,
            response,
            outputs,
            tool_definitions,
        )

    return AgentRunResult(
        text=response.output_text,
        discovered_event_ids=discovered_event_ids,
    )


if __name__ == "__main__":
    result = run_agent(
        "Co ciekawego w Tychach, Katowicach i Gliwicach przez najbliższe 30 dni?"
    )
    print(result.text)
