# ADR-018: Service Coverage Renewal identity gates, separate from Evidence.Read.
# Role provisioning and runtime cutover are deliberately separate owner-run gates.
variable "renewal_identity_enabled" {
  type    = bool
  default = false
}

variable "renewal_agent_principal_id" {
  type    = string
  default = ""
  validation {
    condition     = !var.renewal_identity_enabled || length(var.renewal_agent_principal_id) == 36
    error_message = "Renewal.Read requires the owner-verified renewal agent service principal object id."
  }
}

data "azuread_service_principal" "renewal_agent" {
  count     = var.renewal_identity_enabled ? 1 : 0
  object_id = var.renewal_agent_principal_id
}

resource "azuread_app_role_assignment" "renewal_read" {
  count               = var.renewal_identity_enabled ? 1 : 0
  app_role_id         = "5c9d4a3e-7b21-4f6e-9d08-1a2b3c4d5e6f"
  principal_object_id = data.azuread_service_principal.renewal_agent[0].object_id
  resource_object_id  = azuread_service_principal.api.object_id
  depends_on          = [azuread_application.api]
}

# Storage and state for issued coverage are a separate opt-in from the identity gate.
# The runtime gate additionally requires a pinned, deployed renewal agent version.
variable "renewal_infrastructure_enabled" {
  type    = bool
  default = false
}

variable "renewal_runtime_enabled" {
  type    = bool
  default = false
  validation {
    condition     = !var.renewal_runtime_enabled || (var.renewal_infrastructure_enabled && var.renewal_identity_enabled && can(regex("^[1-9][0-9]*$", var.renewal_agent_version)))
    error_message = "Renewal runtime needs its infrastructure, the identity gate, and a pinned deployed agent version."
  }
}

variable "renewal_agent_version" {
  type    = string
  default = ""
}

# A dedicated Cosmos container (ADR-018 D7): coverage state never shares the runs
# partition space, and the API identity is scoped to this container alone.
resource "azurerm_cosmosdb_sql_container" "coverage" {
  count                 = var.renewal_infrastructure_enabled ? 1 : 0
  name                  = "coverage"
  resource_group_name   = azurerm_resource_group.main.name
  account_name          = azurerm_cosmosdb_account.main.name
  database_name         = azurerm_cosmosdb_sql_database.main.name
  partition_key_paths   = ["/run_id"]
  partition_key_version = 2
}

resource "azurerm_cosmosdb_sql_role_assignment" "coverage" {
  count               = var.renewal_infrastructure_enabled ? 1 : 0
  resource_group_name = azurerm_resource_group.main.name
  account_name        = azurerm_cosmosdb_account.main.name
  role_definition_id  = "${azurerm_cosmosdb_account.main.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002"
  principal_id        = azurerm_user_assigned_identity.api.principal_id
  scope               = "${azurerm_cosmosdb_account.main.id}/dbs/${azurerm_cosmosdb_sql_database.main.name}/colls/${azurerm_cosmosdb_sql_container.coverage[0].name}"
}

# Issued coverage documents are written by the isolated executor via the API identity.
resource "azapi_resource" "issued_coverage" {
  count     = var.renewal_infrastructure_enabled ? 1 : 0
  type      = "Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01"
  name      = "issued-coverage"
  parent_id = "${azurerm_storage_account.main.id}/blobServices/default"
  body      = { properties = { publicAccess = "None" } }
}

resource "azurerm_role_assignment" "issued_coverage_writer" {
  count                = var.renewal_infrastructure_enabled ? 1 : 0
  scope                = azapi_resource.issued_coverage[0].id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.api.principal_id
  principal_type       = "ServicePrincipal"
}

locals {
  # Owner-approved, read-only Manager identity for the two-person renewal gate.
  renewal_operations_object_id = var.approver_user_id
  renewal_manager_object_id    = "4243bff0-ef6a-4c2a-a3ae-8ee20fd4a1b8"
  renewal_api_env = var.renewal_infrastructure_enabled ? {
    INNEXQ_RENEWAL_ENABLED              = tostring(var.renewal_runtime_enabled)
    INNEXQ_RENEWAL_COVERAGE_CONTAINER   = azurerm_cosmosdb_sql_container.coverage[0].name
    INNEXQ_RENEWAL_ISSUED_CONTAINER     = "issued-coverage"
    INNEXQ_RENEWAL_BLOB_ENDPOINT        = azurerm_storage_account.main.primary_blob_endpoint
    INNEXQ_RENEWAL_OPERATIONS_OBJECT_ID = local.renewal_operations_object_id
    INNEXQ_RENEWAL_MANAGER_OBJECT_ID    = local.renewal_manager_object_id
    INNEXQ_RENEWAL_AGENT_NAME           = "innexq-renewal-coordinator"
    INNEXQ_RENEWAL_AGENT_VERSION        = var.renewal_agent_version
  } : {}
}

