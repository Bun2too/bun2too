mock_provider "railway" {
  mock_resource "railway_service_domain" {
    defaults = { domain = "bun2too-support-qa.up.railway.app" }
  }
  mock_resource "railway_service" {
    defaults = { id = "33333333-3333-4333-8333-333333333301" }
  }
  mock_resource "railway_project" {
    defaults = { id = "11111111-1111-4111-8111-111111111111", default_environment = { id = "22222222-2222-4222-8222-222222222201" } }
  }
}

mock_provider "random" {}

variables {
  railway_api_token = "test"
  runtime_secrets = {
    RELAY_TENANT_KEYS = "k:bun2too"
    ANTHROPIC_API_KEY = "sk-test"
  }
}

run "qa_is_live_and_targets_qa" {
  command = apply
  variables {
    environment = "qa"
  }

  assert {
    condition     = railway_project.support.name == "bun2too-support-qa"
    error_message = "The Railway project is named like the HCP workspace."
  }

  assert {
    condition     = railway_project.support.default_environment.name == "qa"
    error_message = "The project's Railway environment is named qa, which railway-up.sh deploys to."
  }

  assert {
    condition     = output.environment_id == "22222222-2222-4222-8222-222222222201"
    error_message = "Variables and the domain target the project's own environment."
  }

  assert {
    condition = alltrue([for c in [railway_variable_collection.gateway, railway_variable_collection.agents] :
    !contains([for v in c.variables : v.name], "RELAY_OFFLINE")])
    error_message = "Deployed environments run live; offline mode is for local runs only."
  }

  assert {
    condition     = railway_service.gateway.dockerfile_path == "apps/gateway/Dockerfile" && railway_service.agents.dockerfile_path == "services/agents/Dockerfile"
    error_message = "Each service builds its own Dockerfile; railway up uploads the product directory, which has no root Dockerfile."
  }

  assert {
    condition = alltrue([for c in [railway_variable_collection.gateway, railway_variable_collection.agents] :
    [for v in c.variables : v.value if v.name == "PORT"] == ["8080"]])
    error_message = "Railway health-checks $PORT, so both services set it to the port they listen on."
  }
}

run "secrets_split_by_service" {
  command = apply
  variables {
    environment = "prod"
  }

  assert {
    condition     = contains([for v in railway_variable_collection.gateway.variables : v.name], "RELAY_TENANT_KEYS")
    error_message = "Tenant keys belong to the gateway."
  }

  assert {
    condition     = !contains([for v in railway_variable_collection.gateway.variables : v.name], "ANTHROPIC_API_KEY")
    error_message = "Model keys must not reach the gateway."
  }

  assert {
    condition     = contains([for v in railway_variable_collection.agents.variables : v.name], "ANTHROPIC_API_KEY")
    error_message = "Model keys belong to agents."
  }

}

run "rejects_unknown_environment" {
  command = plan
  variables {
    environment = "staging"
  }
  expect_failures = [var.environment]
}

run "rejects_dev" {
  command = plan
  variables {
    environment = "dev"
  }
  expect_failures = [var.environment]
}
