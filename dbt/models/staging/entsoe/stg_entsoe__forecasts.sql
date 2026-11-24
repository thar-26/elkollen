-- One row per price area, series and native interval (15 or 60 minutes), latest load.

with source as (

    select * from {{ source('entsoe', 'entsoe_forecasts') }}

),

-- RAW is append-only: keep the most recent load of each interval.
latest_load as (

    select *
    from source
    qualify row_number() over (
        partition by area, series, interval_start_utc
        order by loaded_at desc, ingest_run_id desc
    ) = 1

)

select
    area                                                                    as price_area,
    series,
    delivery_date,
    interval_start_utc,
    {{ dbt.dateadd('minute', 'resolution_minutes', 'interval_start_utc') }} as interval_end_utc,
    interval_start_local,
    resolution_minutes                                                      as interval_minutes,
    mw,
    document_type,
    ingest_run_id,
    loaded_at
from latest_load
