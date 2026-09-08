locals {
  api_env = {
    INNEXQ_ENVIRONMENT                        = "dev"
    INNEXQ_TENANT_ID                          = var.tenant_id
    INNEXQ_API_AUDIENCE                       = azuread_application.api.client_id
    INNEXQ_APPROVER_USER_ID                   = var.approver_user_id
    INNEXQ_MANAGED_IDENTITY_CLIENT_ID         = azurerm_user_assigned_identity.api.client_id
    INNEXQ_AGENT_PRINCIPAL_ID                 = var.agent_principal_id
    INNEXQ_COSMOS_ENDPOINT                    = azurerm_cosmosdb_account.main.endpoint
    INNEXQ_COSMOS_DATABASE                    = azurerm_cosmosdb_sql_database.main.name
    INNEXQ_COSMOS_CONTAINER                   = azurerm_cosmosdb_sql_container.runs.name
    INNEXQ_GRAPH_SITE_ID                      = var.graph_site_id
    INNEXQ_GRAPH_DRIVE_ID                     = var.graph_drive_id
    INNEXQ_GRAPH_FOLDER_ID                    = var.graph_folder_id
    INNEXQ_SENDER_MAILBOX                     = "superuser@alfacloud.gr"
    INNEXQ_TEST_RECIPIENT                     = "passadis@outlook.com"
    INNEXQ_TEAMS_TEAM_ID                      = "ee42f3fa-d2aa-4033-99ef-bddea5363b46"
    INNEXQ_TEAMS_CHANNEL_ID                   = "19:f87553c02fda46978cf84bf2e965dcf3@thread.tacv2"
    INNEXQ_FOUNDRY_PROJECT_ENDPOINT           = "https://${azurerm_cognitive_account.main.custom_subdomain_name}.services.ai.azure.com/api/projects/${azapi_resource.project.name}"
    INNEXQ_FOUNDRY_AGENT_NAME                 = "innexq-agent"
    AZURE_CLIENT_ID                           = azurerm_user_assigned_identity.api.client_id
    APPLICATIONINSIGHTS_AUTHENTICATION_STRING = "Authorization=AAD;ClientId=${azurerm_user_assigned_identity.api.client_id}"
  }
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.environment_name}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${var.environment_name}-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.api.id]
  }
  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.api.id
  }
  secret {
    name  = "applicationinsights-connection-string" # pragma: allowlist secret
    value = azurerm_application_insights.main.connection_string
  }
  template {
    min_replicas = 0
    max_replicas = 1
    container {
      name = "innexq-api"
      # azd replaces this only after the real image has been built and pushed.
      image  = "mcr.microsoft.com/dotnet/samples:aspnetapp"
      cpu    = 0.5
      memory = "1Gi"
      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }
      env {
        name        = "APPLICATIONINSIGHTS_CONNECTION_STRING"
        secret_name = "applicationinsights-connection-string" # pragma: allowlist secret
      }
      liveness_probe {
        transport = "TCP"
        port      = 8080
      }
      readiness_probe {
        transport = "TCP"
        port      = 8080
      }
    }
  }
  ingress {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8080
    transport                  = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
  depends_on = [azurerm_role_assignment.api_acr]
  tags       = merge(local.tags, { "azd-service-name" = "innexq-api" })
}

resource "azurerm_bot_service_azure_bot" "main" {
  name                         = "bot-innexq-${local.suffix}"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = "westeurope"
  sku                          = "F0"
  display_name                 = "InnexQ Approvals"
  microsoft_app_type           = "UserAssignedMSI"
  microsoft_app_id             = azurerm_user_assigned_identity.api.client_id
  microsoft_app_msi_id         = azurerm_user_assigned_identity.api.id
  microsoft_app_tenant_id      = var.tenant_id
  local_authentication_enabled = false
  endpoint                     = "https://${azurerm_container_app.api.ingress[0].fqdn}/api/messages"
  tags                         = local.tags
}

resource "azurerm_bot_channel_ms_teams" "main" {
  bot_name            = azurerm_bot_service_azure_bot.main.name
  location            = azurerm_bot_service_azure_bot.main.location
  resource_group_name = azurerm_resource_group.main.name
}
