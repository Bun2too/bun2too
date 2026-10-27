mock_provider "railway" {}

variables {
  railway_api_token = "test-only-account-token"
  github_repository      = "bun2too/crew-team"
  railway_project_id     = "11111111-1111-4111-8111-111111111111"
  railway_environment_id = "22222222-2222-4222-8222-222222222222"
  postgres_service_id    = "33333333-3333-4333-8333-333333333333"
  crewai_service_id      = "44444444-4444-4444-8444-444444444444"
  postgres_password      = "test-only-password"
}

run "qa_only_changes_environment_variables" {
  command = plan
  variables {
    deployment_environment = "qa"
  }
  assert {
    condition     = length(railway_project.fb_pipeline) == 0 && length(railway_service.postgres_db) == 0 && length(railway_service.crewai_service) == 0 && length(railway_service.n8n_engine) == 0
    error_message = "QA must not manage shared projects or services."
  }
  assert {
    condition     = railway_variable.postgres_password.environment_id == var.railway_environment_id && railway_variable.postgres_password.service_id == var.postgres_service_id && railway_variable.postgres_password.value == var.postgres_password
    error_message = "Postgres credentials must target the selected environment and service."
  }
  assert {
    condition     = railway_variable.postgres_config["PGDATA"].value == "/var/lib/postgresql/data/pgdata"
    error_message = "Postgres data must live on the mounted volume."
  }
}

run "reject_empty_password" {
  command = plan
  variables {
    deployment_environment = "qa"
    postgres_password      = "  "
  }
  expect_failures = [var.postgres_password]
}

run "production_owns_shared_services" {
  command = plan
  variables {
    deployment_environment = "production"
  }
  assert {
    condition     = length(railway_project.fb_pipeline) == 1 && length(railway_service.postgres_db) == 1 && length(railway_service.crewai_service) == 1
    error_message = "Production must own the shared infrastructure."
  }
  assert {
    condition     = railway_service.postgres_db[0].volume.mount_path == "/var/lib/postgresql/data"
    error_message = "Postgres must have persistent storage."
  }
}

run "n8n_volume_is_managed_by_environment_scoped_provisioner" {
  command = plan
  variables {
    deployment_environment = "production"
    n8n_volume_ready       = false
  }
  assert {
    condition     = railway_service.n8n_engine[0].volume == null
    error_message = "The provider must not create a nested n8n volume; the scoped provisioner owns storage."
  }
}

run "runtime_variables_target_environment" {
  command = plan
  variables {
    deployment_environment = "qa"
    n8n_service_id         = "55555555-5555-4555-8555-555555555555"
    marketing_runtime_config = {
      PUBLISHING_ENABLED = "false"
      MARKETING_API_KEY  = "test-only-key"
    }
    n8n_runtime_config = {
      GENERIC_TIMEZONE = "America/Chicago"
      RAILWAY_RUN_UID  = "1000"
    }
  }
  assert {
    condition     = railway_variable_collection.marketing_runtime[0].service_id == var.crewai_service_id && railway_variable_collection.marketing_runtime[0].environment_id == var.railway_environment_id && railway_variable_collection.n8n_runtime[0].service_id == var.n8n_service_id
    error_message = "Runtime configuration must target the selected service and environment."
  }
  assert {
    condition     = length(railway_variable_collection.marketing_runtime) == 1 && length(railway_variable_collection.marketing_runtime[0].variables) == 2 && railway_variable_collection.marketing_runtime[0].variables[0].name == "MARKETING_API_KEY" && railway_variable_collection.marketing_runtime[0].variables[0].value == "test-only-key"
    error_message = "Runtime keys must be batched into one collection per service with stable ordering and preserved values."
  }
  assert {
    condition     = { for v in railway_variable_collection.n8n_runtime[0].variables : v.name => v.value }["RAILWAY_RUN_UID"] == "0" && { for v in railway_variable_collection.n8n_runtime[0].variables : v.name => v.value }["N8N_USER_FOLDER"] == "/home/node" && { for v in railway_variable_collection.n8n_runtime[0].variables : v.name => v.value }["GENERIC_TIMEZONE"] == "America/Chicago"
    error_message = "n8n must be able to write Railway's root-owned volume while retaining its /home/node/.n8n data location and user configuration."
  }
}

run "empty_maps_do_not_create_collections" {
  command = plan
  variables {
    deployment_environment = "qa"
  }
  assert {
    condition     = length(railway_variable_collection.marketing_runtime) == 0 && length(railway_variable_collection.n8n_runtime) == 0
    error_message = "Empty maps must not create invalid empty collections."
  }
}
