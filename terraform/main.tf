# Terraform configuration to deploy PostgreSQL and n8n onto Railway dynamically
terraform {
  required_version = ">= 1.7.0"
  cloud {} # TF_CLOUD_ORGANIZATION and TF_WORKSPACE select durable HCP state.
  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "~> 0.6.2"
    }
  }
}

provider "railway" {
  # CI maps secrets.RAILWAY_API_TOKEN to the provider's RAILWAY_TOKEN variable.
}

variable "deployment_environment" {
  type = string
  validation {
    condition     = contains(["production", "qa"], var.deployment_environment)
    error_message = "deployment_environment must be production or qa."
  }
}

variable "railway_project_id" {
  type        = string
  description = "Existing shared Railway project ID."
}
variable "railway_environment_id" {
  type        = string
  description = "Existing environment ID, distinct for production and QA."
}
variable "postgres_service_id" {
  type = string
}
variable "crewai_service_id" {
  type = string
}

locals {
  owns_shared_resources = var.deployment_environment == "production"
}

variable "github_repository" {
  description = "GitHub repository in owner/name format; CI supplies github.repository."
  type        = string

  validation {
    condition     = can(regex("^[^/[:space:]]+/[^/[:space:]]+$", var.github_repository))
    error_message = "Use a GitHub repository in owner/name format."
  }
}

variable "postgres_password" {
  description = "Initial Postgres superuser password, supplied from the environment's GitHub secret."
  type        = string
  sensitive   = true

  validation {
    condition     = length(trimspace(var.postgres_password)) > 0
    error_message = "postgres_password must be non-empty. Set the POSTGRES_PASSWORD environment secret."
  }
}

variable "postgres_user" {
  description = "Initial database administrator username."
  type        = string
  default     = "postgres"
}

variable "postgres_database" {
  description = "Initial database name."
  type        = string
  default     = "bun2too"
}

resource "railway_project" "fb_pipeline" {
  count       = local.owns_shared_resources ? 1 : 0
  name        = "ai-fb-publisher-pipeline"
  description = "Resilient automated AI workflow architecture"
  lifecycle {
    prevent_destroy = true
    postcondition {
      condition     = self.id == var.railway_project_id && self.default_environment.id == var.railway_environment_id
      error_message = "Production state must match the configured project and production environment IDs."
    }
  }
}

resource "railway_service" "postgres_db" {
  count        = local.owns_shared_resources ? 1 : 0
  project_id   = railway_project.fb_pipeline[0].id
  name         = "pipeline-postgres"
  source_image = "postgres:15-alpine"
  volume = {
    name       = "postgres-data"
    mount_path = "/var/lib/postgresql/data"
  }
  lifecycle {
    prevent_destroy = true
    postcondition {
      condition     = self.id == var.postgres_service_id
      error_message = "The production Postgres service ID must match the imported state."
    }
  }
}

resource "railway_variable" "postgres_password" {
  service_id     = var.postgres_service_id
  environment_id = var.railway_environment_id
  name           = "POSTGRES_PASSWORD"
  value          = var.postgres_password
}

resource "railway_variable" "postgres_config" {
  for_each = {
    POSTGRES_USER = var.postgres_user
    POSTGRES_DB   = var.postgres_database
    PGDATA        = "/var/lib/postgresql/data/pgdata"
  }
  service_id     = var.postgres_service_id
  environment_id = var.railway_environment_id
  name           = each.key
  value          = each.value
}

resource "railway_service" "crewai_service" {
  count      = local.owns_shared_resources ? 1 : 0
  project_id = railway_project.fb_pipeline[0].id
  name       = "crewai-microservice"
  # GitHub Actions uploads the checked-out branch to the selected environment.
  # A project-wide source_repo_branch would also affect the QA service instance.
  root_directory = "crewai_agents"
  volume = {
    name       = "marketing-work-history"
    mount_path = "/data"
  }
  lifecycle {
    prevent_destroy = true
    postcondition {
      condition     = self.id == var.crewai_service_id
      error_message = "The production CrewAI service ID must match the imported state."
    }
  }
}

resource "railway_variable" "crewai_data_dir" {
  service_id     = var.crewai_service_id
  environment_id = var.railway_environment_id
  name           = "DATA_DIR"
  value          = "/data"
}

resource "railway_service" "n8n_engine" {
  count        = local.owns_shared_resources ? 1 : 0
  project_id   = railway_project.fb_pipeline[0].id
  name         = "n8n-orchestrator"
  source_image = "docker.io/n8nio/n8n:latest"
  # Always persist SQLite, users, API keys, workflows and local encryption config.
  # The plan guard requires explicit migration acknowledgement for an existing
  # service with no volume; a normal update cannot remove or replace its volume.
  volume = {
    name       = "n8n-data"
    mount_path = "/home/node/.n8n"
  }
  lifecycle {
    prevent_destroy = true
  }
}

variable "n8n_volume_ready" {
  type        = bool
  default     = false
  description = "Acknowledge a prepared migration when attaching storage to an existing service without a volume. Does not toggle or detach storage."
}

variable "n8n_service_id" {
  type    = string
  default = ""
}

variable "marketing_runtime_config" {
  type        = map(string)
  sensitive   = true
  default     = {}
  description = "CrewAI runtime variables and secrets. Stored in sensitive HCP state. DATA_DIR is managed separately."
  validation {
    condition     = !contains(keys(var.marketing_runtime_config), "DATA_DIR")
    error_message = "Do not include DATA_DIR in marketing_runtime_config."
  }
}

variable "n8n_runtime_config" {
  type        = map(string)
  sensitive   = true
  default     = {}
  description = "n8n runtime variables. Preserve the existing N8N_ENCRYPTION_KEY when migrating."
}

// Forget legacy per-key state without deleting live variables. The collection
// upserts the supplied map, including values written by a partially failed apply.
removed {
  from = railway_variable.marketing_runtime
  lifecycle {
    destroy = false
  }
}

removed {
  from = railway_variable.n8n_runtime
  lifecycle {
    destroy = false
  }
}

resource "railway_variable_collection" "marketing_runtime" {
  count          = length(nonsensitive(keys(var.marketing_runtime_config))) > 0 ? 1 : 0
  service_id     = var.crewai_service_id
  environment_id = var.railway_environment_id
  variables = [for name in sort(nonsensitive(keys(var.marketing_runtime_config))) : {
    name  = name
    value = var.marketing_runtime_config[name]
  }]
}

resource "railway_variable_collection" "n8n_runtime" {
  # Provider variable updates restart n8n. Attach storage first in production.
  depends_on     = [railway_service.n8n_engine]
  count          = length(nonsensitive(keys(var.n8n_runtime_config))) > 0 ? 1 : 0
  service_id     = var.n8n_service_id
  environment_id = var.railway_environment_id
  variables = [for name in sort(nonsensitive(keys(var.n8n_runtime_config))) : {
    name  = name
    value = var.n8n_runtime_config[name]
  }]
  lifecycle {
    precondition {
      condition     = length(var.n8n_service_id) > 0
      error_message = "Set n8n_service_id before configuring n8n runtime variables."
    }
  }
}

output "railway_project_id" {
  description = "Project targeted by the Railway CLI deployment."
  value       = var.railway_project_id
}

output "crewai_service_id" {
  description = "CrewAI service targeted by the Railway CLI deployment."
  value       = var.crewai_service_id
}

output "railway_environment_id" {
  description = "Environment targeted by this workspace and the Railway CLI deployment."
  value       = var.railway_environment_id
}

# Preserve resource addresses when migrating the original production state.
moved {
  from = railway_project.fb_pipeline
  to   = railway_project.fb_pipeline[0]
}
moved {
  from = railway_service.postgres_db
  to   = railway_service.postgres_db[0]
}
moved {
  from = railway_service.crewai_service
  to   = railway_service.crewai_service[0]
}
moved {
  from = railway_service.n8n_engine
  to   = railway_service.n8n_engine[0]
}
