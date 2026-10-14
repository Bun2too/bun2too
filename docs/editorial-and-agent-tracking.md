# Daily editorial coverage and agent execution tracking

The packaged marketing profile rotates seven daily themes: concepts and research; enterprise use cases; retrieval and data; security and privacy; evaluation and reliability; responsible AI and governance; and agent implementation. Research is drawn round-robin from Hugging Face, AWS machine learning, Google Research, Cloudflare, and GitHub. Feed failures are recorded; future-dated and stale entries are excluded.

Each scheduled run receives the preceding seven days of successfully published article titles and citations. The Product Owner must explain topic selection, rejected alternatives, and sources. The Editor checks theme coverage, repetition, and provider neutrality. A deterministic headline check blocks repeated titles and repeated Microsoft/Copilot/Azure, OpenAI, Google, Anthropic, Amazon, or Meta product-family mentions within that history. This is a conservative headline heuristic; semantic repetition and unnamed providers remain editorial checks. Body comparisons are allowed. Unsupported themes may be replaced with an evidenced, underrepresented theme with a recorded explanation.

The policy takes effect with the next generated campaign; existing approved articles are not regenerated. An externally supplied `MARKETING_PROFILE_PATH` must also be updated to adopt the expanded feeds and brief.

## Where to inspect work

Authenticated `GET /runs/{run_id}/work` returns the event journal, remote Jira/Confluence links and an `agents` report for every configured role. It includes execution status, durations, failures, model-call counts, token usage, estimated cost, and the latest structured deliverable (decisions, evidence, assumptions, risks and content review). Missing timing, usage and pricing remain null. Counts and durations include retries; latest deliverables belong to the current run attempt. Old runs retain their available evidence; historical measurements are not invented. Execution completion is not a quality score: inspect Tester/Editor approvals and the run's quality evaluation separately.

Each new scheduled run gets a distinct Jira Epic with two Stories: **Generate daily campaign** and **Publish approved content**. The application records actual state, approval, blockers and remote Facebook post ID. Once agent output or failure diagnostics exist, a Confluence dossier contains the artifact, agent deliverables, performance report, editorial context and trace correlation. Lifecycle events record explicit operational actions and concise decision summaries, not private model reasoning. Jira workflow status, assignee and sprint remain human-owned; the descriptions carry application outcomes.

Tracking synchronizes at generation start/end, approval, publication and reconciliation. `ATLASSIAN_AUTO_PUBLISH=true` enables remote synchronization using the existing configured Jira project, Confluence space and Atlassian credentials. With it disabled, records remain queued locally. Existing publication limits still apply. Tracking outages are recorded in `atlassian_sync_failed` / `atlassian_sync_incomplete` and do not change Facebook delivery outcomes.

After fixing a tracking outage, use authenticated `POST /runs/{run_id}/atlassian/publish` to synchronize the current snapshot. Unknown remote outcomes require the existing publication reconciliation endpoint before revision; they must not be blindly retried. Existing conflict protection preserves human edits. No historical runs are automatically backfilled.

Deploy the updated CrewAI service and its profile through the existing deployment workflow. No database migration or additional credentials are needed if the existing Atlassian integration is already configured.
