{#- Within a partition, each interval must start exactly where the previous one ended:
    no gaps, no overlaps. Checked across midnight too, as long as the next row is on
    the same or the following day; whole missing days are a separate (date-spine) test
    added with the marts in phase 2. Returns the offending pairs. -#}
{% test contiguous_intervals(model, partition_by, start_column, end_column, date_column) %}

with ordered as (

    select
        {{ partition_by }} as partition_value,
        {{ date_column }}  as day,
        {{ start_column }} as interval_start,
        {{ end_column }}   as interval_end,
        lead({{ start_column }}) over (partition by {{ partition_by }} order by {{ start_column }}) as next_start,
        lead({{ date_column }})  over (partition by {{ partition_by }} order by {{ start_column }}) as next_day
    from {{ model }}

)

select *
from ordered
where next_start is not null
  and {{ dbt.datediff('day', 'next_day', 'day') }} <= 1
  and next_start <> interval_end

{% endtest %}
