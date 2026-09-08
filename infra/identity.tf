# The API registration defines a token audience; no credential is created.
resource "azuread_application" "api" {
  display_name     = "${var.environment_name}-api"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azurerm_client_config.current.object_id]
  api {
    requested_access_token_version = 2
    oauth2_permission_scope {
      id                         = "ae5979f3-847e-4b24-aeee-03783e296d5d"
      enabled                    = true
      type                       = "Admin"
      value                      = "user_impersonation"
      admin_consent_display_name = "Operate InnexQ as the signed-in user"
      admin_consent_description  = "Call the InnexQ controller, subject to its configured tenant and user authorization."
    }
  }
  app_role {
    id                   = "a2c27a16-2e11-4e33-a650-edde1ef02e07"
    allowed_member_types = ["Application"]
    description          = "Call only the deterministic pricing and authority read surface."
    display_name         = "Pricing Read"
    enabled              = true
    value                = "Pricing.Read"
  }
}

resource "azuread_application_identifier_uri" "api" {
  application_id = azuread_application.api.id
  identifier_uri = "api://${azuread_application.api.client_id}"
}

resource "azuread_service_principal" "api" {
  client_id = azuread_application.api.client_id
  owners    = [data.azurerm_client_config.current.object_id]
}

# Explicit delegated scope enables the authenticated owner's CLI smoke harness.
resource "azuread_application_pre_authorized" "cli" {
  application_id       = azuread_application.api.id
  authorized_client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
  permission_ids       = ["ae5979f3-847e-4b24-aeee-03783e296d5d"]
}

data "azuread_service_principal" "graph" {
  client_id = "00000003-0000-0000-c000-000000000000"
}

# Sites.Selected alone grants no site access. Bootstrap supplies the one-site grant.
# Mail permission is mailbox-scoped Exchange application RBAC, never Graph Mail.Send.
resource "azuread_app_role_assignment" "site_selected" {
  app_role_id         = data.azuread_service_principal.graph.app_role_ids["Sites.Selected"]
  principal_object_id = azurerm_user_assigned_identity.api.principal_id
  resource_object_id  = data.azuread_service_principal.graph.object_id
}

resource "azurerm_cosmosdb_sql_role_assignment" "api" {
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.api.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.main.name}/colls/${azurerm_cosmosdb_sql_container.runs.name}"
}

resource "azurerm_role_assignment" "api_acr" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "api_artifacts" {
  scope                = azapi_resource.blob_container["artifacts"].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "api_foundry" {
  scope                = azapi_resource.project.id
  role_definition_name = "Azure AI User"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "api_telemetry" {
  scope                = azurerm_application_insights.main.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "project_model" {
  scope                = azurerm_cognitive_account.main.id
  role_definition_name = "Azure AI User"
  principal_id         = azapi_resource.project.output.identity.principalId
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "project_acr" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azapi_resource.project.output.identity.principalId
  principal_type       = "ServicePrincipal"
}

# The bootstrap identity can seed only the new corpus/search resources.
resource "azurerm_role_assignment" "seed_corpus" {
  scope                = azapi_resource.blob_container["corpus"].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "seed_search" {
  for_each             = toset(["Search Service Contributor", "Search Index Data Contributor"])
  scope                = azurerm_search_service.main.id
  role_definition_name = each.key
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "deployer_foundry" {
  scope                = azurerm_cognitive_account.main.id
  role_definition_name = "Azure AI User"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "agent_search" {
  count                = var.agent_principal_id == "" ? 0 : 1
  scope                = azurerm_search_service.main.id
  role_definition_name = "Search Index Data Reader"
  principal_id         = var.agent_principal_id
  principal_type       = "ServicePrincipal"
}

resource "azuread_app_role_assignment" "agent_pricing" {
  count               = var.agent_principal_id == "" ? 0 : 1
  app_role_id         = "a2c27a16-2e11-4e33-a650-edde1ef02e07"
  principal_object_id = var.agent_principal_id
  resource_object_id  = azuread_service_principal.api.object_id
}
