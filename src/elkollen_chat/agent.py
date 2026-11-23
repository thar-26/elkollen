"""The assistant loop: model <-> MCP tools, for one signed-in user.

* The model sees only the MCP server's tool list. Every number it can know comes from a
  tool call made over MCP with a short-lived token for *this* user, so per-user tools
  can only ever return this user's data.
* At most MAX_ROUNDS tool rounds per question.
* The final answer is checked by grounding.check(); unverified numbers are returned
  for the UI to flag.
* The trace (which tool, which arguments, what came back) is returned with the answer
  so the chat panel can show its working.
"""

import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import anyio
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

import elkollen_auth
from elkollen_chat import grounding
from elkollen_chat.llm import ChatModel

MAX_ROUNDS = 4
MAX_TOOL_TEXT = 12_000  # characters of one tool result passed back to the model

SYSTEM_PROMPT = """\
You are Elkollen, an assistant for Swedish electricity spot prices.
Rules:
- Use only numbers returned by the tools. Never estimate, remember or invent a price,
  cost or saving. If a tool returns no data, say that the data is not available.
- Call tools to answer; for questions about the user's own consumption or bill use
  cost_of_my_usage or compare_plans (they already know who the user is).
- Prices are in öre/kWh, costs in SEK. Say that spot prices exclude VAT, energy tax,
  supplier markup and grid fees when you talk about what someone pays.
- Give times in Swedish local time (use the start_local fields), as HH:MM.
- Write dates as day and month name (for example "24 november"). Do not write the
  year unless the user asks for it.
- Round as written: 176.99 is "177", not "176".
- Answer in {language}, briefly: two to five sentences.
Now: {now} (Europe/Stockholm). The user's price area: {area}."""

LANGUAGES = {"sv": "Swedish", "en": "English"}


def tool_schema(tools) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


@asynccontextmanager
async def mcp_session(
    user_id: str,
    secret: str,
    url: str | None = None,
    http_client_factory: Callable[[dict], httpx2.AsyncClient] | None = None,
) -> AsyncIterator[ClientSession]:
    """An initialized MCP session that acts as `user_id` (token minted for 5 minutes)."""
    url = url or os.environ.get("ELKOLLEN_MCP_URL", "http://127.0.0.1:8001/mcp")
    token = elkollen_auth.mint(user_id, elkollen_auth.AUDIENCE_MCP, secret, ttl_seconds=300)
    headers = {"Authorization": f"Bearer {token}"}
    client = (
        http_client_factory(headers)
        if http_client_factory
        else httpx2.AsyncClient(headers=headers, timeout=30)
    )
    async with (
        client as http,
        streamable_http_client(url, http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        yield session


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


async def answer(
    question: str,
    history: list[dict],
    *,
    model: ChatModel,
    session: ClientSession,
    locale: str = "sv",
    price_area: str | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(ZoneInfo("Europe/Stockholm"))
    tools = tool_schema((await session.list_tools()).tools)
    system = SYSTEM_PROMPT.format(
        language=LANGUAGES.get(locale, "Swedish"),
        now=now.strftime("%Y-%m-%d %H:%M, %A"),
        area=price_area or "unknown",
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    messages += [{"role": h["role"], "content": h["content"]} for h in history[-10:]]
    messages.append({"role": "user", "content": question})

    trace: list[dict] = []
    for _ in range(MAX_ROUNDS):
        turn = await anyio.to_thread.run_sync(model.complete, messages, tools)
        if not turn.tool_calls:
            text = (turn.content or "").strip()
            evidence = [t["result"] for t in trace if t["ok"]] + [t["arguments"] for t in trace]
            return {
                "answer": text,
                "tool_calls": trace,
                "grounding": grounding.check(text, evidence, question),
                "model": model.name,
            }
        messages.append(
            {
                "role": "assistant",
                "content": turn.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                    }
                    for c in turn.tool_calls
                ],
            }
        )
        for call in turn.tool_calls:
            result = await session.call_tool(call.name, call.arguments)
            text = result.content[0].text if result.content else ""
            trace.append(
                {
                    "tool": call.name,
                    "arguments": call.arguments,
                    "ok": not result.is_error,
                    "result": _parse(text),
                }
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": text[:MAX_TOOL_TEXT]}
            )

    return {
        "answer": "",
        "tool_calls": trace,
        "grounding": {"numbers_checked": 0, "ungrounded": [], "unverified_dates": [], "ok": True},
        "model": model.name,
        "error": "the assistant needed too many steps; try a more specific question",
    }
