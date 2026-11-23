{#- Use the layer name (staging, marts) as the schema everywhere, instead of dbt's
    default "<target_schema>_<custom_schema>". Terraform creates exactly these schemas. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
