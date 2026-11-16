terraform {
  required_version = ">= 1.7.0"
  cloud {} # TF_CLOUD_ORGANIZATION and TF_WORKSPACE=bun2too-support-project select state.
  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "~> 0.6.2"
    }
  }
}

provider "railway" {
  token = var.railway_api_token
}

variable "railway_api_token" {
  description = "Railway account or workspace token (not a project token)."
  type        = string
  sensitive   = true
}

variable "workspace_id" {
  description = "Railway workspace that owns the project. Required when the token can see several workspaces."
  type        = string
  default     = null
}

variable "project_name" {
  type    = string
  default = "bun2too-support"
}

variable "postgres_image" {
  type    = string
  default = "ghcr.io/railwayapp-templates/postgres-ssl:16"
}

locals {
  extra_environments = toset(["dev", "qa"])
}

resource "railway_project" "support" {
  name         = var.project_name
  description  = "Relay support intake for Bun2too: gateway, agents and Postgres. POC; GA target is GCP Cloud Run."
  workspace_id = var.workspace_id
  default_environment = {
    name = "prod"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "railway_environment" "this" {
  for_each   = local.extra_environments
  name       = each.key
  project_id = railway_project.support.id
}

# Source comes from `railway up` in CI; Dockerfile paths are per-environment variables.
resource "railway_service" "gateway" {
  name                = "gateway"
  project_id          = railway_project.support.id
  healthcheck_path    = "/healthz"
  healthcheck_timeout = 60
}

resource "railway_service" "agents" {
  name                = "agents"
  project_id          = railway_project.support.id
  healthcheck_path    = "/healthz"
  healthcheck_timeout = 120
}

resource "railway_service" "postgres" {
  name         = "postgres"
  project_id   = railway_project.support.id
  source_image = var.postgres_image
  lifecycle {
    prevent_destroy = true
  }
}

output "project_id" {
  value = railway_project.support.id
}

output "environment_ids" {
  value = merge(
    { prod = railway_project.support.default_environment.id },
    { for name, env in railway_environment.this : name => env.id },
  )
}

output "service_ids" {
  value = {
    gateway  = railway_service.gateway.id
    agents   = railway_service.agents.id
    postgres = railway_service.postgres.id
  }
}
