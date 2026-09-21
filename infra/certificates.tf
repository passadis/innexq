# E1 is deliberately opt-in. Provision sources/identities, seed exact PDFs, deploy
# the team, then set an immutable agent version before enabling the customer API.
variable "certificate_infrastructure_enabled" {
  type    = bool
  default = false
}

variable "certificate_runtime_enabled" {
  type    = bool
  default = false
  validation {
    condition     = !var.certificate_runtime_enabled || (var.certificate_infrastructure_enabled && can(regex("^[1-9][0-9]*$", var.certificate_agent_version)))
    error_message = "Certificate runtime needs its infrastructure and a pinned deployed agent version."
  }
}

variable "certificate_agent_version" {
  type    = string
  default = ""
}

locals {
  customer_name   = "ca-${var.environment_name}-customer"
  customer_origin = "https://${local.customer_name}.${azurerm_container_app_environment.main.default_domain}"
  certificate_customer_bindings = {
    "b6491861-0f01-451a-aa40-fd1957c20747" = "DEMO-FAB"
    "89921dc2-cc4a-4e61-bfb5-c6ec807615a9" = "DEMO-NW"
  }
  certificate_api_env = var.certificate_infrastructure_enabled ? {
    INNEXQ_CERTIFICATES_ENABLED           = tostring(var.certificate_runtime_enabled)
    INNEXQ_CUSTOMER_ORIGINS               = jsonencode([local.customer_origin])
    INNEXQ_CUSTOMER_BINDINGS              = jsonencode(local.certificate_customer_bindings)
    INNEXQ_CERTIFICATE_BLOB_ENDPOINT      = azurerm_storage_account.main.primary_blob_endpoint
    INNEXQ_CERTIFICATE_CONTAINER          = "certificate-sources"
    INNEXQ_CERTIFICATE_READER_CLIENT_ID   = azurerm_user_assigned_identity.certificate_reader[0].client_id
    INNEXQ_DOCUMENT_INTELLIGENCE_ENDPOINT = azurerm_cognitive_account.documents[0].endpoint
    INNEXQ_CERTIFICATE_AGENT_NAME         = "innexq-certificate-team"
    INNEXQ_CERTIFICATE_AGENT_VERSION      = var.certificate_agent_version
  } : {}
}

resource "azapi_resource" "certificate_sources" {
  count     = var.certificate_infrastructure_enabled ? 1 : 0
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = "certificate-sources"
  parent_id = "${azurerm_storage_account.main.id}/blobServices/default"
  body      = { properties = { publicAccess = "None" } }
}

resource "azurerm_cognitive_account" "documents" {
  count                 = var.certificate_infrastructure_enabled ? 1 : 0
  name                  = "di-innexq-${local.suffix}"
  custom_subdomain_name = "di-innexq-${local.suffix}"
  resource_group_name   = azurerm_resource_group.main.name
  location              = var.location
  kind                  = "FormRecognizer"
  sku_name              = "S0"
  local_auth_enabled    = false
  tags                  = local.tags
}

resource "azurerm_user_assigned_identity" "certificate_reader" {
  count               = var.certificate_infrastructure_enabled ? 1 : 0
  name                = "id-${var.environment_name}-certificate-reader"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "certificate_blob_reader" {
  count                = var.certificate_infrastructure_enabled ? 1 : 0
  scope                = azapi_resource.certificate_sources[0].id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = azurerm_user_assigned_identity.certificate_reader[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "certificate_extraction" {
  count                = var.certificate_infrastructure_enabled ? 1 : 0
  scope                = azurerm_cognitive_account.documents[0].id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_user_assigned_identity.certificate_reader[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "certificate_seed" {
  count                = var.certificate_infrastructure_enabled ? 1 : 0
  scope                = azapi_resource.certificate_sources[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azuread_application" "customer" {
  count            = var.certificate_infrastructure_enabled ? 1 : 0
  display_name     = "${var.environment_name}-customer-portal"
  sign_in_audience = "AzureADMyOrg"
  owners           = [data.azurerm_client_config.current.object_id]
  single_page_application {
    redirect_uris = ["${local.customer_origin}/redirect.html"]
  }
  required_resource_access {
    resource_app_id = azuread_application.api.client_id
    resource_access {
      id   = "a85084b7-1e53-4bba-aef6-237da49e681b"
      type = "Scope"
    }
  }
}

resource "azuread_service_principal" "customer" {
  count                        = var.certificate_infrastructure_enabled ? 1 : 0
  client_id                    = azuread_application.customer[0].client_id
  app_role_assignment_required = true
  owners                       = [data.azurerm_client_config.current.object_id]
}

resource "azuread_app_role_assignment" "customer_login" {
  for_each            = var.certificate_infrastructure_enabled ? local.certificate_customer_bindings : {}
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = each.key
  resource_object_id  = azuread_service_principal.customer[0].object_id
}

resource "azuread_application_pre_authorized" "customer" {
  count                = var.certificate_infrastructure_enabled ? 1 : 0
  application_id       = azuread_application.api.id
  authorized_client_id = azuread_application.customer[0].client_id
  permission_ids       = ["a85084b7-1e53-4bba-aef6-237da49e681b"]
}

resource "azurerm_user_assigned_identity" "customer" {
  count               = var.certificate_infrastructure_enabled ? 1 : 0
  name                = "id-${var.environment_name}-customer"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "customer_acr" {
  count                = var.certificate_infrastructure_enabled ? 1 : 0
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.customer[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_container_app" "customer" {
  count                        = var.certificate_infrastructure_enabled ? 1 : 0
  name                         = local.customer_name
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"
  revision_mode                = "Single"
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.customer[0].id]
  }
  template {
    min_replicas = 0
    max_replicas = 1
    container {
      name   = "innexq-customer"
      image  = "mcr.microsoft.com/dotnet/samples:aspnetapp"
      cpu    = 0.25
      memory = "0.5Gi"
      dynamic "env" {
        for_each = {
          INNEXQ_WEB_TENANT_ID  = var.tenant_id
          INNEXQ_WEB_CLIENT_ID  = azuread_application.customer[0].client_id
          INNEXQ_WEB_API_ORIGIN = "https://${azurerm_container_app.api.ingress[0].fqdn}"
          INNEXQ_WEB_API_SCOPE  = "api://${azuread_application.api.client_id}/Certificates.Request"
        }
        content {
          name  = env.key
          value = env.value
        }
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
    ignore_changes = [template[0].container[0].image, template[0].revision_suffix, registry]
  }
  tags = merge(local.tags, { "azd-service-name" = "innexq-customer" })
}

output "INNEXQ_CUSTOMER_URL" {
  value = var.certificate_infrastructure_enabled ? local.customer_origin : ""
}
