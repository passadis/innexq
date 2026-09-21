locals {
  suffix = substr(sha256("${var.subscription_id}/${var.environment_name}"), 0, 8)
  tags   = merge(var.tags, { "azd-env-name" = var.environment_name })
}

data "azurerm_client_config" "current" {}

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.environment_name}-swc"
  location = var.location
  tags     = local.tags
}

resource "azurerm_user_assigned_identity" "api" {
  name                = "id-${var.environment_name}-api"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  tags                = local.tags
}

resource "azurerm_container_registry" "main" {
  name                = "acrinnexq${local.suffix}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${var.environment_name}"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_application_insights" "main" {
  name                         = "appi-${var.environment_name}"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = var.location
  application_type             = "web"
  workspace_id                 = azurerm_log_analytics_workspace.main.id
  local_authentication_enabled = false
  retention_in_days            = 30
  tags                         = local.tags
}

resource "azurerm_cosmosdb_account" "main" {
  name                         = "cosmos-innexq-${local.suffix}"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = var.location
  offer_type                   = "Standard"
  kind                         = "GlobalDocumentDB"
  local_authentication_enabled = false
  minimal_tls_version          = "Tls12"
  capabilities {
    name = "EnableServerless"
  }
  consistency_policy {
    consistency_level = "Session"
  }
  geo_location {
    location          = var.location
    failover_priority = 0
  }
  tags = local.tags
}

resource "azurerm_cosmosdb_sql_database" "main" {
  name                = "innexq"
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
}

resource "azurerm_cosmosdb_sql_container" "runs" {
  name                  = "runs"
  resource_group_name   = azurerm_resource_group.main.name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/run_id"]
  partition_key_version = 2
}

resource "azurerm_storage_account" "main" {
  name                            = "stinnexq${local.suffix}"
  resource_group_name             = azurerm_resource_group.main.name
  location                        = var.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  local_user_enabled              = false
  default_to_oauth_authentication = true
  blob_properties {
    versioning_enabled = true
    delete_retention_policy {
      days = 7
    }
    container_delete_retention_policy {
      days = 7
    }
  }
  tags = local.tags
}

# ARM container resources avoid data-plane key access during provisioning.
resource "azapi_resource" "blob_container" {
  for_each  = toset(["corpus", "artifacts"])
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = each.key
  parent_id = "${azurerm_storage_account.main.id}/blobServices/default"
  body = {
    properties = { publicAccess = "None" }
  }
}

resource "azurerm_search_service" "main" {
  name                         = "search-innexq-${local.suffix}"
  resource_group_name          = azurerm_resource_group.main.name
  location                     = var.location
  sku                          = "free"
  local_authentication_enabled = false
  # Free supports incoming Entra RBAC, not an outbound service managed identity.
  # Extractive GA knowledge-base retrieval makes no outbound model calls.
  lifecycle {
    # AzureRM 4.81 rejects Free-tier semantic settings; the ARM patch below owns this.
    ignore_changes = [semantic_search_sku]
  }
  tags = local.tags
}

# Narrow PATCH: no resource replacement, key auth, SKU change or paid billing consent.
# https://learn.microsoft.com/azure/search/semantic-how-to-enable-disable
resource "azapi_update_resource" "search_free_semantic" {
  type        = "Microsoft.Search/searchServices@2026-03-01-preview"
  resource_id = azurerm_search_service.main.id
  body = {
    properties = { semanticSearch = "free" }
  }
}

resource "azurerm_cognitive_account" "main" {
  name                       = "ai-innexq-${local.suffix}"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = var.location
  kind                       = "AIServices"
  sku_name                   = "S0"
  custom_subdomain_name      = "ai-innexq-${local.suffix}"
  project_management_enabled = true
  local_auth_enabled         = false
  identity {
    type = "SystemAssigned"
  }
  tags = local.tags
}

# Verified ARM schema: learn.microsoft.com/azure/templates/microsoft.cognitiveservices/2025-06-01/accounts/projects
resource "azapi_resource" "project" {
  # Foundry rejects concurrent child writes while a model deployment is in progress.
  depends_on = [azurerm_cognitive_deployment.reasoning]
  type       = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name       = "innexq-project"
  parent_id  = azurerm_cognitive_account.main.id
  location   = var.location
  identity {
    type = "SystemAssigned"
  }
  body = {
    properties = {
      displayName = "InnexQ"
      description = "Governed enterprise workflows: Contract Renewal Phase 1"
    }
  }
  response_export_values = ["identity.principalId", "properties.endpoints"]
  tags                   = local.tags
}

resource "azurerm_cognitive_deployment" "reasoning" {
  name                   = "gpt-5.4-mini"
  cognitive_account_id   = azurerm_cognitive_account.main.id
  version_upgrade_option = "NoAutoUpgrade"
  model {
    format  = "OpenAI"
    name    = "gpt-5.4-mini"
    version = "2026-03-17"
  }
  sku {
    name     = "GlobalStandard"
    capacity = 10
  }
}
