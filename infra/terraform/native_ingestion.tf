# Snowflake-native price ingestion (hybrid design, see docs/decisions/0002).
#
# OFF by default. Snowflake trial accounts do not allow external network access, so
# until the account is upgraded (or Snowflake support enables it) prices are fetched
# by the scheduled GitHub workflow and loaded with the LOADER user. Turning this on:
#   terraform apply -var enable_native_ingestion=true
# then set the GitHub variable SNOWFLAKE_NATIVE_INGESTION=true so the workflow stops
# fetching and only runs dbt.
#
# The procedure body is elpris.py + snowflake_proc.py from this repo, unchanged; the
# same concatenation is executed in tests/ingest/test_snowflake_proc.py.

variable "enable_native_ingestion" {
  description = "Create the network rule, external access integration, procedure and task that fetch prices from inside Snowflake. Needs an account with external network access."
  type        = bool
  default     = false
}

locals {
  native = var.enable_native_ingestion ? 1 : 0

  proc_source_files = [
    "${path.module}/../../src/elkollen_ingest/elpris.py",
    "${path.module}/../../src/elkollen_ingest/snowflake_proc.py",
  ]
}

# Egress to exactly one host. Nothing else is reachable from the procedure.
resource "snowflake_network_rule" "elpris_api" {
  count      = local.native
  database   = snowflake_database.elkollen.name
  schema     = snowflake_schema.layer["RAW"].name
  name       = "ELPRIS_API_EGRESS"
  type       = "HOST_PORT"
  mode       = "EGRESS"
  value_list = ["www.elprisetjustnu.se:443"]
  comment    = "Only host the price ingestion procedure may call."
}

resource "snowflake_external_access_integration" "elpris_api" {
  count                 = local.native
  name                  = "${var.project_prefix}_ELPRIS_API_ACCESS"
  allowed_network_rules = [snowflake_network_rule.elpris_api[0].fully_qualified_name]
  enabled               = true
  comment               = "Lets RAW.INGEST_PRICES reach the elprisetjustnu.se API."
}

resource "snowflake_procedure_python" "ingest_prices" {
  count    = local.native
  database = snowflake_database.elkollen.name
  schema   = snowflake_schema.layer["RAW"].name
  name     = "INGEST_PRICES"

  arguments {
    arg_name          = "DAYS_BACK"
    arg_data_type     = "NUMBER"
    arg_default_value = "0"
  }
  arguments {
    arg_name          = "DAYS_AHEAD"
    arg_data_type     = "NUMBER"
    arg_default_value = "1"
  }

  return_type                  = "VARCHAR"
  runtime_version              = "3.12"
  snowpark_package             = "snowflake-snowpark-python"
  packages                     = ["httpx==0.28.1", "pydantic==2.14.1", "tzdata"]
  handler                      = "run"
  procedure_definition         = join("\n", [for f in local.proc_source_files : file(f)])
  external_access_integrations = [snowflake_external_access_integration.elpris_api[0].name]
  execute_as                   = "OWNER"
  comment                      = "Fetch day-ahead prices (today, tomorrow) and append to RAW.ELPRIS_PRICES."
}

# Runs on the project warehouse, so it is covered by the resource monitor's credit cap
# (serverless tasks are not covered by resource monitors).
resource "snowflake_task" "ingest_prices" {
  count     = local.native
  database  = snowflake_database.elkollen.name
  schema    = snowflake_schema.layer["RAW"].name
  name      = "INGEST_PRICES_DAILY"
  warehouse = snowflake_warehouse.elkollen.name

  # Tomorrow's prices are published from about 13:00 Stockholm time; the second run
  # catches a late publication. Timezone-aware, so DST needs no manual change.
  schedule {
    using_cron = "20 13,16 * * * Europe/Stockholm"
  }

  sql_statement                   = "CALL ${snowflake_database.elkollen.name}.RAW.INGEST_PRICES(0, 1)"
  started                         = true
  suspend_task_after_num_failures = 4
  user_task_timeout_ms            = 600000
  comment                         = "Twice-daily price ingestion. Failures are visible in TASK_HISTORY."
}

# Least privilege: the procedure and task belong to the LOADER role, which can only
# write RAW, use this one integration and run tasks.
resource "snowflake_grant_privileges_to_account_role" "loader_integration_usage" {
  count             = local.native
  account_role_name = snowflake_account_role.role["LOADER"].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "INTEGRATION"
    object_name = snowflake_external_access_integration.elpris_api[0].name
  }
}

resource "snowflake_grant_privileges_to_account_role" "loader_execute_task" {
  count             = local.native
  account_role_name = snowflake_account_role.role["LOADER"].name
  privileges        = ["EXECUTE TASK"]
  on_account        = true
}

resource "snowflake_grant_ownership" "ingest_procedure" {
  count             = local.native
  account_role_name = snowflake_account_role.role["LOADER"].name
  on {
    object_type = "PROCEDURE"
    object_name = snowflake_procedure_python.ingest_prices[0].fully_qualified_name
  }
  depends_on = [snowflake_grant_privileges_to_account_role.loader_integration_usage]
}

resource "snowflake_grant_ownership" "ingest_task" {
  count             = local.native
  account_role_name = snowflake_account_role.role["LOADER"].name
  on {
    object_type = "TASK"
    object_name = snowflake_task.ingest_prices[0].fully_qualified_name
  }
  depends_on = [
    snowflake_grant_ownership.ingest_procedure,
    snowflake_grant_privileges_to_account_role.loader_execute_task,
  ]
}
