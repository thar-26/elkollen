output "database" {
  value = snowflake_database.elkollen.name
}

output "warehouse" {
  value = snowflake_warehouse.elkollen.name
}

output "service_users" {
  description = "Service user per role. Put these names in .env (ELKOLLEN_SF_*_USER)."
  value       = { for k, u in snowflake_service_user.svc : k => u.name }
}
