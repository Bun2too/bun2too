# Terraform configuration to deploy PostgreSQL and n8n onto Railway dynamically
terraform {
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

variable "github_repository" {
  description = "GitHub repository in owner/name format; CI supplies github.repository."
  type        = string

  validation {
    condition     = can(regex("^[^/[:space:]]+/[^/[:space:]]+$", var.github_repository))
    error_message = "Use a GitHub repository in owner/name format."
  }
}

resource "railway_project" "fb_pipeline" {
  name        = "ai-fb-publisher-pipeline"
  description = "Resilient automated AI workflow architecture"
}

resource "railway_service" "postgres_db" {
  project_id   = railway_project.fb_pipeline.id
  name         = "pipeline-postgres"
  source_image = "postgres:15-alpine"
}

resource "railway_service" "crewai_service" {
  project_id         = railway_project.fb_pipeline.id
  name               = "crewai-microservice"
  source_repo        = var.github_repository
  source_repo_branch = "main"
  root_directory     = "crewai_agents"
}

resource "railway_service" "n8n_engine" {
  project_id   = railway_project.fb_pipeline.id
  name         = "n8n-orchestrator"
  source_image = "docker.io/n8nio/n8n:latest"
}

output "railway_project_id" {
  description = "Project targeted by the Railway CLI deployment."
  value       = railway_project.fb_pipeline.id
}

output "crewai_service_id" {
  description = "CrewAI service targeted by the Railway CLI deployment."
  value       = railway_service.crewai_service.id
}

output "railway_environment_id" {
  description = "Default project environment targeted by the Railway CLI deployment."
  value       = railway_project.fb_pipeline.default_environment.id
}
