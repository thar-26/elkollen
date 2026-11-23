from datetime import date

import httpx
import pytest
import respx

from elkollen_ingest.elpris import ElprisClient, day_url

DAY = date(2025, 10, 1)
URL = day_url("SE3", DAY)
ROW = {
    "SEK_per_kWh": 0.5,
    "EUR_per_kWh": 0.045,
    "EXR": 11.0,
    "time_start": "2025-10-01T00:00:00+02:00",
    "time_end": "2025-10-01T00:15:00+02:00",
}


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def client(sleeps):
    c = ElprisClient(user_agent="elkollen-test", sleep=sleeps.append)
    yield c
    c.close()


def test_url_format():
    assert URL == "https://www.elprisetjustnu.se/api/v1/prices/2025/10-01_SE3.json"


@respx.mock
def test_not_published_yet_returns_none(client):
    respx.get(URL).mock(return_value=httpx.Response(404))
    assert client.fetch_day("SE3", DAY) is None


@respx.mock
def test_sends_user_agent_and_pauses(client, sleeps):
    route = respx.get(URL).mock(return_value=httpx.Response(200, json=[ROW]))
    prices = client.fetch_day("SE3", DAY)
    assert prices is not None and len(prices.points) == 1
    assert route.calls[0].request.headers["User-Agent"] == "elkollen-test"
    assert sleeps == [0.25]


@respx.mock
def test_retries_server_errors_with_backoff(client, sleeps):
    respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, json=[ROW])]
    )
    assert client.fetch_day("SE3", DAY) is not None
    assert sleeps[:2] == [1, 2]


@respx.mock
def test_gives_up_after_max_retries(client):
    respx.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_day("SE3", DAY)


@respx.mock
def test_client_errors_are_not_retried(client):
    route = respx.get(URL).mock(return_value=httpx.Response(400))
    with pytest.raises(httpx.HTTPStatusError):
        client.fetch_day("SE3", DAY)
    assert route.call_count == 1


def test_rejects_unknown_area(client):
    with pytest.raises(ValueError, match="unknown price area"):
        client.fetch_raw("SE5", DAY)


def test_rejects_days_before_api_history(client):
    with pytest.raises(ValueError, match="before the first day"):
        client.fetch_raw("SE3", date(2020, 1, 1))
