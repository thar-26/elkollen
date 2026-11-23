-- Latest load of each (user, interval) reading.

select
    user_id,
    meter_id,
    interval_start_utc,
    {{ dbt.dateadd('minute', 'interval_minutes', 'interval_start_utc') }} as interval_end_utc,
    interval_minutes,
    kwh,
    source,
    loaded_at
from {{ source('app', 'consumption_readings') }}
qualify row_number() over (
    partition by user_id, interval_start_utc
    order by loaded_at desc, ingest_run_id desc
) = 1
