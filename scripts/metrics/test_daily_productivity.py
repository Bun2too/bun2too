import datetime as dt
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

import daily_productivity as metrics


class FixedDateTime(dt.datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 11, 24, 12, tzinfo=dt.timezone.utc)
        return value.astimezone(tz) if tz else value


def job(name, conclusion, steps=None):
    return {"name": name, "conclusion": conclusion, "steps": steps or []}


def qa_job(conclusion="success", intake="success", failed_step=None):
    steps = [{"name": "Intake journey", "conclusion": intake}]
    if failed_step:
        steps.insert(0, {"name": failed_step, "conclusion": "failure"})
    return job("qa / deploy", conclusion, steps)


class MetricsTests(unittest.TestCase):
    @patch.object(metrics, "github_get")
    def test_pr_scan_stops_after_pagination_reaches_older_updates(self, github_get):
        github_get.return_value = [{"updated_at": "2026-10-25T00:00:00Z"}]
        self.assertEqual(metrics.collect_pr_context("Bun2too/bun2too", "token", dt.date(2026, 11, 1)), [])
        github_get.assert_called_once()

    @patch.object(metrics, "github_pages")
    @patch.object(metrics, "github_get")
    def test_pr_context_records_failed_bot_verdict_without_retaining_text(self, github_get, github_pages):
        merged_at = "2026-11-23T12:00:00Z"
        github_get.return_value = [{
            "updated_at": merged_at,
            "merged_at": merged_at,
            "number": 9,
            "created_at": "2026-11-23T09:00:00Z",
            "merge_commit_sha": "merge-sha",
            "head": {"sha": "head-sha"},
            "user": {"type": "Bot"},
        }]
        github_pages.side_effect = [
            [],
            [{"state": "COMMENTED", "submitted_at": merged_at, "user": {"type": "Bot"}, "body": "CROSS-REVIEW (codex): FAIL"}],
            [],
        ]
        result = metrics.collect_pr_context("Bun2too/bun2too", "token", dt.date(2026, 11, 1))
        self.assertTrue(result[0]["failed_verdict"])
        self.assertNotIn("body", result[0])

    def test_run_classification_covers_pre_qa_and_qa_outcomes(self):
        self.assertEqual(metrics.classify_run({"conclusion": "failure"}, []), "workflow_invalid")
        self.assertEqual(
            metrics.classify_run({}, [job("verify", "failure")]), "verify_failed"
        )
        self.assertEqual(metrics.classify_run({}, [qa_job()]), "qa_green")
        self.assertEqual(
            metrics.classify_run({}, [qa_job("failure", "skipped", "Deploy to Railway")]),
            "qa_failed:Deploy to Railway",
        )
        self.assertEqual(metrics.classify_run({}, [qa_job("success", "failure")]), "qa_failed:Intake journey")
        self.assertEqual(
            metrics.classify_run({}, [job("qa / deploy", "success")]),
            "qa_failed:Intake journey (missing)",
        )
        self.assertEqual(
            metrics.classify_run({}, [job("dev / deploy", "success", [{"name": "Offline intake journey", "conclusion": "success"}])]),
            "retired_dev_offline",
        )
        self.assertEqual(metrics.classify_run({"conclusion": "cancelled"}, []), "cancelled")

    def test_failed_verdict_requires_exact_standalone_line(self):
        self.assertTrue(metrics.has_failed_verdict("Reviewed SHA\nCROSS-REVIEW (codex): FAIL\nFinding"))
        self.assertTrue(metrics.has_failed_verdict("VERDICT: FAIL"))
        self.assertFalse(metrics.has_failed_verdict("The previous verdict was FAIL"))
        self.assertFalse(metrics.has_failed_verdict("CROSS-REVIEW (codex): PASS"))

    @patch.object(metrics, "collect_pr_context")
    @patch.object(metrics, "pending_deployments")
    @patch.object(metrics, "run_jobs")
    @patch.object(metrics, "action_runs")
    def test_report_classifies_runs_and_matches_prod_approval_by_pending_environment(
        self, action_runs, run_jobs, pending_deployments, collect_pr_context
    ):
        timestamp = "2026-11-23T12:00:00Z"
        runs = [
            {"id": 1, "created_at": timestamp, "updated_at": timestamp, "head_sha": "sha-green", "status": "waiting"},
            {"id": 2, "created_at": timestamp, "updated_at": timestamp, "head_sha": "sha-not-waiting", "status": "completed"},
            {"id": 3, "created_at": timestamp, "updated_at": timestamp, "head_sha": "sha-fail", "status": "completed"},
            {"id": 4, "created_at": timestamp, "updated_at": timestamp, "head_sha": "sha-verify", "status": "completed"},
            {"id": 5, "created_at": timestamp, "updated_at": timestamp, "head_sha": "sha-empty", "status": "completed", "conclusion": "failure"},
            {"id": 6, "created_at": timestamp, "updated_at": timestamp, "head_sha": "sha-dev", "status": "completed"},
            {"id": 7, "created_at": timestamp, "updated_at": timestamp, "head_sha": "sha-cancel", "status": "completed", "conclusion": "cancelled"},
        ]
        action_runs.return_value = runs
        jobs_by_id = {
            1: [qa_job()],
            2: [qa_job()],
            3: [qa_job("failure", "skipped", "Intake journey")],
            4: [job("verify", "failure")],
            5: [],
            6: [job("dev / deploy", "success", [{"name": "Offline intake journey", "conclusion": "success"}])],
            7: [],
        }
        run_jobs.side_effect = lambda repo, run_id, token: jobs_by_id[run_id]
        pending_deployments.return_value = [{"environment": {"name": "support-prod"}}]
        collect_pr_context.return_value = [{
            "number": 12,
            "created_at": "2026-11-23T10:00:00Z",
            "merged_at": "2026-11-23T11:00:00Z",
            "merge_sha": None,
            "head_sha": "sha-green",
            "area": "root",
            "author_type": "Bot",
            "requested_changes": False,
            "failed_verdict": True,
        }]

        with patch.object(metrics.dt, "datetime", FixedDateTime):
            report = metrics.build_report("Bun2too/bun2too", "token")

        day = report["today"]
        self.assertEqual(day["workflow_runs"], 7)
        self.assertEqual(day["qa_gate_passes"], 2)
        self.assertEqual(day["qa_failures"], 1)
        self.assertEqual(day["retired_dev_offline_attempts"], 1)
        self.assertEqual(day["run_classes"]["workflow_invalid"], 1)
        self.assertEqual(day["run_classes"]["verify_failed"], 1)
        self.assertEqual(day["failed_verdict_prs"], 1)
        self.assertEqual(day["pr_to_qa_minutes"], 120.0)
        self.assertEqual([entry["run_id"] for entry in report["pending_prod_approvals"]], [1])
        self.assertEqual(pending_deployments.call_count, 1)

    @patch.object(metrics, "confluence_request")
    def test_resolves_numeric_space_id_from_key(self, request):
        request.return_value = {"results": [{"id": "12345", "key": metrics.SPACE_KEY}]}
        self.assertEqual(metrics.resolve_space_id("https://api.example", "token"), "12345")
        self.assertIn("keys=", request.call_args.args[1])

    @patch.object(metrics, "confluence_request")
    def test_publish_page_creates_then_updates_and_refuses_wrong_parent(self, request):
        request.side_effect = [
            {"results": []},
            {"_links": {"webui": "/created"}},
            {"results": [{"id": "7", "title": "Report", "parentId": metrics.PARENT_ID, "version": {"number": 2}}]},
            {"_links": {"webui": "/updated"}},
        ]
        self.assertEqual(metrics.publish_page("Report", "<p>x</p>", "api", "token", "12345"), "/created")
        self.assertEqual(metrics.publish_page("Report", "<p>y</p>", "api", "token", "12345"), "/updated")
        update_body = request.call_args.args[2]
        self.assertEqual(update_body["version"]["number"], 3)
        self.assertEqual(update_body["spaceId"], 12345)

        request.reset_mock()
        request.side_effect = None
        request.return_value = {"results": [{"id": "8", "title": "Report", "parentId": "elsewhere"}]}
        with self.assertRaises(metrics.ApiError):
            metrics.publish_page("Report", "<p>x</p>", "api", "token", "12345")

    def test_real_design_document_converts_to_well_formed_storage_xhtml(self):
        design = metrics.Path("docs/agents/daily-agent-delivery-metrics.md").read_text(encoding="utf-8")
        storage = metrics.markdown_to_storage(design)
        ElementTree.fromstring(f"<root>{storage}</root>")


if __name__ == "__main__":
    unittest.main()
