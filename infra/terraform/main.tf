locals {
  db_name        = var.project_prefix
  warehouse_name = "${var.project_prefix}_WH"
  schemas = {
    RAW     = "Landing zone. Append-only, rows exactly as received from sources."
    STAGING = "Typed, deduplicated, renamed. One model per source table (dbt)."
    MARTS   = "Business-ready models read by the API and the MCP server (dbt)."
  }
}

resource "snowflake_database" "elkollen" {
  name                        = local.db_name
  comment                     = "Elkollen: Swedish 15-minute electricity prices. Managed by Terraform."
  data_retention_time_in_days = 1
}

resource "snowflake_schema" "layer" {
  for_each = local.schemas

  database = snowflake_database.elkollen.name
  name     = each.key
  comment  = each.value
}

# Cost guardrail: the only warehouse the project uses is capped by this monitor.
resource "snowflake_resource_monitor" "elkollen" {
  name            = "${var.project_prefix}_MONITOR"
  credit_quota    = var.monthly_credit_quota
  frequency       = "MONTHLY"
  start_timestamp = "IMMEDIATELY"

  notify_triggers           = [50, 80]
  suspend_trigger           = 90
  suspend_immediate_trigger = 100
}

resource "snowflake_warehouse" "elkollen" {
  name                = local.warehouse_name
  warehouse_size      = "XSMALL"
  auto_suspend        = 60
  auto_resume         = "true"
  initially_suspended = true
  resource_monitor    = snowflake_resource_monitor.elkollen.name
  comment             = "Elkollen compute. Suspends after 60 s idle; capped by ${snowflake_resource_monitor.elkollen.name}."
}
