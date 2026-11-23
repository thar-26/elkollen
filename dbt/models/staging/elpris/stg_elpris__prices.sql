-- One row per price area and native price interval (hourly before 2025-10-01,
-- 15-minute after). The unified 15-minute grain is built on top of this in phase 2.

with source as (

    select * from {{ source('elpris', 'elpris_prices') }}

),

-- RAW is append-only: keep the most recent load of each interval.
latest_load as (

    select *
    from source
    qualify row_number() over (
        partition by area, time_start
        order by loaded_at desc, ingest_run_id desc
    ) = 1

),

parsed as (

    select
        area                                             as price_area,
        delivery_date,
        {{ elkollen.iso_local_timestamp('time_start') }} as interval_start_local,
        {{ elkollen.iso_offset_minutes('time_start') }}  as utc_offset_minutes,
        {{ elkollen.iso_to_utc('time_start') }}          as interval_start_utc,
        {{ elkollen.iso_to_utc('time_end') }}            as source_interval_end_utc,
        sek_per_kwh,
        eur_per_kwh,
        exr,
        source_url,
        ingest_run_id,
        loaded_at
    from latest_load

),

-- The day's resolution is the shortest declared interval. We do not trust time_end
-- row by row: on fall-back days the source declares one interval an hour too long.
with_resolution as (

    select
        *,
        min({{ dbt.datediff('interval_start_utc', 'source_interval_end_utc', 'minute') }})
            over (partition by price_area, delivery_date) as interval_minutes
    from parsed

),

final as (

    select
        price_area,
        delivery_date,
        interval_start_utc,
        {{ dbt.dateadd('minute', 'interval_minutes', 'interval_start_utc') }} as interval_end_utc,
        interval_start_local,
        utc_offset_minutes,
        interval_minutes,
        case interval_minutes when 15 then 'PT15M' when 60 then 'PT60M' end as source_resolution,
        sek_per_kwh                         as price_sek_per_kwh,
        round(sek_per_kwh * 100, 4)         as price_ore_per_kwh,
        eur_per_kwh                         as price_eur_per_kwh,
        exr                                 as eur_sek_rate,
        source_interval_end_utc
            <> {{ dbt.dateadd('minute', 'interval_minutes', 'interval_start_utc') }}
                                            as has_source_end_mismatch,
        source_url,
        ingest_run_id,
        loaded_at
    from with_resolution

)

select * from final
