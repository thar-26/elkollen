"""Security tests that go through the real MCP server: streamable HTTP app, the SDK's
bearer middleware, JSON-RPC, our tools, and a warehouse built by dbt.

The core requirement: user A can never read user B's rows through the MCP server.
"""

import json
import logging
import time

import anyio
import httpx2
import jwt
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

import elkollen_auth
from tests.conftest import DELETED_USER

SECRET = "test-secret-" + "x" * 40
BASE = "http://127.0.0.1:8001"
ANNA, ERIK = "demo-anna", "demo-erik"
WEEK = {"start_date": "2025-09-29", "end_date": "2025-10-05"}
JSONRPC_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture(scope="module")
def app(warehouse):
    """Factory: the SDK's session manager runs once per app, so each request gets one."""
    from elkollen_mcp.server import build_server

    def make():
        server = build_server(warehouse, SECRET, resource_server_url=BASE + "/mcp")
        return server.streamable_http_app(stateless_http=True, json_response=True)

    return make


def token_for(user_id: str, audience: str = elkollen_auth.AUDIENCE_MCP) -> str:
    return elkollen_auth.mint(user_id, audience, SECRET)


def call_tool(app, token: str, tool: str, arguments: dict) -> tuple[bool, dict | str]:
    """Initialize a real MCP session over HTTP and call one tool."""

    async def go():
        asgi = app()
        async with (
            asgi.router.lifespan_context(asgi),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=asgi),
                base_url=BASE,
                headers={"Authorization": f"Bearer {token}"},
            ) as http,
            streamable_http_client(BASE + "/mcp", http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            text = result.content[0].text if result.content else ""
            try:
                payload = result.structured_content or json.loads(text)
            except ValueError:
                payload = text
            return bool(result.is_error), payload

    return anyio.run(go)


def list_tools(app, token: str):
    async def go():
        asgi = app()
        async with (
            asgi.router.lifespan_context(asgi),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=asgi),
                base_url=BASE,
                headers={"Authorization": f"Bearer {token}"},
            ) as http,
            streamable_http_client(BASE + "/mcp", http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            return (await session.list_tools()).tools

    return anyio.run(go)


def raw_status(app, authorization: str | None) -> int:
    async def go():
        asgi = app()
        async with asgi.router.lifespan_context(asgi):
            headers = dict(JSONRPC_HEADERS)
            if authorization is not None:
                headers["Authorization"] = authorization
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=asgi), base_url=BASE
            ) as http:
                r = await http.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers=headers,
                )
                return r.status_code

    return anyio.run(go)


def mart_total_kwh(warehouse, user_id):
    return warehouse.fetch(
        "select sum(kwh) as kwh from marts.fct_consumption_15min "
        "where user_id = :u and delivery_date between :s and :e",
        {"u": user_id, "s": WEEK["start_date"], "e": WEEK["end_date"]},
    )[0]["kwh"]


# ------------------------------------------------------------------ authentication


def _forged(claims_override: dict, key: str = SECRET, algorithm: str = "HS256") -> str:
    now = int(time.time())
    claims = {
        "iss": elkollen_auth.ISSUER,
        "aud": elkollen_auth.AUDIENCE_MCP,
        "sub": ANNA,
        "scope": elkollen_auth.SCOPE,
        "iat": now,
        "exp": now + 300,
    }
    claims.update(claims_override)
    return jwt.encode(claims, key, algorithm=algorithm)


@pytest.mark.parametrize(
    ("label", "authorization"),
    [
        ("no token", None),
        ("garbage", "Bearer not-a-jwt"),
        ("wrong secret", "Bearer " + _forged({}, key="another-secret-" + "y" * 40)),
        (
            "expired",
            "Bearer " + _forged({"iat": int(time.time()) - 900, "exp": int(time.time()) - 600}),
        ),
        ("API audience", "Bearer " + _forged({"aud": elkollen_auth.AUDIENCE_API})),
        ("other issuer", "Bearer " + _forged({"iss": "someone-else"})),
        ("no scope", "Bearer " + _forged({"scope": ""})),
        ("lifetime too long", "Bearer " + _forged({"exp": int(time.time()) + 86400})),
        (
            "alg none",
            "Bearer " + jwt.encode({"sub": ANNA, "aud": "elkollen-mcp"}, None, algorithm="none"),
        ),
    ],
)
def test_requests_without_a_valid_token_are_refused(app, label, authorization):
    assert raw_status(app, authorization) == 401, label


def test_a_valid_token_is_accepted(app):
    assert raw_status(app, "Bearer " + token_for(ANNA)) == 200


# ------------------------------------------------------------------ tool surface


def test_exactly_five_read_only_tools_and_none_takes_a_user(app):
    tools = list_tools(app, token_for(ANNA))
    assert {t.name for t in tools} == {
        "get_prices",
        "cheapest_window",
        "cost_of_my_usage",
        "compare_plans",
        "explain_spike",
    }
    for t in tools:
        assert t.annotations.read_only_hint is True
        params = set(t.input_schema.get("properties", {}))
        assert not any("user" in p.lower() for p in params), (t.name, params)


# ------------------------------------------------------------------ user isolation


def test_user_a_cannot_read_user_b_through_mcp(app, warehouse):
    is_error, anna = call_tool(app, token_for(ANNA), "cost_of_my_usage", WEEK)
    assert not is_error
    is_error, erik = call_tool(app, token_for(ERIK), "cost_of_my_usage", WEEK)
    assert not is_error
    assert anna["data"]["total_kwh"] == pytest.approx(mart_total_kwh(warehouse, ANNA), abs=1e-3)
    assert erik["data"]["total_kwh"] == pytest.approx(mart_total_kwh(warehouse, ERIK), abs=1e-3)
    assert anna["data"]["total_kwh"] != erik["data"]["total_kwh"]


def test_smuggled_user_argument_cannot_switch_user(app, warehouse):
    """A prompt-injected `user_id` argument must not reach another user's rows."""
    is_error, payload = call_tool(
        app, token_for(ANNA), "cost_of_my_usage", {**WEEK, "user_id": ERIK}
    )
    if not is_error:  # if the SDK ignores unknown arguments, the result must still be Anna's
        assert payload["data"]["total_kwh"] == pytest.approx(
            mart_total_kwh(warehouse, ANNA), abs=1e-3
        )
        assert payload["data"]["total_kwh"] != pytest.approx(mart_total_kwh(warehouse, ERIK))


def test_compare_plans_uses_the_token_users_area(app):
    _, anna = call_tool(app, token_for(ANNA), "compare_plans", WEEK)
    _, erik = call_tool(app, token_for(ERIK), "compare_plans", WEEK)
    assert anna["data"]["price_area"] == "SE3"
    assert erik["data"]["price_area"] == "SE4"


def test_deleted_user_is_refused(app):
    is_error, payload = call_tool(app, token_for(DELETED_USER), "compare_plans", WEEK)
    assert is_error and "no profile" in str(payload)


def test_unknown_user_sees_no_consumption(app):
    is_error, payload = call_tool(app, token_for("stranger"), "cost_of_my_usage", WEEK)
    assert not is_error and payload["data"]["total_kwh"] == 0


# ------------------------------------------------------------------ validation and logging


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("get_prices", {"area": "SE9", "start_date": "2025-10-01", "end_date": "2025-10-01"}, ""),
        (
            "get_prices",
            {"area": "SE3", "start_date": "2025-10-01", "end_date": "2025-11-30"},
            "too long",
        ),
        (
            "cheapest_window",
            {"area": "SE3", "day": "2025-10-01", "duration_minutes": 20},
            "multiple of 15",
        ),
        (
            "explain_spike",
            {"area": "SE1", "interval_start_utc": "2025-10-02T16:40:00"},
            "quarter-hour",
        ),
    ],
)
def test_invalid_input_is_a_tool_error(app, tool, arguments, message):
    is_error, payload = call_tool(app, token_for(ANNA), tool, arguments)
    assert is_error
    assert message in str(payload)


def test_calls_are_audit_logged_without_raw_user_ids(app, caplog):
    caplog.set_level(logging.INFO, logger="elkollen.audit")
    call_tool(app, token_for(ERIK), "cost_of_my_usage", WEEK)
    entries = [json.loads(r.message) for r in caplog.records if r.name == "elkollen.audit"]
    entry = entries[-1]
    assert entry["event"] == "tool_call" and entry["tool"] == "cost_of_my_usage"
    assert entry["ok"] is True and entry["rows_read"] == 7 and entry["truncated"] is False
    assert entry["user"] and ERIK not in json.dumps(entry)
    assert entry["args"] == WEEK and entry["duration_ms"] >= 0


def test_public_tools_answer_with_numbers_and_units(app):
    is_error, payload = call_tool(
        app,
        token_for(ANNA),
        "cheapest_window",
        {"area": "SE4", "day": "2025-10-04", "duration_minutes": 120},
    )
    assert not is_error
    data = payload["data"]
    assert data["unit"] == "öre/kWh"
    assert data["cheapest"]["avg_ore_per_kwh"] <= data["day_avg_ore_per_kwh"]
    assert payload["sources"] == ["marts.fct_prices_15min"]
