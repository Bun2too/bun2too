terraform {
  required_version = ">= 1.7.0"
  cloud {} # TF_CLOUD_ORGANIZATION and TF_WORKSPACE=bun2too-support-<environment> select state.
  required_providers {
    railway = {
      source  = "terraform-community-providers/railway"
      version = "~> 0.6.2"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "railway" {
  token = var.railway_api_token
}

data "terraform_remote_state" "project" {
  backend = "remote"
  config = {
    organization = var.tfc_organization
    workspaces   = { name = var.project_workspace }
  }
}

locals {
  project        = data.terraform_remote_state.project.outputs
  environment_id = local.project.environment_ids[var.environment]
  service_ids    = local.project.service_ids
  subdomain      = "${var.subdomain_prefix}-${var.environment}"
  offline        = var.environment == "dev" ? "1" : ""

  runtime_keys        = toset(nonsensitive(keys(var.runtime_secrets)))
  gateway_secret_keys = toset(["RELAY_TENANT_KEYS"])

  gateway_variables = merge(
    {
      RAILWAY_DOCKERFILE_PATH = "apps/gateway/Dockerfile"
      RELAY_GATEWAY_PORT      = "8080"
      RELAY_AGENTS_URL        = "http://$${{agents.RAILWAY_PRIVATE_DOMAIN}}:8080"
      RELAY_PUBLIC_URL        = "https://${railway_service_domain.gateway.domain}"
      RELAY_OFFLINE           = local.offline
    },
    var.otel_endpoint == "" ? {} : { OTEL_EXPORTER_OTLP_ENDPOINT = var.otel_endpoint },
    { for k in local.runtime_keys : k => var.runtime_secrets[k] if contains(local.gateway_secret_keys, k) },
  )

  agents_variables = merge(
    {
      RAILWAY_DOCKERFILE_PATH = "services/agents/Dockerfile"
      RELAY_AGENTS_HOST       = "::"
      RELAY_AGENTS_PORT       = "8080"
      RELAY_OFFLINE           = local.offline
      DATABASE_URL            = "postgresql://relay:${random_password.postgres.result}@$${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/relay"
    },
    var.otel_endpoint == "" ? {} : { OTEL_EXPORTER_OTLP_ENDPOINT = var.otel_endpoint },
    { for k in local.runtime_keys : k => var.runtime_secrets[k] if !contains(local.gateway_secret_keys, k) },
  )
}

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "railway_variable_collection" "postgres" {
  service_id     = local.service_ids.postgres
  environment_id = local.environment_id
  variables = [
    { name = "POSTGRES_USER", value = "relay" },
    { name = "POSTGRES_DB", value = "relay" },
    { name = "POSTGRES_PASSWORD", value = random_password.postgres.result },
    { name = "PGDATA", value = "/var/lib/postgresql/data/pgdata" },
  ]
}

resource "railway_service_domain" "gateway" {
  subdomain      = local.subdomain
  environment_id = local.environment_id
  service_id     = local.service_ids.gateway
  target_port    = 8080
}

resource "railway_variable_collection" "gateway" {
  service_id     = local.service_ids.gateway
  environment_id = local.environment_id
  variables      = [for name in sort(keys(local.gateway_variables)) : { name = name, value = local.gateway_variables[name] }]
}

resource "railway_variable_collection" "agents" {
  service_id     = local.service_ids.agents
  environment_id = local.environment_id
  variables      = [for name in sort(keys(local.agents_variables)) : { name = name, value = local.agents_variables[name] }]
}

output "environment_id" {
  value = local.environment_id
}

output "gateway_url" {
  value = "https://${railway_service_domain.gateway.domain}"
}

output "project_id" {
  value = local.project.project_id
}

output "postgres_service_id" {
  value = local.service_ids.postgres
}
