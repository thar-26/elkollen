variable "admin_private_key_path" {
  description = "Path to the PKCS#8 private key of the admin user running Terraform. Empty = let the provider read SNOWFLAKE_PRIVATE_KEY or use another authenticator."
  type        = string
  default     = ""
}

variable "project_prefix" {
  description = "Prefix for every Snowflake object, so the project never collides with other work in the account."
  type        = string
  default     = "ELKOLLEN"
}

variable "monthly_credit_quota" {
  description = "Hard monthly credit budget for the project warehouse. The warehouse is suspended at 100%."
  type        = number
  default     = 5

  validation {
    condition     = var.monthly_credit_quota > 0 && var.monthly_credit_quota <= 50
    error_message = "Keep the quota between 1 and 50 credits; this is a portfolio project."
  }
}

variable "loader_rsa_public_key" {
  description = "Public key (body only, no BEGIN/END lines) for the ingestion service user."
  type        = string
  sensitive   = true
}

variable "transformer_rsa_public_key" {
  description = "Public key (body only) for the dbt service user."
  type        = string
  sensitive   = true
}

variable "reader_rsa_public_key" {
  description = "Public key (body only) for the API/MCP read-only service user."
  type        = string
  sensitive   = true
}
