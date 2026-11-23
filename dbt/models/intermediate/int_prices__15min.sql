-- The unified time grain: every price as a 15-minute interval.
--
-- Rows that were 15-minute at the source pass through unchanged. Each hourly row
-- (before 2025-10-01) becomes four 15-minute rows carrying the same hourly price and
-- is_upsampled_from_hourly = true. That is a statement of what was traded, not an
-- estimate: under hourly settlement every quarter of that hour had that price.

with prices as (

    select * from {{ ref('stg_elpris__prices') }}

),

quarters as (

    select 0 as quarter_index
    union all select 1
    union all select 2
    union all select 3

),

expanded as (

    select
        prices.*,
        quarters.quarter_index
    from prices
    inner join quarters
        on quarters.quarter_index < prices.interval_minutes / 15

)

select
    price_area,
    delivery_date,
    {{ dbt.dateadd('minute', '15 * quarter_index', 'interval_start_utc') }}      as interval_start_utc,
    {{ dbt.dateadd('minute', '15 * quarter_index + 15', 'interval_start_utc') }} as interval_end_utc,
    {{ dbt.dateadd('minute', '15 * quarter_index', 'interval_start_local') }}    as interval_start_local,
    utc_offset_minutes,
    15                                as interval_minutes,
    price_sek_per_kwh,
    price_ore_per_kwh,
    price_eur_per_kwh,
    eur_sek_rate,
    source_resolution,
    interval_minutes = 60             as is_upsampled_from_hourly,
    has_source_end_mismatch,
    loaded_at
from expanded
