"""Chat model adapter. One small interface so the provider can be swapped by config.

GroqChatModel talks to Groq's OpenAI-compatible Chat Completions API with tool calling.
The key comes from GROQ_API_KEY and is never logged or returned.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass
class AssistantTurn:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatModel(Protocol):
    name: str

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn: ...


class ChatModelError(RuntimeError):
    """The model provider failed; no answer was produced."""


class GroqChatModel:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ) -> None:
        self.name = model or os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not key:
            raise ChatModelError("GROQ_API_KEY is not set (see .env.example)")
        self._http = httpx.Client(
            headers={"Authorization": f"Bearer {key}"},
            timeout=httpx.Timeout(45.0),
            transport=transport,
        )
        self._sleep = sleep

    def complete(self, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        body = {
            "model": self.name,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_completion_tokens": 1200,
        }
        for attempt in range(3):
            response = self._http.post(GROQ_URL, json=body)
            if response.status_code in (429, 500, 502, 503) and attempt < 2:
                self._sleep(2**attempt)
                continue
            if response.status_code >= 400:
                # Never include the request (it carries the key header) in the error.
                raise ChatModelError(f"model provider returned HTTP {response.status_code}")
            break
        message = response.json()["choices"][0]["message"]
        calls = []
        for c in message.get("tool_calls") or []:
            raw = c["function"].get("arguments") or "{}"
            try:
                args = json.loads(raw)
            except ValueError:
                args = {}
            calls.append(
                ToolCall(id=c["id"], name=c["function"]["name"], arguments=args, raw_arguments=raw)
            )
        return AssistantTurn(content=message.get("content"), tool_calls=calls)
