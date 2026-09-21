locals {
  web_name   = "ca-${var.environment_name}-web"
  web_origin = "https://${local.web_name}.${azurerm_container_app_environment.main.default_domain}"
}

resource "azuread_application" "web" {
  display_name     = "${var.environment_name}-control-room"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azurerm_client_config.current.object_id]
  single_page_application {
    redirect_uris = ["${local.web_origin}/redirect.html"]
  }
  required_resource_access {
    resource_app_id = azuread_application.api.client_id
    resource_access {
      id   = "2a653db0-d8e4-433f-bc96-cec3f2c1f395"
      type = "Scope"
    }
    resource_access {
      id   = "03c5a9e3-0c7c-4baa-9d4b-4f26ff22e517"
      type = "Scope"
    }
  }
}

resource "azuread_service_principal" "web" {
  client_id = azuread_application.web.client_id
  owners    = [data.azurerm_client_config.current.object_id]
}

resource "azuread_application_pre_authorized" "web" {
  application_id       = azuread_application.api.id
  authorized_client_id = azuread_application.web.client_id
  permission_ids       = ["2a653db0-d8e4-433f-bc96-cec3f2c1f395", "03c5a9e3-0c7c-4baa-9d4b-4f26ff22e517"]
}

# The static web host can pull its image; it has no workflow/data-plane permissions.
resource "azurerm_user_assigned_identity" "web" {
  name                = "id-${var.environment_name}-web"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "web_acr" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.web.principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_container_app" "web" {
  name                         = local.web_name
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  revision_mode                = "Single"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.web.id]
  }
  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.web.id
  }
  template {
    min_replicas = 0
    max_replicas = 1
    container {
      name   = "innexq-web"
      image  = "mcr.microsoft.com/dotnet/samples:aspnetapp"
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name  = "INNEXQ_WEB_TENANT_ID"
        value = var.tenant_id
      }
      env {
        name  = "INNEXQ_WEB_CLIENT_ID"
        value = azuread_application.web.client_id
      }
      env {
        name  = "INNEXQ_WEB_API_ORIGIN"
        value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
      }
      env {
        name  = "INNEXQ_WEB_API_SCOPE"
        value = "api://${azuread_application.api.client_id}/Runs.Read"
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
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
  lifecycle {
    ignore_changes = [template[0].container[0].image, template[0].revision_suffix]
  }
  tags = merge(local.tags, { "azd-service-name" = "innexq-web" })
}

output "INNEXQ_WEB_URL" {
  value = local.web_origin
}

output "INNEXQ_WEB_CLIENT_ID" {
  value = azuread_application.web.client_id
}
