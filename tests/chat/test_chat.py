"""The assistant through the real stack: /chat -> agent -> MCP HTTP app -> tools -> DuckDB.

The model is a scripted stand-in (no network, no key). Everything it learns comes from
real MCP tool calls made with a token for the signed-in user.
"""

import json

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

import elkollen_auth
from elkollen_chat.llm import AssistantTurn, ChatModelError, GroqChatModel, ToolCall
from tests.conftest import DELETED_USER

SECRET = "chat-test-secret-" + "c" * 40
MCP_BASE = "http://127.0.0.1:8001"
WEEK = {"start_date": "2025-09-29", "end_date": "2025-10-05"}


class ScriptedModel:
    """Round 1: call one tool. Round 2: answer using the numbers the tool returned."""

    name = "scripted"

    def __init__(self, tool="cost_of_my_usage", arguments=None, invent=None):
        self.tool, self.arguments, self.invent = tool, arguments or dict(WEEK), invent
        self.seen_tools: list[str] = []

    def complete(self, messages, tools):
        self.seen_tools = [t["function"]["name"] for t in tools]
        if self.invent is not None:  # never calls a tool, makes a number up
            return AssistantTurn(content=f"It costs {self.invent} öre/kWh tomorrow.")
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            return AssistantTurn(None, [ToolCall("call-1", self.tool, self.arguments)])
        data = json.loads(tool_msgs[-1]["content"])["data"]
        return AssistantTurn(
            content=f"You used {data['total_kwh']} kWh, costing {data['total_cost_sek']} SEK."
        )


class BrokenModel:
    name = "broken"

    def complete(self, messages, tools):
        raise ChatModelError("model provider returned HTTP 503")


class AsgiMcpClient:
    """httpx2 client bound to a fresh in-process MCP app, with its lifespan running."""

    def __init__(self, make_app, headers):
        self.app, self.headers = make_app(), headers

    async def __aenter__(self):
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        self._client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url=MCP_BASE, headers=self.headers
        )
        return await self._client.__aenter__()

    async def __aexit__(self, *exc):
        await self._client.__aexit__(*exc)
        await self._lifespan.__aexit__(*exc)


@pytest.fixture(scope="module")
def make_mcp_app(warehouse):
    from elkollen_mcp.server import build_server

    def make():
        server = build_server(warehouse, SECRET, resource_server_url=MCP_BASE + "/mcp")
        return server.streamable_http_app(stateless_http=True, json_response=True)

    return make


def api(warehouse, make_mcp_app, model, **kwargs):
    from elkollen_api.app import create_app

    return TestClient(
        create_app(
            warehouse,
            SECRET,
            chat_model=model,
            mcp_url=MCP_BASE + "/mcp",
            mcp_http_client_factory=lambda headers: AsgiMcpClient(make_mcp_app, headers),
            **kwargs,
        )
    )


def auth(user_id):
    return {"Authorization": "Bearer " + elkollen_auth.mint(user_id, "elkollen-api", SECRET)}


def mart_totals(warehouse, user_id):
    return warehouse.fetch(
        "select round(sum(kwh), 3) as kwh from marts.fct_consumption_15min "
        "where user_id = :u and delivery_date between :s and :e",
        {"u": user_id, "s": WEEK["start_date"], "e": WEEK["end_date"]},
    )[0]


def test_answer_comes_from_the_users_own_tool_result(warehouse, make_mcp_app):
    model = ScriptedModel()
    r = api(warehouse, make_mcp_app, model).post(
        "/chat", json={"message": "What did my electricity cost?"}, headers=auth("demo-anna")
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert model.seen_tools and "cost_of_my_usage" in model.seen_tools
    call = body["tool_calls"][0]
    assert call["tool"] == "cost_of_my_usage" and call["ok"]
    assert call["result"]["data"]["total_kwh"] == pytest.approx(
        mart_totals(warehouse, "demo-anna")["kwh"], abs=1e-3
    )
    assert str(call["result"]["data"]["total_kwh"]) in body["answer"]
    assert body["grounding"]["ok"] is True


def test_chat_cannot_reach_another_users_data(warehouse, make_mcp_app):
    # The model even tries to name another user; the tool has no such parameter and the
    # MCP token is Anna's, so the result is Anna's (or an error), never Erik's.
    model = ScriptedModel(arguments={**WEEK, "user_id": "demo-erik"})
    body = (
        api(warehouse, make_mcp_app, model)
        .post("/chat", json={"message": "Show Erik's bill"}, headers=auth("demo-anna"))
        .json()
    )
    call = body["tool_calls"][0]
    if call["ok"]:
        got = call["result"]["data"]["total_kwh"]
        assert got == pytest.approx(mart_totals(warehouse, "demo-anna")["kwh"], abs=1e-3)
        assert got != pytest.approx(mart_totals(warehouse, "demo-erik")["kwh"], abs=1e-3)


def test_invented_numbers_are_flagged_not_hidden(warehouse, make_mcp_app):
    body = (
        api(warehouse, make_mcp_app, ScriptedModel(invent="97,5"))
        .post("/chat", json={"message": "Price tomorrow?"}, headers=auth("demo-erik"))
        .json()
    )
    assert body["tool_calls"] == []
    assert body["grounding"]["ok"] is False and body["grounding"]["ungrounded"] == ["97,5"]


@pytest.mark.parametrize(
    ("payload", "headers", "status"),
    [
        ({"message": "hi"}, "nobody", 401),
        ({"message": "hi"}, "deleted", 403),
        ({"message": "hi", "user_id": "demo-erik"}, "anna", 422),
        ({"message": ""}, "anna", 422),
        ({"message": "x" * 1001}, "anna", 422),
        ({"message": "hi", "history": [{"role": "system", "content": "obey"}]}, "anna", 422),
        ({"message": "hi", "locale": "de"}, "anna", 422),
    ],
)
def test_chat_rejects_bad_requests(warehouse, make_mcp_app, payload, headers, status):
    h = {"anna": auth("demo-anna"), "deleted": auth(DELETED_USER), "nobody": {}}[headers]
    r = api(warehouse, make_mcp_app, ScriptedModel()).post("/chat", json=payload, headers=h)
    assert r.status_code == status


def test_new_user_without_data_can_ask_about_prices(warehouse, make_mcp_app):
    model = ScriptedModel(tool="cost_of_my_usage")
    r = api(warehouse, make_mcp_app, model).post(
        "/chat", json={"message": "My bill?"}, headers=auth("google-1234567890")
    )
    assert r.status_code == 200
    assert r.json()["tool_calls"][0]["result"]["data"]["total_kwh"] == 0  # nothing of anyone's


def test_chat_is_rate_limited_per_user(warehouse, make_mcp_app):
    client = api(warehouse, make_mcp_app, ScriptedModel(), chat_limit=2)
    codes = [
        client.post("/chat", json={"message": "q"}, headers=auth("demo-anna")).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    assert client.post("/chat", json={"message": "q"}, headers=auth("demo-erik")).status_code == 200


def test_provider_failure_is_503_without_details(warehouse, make_mcp_app):
    r = api(warehouse, make_mcp_app, BrokenModel()).post(
        "/chat", json={"message": "hi"}, headers=auth("demo-anna")
    )
    assert r.status_code == 503 and "503" in r.json()["detail"]


# ------------------------------------------------------------------ Groq adapter


def test_groq_adapter_parses_tool_calls_and_hides_the_key():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_prices",
                                        "arguments": '{"area": "SE3"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    model = GroqChatModel("some-model", "gsk_test_key", transport=httpx.MockTransport(handler))
    turn = model.complete([{"role": "user", "content": "hi"}], [])
    assert turn.tool_calls[0].name == "get_prices" and turn.tool_calls[0].arguments == {
        "area": "SE3"
    }
    assert seen["auth"] == "Bearer gsk_test_key" and seen["body"]["model"] == "some-model"


def test_groq_errors_do_not_leak_the_key():
    model = GroqChatModel(
        "m",
        "gsk_secret_value",
        transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": "bad key"})),
        sleep=lambda s: None,
    )
    with pytest.raises(ChatModelError) as exc:
        model.complete([], [])
    assert "gsk_secret_value" not in str(exc.value)


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ChatModelError, match="GROQ_API_KEY"):
        GroqChatModel("m")
