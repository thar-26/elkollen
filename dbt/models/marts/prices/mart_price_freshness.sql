-- Is tomorrow's price list in? One row per price area.
-- Tomorrow's prices are published from about 13:00 Stockholm time; we expect them by
-- var('tomorrow_expected_after_hour') (default 14) to allow for a late publication.
-- The clock can be pinned with var('as_of_stockholm') for tests and replays.

with latest as (

    select
        price_area,
        max(delivery_date) as latest_delivery_date,
        max(loaded_at)     as last_loaded_at_utc
    from {{ ref('fct_prices_15min') }}
    group by price_area

),

clock as (

    select {{ elkollen.stockholm_now() }} as now_stockholm

)

select
    latest.price_area,
    latest.latest_delivery_date,
    latest.last_loaded_at_utc,
    clock.now_stockholm,
    cast(clock.now_stockholm as date)                                       as today_stockholm,
    latest.latest_delivery_date
        >= {{ dbt.dateadd('day', 1, 'cast(clock.now_stockholm as date)') }} as has_tomorrow,
    latest.latest_delivery_date >= cast(clock.now_stockholm as date)        as has_today,
    extract(hour from clock.now_stockholm)
        >= {{ var('tomorrow_expected_after_hour', 14) }}                    as tomorrow_expected
from latest
cross join clock
