"""Elkollen HTTP API.

Public, no sign-in (spot prices are public data):
    GET /health
    GET /areas
    GET /prices                  ?area&start_date&end_date
    GET /prices/cheapest-window  ?area&day&duration_minutes[&earliest_start_utc]
    GET /prices/explain          ?area&interval_start_utc

Signed-in user only (bearer token, audience `elkollen-api`):
    GET /me                      profile (price area)
    GET /me/cost                 ?start_date&end_date
    GET /me/plans                ?start_date&end_date[&fixed_price_ore_per_kwh]

The user is taken from the verified token's subject and nothing else. No endpoint has
a user parameter; extra query parameters are ignored. Deleted or unknown users get 403
on /me endpoints. Everything is read-only and goes through elkollen_data.queries.
Run: uvicorn elkollen_api.app:create_app --factory --port 8000
"""

import hashlib
import json
import logging
import os
import time
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import elkollen_auth
from elkollen_data import queries
from elkollen_data.queries import Area, QueryInputError
from elkollen_data.warehouse import Warehouse, warehouse_from_env

audit = logging.getLogger("elkollen.audit")
bearer = HTTPBearer(auto_error=False)


def _pseudonym(user_id: str | None) -> str | None:
    return hashlib.sha256(user_id.encode()).hexdigest()[:12] if user_id else None


def create_app(warehouse: Warehouse | None = None, secret: str | None = None) -> FastAPI:
    wh = warehouse if warehouse is not None else warehouse_from_env()
    jwt_secret = secret or elkollen_auth.secret_from_env()

    app = FastAPI(
        title="Elkollen API",
        version="0.3.0",
        description="Swedish 15-minute electricity prices and your own consumption. Read-only.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.environ.get("ELKOLLEN_WEB_ORIGIN", "http://localhost:3000")],
        allow_methods=["GET"],
        allow_headers=["Authorization"],
    )

    @app.middleware("http")
    async def audit_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        audit.info(
            json.dumps(
                {
                    "event": "api_call",
                    "path": request.url.path,
                    "status": response.status_code,
                    "user": _pseudonym(getattr(request.state, "user_id", None)),
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
            )
        )
        return response

    @app.exception_handler(QueryInputError)
    async def bad_input(_: Request, exc: QueryInputError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def current_user(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> str:
        unauthorized = HTTPException(
            status_code=401,
            detail="sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise unauthorized
        try:
            claims = elkollen_auth.verify(
                credentials.credentials, elkollen_auth.AUDIENCE_API, jwt_secret
            )
        except elkollen_auth.TokenError:
            raise unauthorized from None
        request.state.user_id = claims["sub"]
        return claims["sub"]

    def active_user(user_id: Annotated[str, Depends(current_user)]) -> dict:
        try:
            profile = queries.user_profile(wh, user_id)
        except QueryInputError:
            profile = None
        if profile is None:
            raise HTTPException(status_code=403, detail="no active profile for this user")
        return profile

    # ------------------------------------------------------------ public

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "warehouse": wh.name}

    @app.get("/areas")
    def areas() -> dict:
        return queries.list_areas(wh).model_dump(mode="json")

    @app.get("/prices")
    def prices(area: Area, start_date: date, end_date: date) -> dict:
        return queries.get_prices(wh, area, start_date, end_date).model_dump(mode="json")

    @app.get("/prices/cheapest-window")
    def cheapest_window(
        area: Area,
        day: date,
        duration_minutes: Annotated[int, Query(ge=15, le=720)],
        earliest_start_utc: datetime | None = None,
    ) -> dict:
        return queries.cheapest_window(
            wh, area, day, duration_minutes, earliest_start_utc
        ).model_dump(mode="json")

    @app.get("/prices/explain")
    def explain(area: Area, interval_start_utc: datetime) -> dict:
        return queries.explain_spike(wh, area, interval_start_utc).model_dump(mode="json")

    # ------------------------------------------------------------ signed-in user

    @app.get("/me")
    def me(profile: Annotated[dict, Depends(active_user)]) -> dict:
        return {
            "display_name": profile["display_name"],
            "price_area": profile["price_area"],
            "is_synthetic": bool(profile["is_synthetic"]),
        }

    @app.get("/me/cost")
    def my_cost(
        profile: Annotated[dict, Depends(active_user)], start_date: date, end_date: date
    ) -> dict:
        return queries.cost_of_my_usage(wh, profile["user_id"], start_date, end_date).model_dump(
            mode="json"
        )

    @app.get("/me/plans")
    def my_plans(
        profile: Annotated[dict, Depends(active_user)],
        start_date: date,
        end_date: date,
        fixed_price_ore_per_kwh: float | None = None,
    ) -> dict:
        return queries.compare_plans(
            wh, profile["user_id"], start_date, end_date, fixed_price_ore_per_kwh
        ).model_dump(mode="json")

    return app
