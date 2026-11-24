variable "environment" {
  type = string
  validation {
    condition     = contains(["qa", "prod"], var.environment)
    error_message = "environment must be qa or prod (dev was removed; ADR 0008)."
  }
}

variable "railway_api_token" {
  description = "Railway account or workspace token (not a project token)."
  type        = string
  sensitive   = true
}

variable "workspace_id" {
  description = "Railway workspace that owns the projects. Required when the token can see several workspaces."
  type        = string
  default     = null
}

variable "postgres_image" {
  type    = string
  default = "ghcr.io/railwayapp-templates/postgres-ssl:16"
}

variable "name_prefix" {
  description = "Railway project and gateway subdomain are <name_prefix>-<environment>, like the HCP Terraform workspace."
  type        = string
  default     = "bun2too-support"
}

variable "otel_endpoint" {
  description = "OTLP HTTP endpoint for traces. Empty disables export."
  type        = string
  default     = ""
}

variable "langsmith" {
  description = "LangSmith trace settings for the agents service (ADR 0009): LANGSMITH_ENDPOINT, LANGSMITH_AGENT_ID, LANGSMITH_AGENT_ENVIRONMENT, LANGSMITH_WORKSPACE_ID, LANGSMITH_HIDE_INPUTS and LANGSMITH_HIDE_OUTPUTS. Empty values stay unset. The API key is LANGSMITH_API_KEY in runtime_secrets."
  type        = map(string)
  default     = {}

  validation {
    condition     = alltrue([for k in keys(var.langsmith) : contains(["LANGSMITH_ENDPOINT", "LANGSMITH_AGENT_ID", "LANGSMITH_AGENT_ENVIRONMENT", "LANGSMITH_WORKSPACE_ID", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS"], k)])
    error_message = "langsmith takes only LANGSMITH_ENDPOINT, LANGSMITH_AGENT_ID, LANGSMITH_AGENT_ENVIRONMENT, LANGSMITH_WORKSPACE_ID, LANGSMITH_HIDE_INPUTS and LANGSMITH_HIDE_OUTPUTS."
  }
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
