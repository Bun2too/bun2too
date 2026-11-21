variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "qa", "prod"], var.environment)
    error_message = "environment must be dev, qa or prod."
  }
}

variable "railway_api_token" {
  description = "Railway account or workspace token (not a project token)."
  type        = string
  sensitive   = true
}

variable "tfc_organization" {
  description = "HCP Terraform organisation holding the project workspace."
  type        = string
}

variable "project_workspace" {
  type    = string
  default = "bun2too-support-app"
}

variable "subdomain_prefix" {
  type    = string
  default = "bun2too-support"
}

variable "otel_endpoint" {
  description = "OTLP HTTP endpoint for traces. Empty disables export."
  type        = string
  default     = ""
}

variable "runtime_secrets" {
  description = "Secrets from the GitHub environment's SUPPORT_RUNTIME_SECRETS JSON. RELAY_TENANT_KEYS goes to the gateway; everything else to agents."
  type        = map(string)
  sensitive   = true
  default     = {}

  validation {
    condition     = alltrue([for k in nonsensitive(keys(var.runtime_secrets)) : can(regex("^[A-Z][A-Z0-9_]*$", k))])
    error_message = "runtime_secrets keys must be UPPER_SNAKE_CASE environment variable names."
  }
}
