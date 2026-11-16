terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 6.0" }
  }
}

variable "project" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "gateway_image" { type = string }
variable "agents_image" { type = string }

provider "google" {
  project = var.project
  region  = var.region
}

resource "google_service_account" "relay" {
  account_id   = "relay-runtime"
  display_name = "Relay runtime"
}

resource "google_cloud_run_v2_service" "agents" {
  name     = "relay-agents"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  template {
    service_account = google_service_account.relay.email
    scaling {
      min_instance_count = 1
      max_instance_count = 20
    }
    containers {
      image = var.agents_image
      resources { limits = { cpu = "1", memory = "1Gi" } }
    }
  }
}

resource "google_cloud_run_v2_service" "gateway" {
  name     = "relay-gateway"
  location = var.region
  template {
    service_account = google_service_account.relay.email
    scaling {
      min_instance_count = 1
      max_instance_count = 20
    }
    containers {
      image = var.gateway_image
      env {
        name  = "RELAY_AGENTS_URL"
        value = google_cloud_run_v2_service.agents.uri
      }
      resources { limits = { cpu = "1", memory = "512Mi" } }
    }
  }
}
