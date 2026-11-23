"""Elkollen MCP server (official MCP Python SDK, 2.x).

Five read-only tools: get_prices, cheapest_window, cost_of_my_usage, compare_plans,
explain_spike. The assistant answers only through them, so every number it gives comes
from the warehouse and the result says where it came from.

Security model
* Transport: streamable HTTP. Every request needs a bearer token (see elkollen_auth)
  for audience `elkollen-mcp` with scope `elkollen:read`; the SDK's bearer middleware
  rejects anything else with 401 before a tool runs.
* Identity: per-user tools read the user id from the *verified token's subject*. No tool
  has a user parameter, so neither the model nor a prompt injection can ask for someone
  else's data.
* Read-only: tools only call elkollen_data.queries, which only SELECTs from marts and
  caps every read at MAX_ROWS rows.
* Audit: one JSON line per call on the `elkollen.audit` logger (tool, arguments, outcome,
  rows, truncation, duration, and a pseudonymous user hash, never the raw id).
"""

import hashlib
import json
import logging
import os
import time
from datetime import date, datetime
from typing import Any

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

import elkollen_auth
from elkollen_data import queries
from elkollen_data.queries import Area, QueryInputError
from elkollen_data.warehouse import Warehouse, warehouse_from_env

audit = logging.getLogger("elkollen.audit")
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)

INSTRUCTIONS = """\
Elkollen answers questions about Swedish electricity spot prices (price areas SE1-SE4,
15-minute intervals, öre/kWh) and about the signed-in user's own consumption.
Only state numbers that a tool returned. If a tool returns no data, say so.
Prices exclude VAT, energy tax, supplier markup and grid fees; say so when it matters.
Times in results are given both in UTC and in Swedish local time (start_local)."""


class JwtTokenVerifier:
    """TokenVerifier for the SDK's bearer middleware, backed by elkollen_auth."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = elkollen_auth.verify(token, elkollen_auth.AUDIENCE_MCP, self._secret)
        except elkollen_auth.TokenError:
            return None
        return AccessToken(
            token=token,
            client_id=claims["iss"],
            scopes=str(claims.get("scope", "")).split(),
            expires_at=claims["exp"],
            subject=claims["sub"],
            resource=claims["aud"],
            claims={"iss": claims["iss"]},
        )


def pseudonym(user_id: str | None) -> str | None:
    if user_id is None:
        return None
    return hashlib.sha256(user_id.encode()).hexdigest()[:12]


def current_user_id() -> str:
    token = get_access_token()
    if token is None or not token.subject:
        raise ToolError("not signed in")
    return token.subject


def _jsonable(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


async def _call(tool: str, fn, args: dict[str, Any], user_id: str | None = None) -> dict:
    started = time.perf_counter()
    entry: dict[str, Any] = {
        "event": "tool_call",
        "tool": tool,
        "user": pseudonym(user_id),
        "args": {k: _jsonable(v) for k, v in args.items()},
    }
    try:
        result = await anyio.to_thread.run_sync(lambda: fn(**args))
    except QueryInputError as exc:
        entry.update(ok=False, error=str(exc))
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        entry.update(ok=False, error=type(exc).__name__)
        raise ToolError("the data service failed; no numbers were returned") from exc
    else:
        entry.update(ok=True, rows_read=result.rows_read, truncated=result.truncated)
        return result.model_dump(mode="json")
    finally:
        entry["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        audit.info(json.dumps(entry, ensure_ascii=False))


def build_server(
    warehouse: Warehouse | None = None,
    secret: str | None = None,
    *,
    issuer_url: str | None = None,
    resource_server_url: str | None = None,
) -> MCPServer:
    wh = warehouse if warehouse is not None else warehouse_from_env()
    server = MCPServer(
        name="elkollen",
        title="Elkollen",
        instructions=INSTRUCTIONS,
        version="0.3.0",
        token_verifier=JwtTokenVerifier(secret or elkollen_auth.secret_from_env()),
        auth=AuthSettings(
            issuer_url=issuer_url
            or os.environ.get("ELKOLLEN_AUTH_ISSUER", "http://localhost:3000"),
            resource_server_url=resource_server_url
            or os.environ.get("ELKOLLEN_MCP_URL", "http://127.0.0.1:8001/mcp"),
            required_scopes=[elkollen_auth.SCOPE],
            # JwtTokenVerifier already refuses tokens whose `aud` is not elkollen-mcp.
            validate_token_resource=False,
        ),
    )

    @server.tool(annotations=READ_ONLY)
    async def get_prices(area: Area, start_date: date, end_date: date) -> dict:
        """15-minute spot prices (öre/kWh) for one price area, at most 14 days."""
        args = {"area": area, "start_date": start_date, "end_date": end_date}
        return await _call(
            "get_prices", lambda **a: queries.get_prices(wh, **a), args, current_user_id()
        )

    @server.tool(annotations=READ_ONLY)
    async def cheapest_window(
        area: Area, day: date, duration_minutes: int, earliest_start_utc: datetime | None = None
    ) -> dict:
        """Cheapest and dearest continuous window of `duration_minutes` (multiple of 15,
        15-720) on one delivery day, e.g. when to run a dishwasher or charge a car."""
        args = {
            "area": area,
            "day": day,
            "duration_minutes": duration_minutes,
            "earliest_start_utc": earliest_start_utc,
        }
        return await _call(
            "cheapest_window", lambda **a: queries.cheapest_window(wh, **a), args, current_user_id()
        )

    @server.tool(annotations=READ_ONLY)
    async def cost_of_my_usage(start_date: date, end_date: date) -> dict:
        """What the signed-in user's own consumption cost at 15-minute spot prices
        (SEK), per day and in total, at most 93 days."""
        user_id = current_user_id()
        args = {"start_date": start_date, "end_date": end_date}
        return await _call(
            "cost_of_my_usage",
            lambda **a: queries.cost_of_my_usage(wh, user_id, **a),
            args,
            user_id,
        )

    @server.tool(annotations=READ_ONLY)
    async def compare_plans(
        start_date: date, end_date: date, fixed_price_ore_per_kwh: float | None = None
    ) -> dict:
        """The signed-in user's consumption priced as 15-minute spot, monthly average
        spot and, optionally, a fixed price in öre/kWh."""
        user_id = current_user_id()
        args = {
            "start_date": start_date,
            "end_date": end_date,
            "fixed_price_ore_per_kwh": fixed_price_ore_per_kwh,
        }
        return await _call(
            "compare_plans",
            lambda **a: queries.compare_plans(wh, user_id, **a),
            args,
            user_id,
        )

    @server.tool(annotations=READ_ONLY)
    async def explain_spike(area: Area, interval_start_utc: datetime) -> dict:
        """Context for one 15-minute price: vs its day, the last 30 days, the same time
        last week, and the other price areas at the same moment."""
        args = {"area": area, "interval_start_utc": interval_start_utc}
        return await _call(
            "explain_spike", lambda **a: queries.explain_spike(wh, **a), args, current_user_id()
        )

    return server


def create_app():
    """ASGI app for uvicorn: stateless streamable HTTP with JSON responses."""
    server = build_server()
    return server.streamable_http_app(stateless_http=True, json_response=True)


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    host = os.environ.get("ELKOLLEN_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("ELKOLLEN_MCP_PORT", "8001"))
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()
