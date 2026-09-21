output "AZURE_RESOURCE_GROUP" {
  value = azurerm_resource_group.main.name
}
output "AZURE_CONTAINER_REGISTRY_NAME" {
  value = azurerm_container_registry.main.name
}
output "AZURE_CONTAINER_REGISTRY_ENDPOINT" {
  value = azurerm_container_registry.main.login_server
}
output "AZURE_CONTAINER_REGISTRY_ID" {
  value = azurerm_container_registry.main.id
}
output "AZURE_CONTAINER_APPS_ENVIRONMENT_ID" {
  value = azurerm_container_app_environment.main.id
}
output "AZURE_INNEXQ_API_NAME" {
  value = azurerm_container_app.api.name
}
output "INNEXQ_API_URL" {
  value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}
output "INNEXQ_API_AUDIENCE" {
  value = azuread_application.api.client_id
}
output "INNEXQ_API_APP_OBJECT_ID" {
  value = azuread_application.api.object_id
}
output "INNEXQ_API_SERVICE_PRINCIPAL_ID" {
  value = azuread_service_principal.api.object_id
}
output "INNEXQ_API_SCOPE" {
  value = "api://${azuread_application.api.client_id}/.default"
}
output "INNEXQ_MANAGED_IDENTITY_CLIENT_ID" {
  value = azurerm_user_assigned_identity.api.client_id
}
output "INNEXQ_MANAGED_IDENTITY_PRINCIPAL_ID" {
  value = azurerm_user_assigned_identity.api.principal_id
}
output "INNEXQ_MANAGED_IDENTITY_RESOURCE_ID" {
  value = azurerm_user_assigned_identity.api.id
}
output "INNEXQ_TENANT_ID" {
  value = var.tenant_id
}
output "INNEXQ_APPROVER_USER_ID" {
  value = var.approver_user_id
}
output "INNEXQ_COSMOS_ENDPOINT" {
  value = azurerm_cosmosdb_account.main.endpoint
}
output "INNEXQ_COSMOS_ACCOUNT_NAME" {
  value = azurerm_cosmosdb_account.main.name
}
output "INNEXQ_COSMOS_DATABASE" {
  value = azurerm_cosmosdb_sql_database.main.name
}
output "INNEXQ_COSMOS_CONTAINER" {
  value = azurerm_cosmosdb_sql_container.runs.name
}
output "AZURE_STORAGE_ACCOUNT_NAME" {
  value = azurerm_storage_account.main.name
}
output "AZURE_STORAGE_BLOB_ENDPOINT" {
  value = azurerm_storage_account.main.primary_blob_endpoint
}
output "AZURE_AI_SEARCH_NAME" {
  value = azurerm_search_service.main.name
}
output "AZURE_AI_SEARCH_ENDPOINT" {
  value = azurerm_search_service.main.endpoint
}
output "AZURE_AI_SEARCH_ID" {
  value = azurerm_search_service.main.id
}
output "AZURE_AI_ACCOUNT_NAME" {
  value = azurerm_cognitive_account.main.name
}
output "AZURE_AI_ACCOUNT_ID" {
  value = azurerm_cognitive_account.main.id
}
output "AZURE_AI_ACCOUNT_PRINCIPAL_ID" {
  value = azurerm_cognitive_account.main.identity[0].principal_id
}
output "AZURE_AI_PROJECT_NAME" {
  value = azapi_resource.project.name
}
output "AZURE_AI_PROJECT_ID" {
  value = azapi_resource.project.id
}
output "AZURE_AI_PROJECT_ENDPOINT" {
  value = local.api_env.INNEXQ_FOUNDRY_PROJECT_ENDPOINT
}
output "FOUNDRY_PROJECT_ENDPOINT" {
  # Current azd agent commands resolve this name; retain the Azure alias above.
  value = local.api_env.INNEXQ_FOUNDRY_PROJECT_ENDPOINT
}
output "AZURE_AI_PROJECT_PRINCIPAL_ID" {
  value = azapi_resource.project.output.identity.principalId
}
output "AZURE_AI_MODEL_DEPLOYMENT_NAME" {
  value = azurerm_cognitive_deployment.reasoning.name
}
output "APPLICATIONINSIGHTS_CONNECTION_STRING" {
  value     = azurerm_application_insights.main.connection_string
  sensitive = true
}
output "APPLICATIONINSIGHTS_RESOURCE_ID" {
  value = azurerm_application_insights.main.id
}
output "INNEXQ_BOT_NAME" {
  value = azurerm_bot_service_azure_bot.main.name
}
