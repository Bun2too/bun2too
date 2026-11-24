#!/usr/bin/env python3
"""Build a read-only 30-day delivery report and publish its dated Confluence page."""

from __future__ import annotations

import base64
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

GITHUB_API = "https://api.github.com"
CONFLUENCE = "https://bun2too.atlassian.net"
SPACE_ID = "~557058817542a500e54a3aac53cc45b225cb37"
PARENT_ID = "250970113"
WINDOW_DAYS = 30
OUTPUT_DIR = Path(os.environ.get("METRICS_OUTPUT_DIR", "artifacts/daily-agent-productivity"))


class ApiError(RuntimeError):
    def __init__(self, operation: str, status: int):
        super().__init__(f"{operation} failed with HTTP {status}")
        self.status = status


def utc_datetime(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def github_get(path: str, token: str) -> dict | list:
    url = f"{GITHUB_API}/{path.lstrip('/')}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise ApiError("GitHub metadata request", error.code) from None
    except (urllib.error.URLError, TimeoutError):
        raise ApiError("GitHub metadata request", 0) from None


def github_pages(path: str, token: str) -> list[dict]:
    results: list[dict] = []
    page = 1
    while True:
        separator = "&" if "?" in path else "?"
        payload = github_get(f"{path}{separator}per_page=100&page={page}", token)
        if isinstance(payload, dict) and "workflow_runs" in payload:
            batch = payload["workflow_runs"]
        elif isinstance(payload, dict) and "items" in payload:
            batch = payload["items"]
        elif isinstance(payload, list):
            batch = payload
        else:
            raise ApiError("GitHub metadata response", 0)
        results.extend(batch)
        if len(batch) < 100:
            return results
        page += 1


def action_runs(repo: str, token: str, since: dt.date) -> list[dict]:
    query = urllib.parse.urlencode({"created": f">={since.isoformat()}"})
    payload = github_get(f"repos/{repo}/actions/workflows/deploy-support.yml/runs?{query}&per_page=100", token)
    if not isinstance(payload, dict) or "workflow_runs" not in payload:
        raise ApiError("GitHub workflow runs", 0)
    runs = list(payload["workflow_runs"])
    page = 2
    while len(payload["workflow_runs"]) == 100:
        payload = github_get(f"repos/{repo}/actions/workflows/deploy-support.yml/runs?{query}&per_page=100&page={page}", token)
        runs.extend(payload.get("workflow_runs", []))
        page += 1
    return runs


def run_jobs(repo: str, run_id: int, token: str) -> list[dict]:
    payload = github_get(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100", token)
    return payload.get("jobs", []) if isinstance(payload, dict) else []


def is_qa_deploy(job: dict) -> bool:
    name = job.get("name", "").lower()
    return "deploy" in name and re.search(r"(^|[^a-z])qa([^a-z]|$)", name) is not None


def summarize_qa_job(job: dict) -> dict:
    steps = job.get("steps", [])
    intake = next((step for step in steps if "intake journey" in step.get("name", "").lower()), None)
    first_failed = next((step for step in steps if step.get("conclusion") == "failure"), None)
    return {
        "conclusion": job.get("conclusion", "unknown"),
        "intake_conclusion": intake.get("conclusion", "missing") if intake else "missing",
        "failure_stage": first_failed.get("name", "unknown") if first_failed else None,
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
    }


def product_area(files: list[dict]) -> str:
    prefixes = {
        "bun2too-support-agent/": "support-agent",
        "bun2too-website/": "website",
        "bun2too-crew-team/": "crew-team",
    }
    areas = {area for item in files for prefix, area in prefixes.items() if item.get("filename", "").startswith(prefix)}
    if len(areas) == 1:
        return next(iter(areas))
    if len(areas) > 1:
        return "multi-product"
    return "root"


def collect_pr_context(repo: str, token: str, since: dt.date) -> list[dict]:
    prs = github_pages(f"repos/{repo}/pulls?state=all&sort=updated&direction=desc", token)
    results = []
    for pr in prs:
        merged_at = pr.get("merged_at")
        if not merged_at or utc_datetime(merged_at).date() < since:
            continue
        number = pr["number"]
        files = github_pages(f"repos/{repo}/pulls/{number}/files", token)
        reviews = github_pages(f"repos/{repo}/pulls/{number}/reviews", token)
        merged_time = utc_datetime(merged_at)
        requested_changes = any(
            review.get("state") == "CHANGES_REQUESTED"
            and review.get("submitted_at")
            and utc_datetime(review["submitted_at"]) <= merged_time
            for review in reviews
        )
        results.append(
            {
                "number": number,
                "created_at": pr["created_at"],
                "merged_at": merged_at,
                "merge_sha": pr.get("merge_commit_sha"),
                "head_sha": (pr.get("head") or {}).get("sha"),
                "area": product_area(files),
                "author_type": (pr.get("user") or {}).get("type", "Unknown"),
                "requested_changes": requested_changes,
            }
        )
    return results


def empty_day(day: dt.date) -> dict:
    return {
        "date": day.isoformat(),
        "qa_attempts": 0,
        "qa_gate_passes": 0,
        "qa_failures": 0,
        "qa_cancelled": 0,
        "qa_unclassified": 0,
        "failure_stages": {},
        "merged_prs": 0,
        "requested_change_prs": 0,
        "merged_by_area": {},
        "merged_bot_prs": 0,
        "merged_human_prs": 0,
        "pr_to_qa_minutes": None,
    }


def build_report(repo: str, token: str) -> dict:
    today = dt.datetime.now(dt.timezone.utc).date()
    report_date = today - dt.timedelta(days=1)
    since = report_date - dt.timedelta(days=WINDOW_DAYS - 1)
    days = {since + dt.timedelta(days=i): empty_day(since + dt.timedelta(days=i)) for i in range(WINDOW_DAYS)}

    runs = action_runs(repo, token, since)
    qa_success_shas: dict[str, list[dt.datetime]] = defaultdict(list)
    failed_stage_totals: Counter[str] = Counter()
    for run in runs:
        day = utc_datetime(run["created_at"]).date()
        if day not in days:
            continue
        jobs = run_jobs(repo, run["id"], token)
        qa_jobs = [job for job in jobs if is_qa_deploy(job)]
        # A skipped QA job (for example, a manual dev-only run) is not an attempt.
        if not qa_jobs:
            continue
        summary = summarize_qa_job(qa_jobs[0])
        row = days[day]
        conclusion = summary["conclusion"]
        if conclusion == "cancelled":
            row["qa_cancelled"] += 1
            continue
        if conclusion == "skipped":
            continue
        row["qa_attempts"] += 1
        if conclusion == "success" and summary["intake_conclusion"] == "success":
            row["qa_gate_passes"] += 1
            sha = run.get("head_sha")
            if sha and run.get("updated_at"):
                qa_success_shas[sha].append(utc_datetime(run["updated_at"]))
        elif conclusion == "failure":
            row["qa_failures"] += 1
            stage = summary["failure_stage"] or "unknown"
            row["failure_stages"][stage] = row["failure_stages"].get(stage, 0) + 1
            failed_stage_totals[stage] += 1
        else:
            row["qa_unclassified"] += 1

    prs = collect_pr_context(repo, token, since)
    area_counts = Counter()
    for pr in prs:
        merged_day = utc_datetime(pr["merged_at"]).date()
        row = days.get(merged_day)
        if row is None:
            continue
        row["merged_prs"] += 1
        author_type = pr["author_type"]
        if author_type == "Bot":
            row["merged_bot_prs"] += 1
        elif author_type == "User":
            row["merged_human_prs"] += 1
        row["requested_change_prs"] += int(pr["requested_changes"])
        row["merged_by_area"][pr["area"]] = row["merged_by_area"].get(pr["area"], 0) + 1
        area_counts[pr["area"]] += 1
        candidates = []
        for sha in {pr.get("merge_sha"), pr.get("head_sha")} - {None}:
            candidates.extend(qa_success_shas.get(sha, []))
        if candidates:
            first_qa = min(candidates)
            minutes = (first_qa - utc_datetime(pr["created_at"])).total_seconds() / 60
            if minutes >= 0:
                # Keep individual values private to this report's aggregate.
                row.setdefault("_lead_times", []).append(round(minutes, 1))

    for row in days.values():
        lead_times = row.pop("_lead_times", [])
        if lead_times:
            row["pr_to_qa_minutes"] = round(median(lead_times), 1)
        row["qa_completion_rate"] = (
            round(row["qa_gate_passes"] / row["qa_attempts"], 4) if row["qa_attempts"] else None
        )

    history = list(days.values())
    today_row = days[report_date]
    total_attempts = sum(row["qa_attempts"] for row in history)
    total_passes = sum(row["qa_gate_passes"] for row in history)
    total_failures = sum(row["qa_failures"] for row in history)
    report = {
        "report_date_utc": report_date.isoformat(),
        "window_start_utc": since.isoformat(),
        "window_end_utc": report_date.isoformat(),
        "repository": repo,
        "source": "GitHub Actions and pull-request metadata; no logs or artifacts",
        "today": today_row,
        "history": history,
        "totals": {
            "qa_attempts": total_attempts,
            "qa_gate_passes": total_passes,
            "qa_failures": total_failures,
            "qa_cancelled": sum(row["qa_cancelled"] for row in history),
            "merged_prs": len(prs),
            "merged_bot_prs": sum(pr["author_type"] == "Bot" for pr in prs),
            "merged_human_prs": sum(pr["author_type"] == "User" for pr in prs),
            "requested_change_prs": sum(pr["requested_changes"] for pr in prs),
            "merged_by_area": dict(area_counts),
            "qa_completion_rate": round(total_passes / total_attempts, 4) if total_attempts else None,
            "failure_stages": dict(failed_stage_totals),
        },
        "customer_outcomes": {"status": "not_measured", "reason": "No sanitized business outcome is emitted by the QA workflow."},
        "limitations": [
            "QA gate pass means the deployment and intake script completed; the script currently accepts rejected as a terminal success.",
            "A green QA gate is not a production release or proof of an accepted customer outcome.",
            "PR-to-QA requires an exact merge SHA match; unmatched runs are not inferred.",
            "Historical days with no run are zero attempts only when GitHub metadata is available; API failures fail the report.",
            "No total token or model cost is reported because interactive agent usage is not fully instrumented.",
        ],
    }
    return report


def bar(value: int, peak: int) -> str:
    if not value:
        return "·"
    return "█" * max(1, min(20, round(value / max(peak, 1) * 20)))


def page_storage(report: dict) -> str:
    today = report["today"]
    totals = report["totals"]
    history = report["history"]
    max_pass = max((row["qa_gate_passes"] for row in history), default=0)
    max_fail = max((row["qa_failures"] for row in history), default=0)
    title = f"Daily agent delivery and quality — {report['report_date_utc']} UTC"
    rows = []
    for row in history:
        rows.append(
            "<tr>"
            f"<td>{row['date']}</td><td>{row['merged_prs']}</td>"
            f"<td>{row['qa_gate_passes']}</td><td>{row['qa_attempts']}</td>"
            f"<td>{row['qa_failures']}</td><td>{row['qa_cancelled']}</td><td>{row['merged_bot_prs']}</td>"
            f"<td>{row['requested_change_prs']}</td>"
            f"<td>{row['pr_to_qa_minutes'] if row['pr_to_qa_minutes'] is not None else '—'}</td>"
            "</tr>"
        )
    product_rows = "".join(f"<tr><td>{html.escape(area)}</td><td>{count}</td></tr>" for area, count in sorted(totals["merged_by_area"].items()))
    failures = "".join(f"<li>{html.escape(name)}: {count}</li>" for name, count in sorted(today["failure_stages"].items())) or "<li>None</li>"
    limitations = "".join(f"<li>{html.escape(item)}</li>" for item in report["limitations"])
    date = report["report_date_utc"]
    pass_chart = " ".join(bar(row["qa_gate_passes"], max_pass) for row in history)
    fail_chart = " ".join(bar(row["qa_failures"], max_fail) for row in history)
    completion_rate = "—" if today["qa_completion_rate"] is None else f"{today['qa_completion_rate']:.0%}"
    pr_to_qa = "—" if today["pr_to_qa_minutes"] is None else f"{today['pr_to_qa_minutes']} min"
    return f"""<h1>Daily agent delivery and quality — {date} UTC</h1>
<p>Read-only report from GitHub workflow and pull-request metadata. The report emphasizes verified release gates; merged PR count is context only.</p>
<h2>Yesterday (UTC)</h2>
<table><tbody>
<tr><th>QA gate passes</th><th>QA attempts</th><th>QA failures</th><th>Cancelled</th><th>Completion rate</th><th>Merged PRs</th><th>Bot-authored PRs</th><th>PRs with requested changes</th><th>PR-to-QA median</th></tr>
<tr><td>{today['qa_gate_passes']}</td><td>{today['qa_attempts']}</td><td>{today['qa_failures']}</td><td>{today['qa_cancelled']}</td><td>{completion_rate}</td><td>{today['merged_prs']}</td><td>{today['merged_bot_prs']}</td><td>{today['requested_change_prs']}</td><td>{pr_to_qa}</td></tr>
</tbody></table>
<h2>Verified customer outcomes</h2>
<p><strong>Not measured.</strong> The QA workflow does not emit a sanitized business outcome. A successful intake script may include a rejected terminal state, so this report does not infer accepted delivery from a green workflow.</p>
<h2>30-day trend (each bar is scaled within its row)</h2>
<table><tbody><tr><th>QA gate passes</th><td><code>{pass_chart}</code></td></tr><tr><th>QA failures</th><td><code>{fail_chart}</code></td></tr></tbody></table>
<h2>Daily history (UTC)</h2>
<table><tbody><tr><th>Date</th><th>Merged PRs</th><th>QA passes</th><th>QA attempts</th><th>QA failures</th><th>Cancelled</th><th>Bot-authored PRs</th><th>Requested-change PRs</th><th>PR-to-QA median (min)</th></tr>{''.join(rows)}</tbody></table>
<h2>Current-day QA failure stages</h2><ul>{failures}</ul>
<h2>Merged PRs by product area (30 days)</h2><table><tbody><tr><th>Area</th><th>Count</th></tr>{product_rows or '<tr><td>None</td><td>0</td></tr>'}</tbody></table>
<h2>Reading this report</h2><ul>{limitations}</ul>
<p><small>Window: {report['window_start_utc']} through {report['window_end_utc']} UTC. No customer data, prompts, model responses, logs, or artifact contents were read.</small></p>"""


def confluence_request(method: str, path: str, body: dict | None, email: str, token: str) -> dict:
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{CONFLUENCE}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response) if response.status != 204 else {}
    except urllib.error.HTTPError as error:
        raise ApiError(f"Confluence {method}", error.code) from None
    except (urllib.error.URLError, TimeoutError):
        raise ApiError(f"Confluence {method}", 0) from None


def publish_page(title: str, storage: str, email: str, token: str) -> str:
    query = urllib.parse.urlencode({"space-id": SPACE_ID, "title": title, "status": "current", "limit": 100})
    existing = confluence_request("GET", f"/wiki/api/v2/pages?{query}", None, email, token)
    titled_pages = [page for page in existing.get("results", []) if page.get("title") == title]
    pages = [page for page in titled_pages if str(page.get("parentId")) == PARENT_ID]
    if titled_pages and not pages:
        raise ApiError("Confluence page exists outside the requested parent folder", 409)
    if pages:
        page = pages[0]
        version = page.get("version", {}).get("number")
        if not isinstance(version, int):
            raise ApiError("Confluence page version lookup", 0)
        payload = {
            "id": page["id"],
            "status": "current",
            "title": title,
            "spaceId": SPACE_ID,
            "body": {"representation": "storage", "value": storage},
            "version": {"number": version + 1, "message": "Refresh daily delivery metrics"},
        }
        updated = confluence_request("PUT", f"/wiki/api/v2/pages/{page['id']}", payload, email, token)
        return updated.get("_links", {}).get("webui", "page updated")
    payload = {
        "spaceId": SPACE_ID,
        "parentId": PARENT_ID,
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage},
    }
    created = confluence_request("POST", "/wiki/api/v2/pages", payload, email, token)
    return created.get("_links", {}).get("webui", "page created")


def markdown_to_storage(markdown: str) -> str:
    """Convert the maintained design note's small Markdown subset to Confluence storage HTML."""
    def inline(text: str) -> str:
        escaped = html.escape(text, quote=False)
        escaped = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', escaped)
        escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        return escaped

    lines = markdown.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith("```"):
            index += 1
            code: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                code.append(lines[index])
                index += 1
            output.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            index += int(index < len(lines))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            output.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue
        if line.startswith("| "):
            table_rows = []
            while index < len(lines) and lines[index].startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    table_rows.append(cells)
                index += 1
            if table_rows:
                head = "".join(f"<th>{inline(cell)}</th>" for cell in table_rows[0])
                body = "".join("<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>" for row in table_rows[1:])
                output.append(f"<table><tbody><tr>{head}</tr>{body}</tbody></table>")
            continue
        if re.match(r"^\s*-\s+", line):
            items = []
            while index < len(lines) and re.match(r"^\s*-\s+", lines[index]):
                items.append("<li>" + inline(re.sub(r"^\s*-\s+", "", lines[index])) + "</li>")
                index += 1
            output.append("<ul>" + "".join(items) + "</ul>")
            continue
        para = [line.strip()]
        index += 1
        while index < len(lines) and lines[index].strip() and not lines[index].startswith(("#", "| ", "```")) and not re.match(r"^\s*-\s+", lines[index]):
            para.append(lines[index].strip())
            index += 1
        output.append("<p>" + inline(" ".join(para)) + "</p>")
    return "\n".join(output)


def write_artifacts(report: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    fields = ["date", "merged_prs", "merged_bot_prs", "merged_human_prs", "qa_gate_passes", "qa_attempts", "qa_failures", "qa_cancelled", "requested_change_prs", "pr_to_qa_minutes"]
    with (OUTPUT_DIR / "history.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in report["history"]:
            writer.writerow({key: row.get(key, "") for key in fields})


def main() -> int:
    repo = os.environ.get("GITHUB_REPOSITORY", "Bun2too/bun2too")
    token = os.environ.get("GITHUB_TOKEN")
    email = os.environ.get("ATLASSIAN_EMAIL")
    atlassian_token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not token:
        print("Missing GITHUB_TOKEN", file=sys.stderr)
        return 2
    try:
        report = build_report(repo, token)
        write_artifacts(report)
        if not email or not atlassian_token:
            raise ApiError("Confluence credentials unavailable", 0)
        design_path = Path("docs/agents/daily-agent-delivery-metrics.md")
        design_storage = markdown_to_storage(design_path.read_text(encoding="utf-8"))
        design_page = publish_page("Daily agent delivery and quality metrics", design_storage, email, atlassian_token)
        report_page = publish_page(
            f"Daily agent delivery and quality — {report['report_date_utc']} UTC",
            page_storage(report),
            email,
            atlassian_token,
        )
    except ApiError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Report date: {report['report_date_utc']} UTC")
    print(f"QA gate passes (30d): {report['totals']['qa_gate_passes']}/{report['totals']['qa_attempts']}")
    print(f"Confluence design page: {design_page}")
    print(f"Confluence daily page: {report_page}")
    print(f"Artifacts: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
