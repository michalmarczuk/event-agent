import json
import os
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from openai import OpenAI

from dataclasses import asdict, is_dataclass

try:
    from .models import Event, EventDetails
except ImportError:  # pragma: no cover - supports script execution
    from models import Event, EventDetails


load_dotenv()

client = OpenAI()

AGENT_INSTRUCTIONS = """
You are an event discovery agent.

Your job is to find interesting events for the user.

Use available tools when you need real event data.
Never invent events.
Prefer upcoming events.
When comparing multiple events, select the most interesting ones
and briefly explain why.
"""


def search_events(city: str, days_ahead: int):
    print(f"TOOL: szukam prawdziwych wydarzeń w: {city}")

    url = "https://app.ticketmaster.com/discovery/v2/events.json"

    start_datetime = datetime.now(timezone.utc)
    end_datetime = start_datetime + timedelta(days=days_ahead)

    params = {
        "apikey": os.getenv("TICKETMASTER_API_KEY"),
        "city": city,
        "countryCode": "PL",
        "size": 10,
        "sort": "date,asc",
        "startDateTime": start_datetime.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "endDateTime": end_datetime.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()

    data = response.json()

    events = data.get("_embedded", {}).get("events", [])

    return [
        Event(
            id=event["id"],
            name=event["name"],
            date=event.get("dates", {}).get("start", {}).get("localDate"),
            city=city,
            venue=None,
            url=event.get("url"),
            source="ticketmaster",
        )
        for event in events
    ]


def get_event_details(event_id: str) -> EventDetails:
    print(f"TOOL: pobieram szczegóły wydarzenia: {event_id}")

    url = f"https://app.ticketmaster.com/discovery/v2/events/{event_id}.json"

    response = requests.get(
        url,
        params={"apikey": os.getenv("TICKETMASTER_API_KEY")},
        timeout=10,
    )
    response.raise_for_status()

    event = response.json()

    venues = event.get("_embedded", {}).get("venues", [])
    venue = venues[0] if venues else {}

    return EventDetails(
        name=event.get("name"),
        date=event.get("dates", {}).get("start", {}).get("localDate"),
        time=event.get("dates", {}).get("start", {}).get("localTime"),
        venue=venue.get("name"),
        city=venue.get("city", {}).get("name"),
        url=event.get("url"),
    )

available_tools = {
    "search_events": search_events,
    "get_event_details": get_event_details,
}


def execute_tool(tool_name: str, arguments: dict):
    tool_function = available_tools[tool_name]
    return tool_function(**arguments)


tools = [
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
}
]

def run_agent(user_input: str) -> str:
    response = client.responses.create(
        model=os.getenv("MODEL"),
        instructions=AGENT_INSTRUCTIONS,
        input=user_input,
        tools=tools,
    )

    while True:
        tool_calls = [
            item for item in response.output
            if item.type == "function_call"
        ]

        if not tool_calls:
            return response.output_text

        outputs = []

        for tool_call in tool_calls:
            arguments = json.loads(tool_call.arguments)
            try:
                result = execute_tool(tool_call.name, arguments)
            except Exception as exception:
                result = {
                    "error": True,
                    "message": str(exception),
                }
            else:
                if isinstance(result, list):
                    result = [
                        asdict(item) if is_dataclass(item) else item
                        for item in result
                    ]
                elif is_dataclass(result):
                    result = asdict(result)

            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call.call_id,
                    "output": json.dumps(result),
                }
            )

        response = client.responses.create(
            model=os.getenv("MODEL"),
            instructions=AGENT_INSTRUCTIONS,
            previous_response_id=response.id,
            input=outputs,
            tools=tools,
        )


if __name__ == "__main__":
    result = run_agent(
        "Co ciekawego w Tychach, Katowicach i Gliwicach przez najbliższe 30 dni?"
    )
    print(result)
