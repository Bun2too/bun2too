mock_provider "railway" {
  mock_resource "railway_service_domain" {
    defaults = { domain = "bun2too-support-dev.up.railway.app" }
  }
}

mock_provider "random" {}

override_data {
  target = data.terraform_remote_state.project
  values = {
    outputs = {
      project_id      = "11111111-1111-4111-8111-111111111111"
      environment_ids = { dev = "22222222-2222-4222-8222-222222222201", qa = "22222222-2222-4222-8222-222222222202", prod = "22222222-2222-4222-8222-222222222203" }
      service_ids     = { gateway = "33333333-3333-4333-8333-333333333301", agents = "33333333-3333-4333-8333-333333333302", postgres = "33333333-3333-4333-8333-333333333303" }
    }
  }
}

variables {
  railway_api_token = "test"
  tfc_organization  = "bun2too"
  runtime_secrets = {
    RELAY_TENANT_KEYS = "k:bun2too"
    ANTHROPIC_API_KEY = "sk-test"
  }
}

run "dev_is_offline_and_targets_dev" {
  command = apply
  variables {
    environment = "dev"
  }

  assert {
    condition     = output.environment_id == "22222222-2222-4222-8222-222222222201"
    error_message = "dev must target the dev environment."
  }

  assert {
    condition     = contains([for v in railway_variable_collection.gateway.variables : v.name if v.value == "1"], "RELAY_OFFLINE")
    error_message = "dev runs in offline mode."
  }
}

run "secrets_split_by_service" {
  command = apply
  variables {
    environment = "qa"
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

  assert {
    condition     = [for v in railway_variable_collection.agents.variables : v.value if v.name == "RELAY_OFFLINE"][0] == ""
    error_message = "qa runs live."
  }
}

run "rejects_unknown_environment" {
  command = plan
  variables {
    environment = "staging"
  }
  expect_failures = [var.environment]
}
