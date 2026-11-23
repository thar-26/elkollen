{#- Every calendar day between the first and last day of each partition (or between
    start_date and end_date when given) must have at least one row. Catches whole
    missing days, which the per-day interval-count test cannot see. Returns the
    missing (partition, day) pairs.

    start_date / end_date accept 'YYYY-MM-DD'; empty or 'None' means "use the data". -#}
{% test no_missing_days(model, date_column, partition_by, start_date=none, end_date=none) %}

{%- set has_start = start_date is not none and start_date | string not in ('', 'None', 'none') -%}
{%- set has_end = end_date is not none and end_date | string not in ('', 'None', 'none') -%}

with present as (

    select distinct
        {{ partition_by }} as partition_value,
        {{ date_column }}  as day
    from {{ model }}

),

bounds as (

    select
        partition_value,
        {% if has_start %} cast('{{ start_date }}' as date) {% else %} min(day) {% endif %} as first_day,
        {% if has_end %} cast('{{ end_date }}' as date) {% else %} max(day) {% endif %}   as last_day
    from present
    group by partition_value

),

expected as (

    select
        bounds.partition_value,
        {{ dbt.dateadd('day', 'numbers.n', 'bounds.first_day') }} as day
    from bounds
    inner join {{ elkollen.numbers_0_to_9999() }} as numbers
        on numbers.n <= {{ dbt.datediff('bounds.first_day', 'bounds.last_day', 'day') }}

)

select expected.partition_value, cast(expected.day as date) as missing_day
from expected
left join present
    on present.partition_value = expected.partition_value
   and present.day = cast(expected.day as date)
where present.day is null

{% endtest %}
