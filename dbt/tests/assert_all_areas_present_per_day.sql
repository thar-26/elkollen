-- Every delivery day that has any price must have prices for all four areas.
-- Returns the incomplete days and how many areas they have.

select
    delivery_date,
    count(distinct price_area) as areas_present
from {{ ref('stg_elpris__prices') }}
group by delivery_date
having count(distinct price_area) <> {{ var('price_areas') | length }}
