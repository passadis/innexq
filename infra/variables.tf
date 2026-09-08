variable "subscription_id" {
  type        = string
  description = "Azure subscription selected explicitly before Phase 1 deployment."
}

variable "environment_name" {
  type        = string
  description = "Short azd environment name used for resource naming and tags."

  validation {
    condition     = can(regex("^[a-z0-9-]{2,20}$", var.environment_name))
    error_message = "environment_name must be 2-20 lowercase letters, numbers, or hyphens."
  }
}

variable "location" {
  type        = string
  description = "Azure region confirmed with the owner after capability and policy checks."
}

variable "tags" {
  type        = map(string)
  description = "Non-sensitive governance tags applied to later resources."
  default = {
    application = "innexq"
    data_class  = "synthetic"
    managed_by  = "azd-terraform"
  }
}

variable "tenant_id" {
  type    = string
  default = "35de4c50-7dcd-4871-8685-61789c017da2"
}

variable "approver_user_id" {
  type    = string
  default = "11b101d5-96dd-4d25-ad68-38b54de937bf"
}

variable "graph_site_id" {
  type        = string
  description = "Verified site ID set after the site-selected access bootstrap. Empty fails API readiness."
  default     = ""
}

variable "graph_drive_id" {
  type    = string
  default = ""
}

variable "graph_folder_id" {
  type    = string
  default = ""
}

variable "agent_principal_id" {
  type        = string
  description = "The actual Hosted Agent identity, resolved after deployment. Never use the executor identity."
  default     = ""
}
