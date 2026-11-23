-- One row per price area and delivery day: summary numbers for cards, the chat
-- assistant and spike explanations.

with prices as (

    select * from {{ ref('fct_prices_15min') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by price_area, delivery_date
            order by price_ore_per_kwh asc, interval_start_utc asc
        ) as cheapest_rank,
        row_number() over (
            partition by price_area, delivery_date
            order by price_ore_per_kwh desc, interval_start_utc asc
        ) as dearest_rank
    from prices

)

select
    price_area,
    delivery_date,
    count(*)                                                        as n_intervals,
    min(price_ore_per_kwh)                                          as min_ore_per_kwh,
    round(avg(price_ore_per_kwh), 4)                                as avg_ore_per_kwh,
    max(price_ore_per_kwh)                                          as max_ore_per_kwh,
    sum(case when price_ore_per_kwh < 0 then 1 else 0 end)          as n_negative_intervals,
    max(case when cheapest_rank = 1 then interval_start_utc end)    as cheapest_interval_start_utc,
    max(case when dearest_rank = 1 then interval_start_utc end)     as dearest_interval_start_utc,
    max(case when is_upsampled_from_hourly then 1 else 0 end) = 1   as is_hourly_source_day
from ranked
group by price_area, delivery_date
