mock_provider "railway" {
  mock_resource "railway_project" {
    defaults = {
      id                  = "11111111-1111-4111-8111-111111111111"
      default_environment = { id = "22222222-2222-4222-8222-222222222203", name = "prod" }
    }
  }
}

variables {
  railway_api_token = "test"
}

run "creates_three_environments_and_three_services" {
  command = apply

  assert {
    condition     = toset(keys(output.environment_ids)) == toset(["dev", "qa", "prod"])
    error_message = "Expected dev, qa and prod environments."
  }

  assert {
    condition     = output.environment_ids["prod"] == "22222222-2222-4222-8222-222222222203"
    error_message = "prod must be the project's default environment."
  }

  assert {
    condition     = toset(keys(output.service_ids)) == toset(["gateway", "agents", "postgres"])
    error_message = "Expected gateway, agents and postgres services."
  }
}
