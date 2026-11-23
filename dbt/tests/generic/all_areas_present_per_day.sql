{#- Every day that has any row must have rows for all price areas in var('price_areas').
    Returns the incomplete days and how many areas they have. -#}
{% test all_areas_present_per_day(model, date_column, area_column) %}

select
    {{ date_column }}               as day,
    count(distinct {{ area_column }}) as areas_present
from {{ model }}
group by {{ date_column }}
having count(distinct {{ area_column }}) <> {{ var('price_areas') | length }}

{% endtest %}
