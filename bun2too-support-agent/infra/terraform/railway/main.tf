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

# One Railway project per environment, named like its HCP Terraform workspace
# (bun2too-support-<environment>). Its only Railway environment carries the same short
# name (qa, prod), which railway-up.sh deploys to.
resource "railway_project" "support" {
  name         = "${var.name_prefix}-${var.environment}"
  description  = "Relay support intake for Bun2too (${var.environment}): gateway, agents and Postgres. POC; GA target is GCP Cloud Run."
  workspace_id = var.workspace_id
  default_environment = {
    name = var.environment
  }
  lifecycle {
    prevent_destroy = true
  }
}

# Source comes from `railway up` in CI, which uploads the product directory as the
# build root. The Dockerfile path is part of the service's build settings: Railway
# looked for ./Dockerfile when it was only a RAILWAY_DOCKERFILE_PATH variable.
resource "railway_service" "gateway" {
  name                = "gateway"
  project_id          = railway_project.support.id
  dockerfile_path     = "apps/gateway/Dockerfile"
  healthcheck_path    = "/healthz"
  healthcheck_timeout = 60
}

resource "railway_service" "agents" {
  name                = "agents"
  project_id          = railway_project.support.id
  dockerfile_path     = "services/agents/Dockerfile"
  healthcheck_path    = "/healthz"
  healthcheck_timeout = 120
}

resource "railway_service" "postgres" {
  name         = "postgres"
  project_id   = railway_project.support.id
  source_image = var.postgres_image
  lifecycle {
    prevent_destroy = true
    # ensure-volume.sh owns the data volume (ADR 0004). Without this, every apply read
    # the attached volume and planned `volume -> null`, detaching it from Postgres.
    ignore_changes = [volume]
  }
}

locals {
  environment_id = railway_project.support.default_environment.id
  subdomain      = "${var.name_prefix}-${var.environment}"

  runtime_keys        = toset(nonsensitive(keys(var.runtime_secrets)))
  gateway_secret_keys = toset(["RELAY_TENANT_KEYS"])

  gateway_variables = merge(
    {
      PORT               = "8080" # Railway health-checks $PORT; it assigns one when unset.
      RELAY_GATEWAY_PORT = "8080"
      RELAY_AGENTS_URL   = "http://$${{agents.RAILWAY_PRIVATE_DOMAIN}}:8080"
      RELAY_PUBLIC_URL   = "https://${railway_service_domain.gateway.domain}"
    },
    var.otel_endpoint == "" ? {} : { OTEL_EXPORTER_OTLP_ENDPOINT = var.otel_endpoint },
    { for k in local.runtime_keys : k => var.runtime_secrets[k] if contains(local.gateway_secret_keys, k) },
  )

  agents_variables = merge(
    {
      PORT              = "8080" # Railway health-checks $PORT; it assigns one when unset.
      RELAY_AGENTS_HOST = "::"
      RELAY_AGENTS_PORT = "8080"
      DATABASE_URL      = "postgresql://relay:${random_password.postgres.result}@$${{postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/relay"
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
  service_id     = railway_service.postgres.id
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
  service_id     = railway_service.gateway.id
  target_port    = 8080
}

resource "railway_variable_collection" "gateway" {
  service_id     = railway_service.gateway.id
  environment_id = local.environment_id
  variables      = [for name in sort(keys(local.gateway_variables)) : { name = name, value = local.gateway_variables[name] }]
}

resource "railway_variable_collection" "agents" {
  service_id     = railway_service.agents.id
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
  value = railway_project.support.id
}

output "postgres_service_id" {
  value = railway_service.postgres.id
}
