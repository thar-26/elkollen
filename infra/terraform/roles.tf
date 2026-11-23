# Three least-privilege roles:
#   LOADER      - ingestion: writes RAW only
#   TRANSFORMER - dbt: reads RAW, owns objects in STAGING and MARTS
#   READER      - API and MCP server: reads MARTS only (row access policies are added in phase 3/5)

locals {
  roles = {
    LOADER      = "Ingestion jobs. Insert-only access to RAW."
    TRANSFORMER = "dbt. Reads RAW, builds STAGING and MARTS."
    READER      = "API and MCP server. Read-only access to MARTS."
  }

  role_names = { for k, _ in local.roles : k => "${var.project_prefix}_${k}" }

  service_users = {
    LOADER      = var.loader_rsa_public_key
    TRANSFORMER = var.transformer_rsa_public_key
    READER      = var.reader_rsa_public_key
  }

  raw     = snowflake_schema.layer["RAW"].fully_qualified_name
  staging = snowflake_schema.layer["STAGING"].fully_qualified_name
  marts   = snowflake_schema.layer["MARTS"].fully_qualified_name

  # schema-level privileges per role
  schema_grants = {
    loader_raw          = { role = "LOADER", schema = local.raw, privileges = ["USAGE", "CREATE TABLE"] }
    transformer_raw     = { role = "TRANSFORMER", schema = local.raw, privileges = ["USAGE"] }
    transformer_staging = { role = "TRANSFORMER", schema = local.staging, privileges = ["USAGE", "CREATE TABLE", "CREATE VIEW"] }
    transformer_marts   = { role = "TRANSFORMER", schema = local.marts, privileges = ["USAGE", "CREATE TABLE", "CREATE VIEW"] }
    reader_marts        = { role = "READER", schema = local.marts, privileges = ["USAGE"] }
  }

  # object-level privileges, applied to existing ("all") and future objects
  object_grants = {
    loader_raw_tables      = { role = "LOADER", schema = local.raw, plural = "TABLES", privileges = ["SELECT", "INSERT"] }
    transformer_raw_tables = { role = "TRANSFORMER", schema = local.raw, plural = "TABLES", privileges = ["SELECT"] }
    reader_marts_tables    = { role = "READER", schema = local.marts, plural = "TABLES", privileges = ["SELECT"] }
    reader_marts_views     = { role = "READER", schema = local.marts, plural = "VIEWS", privileges = ["SELECT"] }
  }
}

resource "snowflake_account_role" "role" {
  for_each = local.roles
  name     = local.role_names[each.key]
  comment  = each.value
}

# Keep the custom roles inside the standard hierarchy so SYSADMIN can manage their objects.
resource "snowflake_grant_account_role" "to_sysadmin" {
  for_each         = local.roles
  role_name        = snowflake_account_role.role[each.key].name
  parent_role_name = "SYSADMIN"
}

resource "snowflake_grant_privileges_to_account_role" "database_usage" {
  for_each          = local.roles
  account_role_name = snowflake_account_role.role[each.key].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.elkollen.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "warehouse_usage" {
  for_each          = local.roles
  account_role_name = snowflake_account_role.role[each.key].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.elkollen.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "schema" {
  for_each          = local.schema_grants
  account_role_name = snowflake_account_role.role[each.value.role].name
  privileges        = each.value.privileges
  on_schema {
    schema_name = each.value.schema
  }
}

resource "snowflake_grant_privileges_to_account_role" "existing_objects" {
  for_each          = local.object_grants
  account_role_name = snowflake_account_role.role[each.value.role].name
  privileges        = each.value.privileges
  on_schema_object {
    all {
      object_type_plural = each.value.plural
      in_schema          = each.value.schema
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "future_objects" {
  for_each          = local.object_grants
  account_role_name = snowflake_account_role.role[each.value.role].name
  privileges        = each.value.privileges
  on_schema_object {
    future {
      object_type_plural = each.value.plural
      in_schema          = each.value.schema
    }
  }
}

# Service users authenticate with key pairs only (no passwords).
resource "snowflake_service_user" "svc" {
  for_each          = local.service_users
  name              = "${var.project_prefix}_${each.key}_SVC"
  comment           = "Service user for ${local.role_names[each.key]}. Key-pair auth only."
  default_role      = snowflake_account_role.role[each.key].name
  default_warehouse = snowflake_warehouse.elkollen.name
  rsa_public_key    = each.value
}

resource "snowflake_grant_account_role" "to_service_user" {
  for_each  = local.service_users
  role_name = snowflake_account_role.role[each.key].name
  user_name = snowflake_service_user.svc[each.key].name
}
