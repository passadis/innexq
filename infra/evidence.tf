# ADR-017: role provisioning and runtime cutover are deliberately separate gates.
variable "evidence_identity_enabled" {
  type    = bool
  default = false
}

variable "evidence_runtime_enabled" {
  type    = bool
  default = false
  validation {
    condition     = !var.evidence_runtime_enabled || (var.evidence_broker_enabled && var.evidence_identity_enabled && var.certificate_runtime_enabled && var.certificate_agent_version != "3")
    error_message = "Evidence runtime needs the broker gate, its identity grant and a separately validated candidate certificate agent version, not accepted v3."
  }
}

variable "evidence_broker_enabled" {
  type    = bool
  default = false
  validation {
    condition     = !var.evidence_broker_enabled || (var.evidence_identity_enabled && var.certificate_runtime_enabled)
    error_message = "Evidence broker needs its identity grant and the existing certificate runtime."
  }
}

variable "evidence_agent_principal_id" {
  type    = string
  default = ""
  validation {
    condition     = !var.evidence_identity_enabled || var.evidence_agent_principal_id == "0bbe2604-5ae0-4463-97ff-3d06b37a749f"
    error_message = "Only the owner-approved, verified certificate agent identity may receive Evidence.Read."
  }
}

data "azuread_service_principal" "evidence_agent" {
  count     = var.evidence_identity_enabled ? 1 : 0
  object_id = var.evidence_agent_principal_id
}

resource "azuread_app_role_assignment" "evidence_read" {
  count               = var.evidence_identity_enabled ? 1 : 0
  app_role_id         = "70f53091-8400-4140-85ac-a4779e0ad4bc"
  principal_object_id = data.azuread_service_principal.evidence_agent[0].object_id
  resource_object_id  = azuread_service_principal.api.object_id
  depends_on          = [azuread_application.api]
}

locals {
  evidence_api_env = var.evidence_broker_enabled ? {
    INNEXQ_EVIDENCE_BROKER_ENABLED     = tostring(var.evidence_broker_enabled)
    INNEXQ_EVIDENCE_TOOLS_ENABLED      = tostring(var.evidence_runtime_enabled)
    INNEXQ_EVIDENCE_AGENT_PRINCIPAL_ID = data.azuread_service_principal.evidence_agent[0].object_id
    INNEXQ_EVIDENCE_AGENT_CLIENT_ID    = data.azuread_service_principal.evidence_agent[0].client_id
    INNEXQ_EVIDENCE_API_HOST           = "ca-${var.environment_name}-api.${azurerm_container_app_environment.main.default_domain}"
  } : {}
}
