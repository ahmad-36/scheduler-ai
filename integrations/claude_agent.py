"""
LLM agent using OpenAI-compatible API.
Works with Groq (free cloud), Ollama (local), or any OpenAI-compatible endpoint.
"""
import json
import datetime
from typing import Callable, Optional

from openai import OpenAI
from dateutil import tz

from core.config import TZ, LLM_BASE_URL, LLM_MODEL

SYSTEM_PROMPT = """You are an intelligent personal scheduling and planning assistant. You help the user manage their calendar, plan their week, research real-world information (transit, places, hours), and make smart time decisions.

You have tools to:
- Search the web (transit times, business hours, local info, weather, events)
- Read and create Google Calendar events
- Remember and retrieve user profile, preferences, and patterns
- Get the current date/time

## How you work

**Memory first**: At the start of a new planning conversation, call get_user_memory to recall what you know about the user. Whenever you learn something new (home location, work hours, commute route, preferences, recurring commitments, goals), immediately save it with update_user_memory. Never make the user repeat themselves.

**Think before acting**: For scheduling requests, first check the calendar for conflicts, consider the user's known patterns, and reason through travel time or preparation time needed before recommending a slot.

**Search for real info**: Don't guess at transit times, journey durations, or local facts. Use search_web to find accurate current info.

**Be direct and actionable**: Give concrete recommendations with specific times. Use markdown formatting — bullet lists and bold text for clarity. Keep responses focused.

**Proactive**: If you notice a tight schedule, missing buffer time, or a potential issue, mention it.

**Calendar confirmations**: Before creating an event, state clearly what you're about to create (title, time, date). Only create it after the user confirms, unless they explicitly say "just do it" or "go ahead and schedule it."

Today's date and time will come from get_current_datetime when needed."""

# OpenAI-format tools
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Get the current date and time in the user's timezone. Call this whenever you need to resolve relative times like 'tomorrow', 'next Monday', 'this afternoon'.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the web for current real-world information. Use for: public transport journey times, train/bus schedules, business hours, venue locations, local events, anything factual needed for scheduling.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Specific search query, e.g. 'Glasgow Central to Edinburgh Waverley train 9am Monday'",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "List the user's upcoming Google Calendar events. Use this to check for conflicts before scheduling, or to give an overview of upcoming commitments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days ahead to fetch (1–30, default 7)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a new event on the user's Google Calendar. Only call this after the user has confirmed the details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title"},
                    "start_datetime": {"type": "string", "description": "ISO 8601 datetime with timezone offset, e.g. 2025-03-22T14:00:00+01:00"},
                    "end_datetime": {"type": "string", "description": "ISO 8601 end datetime with timezone offset"},
                    "description": {"type": "string", "description": "Notes or description (optional)"},
                    "location": {"type": "string", "description": "Location or address (optional)"},
                },
                "required": ["summary", "start_datetime", "end_datetime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_memory",
            "description": "Retrieve everything stored in the user's memory profile: their location, work schedule, commute patterns, preferences, recurring commitments, and goals. Call this at the start of planning sessions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_user_memory",
            "description": "Save or update information about the user to remember for future conversations. Call this proactively whenever you learn something useful. Examples of good keys: home_location, work_location, work_hours, commute_route, wake_time, preferences, goals, recurring_commitments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Short descriptive key like 'home_location' or 'work_hours'"},
                    "value": {"type": "string", "description": "The information to remember. Be descriptive and complete."},
                },
                "required": ["key", "value"],
            },
        },
    },
]


class SchedulerAgent:
    def __init__(
        self,
        api_key: str,
        tz_name: str,
        memory_getter: Callable[[str], Optional[str]],
        memory_setter: Callable[[str, str], None],
        calendar_service=None,
        search_fn: Optional[Callable] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or LLM_BASE_URL or "https://api.groq.com/openai/v1",
        )
        self.model = model or LLM_MODEL or "llama-3.3-70b-versatile"
        self.tz_name = tz_name or TZ
        self.memory_getter = memory_getter
        self.memory_setter = memory_setter
        self.calendar_service = calendar_service
        self.search_fn = search_fn
        self.calendar_updated = False

    def _handle_tool(self, name: str, inp: dict) -> str:
        try:
            if name == "get_current_datetime":
                local_tz = tz.gettz(self.tz_name)
                now = datetime.datetime.now(tz=local_tz)
                return json.dumps({
                    "iso": now.isoformat(),
                    "human": now.strftime("%A, %d %B %Y %H:%M"),
                    "timezone": self.tz_name,
                    "weekday": now.strftime("%A"),
                    "date": now.strftime("%Y-%m-%d"),
                    "time": now.strftime("%H:%M"),
                })

            elif name == "search_web":
                if not self.search_fn:
                    return json.dumps({"error": "Web search not available. Set TAVILY_API_KEY."})
                return json.dumps(self.search_fn(inp["query"]))

            elif name == "list_calendar_events":
                if not self.calendar_service:
                    return json.dumps({"error": "Google Calendar not connected."})
                from integrations.google_calendar import list_events
                days = max(1, min(inp.get("days_ahead", 7), 30))
                events = list_events(self.calendar_service, days_ahead=days)
                return json.dumps({"events": events, "count": len(events)})

            elif name == "create_calendar_event":
                if not self.calendar_service:
                    return json.dumps({"error": "Google Calendar not connected."})
                from integrations.google_calendar import create_event
                create_event(
                    self.calendar_service,
                    summary=inp["summary"],
                    start_iso=inp["start_datetime"],
                    end_iso=inp["end_datetime"],
                    description=inp.get("description", ""),
                    location=inp.get("location", ""),
                )
                self.calendar_updated = True
                return json.dumps({"success": True, "created": inp["summary"]})

            elif name == "get_user_memory":
                all_memory = {}
                index_raw = self.memory_getter("memory:_index")
                known_keys = ["profile", "home_location", "work_location", "work_hours",
                              "commute_route", "wake_time", "sleep_time", "preferences",
                              "goals", "recurring_commitments", "exercise_routine",
                              "dietary_restrictions", "patterns", "notes"]
                if index_raw:
                    try:
                        known_keys = list(set(known_keys + json.loads(index_raw)))
                    except Exception:
                        pass
                for k in known_keys:
                    val = self.memory_getter(f"memory:{k}")
                    if val:
                        all_memory[k] = val
                return json.dumps(all_memory or {"note": "No memory stored yet — fresh start."})

            elif name == "update_user_memory":
                key = inp["key"].strip().lower().replace(" ", "_")
                value = inp["value"]
                self.memory_setter(f"memory:{key}", value)
                index_raw = self.memory_getter("memory:_index")
                try:
                    index = json.loads(index_raw) if index_raw else []
                except Exception:
                    index = []
                if key not in index:
                    index.append(key)
                    self.memory_setter("memory:_index", json.dumps(index))
                return json.dumps({"saved": key})

            return json.dumps({"error": f"Unknown tool: {name}"})

        except Exception as e:
            return json.dumps({"error": str(e)})

    def chat(self, history: list[dict], user_message: str) -> tuple[str, list[dict], bool]:
        """
        One conversation turn with agentic tool loop.
        Returns (reply_text, updated_history, calendar_was_updated).
        history: list of prior messages in OpenAI chat format (plain dicts).
        """
        self.calendar_updated = False

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + list(history) + [
            {"role": "user", "content": user_message}
        ]

        while True:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                max_tokens=4096,
            )

            msg = response.choices[0].message
            finish = response.choices[0].finish_reason

            # Serialise assistant message to plain dict for session storage
            msg_dict: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                msg_dict["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]

            messages.append(msg_dict)

            if finish == "tool_calls" and msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        inp = json.loads(tc.function.arguments)
                    except Exception:
                        inp = {}
                    result = self._handle_tool(tc.function.name, inp)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

            elif finish == "stop":
                reply = msg.content or ""
                # Strip the system message from stored history
                stored = [m for m in messages if m.get("role") != "system"]
                return reply, stored, self.calendar_updated

            else:
                break

        return "Something went wrong. Please try again.", [], self.calendar_updated
