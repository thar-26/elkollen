-- Day-ahead grid forecasts on the same 15-minute grain as fct_prices_15min, one row
-- per price area and quarter: forecast load, wind (onshore + offshore) and solar, MW.
-- An hourly value is a power level held for the hour, so it becomes four quarters with
-- the same MW (flagged), the same way hourly prices are handled.

with forecasts as (

    select * from {{ ref('stg_entsoe__forecasts') }}

),

quarters as (

    select 0 as quarter_index
    union all select 1
    union all select 2
    union all select 3

),

expanded as (

    select
        forecasts.price_area,
        forecasts.series,
        forecasts.delivery_date,
        forecasts.interval_minutes,
        forecasts.mw,
        {{ dbt.dateadd('minute', '15 * quarters.quarter_index', 'forecasts.interval_start_utc') }}
            as interval_start_utc,
        {{ dbt.dateadd('minute', '15 * quarters.quarter_index', 'forecasts.interval_start_local') }}
            as interval_start_local
    from forecasts
    inner join quarters
        on quarters.quarter_index < forecasts.interval_minutes / 15

)

select
    price_area,
    interval_start_utc,
    {{ dbt.dateadd('minute', '15', 'interval_start_utc') }}    as interval_end_utc,
    min(interval_start_local)                                  as interval_start_local,
    min(delivery_date)                                         as delivery_date,
    15                                                         as interval_minutes,
    max(case when series = 'load_forecast' then mw end)        as load_mw,
    sum(case when series in ('wind_onshore_forecast', 'wind_offshore_forecast')
             then mw end)                                      as wind_mw,
    max(case when series = 'solar_forecast' then mw end)       as solar_mw,
    max(case when series = 'load_forecast' and interval_minutes = 60
             then 1 else 0 end) = 1                            as is_load_upsampled_from_hourly
from expanded
group by price_area, interval_start_utc
