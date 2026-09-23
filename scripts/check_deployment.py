"""Read-only checks for CI targets. Never print credentials or API response bodies."""
import datetime
import time
import argparse
from contextlib import contextmanager
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def trace(event, **fields):
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    print(f"[{stamp}] {event} {json.dumps(fields, sort_keys=True)}", flush=True)


def trace_context(env):
    names = ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT', 'GITHUB_SHA', 'GITHUB_REF_NAME',
             'DEPLOY_ENVIRONMENT', 'TF_CLOUD_ORGANIZATION', 'TF_WORKSPACE',
             'RAILWAY_PROJECT_ID', 'RAILWAY_ENVIRONMENT_ID', 'POSTGRES_SERVICE_ID',
             'CREWAI_SERVICE_ID')
    trace('Deployment context', **{name: env.get(name) for name in names})
    trace('Credential presence', **{name: bool(env.get(name, '').strip()) for name in
                                  ('TF_API_TOKEN', 'RAILWAY_API_TOKEN', 'POSTGRES_PASSWORD')})


@contextmanager
def api_check(label):
    """Report the operation, never exception text or response bodies containing secrets."""
    started = time.monotonic()
    trace(f"Checking {label}")
    try:
        yield
    except HTTPError as exc:
        hint = {
            401: "Check the selected GitHub environment's token and its expiration.",
            403: "Check token permissions and access restrictions for the runner.",
            404: "Check target names/IDs and token access; inaccessible resources may return 404.",
            429: "API rate limit reached; retry later.",
        }.get(exc.code, "Check the API service status and runner access.")
        raise ValueError(f"{label}: HTTP {exc.code}. {hint}") from None
    except (TimeoutError, URLError):
        raise ValueError(f"{label}: network/TLS/DNS error or timeout from this runner.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError(f"{label}: response was not valid JSON.") from None
    except KeyError as exc:
        # Only report known schema keys; arbitrary exception text may contain secrets.
        field = exc.args[0] if exc.args else None
        known = {"data", "attributes", "execution-mode", "project", "environments",
                 "services", "edges", "node", "id", "name"}
        detail = f"missing field '{field}'" if field in known else "missing required field"
        raise ValueError(f"{label}: unexpected JSON response ({detail}).") from None
    except (TypeError, AttributeError):
        raise ValueError(f"{label}: unexpected JSON response (null or wrong field type).") from None
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from None
    finally:
        trace("Check finished", check=label, duration_seconds=round(time.monotonic() - started, 3))
    trace(f"Passed {label}")


def request_json(url, token, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data=data, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    })
    details = {}
    if payload is not None:
        details['query'] = payload.get('query')
        details['variables'] = {key: value for key, value in payload.get('variables', {}).items()
                                if key in ('id', 'projectId', 'environmentId', 'serviceId')}
    trace('API request', method=request.get_method(), url=url, timeout_seconds=30,
          authentication='Bearer [REDACTED]', **details)
    started = time.monotonic()
    try:
        with urlopen(request, timeout=30) as response:
            trace('API response', status=getattr(response, 'status', None),
                  duration_seconds=round(time.monotonic() - started, 3))
            result = json.load(response)
            if isinstance(result, dict) and result.get('errors'):
                errors = result['errors']
                trace('API reported errors', count=len(errors) if isinstance(errors, list) else None,
                      response_body='omitted')
            return result
    except HTTPError as exc:
        trace('API response', status=exc.code,
              duration_seconds=round(time.monotonic() - started, 3))
        raise
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        trace('API failure', error_type=type(exc).__name__,
              duration_seconds=round(time.monotonic() - started, 3))
        raise


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
    org = quote(env["TF_CLOUD_ORGANIZATION"], safe="")
    workspace = quote(env["TF_WORKSPACE"], safe="")
    with api_check(f"HCP workspace GET /api/v2/organizations/{org}/workspaces/{workspace}"):
        hcp = request(f"https://app.terraform.io/api/v2/organizations/{org}/workspaces/{workspace}",
                      env["TF_API_TOKEN"])
        attributes = hcp["data"]["attributes"]
        mode = attributes["execution-mode"]
        # Only emit known enum/boolean values, never arbitrary API response content.
        reported_mode = mode if isinstance(mode, str) and mode in ("local", "remote", "agent") else "unknown/null"
        overwrites = attributes.get("setting-overwrites") or {}
        override = overwrites.get("execution-mode") if isinstance(overwrites, dict) else None
        reported_override = str(override).lower() if type(override) is bool else "unavailable"
        print(f"HCP execution-mode={reported_mode}; "
              f"setting-overwrites.execution-mode={reported_override}", flush=True)
        if mode != "local":
            raise ValueError(
                f"HCP returned execution-mode={reported_mode}; required local. "
                "Set the HCP workspace execution mode to Local; GitHub runs Terraform. "
                f"Verify the saved workspace setting at https://app.terraform.io/app/{org}"
                f"/workspaces/{workspace}/settings/general and compare a fresh API read.")
    with api_check("Railway project lookup POST https://backboard.railway.com/graphql/v2"):
        result = request("https://backboard.railway.com/graphql/v2", env["RAILWAY_API_TOKEN"], {
            "query": "query($id: String!) { project(id: $id) { environments { edges { node { id name } } } services { edges { node { id } } } } }",
            "variables": {"id": env["RAILWAY_PROJECT_ID"]},
        })
        if result.get("errors") or not result.get("data", {}).get("project"):
            raise ValueError("Railway project lookup failed; check the token and project ID")
        project = result["data"]["project"]
        environments = {e["node"]["id"]: e["node"]["name"] for e in project["environments"]["edges"]}
        trace('Railway environment validation', expected_name=expected,
              selected_id=env["RAILWAY_ENVIRONMENT_ID"],
              actual_name=environments.get(env["RAILWAY_ENVIRONMENT_ID"]),
              environment_count=len(environments))
        if environments.get(env["RAILWAY_ENVIRONMENT_ID"]) != expected:
            raise ValueError("Railway environment ID does not match the branch's environment in this project")
        services = {e["node"]["id"] for e in project["services"]["edges"]}
        trace('Railway service validation', service_count=len(services),
              postgres_found=env["POSTGRES_SERVICE_ID"] in services,
              crewai_found=env["CREWAI_SERVICE_ID"] in services)
        if not {env["POSTGRES_SERVICE_ID"], env["CREWAI_SERVICE_ID"]}.issubset(services):
            raise ValueError("Service IDs do not belong to the selected Railway project")
        if env["POSTGRES_SERVICE_ID"] == env["CREWAI_SERVICE_ID"]:
            raise ValueError("Postgres and CrewAI must target different services")


def check_postgres_variables(env, request=request_json):
    """Verify Railway configuration after apply, without exposing variable values.

    This does not establish that a running database has restarted or is healthy.
    """
    for name in ("RAILWAY_API_TOKEN", "RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID",
                 "POSTGRES_SERVICE_ID", "POSTGRES_PASSWORD"):
        if not env.get(name, "").strip():
            raise ValueError(f"Missing {name}; cannot verify Postgres configuration")
    with api_check("Railway Postgres variables lookup POST https://backboard.railway.com/graphql/v2"):
        result = request("https://backboard.railway.com/graphql/v2", env["RAILWAY_API_TOKEN"], {
            "query": """query($projectId: String!, $environmentId: String!, $serviceId: String!) {
              variablesForServiceDeployment(projectId: $projectId,
                environmentId: $environmentId, serviceId: $serviceId)
            }""",
            "variables": {
                "projectId": env["RAILWAY_PROJECT_ID"],
                "environmentId": env["RAILWAY_ENVIRONMENT_ID"],
                "serviceId": env["POSTGRES_SERVICE_ID"],
            },
        })
        data = result.get("data") or {}
        variables = data.get("variablesForServiceDeployment")
        if result.get("errors") or not isinstance(variables, dict):
            raise ValueError("Railway Postgres variable lookup failed; check API access and service/environment IDs")
        password = variables.get("POSTGRES_PASSWORD")
        if not isinstance(password, str) or not password.strip():
            raise ValueError("Railway POSTGRES_PASSWORD is missing, empty or unavailable through the API. "
                             "Check the selected Postgres service's Variables and Terraform apply; "
                             "sealed values cannot be verified through this check.")
        if password != env["POSTGRES_PASSWORD"]:
            raise ValueError("Railway POSTGRES_PASSWORD does not match this GitHub environment's secret. "
                             "Check the Terraform target and applied changes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-postgres", action="store_true",
                        help="Read back Postgres password configuration after Terraform apply")
    args = parser.parse_args()
    trace("Deployment diagnostics v3")
    trace_context(os.environ)
    try:
        if args.verify_postgres:
            check_postgres_variables(os.environ)
        else:
            check(os.environ)
    except (HTTPError, URLError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        print("::error::Deployment API check failed. Check HCP/Railway access and target configuration.", file=sys.stderr)
        return 1
    except ValueError as exc:
        print("::error::" + str(exc), file=sys.stderr)
        return 1
    if args.verify_postgres:
        print("Railway Postgres password configuration matches the selected environment. "
              "Check the latest runtime logs separately to confirm database readiness.")
    else:
        print("Deployment environment, Railway targets and HCP workspace verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
