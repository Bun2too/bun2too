# Terraform configuration to deploy PostgreSQL and n8n onto Railway dynamically
terraform {
  required_providers {
    railway = {
      source  = "terraform-community/railway"
      version = "~> 0.2.0"
    }
  }
}

provider "railway" {
  # Token passed via environment variable RAILWAY_TOKEN
}

resource "railway_project" "fb_pipeline" {
  name        = "ai-fb-publisher-pipeline"
  description = "Resilient automated AI workflow architecture"
}

resource "railway_service" "postgres_db" {
  project_id = railway_project.fb_pipeline.id
  name       = "pipeline-postgres"
  source {
    image = "postgres:15-alpine"
  }
}

resource "railway_service" "crewai_service" {
  project_id = railway_project.fb_pipeline.id
  name       = "crewai-microservice"
  source {
    repo = "github_username/repo_name" # Replaced dynamically or via environment
  }
}

resource "railway_service" "n8n_engine" {
  project_id = railway_project.fb_pipeline.id
  name       = "n8n-orchestrator"
  source {
    image = "docker.io/n8nio/n8n:latest"
  }
}
