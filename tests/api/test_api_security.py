"""Security tests through the HTTP API: user A can never read user B's rows."""

import json
import logging
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import elkollen_auth
from tests.conftest import DELETED_USER

SECRET = "api-test-secret-" + "z" * 40
ANNA, ERIK = "demo-anna", "demo-erik"
WEEK = {"start_date": "2025-09-29", "end_date": "2025-10-05"}


@pytest.fixture(scope="module")
def client(warehouse):
    from elkollen_api.app import create_app

    return TestClient(create_app(warehouse, SECRET))


def auth(user_id: str, audience: str = elkollen_auth.AUDIENCE_API) -> dict:
    return {"Authorization": "Bearer " + elkollen_auth.mint(user_id, audience, SECRET)}


def mart_total_kwh(warehouse, user_id):
    return warehouse.fetch(
        "select sum(kwh) as kwh from marts.fct_consumption_15min "
        "where user_id = :u and delivery_date between :s and :e",
        {"u": user_id, "s": WEEK["start_date"], "e": WEEK["end_date"]},
    )[0]["kwh"]


# ------------------------------------------------------------------ public endpoints


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_prices_are_public(client):
    params = {"area": "SE3", "start_date": "2025-10-26", "end_date": "2025-10-26"}
    r = client.get("/prices", params=params)
    assert r.status_code == 200
    assert r.json()["data"]["summary"]["n_intervals"] == 100


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/prices", {"area": "SE9", "start_date": "2025-10-01", "end_date": "2025-10-01"}),
        ("/prices", {"area": "SE3", "start_date": "2025-10-01", "end_date": "2025-12-01"}),
        ("/prices", {"area": "SE3", "start_date": "yesterday", "end_date": "2025-10-01"}),
        ("/prices/cheapest-window", {"area": "SE3", "day": "2025-10-01", "duration_minutes": 20}),
        ("/prices/cheapest-window", {"area": "SE3", "day": "2025-10-01", "duration_minutes": 0}),
        ("/prices/explain", {"area": "SE1", "interval_start_utc": "2025-10-02T16:40:00"}),
    ],
)
def test_bad_input_is_422(client, path, params):
    assert client.get(path, params=params).status_code == 422


# ------------------------------------------------------------------ authentication


def _forged(**override) -> str:
    now = int(time.time())
    claims = {
        "iss": elkollen_auth.ISSUER,
        "aud": elkollen_auth.AUDIENCE_API,
        "sub": ANNA,
        "scope": elkollen_auth.SCOPE,
        "iat": now,
        "exp": now + 300,
    }
    claims.update(override)
    key = claims.pop("_key", SECRET)
    return jwt.encode(claims, key, algorithm="HS256")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer nope"},
        {"Authorization": "Basic ZGVtbzpkZW1v"},
        {"Authorization": "Bearer " + _forged(_key="other-secret-" + "q" * 40)},
        {"Authorization": "Bearer " + _forged(aud=elkollen_auth.AUDIENCE_MCP)},
        {
            "Authorization": "Bearer "
            + _forged(iat=int(time.time()) - 900, exp=int(time.time()) - 600)
        },
        {"Authorization": "Bearer " + _forged(scope="")},
    ],
    ids=["none", "garbage", "basic", "wrong-secret", "mcp-audience", "expired", "no-scope"],
)
@pytest.mark.parametrize("path", ["/me", "/me/cost", "/me/plans"])
def test_me_endpoints_need_a_valid_api_token(client, headers, path):
    r = client.get(path, params=WEEK, headers=headers)
    assert r.status_code == 401
    assert r.headers.get("www-authenticate") == "Bearer"


# ------------------------------------------------------------------ user isolation


def test_user_a_cannot_read_user_b_through_the_api(client, warehouse):
    anna = client.get("/me/cost", params=WEEK, headers=auth(ANNA)).json()
    erik = client.get("/me/cost", params=WEEK, headers=auth(ERIK)).json()
    assert anna["data"]["total_kwh"] == pytest.approx(mart_total_kwh(warehouse, ANNA), abs=1e-3)
    assert erik["data"]["total_kwh"] == pytest.approx(mart_total_kwh(warehouse, ERIK), abs=1e-3)
    assert anna["data"]["total_kwh"] != erik["data"]["total_kwh"]


@pytest.mark.parametrize("smuggled", [{"user_id": ERIK}, {"user": ERIK}, {"sub": ERIK}])
def test_query_parameters_cannot_switch_user(client, warehouse, smuggled):
    r = client.get("/me/cost", params={**WEEK, **smuggled}, headers=auth(ANNA))
    assert r.status_code == 200
    expected = mart_total_kwh(warehouse, ANNA)
    assert r.json()["data"]["total_kwh"] == pytest.approx(expected, abs=1e-3)


def test_me_returns_only_own_profile_without_personal_data(client):
    body = client.get("/me", headers=auth(ERIK)).json()
    assert body == {"display_name": "Erik (demo)", "price_area": "SE4", "is_synthetic": True}


def test_plans_use_the_token_users_area(client):
    anna = client.get("/me/plans", params=WEEK, headers=auth(ANNA)).json()
    erik = client.get("/me/plans", params=WEEK, headers=auth(ERIK)).json()
    assert anna["data"]["price_area"] == "SE3"
    assert erik["data"]["price_area"] == "SE4"


@pytest.mark.parametrize("user_id", [DELETED_USER, "stranger"])
@pytest.mark.parametrize("path", ["/me", "/me/cost", "/me/plans"])
def test_deleted_or_unknown_users_are_forbidden(client, user_id, path):
    assert client.get(path, params=WEEK, headers=auth(user_id)).status_code == 403


def test_no_endpoint_accepts_a_user_parameter(client):
    spec = client.get("/openapi.json").json()
    for path, methods in spec["paths"].items():
        # Only the assistant takes a POST body (a question); it reads data via MCP tools.
        # POST only where a body is needed (a question, an upload); neither writes data.
        allowed = {"get", "post"} if path in {"/chat", "/consumption/analyse"} else {"get"}
        assert set(methods) <= allowed, f"{path} must be read-only"
        for op in methods.values():
            for p in op.get("parameters", []):
                assert "user" not in p["name"].lower(), (path, p["name"])
    for schema in ("ChatRequest", "UploadRequest"):
        body = spec["components"]["schemas"][schema]["properties"]
        assert not any("user" in name.lower() for name in body), (schema, body)


def test_requests_are_audit_logged_without_raw_user_ids(client, caplog):
    caplog.set_level(logging.INFO, logger="elkollen.audit")
    client.get("/me/cost", params=WEEK, headers=auth(ERIK))
    entry = json.loads([r for r in caplog.records if r.name == "elkollen.audit"][-1].message)
    assert entry["event"] == "api_call" and entry["path"] == "/me/cost"
    assert entry["status"] == 200 and entry["user"] and ERIK not in json.dumps(entry)
