{#- Snowflake privacy controls for per-user marts (decision 0003).

    * mask_pii: meter_id and address are shown in full only to the TRANSFORMER role
      (which builds the tables). Every other role, including the app's READER, sees
      '****' + the last 4 characters.
    * rap_active_user_status / rap_active_user_id: the app role only sees users whose
      status is 'active'. Setting a user to 'deleted' hides their rows immediately,
      before the physical purge.

    Snowflake cannot tell end users apart here: the API and MCP server connect as one
    service user. Per-end-user isolation is therefore enforced in the application layer
    (every query is scoped to the verified user id) and covered by automated tests;
    these policies are defence in depth for roles and deletion.

    dbt rebuilds the tables, which drops attachments, so the post-hook re-applies them
    on every run. On DuckDB (local dev and CI, synthetic data only) this is a no-op. -#}

{% macro apply_privacy_policies(relation, model_name) %}
    {% if target.type != 'snowflake' or not execute %}
        {{ return('select 1 as privacy_policies_not_applicable') }}
    {% endif %}

    {% set schema = relation.database ~ '.' ~ relation.schema %}
    {% set full_access_role = var('privacy_full_access_role', 'ELKOLLEN_TRANSFORMER') %}
    {% set staging = relation.database ~ '.staging' %}

    {% set statements = [
        "create masking policy if not exists " ~ schema ~ ".mask_pii as (val string) returns string -> val",
        "alter masking policy " ~ schema ~ ".mask_pii set body -> case when current_role() = '"
            ~ full_access_role ~ "' then val when val is null then null else '****' || right(val, 4) end",
        "create row access policy if not exists " ~ schema ~ ".rap_active_user_status as (status varchar) returns boolean -> true",
        "alter row access policy " ~ schema ~ ".rap_active_user_status set body -> current_role() = '"
            ~ full_access_role ~ "' or status = 'active'",
        "create row access policy if not exists " ~ schema ~ ".rap_active_user_id as (user_id varchar) returns boolean -> true",
        "alter row access policy " ~ schema ~ ".rap_active_user_id set body -> current_role() = '"
            ~ full_access_role ~ "' or exists (select 1 from " ~ staging
            ~ ".stg_app__users u where u.user_id = user_id and u.status = 'active')",
    ] %}

    {% if model_name == 'dim_app_users' %}
        {% do statements.append("alter table " ~ relation ~ " modify column meter_id set masking policy " ~ schema ~ ".mask_pii") %}
        {% do statements.append("alter table " ~ relation ~ " modify column address set masking policy " ~ schema ~ ".mask_pii") %}
        {% do statements.append("alter table " ~ relation ~ " add row access policy " ~ schema ~ ".rap_active_user_status on (status)") %}
    {% elif model_name == 'fct_consumption_15min' %}
        {% do statements.append("alter table " ~ relation ~ " add row access policy " ~ schema ~ ".rap_active_user_id on (user_id)") %}
    {% endif %}

    {% for sql in statements %}
        {% do run_query(sql) %}
    {% endfor %}

    {{ return('select 1 as privacy_policies_applied') }}
{% endmacro %}
