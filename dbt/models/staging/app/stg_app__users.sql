-- Latest known state of each user.

select
    user_id,
    display_name,
    price_area,
    meter_id,
    address,
    status,
    is_synthetic,
    created_at,
    loaded_at
from {{ source('app', 'app_users') }}
qualify row_number() over (partition by user_id order by loaded_at desc, ingest_run_id desc) = 1
