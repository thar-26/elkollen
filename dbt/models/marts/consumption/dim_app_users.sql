-- One row per user. On Snowflake, meter_id and address are masked for the app role and
-- a row access policy hides users whose status is not 'active' (see macros/privacy.sql).

{{ config(post_hook=["{{ elkollen.apply_privacy_policies(this, 'dim_app_users') }}"]) }}

select
    user_id,
    display_name,
    price_area,
    meter_id,
    address,
    status,
    is_synthetic,
    created_at
from {{ ref('stg_app__users') }}
