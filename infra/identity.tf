# The API registration defines a token audience; no credential is created.
resource "azuread_application" "api" {
  lifecycle {
    # The identifier-uri child resource owns this self-referencing value.
    ignore_changes = [identifier_uris]
  }
  display_name     = "${var.environment_name}-api"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azurerm_client_config.current.object_id]
  api {
    requested_access_token_version = 2
    oauth2_permission_scope {
      id                         = "03c5a9e3-0c7c-4baa-9d4b-4f26ff22e517"
      enabled                    = true
      type                       = "Admin"
      value                      = "Cases.Manage"
      admin_consent_display_name = "Manage assigned InnexQ held cases"
      admin_consent_description  = "Assigned Operations may acknowledge, add internal notes and close without release. No PDF release, renewal approval, customer email or Graph authority."
    }
    dynamic "oauth2_permission_scope" {
      for_each = var.certificate_infrastructure_enabled ? [1] : []
      content {
        id                         = "a85084b7-1e53-4bba-aef6-237da49e681b"
        enabled                    = true
        type                       = "Admin"
        value                      = "Certificates.Request"
        admin_consent_display_name = "Request your existing InnexQ certificates"
        admin_consent_description  = "Assigned customers may request and download only their eligible existing PDFs. No employee, Graph or commercial authority."
      }
    }
    oauth2_permission_scope {
      id                         = "2a653db0-d8e4-433f-bc96-cec3f2c1f395"
      enabled                    = true
      type                       = "Admin"
      value                      = "Runs.Read"
      admin_consent_display_name = "Read your InnexQ Runs"
      admin_consent_description  = "Inspect only authorized Run evidence, briefs, events and receipts. Cannot trigger workflows or approvals."
    }
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
  dynamic "app_role" {
    for_each = var.evidence_identity_enabled ? [1] : []
    content {
      id                   = "70f53091-8400-4140-85ac-a4779e0ad4bc"
      allowed_member_types = ["Application"]
      description          = "Read only controller-scoped evidence through MCP. No workflow, release, Graph or execution authority."
      display_name         = "Evidence Read"
      enabled              = true
      value                = "Evidence.Read"
    }
  }
  dynamic "app_role" {
    for_each = var.renewal_identity_enabled ? [1] : []
    content {
      id                   = "5c9d4a3e-7b21-4f6e-9d08-1a2b3c4d5e6f"
      allowed_member_types = ["Application"]
      description          = "Read only controller-scoped Service Coverage Renewal evidence through MCP. No pricing authority, approval, document issuance, Graph or execution capability."
      display_name         = "Renewal Read"
      enabled              = true
      value                = "Renewal.Read"
    }
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
  scope = azapi_resource.project.id
  # Foundry User (formerly Azure AI User): stable ID avoids display-name rollout drift.
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
  principal_id       = azurerm_user_assigned_identity.api.principal_id
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "api_telemetry" {
  scope                = azurerm_application_insights.main.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "project_model" {
  scope              = azurerm_cognitive_account.main.id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
  principal_id       = azapi_resource.project.output.identity.principalId
  principal_type     = "ServicePrincipal"
}

resource "azurerm_role_assignment" "project_acr" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azapi_resource.project.output.identity.principalId
  principal_type       = "ServicePrincipal"
}

# Hosted agent containers export telemetry under the Foundry project identity.
# App Insights enforces Entra-only ingestion, so publish rights are mandatory.
resource "azurerm_role_assignment" "project_telemetry" {
  scope                = azurerm_application_insights.main.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = azapi_resource.project.output.identity.principalId
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "agent_telemetry" {
  count                = var.agent_principal_id == "" ? 0 : 1
  scope                = azurerm_application_insights.main.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = var.agent_principal_id
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
  scope              = azurerm_cognitive_account.main.id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
  principal_id       = data.azurerm_client_config.current.object_id
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
