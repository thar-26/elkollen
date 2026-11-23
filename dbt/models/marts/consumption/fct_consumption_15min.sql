-- One row per user and 15-minute interval, priced at the spot price of the user's area.
-- spot_cost_sek is energy x spot price only: no VAT, energy tax, supplier markup or grid
-- fees. On Snowflake a row access policy hides rows of users who are not active.

{{ config(post_hook=["{{ elkollen.apply_privacy_policies(this, 'fct_consumption_15min') }}"]) }}

with consumption as (

    select * from {{ ref('stg_app__consumption') }}
    where interval_minutes = 15

),

users as (

    select user_id, price_area from {{ ref('stg_app__users') }}

),

prices as (

    select
        price_area,
        interval_start_utc,
        delivery_date,
        interval_start_local,
        price_sek_per_kwh,
        price_ore_per_kwh,
        is_upsampled_from_hourly
    from {{ ref('fct_prices_15min') }}

)

select
    consumption.user_id,
    users.price_area,
    prices.delivery_date,
    consumption.interval_start_utc,
    consumption.interval_end_utc,
    prices.interval_start_local,
    consumption.kwh,
    prices.price_ore_per_kwh,
    round(consumption.kwh * prices.price_sek_per_kwh, 6)  as spot_cost_sek,
    prices.is_upsampled_from_hourly                         as price_is_upsampled_from_hourly,
    prices.interval_start_utc is not null                   as has_price,
    consumption.source
from consumption
inner join users
    on users.user_id = consumption.user_id
left join prices
    on prices.price_area = users.price_area
   and prices.interval_start_utc = consumption.interval_start_utc
