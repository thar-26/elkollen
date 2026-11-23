{#- Every (partition, local day) must have exactly the number of intervals the Swedish
    clock says the day has: 24/23/25 for hourly days and 96/92/100 for 15-minute days.
    The expectation comes from a calendar rule (macros/time.sql), not from the data,
    so a missing or duplicated interval anywhere in the day fails this test. It also
    fails if one day mixes resolutions. Returns the offending days. -#}
{% test expected_intervals_per_day(model, partition_by, date_column, interval_minutes_column) %}

with per_day as (

    select
        {{ partition_by }}                 as partition_value,
        {{ date_column }}                  as day,
        min({{ interval_minutes_column }}) as interval_minutes,
        max({{ interval_minutes_column }}) as max_interval_minutes,
        count(*)                           as actual_intervals
    from {{ model }}
    group by 1, 2

),

checked as (

    select
        *,
        {{ elkollen.stockholm_day_minutes('day') }} / interval_minutes as expected_intervals
    from per_day

)

select *
from checked
where actual_intervals <> expected_intervals
   or interval_minutes <> max_interval_minutes

{% endtest %}
