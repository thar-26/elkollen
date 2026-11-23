{#- Time helpers that behave the same on Snowflake and DuckDB.

    The source sends ISO 8601 timestamps with an explicit offset, e.g.
    2025-10-26T02:45:00+02:00. We parse wall-clock time and offset from the string
    itself instead of relying on each engine's timezone database, so a DST day is
    handled identically everywhere and the original offset is kept as data. -#}

{% macro iso_local_timestamp(col) -%}
    cast(replace(substr({{ col }}, 1, 19), 'T', ' ') as timestamp)
{%- endmacro %}

{% macro iso_offset_minutes(col) -%}
    (case when substr({{ col }}, 20, 1) = '-' then -1 else 1 end)
    * (cast(substr({{ col }}, 21, 2) as integer) * 60 + cast(substr({{ col }}, 24, 2) as integer))
{%- endmacro %}

{% macro iso_to_utc(col) -%}
    {{ dbt.dateadd('minute', '-1 * (' ~ elkollen.iso_offset_minutes(col) ~ ')', elkollen.iso_local_timestamp(col)) }}
{%- endmacro %}


{#- ISO day of week, Monday = 1 ... Sunday = 7 -#}
{% macro iso_dow(date_expr) -%}
    {{ return(adapter.dispatch('iso_dow', 'elkollen')(date_expr)) }}
{%- endmacro %}

{% macro default__iso_dow(date_expr) -%}
    isodow({{ date_expr }})
{%- endmacro %}

{% macro snowflake__iso_dow(date_expr) -%}
    dayofweekiso({{ date_expr }})
{%- endmacro %}


{#- Swedish local day length in minutes, from an independent calendar rule rather than
    from the data. EU rule since 1996: clocks go forward on the last Sunday of March
    (23-hour day) and back on the last Sunday of October (25-hour day). The last Sunday
    of a 31-day month is always on day 25-31. -#}
{% macro stockholm_day_minutes(date_expr) -%}
    (1440
     + case
         when extract(month from {{ date_expr }}) = 3 and extract(day from {{ date_expr }}) >= 25
              and {{ elkollen.iso_dow(date_expr) }} = 7 then -60
         when extract(month from {{ date_expr }}) = 10 and extract(day from {{ date_expr }}) >= 25
              and {{ elkollen.iso_dow(date_expr) }} = 7 then 60
         else 0
       end)
{%- endmacro %}


{#- Current wall-clock time in Sweden as a timestamp without zone. Pin it with
    var('as_of_stockholm', 'YYYY-MM-DD HH:MI:SS') for unit tests and replays. -#}
{% macro stockholm_now() -%}
    {%- set pinned = var('as_of_stockholm', none) -%}
    {%- if pinned -%}
        cast('{{ pinned }}' as timestamp)
    {%- else -%}
        {{ return(adapter.dispatch('stockholm_now', 'elkollen')()) }}
    {%- endif -%}
{%- endmacro %}

{% macro default__stockholm_now() -%}
    cast(timezone('Europe/Stockholm', now()) as timestamp)
{%- endmacro %}

{% macro snowflake__stockholm_now() -%}
    convert_timezone('Europe/Stockholm', current_timestamp())::timestamp_ntz
{%- endmacro %}


{#- Integers 0..9999 in plain SQL (no engine-specific generator): enough for a
    27-year day spine. -#}
{% macro numbers_0_to_9999() -%}
    (
        with digits as (
            select 0 as d union all select 1 union all select 2 union all select 3
            union all select 4 union all select 5 union all select 6 union all select 7
            union all select 8 union all select 9
        )
        select a.d + 10 * b.d + 100 * c.d + 1000 * e.d as n
        from digits a cross join digits b cross join digits c cross join digits e
    )
{%- endmacro %}
