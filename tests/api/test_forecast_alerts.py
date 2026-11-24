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


@pytest.mark.parametrize("with_grid", [True, False])
def test_forecast_shows_the_backtest_of_the_model_it_used(warehouse, monkeypatch, with_grid):
    """Synthetic history in place of the warehouse readers, so a forecast succeeds."""
    import numpy as np
    import pandas as pd

    from elkollen_api.app import create_app
    from elkollen_forecast import model

    idx = pd.date_range("2026-01-01", "2026-02-14 22:45", freq="15min", tz="UTC")
    hour = idx.tz_convert("Europe/Stockholm").hour
    prices = pd.DataFrame({"area": "SE3", "start_utc": idx, "ore": 50 + 30 * np.sin(hour / 4)})
    grid_idx = pd.date_range("2026-01-01", "2026-02-15 22:45", freq="15min", tz="UTC")
    grid = pd.DataFrame(
        {"area": "SE3", "start_utc": grid_idx, "load_mw": 1e4, "wind_mw": 900.0, "solar_mw": 0.0}
    )
    monkeypatch.setattr(model, "load_prices", lambda wh, since: prices)
    monkeypatch.setattr(model, "load_grid", lambda wh, since: grid if with_grid else grid.iloc[0:0])
    body = (
        TestClient(create_app(warehouse, SECRET))
        .get("/forecast", params={"area": "SE3", "day": "2026-02-15"})
        .json()
    )
    expected = "ridge_with_grid_forecasts" if with_grid else "ridge"
    assert body["published"] is False
    assert len(body["intervals"]) == 96
    assert body["method"] == expected
    assert body["backtest"]["method"] == expected  # numbers of the model actually used


@pytest.mark.parametrize("path", ["/alerts", "/forecast"])
def test_bad_input_is_rejected(client, path):
    assert client.get(path, params={"area": "SE9", "day": "2025-10-01"}).status_code == 422
