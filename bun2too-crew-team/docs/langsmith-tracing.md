# LangSmith tracing for the CrewAI team

The service mirrors its existing application spans to LangSmith using the SDK's [custom RunTree instrumentation](https://docs.langchain.com/langsmith/annotate-code). It traces the actual CrewAI execution rather than creating a separate OpenAI quickstart client. No LangChain agent migration or `deepagents` dependency is needed. The existing OpenAI dependency and model settings remain in use.

Install the service requirements and configure `crewai_agents/.env` (ignored by Git):

```sh
.venv/bin/python -m pip install -r crewai_agents/requirements.txt
```

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=<workspace API key>
LANGSMITH_AGENT_ID=crew-ai-agents
LANGSMITH_AGENT_ENVIRONMENT=local
```

Use the existing `OPENAI_API_KEY` and `LLM_MODEL`. Restart the service with its usual command (`.venv/bin/python crewai_agents/start.py`). For hosted execution, add these LangSmith values to the existing runtime secret map, use the appropriate environment, and redeploy. Never commit the API key.

The pinned LangSmith SDK supports [agent addressing](https://docs.langchain.com/langsmith/log-traces-to-agent). Agent ID and environment must be set together. This requires an agent-based LangSmith workspace. Do not combine them with `LANGSMITH_PROJECT`, `LANGCHAIN_PROJECT`, or `LANGCHAIN_SESSION`. For a classic project-based workspace, unset both agent variables and set `LANGSMITH_PROJECT=crew-ai-agents` instead.

## What appears in LangSmith

Select agent **crew-ai-agents**, open **Tracing**, and choose **Local**. Campaign execution nests crew kickoff, agent tasks, model calls, retrieval, checks and publication operations. Background publishing runs are separate traces correlated by `run.id`; the durable journal also records `langsmith.run_id` and `langsmith.trace_id`. SDK IDs are available in authenticated `GET /runs/{run_id}/work` events.

LLM spans carry measured token usage and model metadata. Task steps carry role/tool names, duration and outcomes. Application errors record exception types, not exception messages or private reasoning. Tracing remains available with OTLP/Datadog disabled and can run alongside them. SQLite transaction spans are excluded to avoid noise.

By default, prompts, tool inputs, article text and decision summaries are not exported. Existing `TELEMETRY_CAPTURE_CONTENT=true` additionally allows redacted agent summaries, decisions, evidence and tool inputs. This opt-in affects other telemetry exporters too. Full LLM prompts/responses are not automatically captured by this adapter.

LangSmith export is asynchronous and best effort; failures do not change campaign or Facebook outcomes. The local event journal remains durable. Authenticated `GET /observability/status` includes LangSmith configuration, queued-run count and observed SDK export failures. A queued count is not proof of remote receipt. Configuration/client changes require a restart.

## Verify without generating or publishing content

```sh
.venv/bin/python scripts/check_langsmith.py
.venv/bin/python scripts/check_langsmith.py --send
```

The first command validates configuration locally. The second sends one synthetic parent/child trace, flushes it, and checks that the parent can be read back with a completion timestamp. It does not invoke a model, start campaign workers, create Jira records or publish to Facebook. Authentication/ingestion failures are reported by exception type without printing credentials.
