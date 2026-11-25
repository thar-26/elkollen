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


@pytest.mark.parametrize("with_grid", [True, False, None])  # None: mart missing
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

    def load_prices(wh, since, area=None):
        assert area == "SE3"  # the API loads only the requested area
        return prices

    monkeypatch.setattr(model, "load_prices", load_prices)

    def load_grid(wh, since, area=None):
        assert area == "SE3"
        if with_grid is None:
            raise RuntimeError("table marts.fct_grid_forecast_15min does not exist")
        return grid if with_grid else grid.iloc[0:0]

    monkeypatch.setattr(model, "load_grid", load_grid)
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


def test_health_answers_while_forecast_waits_on_a_slow_warehouse(warehouse):
    """Render restarts the service when /health takes over 5 s. Warehouse calls must run
    in worker threads, never on the event loop, so a slow query cannot freeze /health."""
    import time

    import anyio
    import httpx

    from elkollen_api.app import create_app

    class SlowWarehouse:
        name = warehouse.name

        def fetch(self, sql, params=None):
            time.sleep(1.5)  # a slow Snowflake query
            return warehouse.fetch(sql, params)

    app = create_app(SlowWarehouse(), SECRET)
    timings = {}

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

            async def slow_forecast():
                await client.get("/forecast", params={"area": "SE3", "day": "2025-10-06"})

            async with anyio.create_task_group() as tg:
                # Timer starts before the pause: a blocked event loop also delays the pause.
                start = time.monotonic()
                tg.start_soon(slow_forecast)
                await anyio.sleep(0.2)  # the forecast request is now inside its slow query
                r = await client.get("/health")
                timings["health"] = time.monotonic() - start
                assert r.status_code == 200

    anyio.run(scenario)
    assert timings["health"] < 1.0, f"/health answered after {timings['health']:.2f}s"


@pytest.mark.parametrize("path", ["/alerts", "/forecast"])
def test_bad_input_is_rejected(client, path):
    assert client.get(path, params={"area": "SE9", "day": "2025-10-01"}).status_code == 422
