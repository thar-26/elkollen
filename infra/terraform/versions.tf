terraform {
  required_version = ">= 1.6"

  required_providers {
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 2.0"
    }
  }

  # State is local by default and git-ignored. For a shared setup, configure a
  # remote backend (encrypted bucket). State holds object names, not passwords.
}

# Connection settings come from environment variables, never from this repo:
#   SNOWFLAKE_ORGANIZATION_NAME, SNOWFLAKE_ACCOUNT_NAME, SNOWFLAKE_USER,
#   SNOWFLAKE_ROLE, SNOWFLAKE_AUTHENTICATOR=SNOWFLAKE_JWT
# and the admin private key, read from the path in var.admin_private_key_path.
provider "snowflake" {
  private_key = var.admin_private_key_path == "" ? null : file(var.admin_private_key_path)
}
