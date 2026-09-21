"""Read-only checks for CI targets. Never print credentials or API response bodies."""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def request_json(url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def check(env, request=request_json):
    expected = {"main": "production", "qa": "qa"}.get(env.get("GITHUB_REF_NAME"))
    if not expected or env.get("DEPLOY_ENVIRONMENT") != expected:
        raise ValueError("Branch/environment mapping is invalid")
    required = ["RAILWAY_API_TOKEN", "POSTGRES_PASSWORD", "TF_API_TOKEN",
                "TF_CLOUD_ORGANIZATION", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
                "POSTGRES_SERVICE_ID", "CREWAI_SERVICE_ID", "TF_WORKSPACE"]
    for name in required:
        if not env.get(name, "").strip():
            raise ValueError(f"Missing {name}; configure it in the selected GitHub environment")
    if env["TF_WORKSPACE"] != "bun2too-" + expected:
        raise ValueError("HCP workspace must match the selected deployment environment")
    org = quote(env["TF_CLOUD_ORGANIZATION"], safe="")
    workspace = quote(env["TF_WORKSPACE"], safe="")
    hcp = request(f"https://app.terraform.io/api/v2/organizations/{org}/workspaces/{workspace}",
                  env["TF_API_TOKEN"])
    if hcp["data"]["attributes"]["execution-mode"] != "local":
        raise ValueError("Set the HCP workspace execution mode to Local; GitHub runs Terraform")
    result = request("https://backboard.railway.com/graphql/v2", env["RAILWAY_API_TOKEN"], {
        "query": "query($id: String!) { project(id: $id) { environments { edges { node { id name } } } services { edges { node { id } } } } }",
        "variables": {"id": env["RAILWAY_PROJECT_ID"]},
    })
    if result.get("errors") or not result.get("data", {}).get("project"):
        raise ValueError("Railway project lookup failed; check the token and project ID")
    project = result["data"]["project"]
    environments = {e["node"]["id"]: e["node"]["name"] for e in project["environments"]["edges"]}
    if environments.get(env["RAILWAY_ENVIRONMENT_ID"]) != expected:
        raise ValueError("Railway environment ID does not match the branch's environment in this project")
    services = {e["node"]["id"] for e in project["services"]["edges"]}
    if not {env["POSTGRES_SERVICE_ID"], env["CREWAI_SERVICE_ID"]}.issubset(services):
        raise ValueError("Service IDs do not belong to the selected Railway project")
    if env["POSTGRES_SERVICE_ID"] == env["CREWAI_SERVICE_ID"]:
        raise ValueError("Postgres and CrewAI must target different services")


if __name__ == "__main__":
    try:
        check(os.environ)
    except (HTTPError, URLError, KeyError, TypeError, json.JSONDecodeError):
        print("::error::Deployment preflight API check failed. Check HCP/Railway access and workspace configuration.", file=sys.stderr)
        sys.exit(1)
    except ValueError as exc:
        print("::error::" + str(exc), file=sys.stderr)
        sys.exit(1)
    print("Deployment environment, Railway targets and HCP workspace verified.")
