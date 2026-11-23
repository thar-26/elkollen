import pytest
from fastapi.testclient import TestClient

SECRET = "forecast-test-secret-" + "f" * 40


@pytest.fixture(scope="module")
def client(warehouse):
    from elkollen_api.app import create_app

    return TestClient(create_app(warehouse, SECRET))


def test_negative_prices_raise_an_alert(client):
    # SE1 on 2025-10-02 had negative quarters (down to -104.3 öre/kWh) in the real data.
    body = client.get("/alerts", params={"area": "SE1", "day": "2025-10-02"}).json()
    assert body["data"]["published"] is True
    negative = next(a for a in body["data"]["alerts"] if a["kind"] == "negative_prices")
    assert negative["lowest_ore_per_kwh"] == pytest.approx(-104.304)
    assert negative["n_quarters"] > 0


def test_unpublished_day_has_no_alerts(client):
    body = client.get("/alerts", params={"area": "SE3", "day": "2030-01-01"}).json()
    assert body["data"]["published"] is False and body["data"]["alerts"] == []


def test_published_days_are_not_forecast(client):
    body = client.get("/forecast", params={"area": "SE3", "day": "2025-10-01"}).json()
    assert body["published"] is True and body["intervals"] == []


def test_forecast_refuses_without_enough_history(client):
    # The CI fixtures hold a week of continuous history, not the 14 days needed.
    r = client.get("/forecast", params={"area": "SE3", "day": "2025-10-06"})
    assert r.status_code == 422


@pytest.mark.parametrize("path", ["/alerts", "/forecast"])
def test_bad_input_is_rejected(client, path):
    assert client.get(path, params={"area": "SE9", "day": "2025-10-01"}).status_code == 422
