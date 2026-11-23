-- One row per price area and 15-minute interval: the table the API, the MCP tools
-- and the charts read. Join on interval_start_utc, never on local time (local time
-- repeats on the autumn clock-change day).

select
    price_area,
    delivery_date,
    interval_start_utc,
    interval_end_utc,
    interval_start_local,
    utc_offset_minutes,
    row_number() over (
        partition by price_area, delivery_date
        order by interval_start_utc
    )                           as interval_of_day,
    interval_minutes,
    price_sek_per_kwh,
    price_ore_per_kwh,
    price_eur_per_kwh,
    eur_sek_rate,
    is_upsampled_from_hourly,
    source_resolution,
    has_source_end_mismatch,
    loaded_at
from {{ ref('int_prices__15min') }}
