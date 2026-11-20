#!/usr/bin/env python3
"""Turn one factory run into one OpenTelemetry trace and a GitHub job summary.

The trace is a waterfall: the run, its jobs and steps (from the GitHub API), and inside the
agent steps every model turn, tool call and subagent (from Claude Code's session transcripts,
which time-stamp each entry). Spans follow the OpenTelemetry GenAI conventions, as Relay's
do (bun2too-support-agent/docs/adr/0004), so any OTLP backend shows them as model calls.

Runs in agent-review.yml's trace job, never on an agent's runner. The transcripts are agent
output: they are secret-scanned first, and --no-content drops every prompt, reply and tool
input or result when the scan finds something. Standard library only.
"""

import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

LIMIT = 16_000  # characters per content attribute
ROLES = {
    "review": [".github/workflows/agent-review.yml", ".claude/skills/factory-review/SKILL.md"],
    "rework": [".github/workflows/agent-rework.yml"],
}


def ns(ts):
    if not ts:
        return None
    return int(dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1e9)


def short(text, n=LIMIT):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= n else text[:n] + f"... ({len(text) - n} more characters)"


def otlp_value(v):
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (list, tuple)) and all(isinstance(x, str) for x in v):
        return {"arrayValue": {"values": [{"stringValue": x} for x in v]}}
    return {"stringValue": v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}


class Trace:
    def __init__(self, key, content):
        self.trace_id = hashlib.sha256(key.encode()).hexdigest()[:32]
        self.content = content
        self.spans = []

    def add(self, name, start, end, parent=None, attrs=None, content=None, error=None, depth=0, key=None):
        span_id = hashlib.sha256(f"{self.trace_id}/{key or len(self.spans)}".encode()).hexdigest()[:16]
        attrs = {k: v for k, v in (attrs or {}).items() if v is not None}
        if self.content:
            attrs.update({k: short(v) for k, v in (content or {}).items() if v not in (None, "", [])})
        end = max(end or start, start)
        self.spans.append({
            "traceId": self.trace_id, "spanId": span_id, "parentSpanId": parent or "",
            "name": name, "kind": 1, "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
            "attributes": [{"key": k, "value": otlp_value(v)} for k, v in attrs.items()],
            "status": {"code": 2, "message": short(error, 500)} if error else {"code": 0},
            "_depth": depth, "_attrs": attrs,
        })
        return span_id

    def span(self, span_id):
        return next(s for s in self.spans if s["spanId"] == span_id)

    def set(self, span_id, attrs):
        self.span(span_id)["attributes"] += [{"key": k, "value": otlp_value(v)} for k, v in attrs.items()]


# --- GitHub jobs and steps ---------------------------------------------------------------

def add_jobs(trace, jobs, root, now):
    """Adds a span per job and step. Returns {job short name: (span id, agent step span id, depth)}."""
    found = {}
    for job in sorted(jobs, key=lambda j: j.get("started_at") or ""):
        if job.get("conclusion") == "skipped" or not job.get("started_at") or job["name"] == "trace":
            continue
        start, end = ns(job["started_at"]), ns(job.get("completed_at")) or now
        failed = job.get("conclusion") in ("failure", "timed_out", "cancelled")
        jid = trace.add(f"job {job['name']}", start, end, root, depth=1, key=f"job/{job['id']}",
                        error=f"job {job.get('conclusion')}" if failed else None,
                        attrs={"cicd.pipeline.task.name": job["name"], "cicd.pipeline.task.run.id": job["id"],
                               "cicd.pipeline.task.run.url.full": job.get("html_url"),
                               "cicd.pipeline.task.run.result": job.get("conclusion")})
        agent_step = None
        for step in job.get("steps") or []:
            if step.get("conclusion") == "skipped" or not step.get("started_at"):
                continue
            s_failed = step.get("conclusion") == "failure"
            sid = trace.add(f"step {step['name']}", ns(step["started_at"]), ns(step.get("completed_at")) or now,
                            jid, depth=2, key=f"job/{job['id']}/{step['number']}",
                            error="step failed" if s_failed else None,
                            attrs={"cicd.pipeline.task.step.name": step["name"], "cicd.pipeline.task.step.number": step["number"],
                                   "cicd.pipeline.task.step.result": step.get("conclusion")})
            if step["name"].startswith("Run ./.github/actions/factory-agent"):
                agent_step = sid
        found[job["name"].split(" / ")[-1]] = (jid, agent_step)
    return found


# --- Claude Code transcripts ---------------------------------------------------------------

def load(path):
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("type") in ("user", "assistant") and e.get("timestamp"):
                entries.append(e)
    return entries


def blocks(message):
    content = (message or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def result_text(block):
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(x.get("text", f"[{x.get('type')}]") for x in c if isinstance(x, dict))
    return c if isinstance(c, str) else json.dumps(c)


class Session:
    """One agent's transcript: model turns and tool calls, recursing into subagents."""

    def __init__(self, trace, folder, summary):
        self.trace, self.folder, self.summary = trace, folder, summary
        self.metas = {}
        for meta in glob.glob(os.path.join(folder, "**", "subagents", "*.meta.json"), recursive=True):
            try:
                with open(meta, encoding="utf-8") as f:
                    m = json.load(f)
                self.metas[m.get("toolUseId")] = (meta[: -len(".meta.json")] + ".jsonl", m)
            except (OSError, ValueError):
                pass

    def run(self, path, parent, depth, name, attrs=None, content=None, totals=None):
        entries = load(path)
        if not entries:
            return None
        start, end = ns(entries[0]["timestamp"]), ns(entries[-1]["timestamp"])
        model = next((e["message"].get("model") for e in entries if e["type"] == "assistant"), None)
        agent = self.trace.add(f"invoke_agent {name}", start, end, parent, depth=depth, key=f"{path}/agent",
                               attrs={"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": name,
                                      "gen_ai.provider.name": "anthropic", "gen_ai.request.model": model,
                                      "gen_ai.conversation.id": entries[0].get("sessionId"), **(attrs or {})},
                               content=content)
        turns, usage = [], {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
        # Listed before the subagents it starts, which add their own entries as they run.
        self.summary.append({"name": name, "span": agent, "depth": depth, "start": start, "end": end, "model": model,
                             "turns": turns, "usage": usage, "totals": totals})
        pending_input, open_tools, last_ts, i = [], {}, start, 0
        while i < len(entries):
            e = entries[i]
            if e["type"] == "user":
                for b in blocks(e.get("message")):
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in open_tools:
                        self.tool(open_tools.pop(b["tool_use_id"]), b, ns(e["timestamp"]), agent, depth + 1, path, turns)
                    if b.get("type") in ("text", "tool_result"):
                        pending_input.append(b)
                last_ts = ns(e["timestamp"])
                i += 1
                continue
            # One model response is several entries with the same message id, one per block.
            msg_id, group = e["message"].get("id"), []
            while i < len(entries) and entries[i]["type"] == "assistant" and entries[i]["message"].get("id") == msg_id:
                group.append(entries[i])
                i += 1
            msg = group[-1]["message"]
            u = msg.get("usage") or {}
            usage["in"] += u.get("input_tokens", 0)
            usage["out"] += u.get("output_tokens", 0)
            usage["cache_read"] += u.get("cache_read_input_tokens", 0)
            usage["cache_write"] += u.get("cache_creation_input_tokens", 0)
            out = [b for g in group for b in blocks(g["message"])]
            text = "\n\n".join(b["text"] for b in out if b.get("type") == "text" and b.get("text"))
            thinking = "\n\n".join(b["thinking"] for b in out if b.get("type") == "thinking" and b.get("thinking"))
            calls = [b for b in out if b.get("type") == "tool_use"]
            t_end = ns(group[-1]["timestamp"])
            n = len(turns) + 1
            self.trace.add(f"chat {msg.get('model')}", last_ts, t_end, agent, depth=depth + 1, key=f"{path}/{msg_id}",
                           attrs={"gen_ai.operation.name": "chat", "gen_ai.provider.name": "anthropic",
                                  "gen_ai.request.model": msg.get("model"), "gen_ai.response.id": msg_id,
                                  "gen_ai.response.finish_reasons": [msg.get("stop_reason") or "unknown"],
                                  "gen_ai.usage.input_tokens": u.get("input_tokens"),
                                  "gen_ai.usage.output_tokens": u.get("output_tokens"),
                                  "gen_ai.usage.cache_read.input_tokens": u.get("cache_read_input_tokens"),
                                  "gen_ai.usage.cache_creation.input_tokens": u.get("cache_creation_input_tokens"),
                                  "factory.turn": n, "factory.thinking": any(b.get("type") == "thinking" for b in out),
                                  "factory.tool_calls": [c.get("name", "") for c in calls]},
                           content={"gen_ai.input.messages": json.dumps([{"role": "user", "parts": pending_input}], ensure_ascii=False) if pending_input else None,
                                    "gen_ai.output.messages": json.dumps([{"role": "assistant", "parts": out}], ensure_ascii=False),
                                    "input.value": "\n\n".join(b.get("text") or result_text(b) for b in pending_input) or None,
                                    "output.value": text or None, "factory.thinking.text": thinking or None})
            turns.append({"n": n, "start": last_ts, "end": t_end, "tokens": u.get("output_tokens", 0),
                          "text": text, "thinking": thinking, "calls": []})
            for g in group:
                for b in blocks(g["message"]):
                    if b.get("type") == "tool_use":
                        open_tools[b["id"]] = (b, ns(g["timestamp"]), n)
            pending_input, last_ts = [], t_end
        for call in open_tools.values():  # never answered: the run stopped mid-call
            self.tool(call, {"is_error": True, "content": "no result: the run stopped before the tool returned"}, end, agent, depth + 1, path, turns)
        self.trace.set(agent, {"gen_ai.usage.input_tokens": usage["in"], "gen_ai.usage.output_tokens": usage["out"],
                               "gen_ai.usage.cache_read.input_tokens": usage["cache_read"],
                               "gen_ai.usage.cache_creation.input_tokens": usage["cache_write"], "factory.turns": len(turns)})
        return agent

    def tool(self, call, result, t_end, parent, depth, path, turns):
        b, t_start, turn = call
        error = result_text(result) if result.get("is_error") else None
        tid = self.trace.add(f"execute_tool {b.get('name')}", t_start, t_end, parent, depth=depth, key=f"{path}/{b['id']}",
                             error=("tool error" if not self.trace.content else error) if error else None,
                             attrs={"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": b.get("name"),
                                    "gen_ai.tool.call.id": b.get("id"), "factory.turn": turn},
                             content={"gen_ai.tool.call.arguments": json.dumps(b.get("input"), ensure_ascii=False),
                                      "gen_ai.tool.call.result": result_text(result),
                                      "input.value": json.dumps(b.get("input"), ensure_ascii=False),
                                      "output.value": result_text(result)})
        turns[turn - 1]["calls"].append({"name": b.get("name"), "input": b.get("input"), "result": result_text(result),
                                         "error": bool(error), "ms": (t_end - t_start) // 1_000_000})
        if b["id"] in self.metas:
            sub_path, meta = self.metas[b["id"]]
            if os.path.exists(sub_path):
                self.run(sub_path, tid, depth + 1, meta.get("agentType") or "subagent",
                         attrs={"gen_ai.agent.description": meta.get("description")})


def add_agent(trace, folder, role, parent, depth, summary):
    """One agent job's trace folder: config.json, run.json and Claude Code's transcripts."""
    def read(name):
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    config, run = read("config.json"), read("run.json")
    paths = [p for p in glob.glob(os.path.join(folder, "transcripts", "**", "*.jsonl"), recursive=True)
             if "/subagents/" not in p]
    sid = run.get("session_id")
    main = next((p for p in paths if sid and os.path.basename(p) == f"{sid}.jsonl"), None)
    main = main or (max(paths, key=os.path.getsize) if paths else None)
    attrs = {"factory.role": role, "factory.provider": config.get("provider"),
             "gen_ai.request.max_turns": config.get("max_turns"), "factory.max_budget_usd": config.get("max_budget_usd"),
             "factory.allowed_tools": config.get("allowed_tools"), "factory.read_only": config.get("read_only"),
             "factory.claude_settings": config.get("settings"), "factory.prompt.source": ", ".join(ROLES.get(role, [])),
             "factory.cost_usd": run.get("total_cost_usd"), "factory.num_turns": run.get("num_turns"),
             "factory.result": run.get("subtype"), "factory.claude_code.version": run.get("claude_code_version"),
             "factory.permission_denials": run.get("permission_denials")}
    content = {"gen_ai.system_instructions": config.get("prompt"), "input.value": config.get("prompt"),
               "output.value": run.get("result")}
    session = Session(trace, folder, summary)
    if main and session.run(main, parent, depth, role, attrs, content, run):
        return
    # Codex and Gemini leave no transcript: the agent is one span over its step.
    step = trace.span(parent)
    trace.add(f"invoke_agent {role}", int(step["startTimeUnixNano"]), int(step["endTimeUnixNano"]), parent,
              attrs, content, depth=depth, key=f"{role}/agent")


# --- outputs -------------------------------------------------------------------------------

def md(text, n=600):
    text = short(text or "", n)
    return text.replace("\r", "")


def cell(text):
    return md(text, 80).replace("|", "\\|").replace("\n", " ")


def waterfall(trace, spans, out, limit=200, width=32):
    """A table with one bar per span, scaled to the spans shown, in depth-first order."""
    t0 = min(int(s["startTimeUnixNano"]) for s in spans)
    total = max(max(int(s["endTimeUnixNano"]) for s in spans) - t0, 1)
    by_id = {s["spanId"]: s for s in trace.spans}

    def path(s):  # parents before children, siblings by start time
        chain = []
        while s:
            chain.append((int(s["startTimeUnixNano"]), s["spanId"]))
            s = by_id.get(s["parentSpanId"])
        return list(reversed(chain))
    base = min(s["_depth"] for s in spans)
    out += ["| Span | Start | Took | Waterfall |", "| --- | ---: | ---: | --- |"]
    rows = sorted(spans, key=path)
    for s in rows[:limit]:
        a, b = int(s["startTimeUnixNano"]) - t0, int(s["endTimeUnixNano"]) - t0
        left = min(round(a / total * width), width - 1)
        bar = ("░" * left + "█" * max(1, round((b - a) / total * width)) + "░" * width)[:width]
        mark = " ❌" if s["status"]["code"] == 2 else ""
        out.append(f"| {'&nbsp;&nbsp;' * (s['_depth'] - base)}{cell(s['name'])}{mark} | {a / 1e9:.1f}s | {(b - a) / 1e9:.1f}s | `{bar}` |")
    if len(rows) > limit:
        out.append(f"| … {len(rows) - limit} more spans in the trace | | | |")


def descendants(trace, span_id):
    found, ids = [], {span_id}
    for s in sorted(trace.spans, key=lambda s: s["_depth"]):
        if s["spanId"] in ids or s["parentSpanId"] in ids:
            ids.add(s["spanId"])
            found.append(s)
    return found


def write_summary(trace, summary, args, exported):
    out = [f"## Factory trace: PR #{args.pr}", ""]
    link = args.trace_url.replace("{trace_id}", trace.trace_id) if args.trace_url else ""
    out.append(f"Trace ID `{trace.trace_id}`" + (f" · [open the trace]({link})" if link and exported else "")
               + f" · {len(trace.spans)} spans · OTLP file in this run's `trace` artifact")
    if not exported:
        out.append(f"\n> {args.export_note}")
    if not trace.content:
        out.append("\n> The secret scan flagged the agent transcripts, so prompts, replies and tool input/output are left out of this trace and summary (AGENTS.md rule 11).")
    out += ["", "### Run", ""]
    # Jobs, and steps only when they run an agent or failed.
    waterfall(trace, [s for s in trace.spans if s["_depth"] <= 2 and (
        not s["name"].startswith("step ") or "factory-agent" in s["name"] or s["status"]["code"] == 2)], out)
    for agent in summary:
        u, r = agent["usage"], agent["totals"] or {}
        top = agent["totals"] is not None
        out.append(f"\n### Agent: {agent['name']} ({agent['model']})" if top else f"\n#### Subagent: {agent['name']}")
        bits = [f"{len(agent['turns'])} turns", f"{(agent['end'] - agent['start']) / 1e9:.0f}s",
                f"{u['out']:,} output tokens", f"{u['in'] + u['cache_read'] + u['cache_write']:,} input tokens ({u['cache_read']:,} from cache)"]
        if r.get("total_cost_usd") is not None:
            bits.append(f"${r['total_cost_usd']:.3f}")
        if r.get("permission_denials"):
            bits.append(f"{len(r['permission_denials'])} refused tool calls")
        out.append(" · ".join(bits))
        if top:  # one waterfall per top-level agent, subagents included, on its own time scale
            out.append("")
            waterfall(trace, descendants(trace, agent["span"]), out)
            out.append("")
        for t in agent["turns"]:
            names = ", ".join(c["name"] + (" ❌" if c["error"] else "") for c in t["calls"]) or "reply"
            out.append(f"<details><summary>Turn {t['n']} · {(t['end'] - t['start']) / 1e9:.1f}s · {t['tokens']:,} tokens · {names}</summary>\n")
            if trace.content:
                if t["thinking"]:
                    out.append(f"**Thinking**\n\n```text\n{md(t['thinking'], 2000)}\n```")
                if t["text"]:
                    out.append(md(t["text"], 3000) + "\n")
                for c in t["calls"]:
                    out.append(f"**{c['name']}** ({c['ms']} ms){' failed' if c['error'] else ''}\n\n```json\n{md(json.dumps(c['input'], ensure_ascii=False), 1500)}\n```\n```text\n{md(c['result'], 1500)}\n```")
            out.append("</details>")
    text = "\n".join(out)
    if len(text.encode()) > 900_000:  # GitHub caps a step summary at 1 MiB
        text = text.encode()[:900_000].decode(errors="ignore") + "\n\n(Summary cut at the 1 MiB limit; the full trace has everything.)\n</details>"
    with open(args.summary, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def export(trace, endpoint, headers, resource):
    url = endpoint.rstrip("/") + ("" if endpoint.rstrip("/").endswith("/v1/traces") else "/v1/traces")
    hdrs = {"Content-Type": "application/json"}
    for pair in filter(None, headers.split(",")):
        k, _, v = pair.partition("=")
        hdrs[k.strip()] = urllib.parse.unquote(v.strip())
    for i in range(0, len(trace.spans), 200):
        body = json.dumps(payload(trace.spans[i:i + 200], resource)).encode()
        req = urllib.request.Request(url, data=body, headers=hdrs, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status >= 300:
                raise RuntimeError(f"HTTP {r.status}")


def payload(spans, resource):
    clean = [{k: v for k, v in s.items() if not k.startswith("_")} for s in spans]
    return {"resourceSpans": [{"resource": {"attributes": [{"key": k, "value": otlp_value(v)} for k, v in resource.items()]},
                               "scopeSpans": [{"scope": {"name": "bun2too-factory-trace"}, "spans": clean}]}]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jobs", required=True, help="JSON lines, one GitHub job per line")
    p.add_argument("--traces", required=True, help="Folder with one trace-<role> folder per agent job")
    p.add_argument("--repo", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--attempt", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--verdict", default="")
    p.add_argument("--no-content", action="store_true")
    p.add_argument("--out", required=True, help="Where to write the OTLP JSON")
    p.add_argument("--summary", required=True)
    p.add_argument("--trace-url", default="")
    args = p.parse_args()

    now = int(dt.datetime.now(dt.timezone.utc).timestamp() * 1e9)
    trace = Trace(f"{args.repo}/{args.run_id}/{args.attempt}", content=not args.no_content)
    with open(args.jobs, encoding="utf-8") as f:
        jobs = [json.loads(line) for line in f if line.strip()]
    starts = [ns(j["started_at"]) for j in jobs if j.get("started_at") and j.get("conclusion") != "skipped"]
    run_url = f"https://github.com/{args.repo}/actions/runs/{args.run_id}/attempts/{args.attempt}"
    root = trace.add(f"agent-review PR #{args.pr}", min(starts or [now]), now, None, key="run",
                     attrs={"cicd.pipeline.name": "agent-review", "cicd.pipeline.run.id": int(args.run_id),
                            "cicd.pipeline.run.url.full": run_url, "vcs.repository.name": args.repo,
                            "vcs.ref.head.revision": args.head_sha, "vcs.change.id": args.pr,
                            "session.id": f"{args.repo}#{args.pr}", "factory.verdict": args.verdict or None})
    found = add_jobs(trace, jobs, root, now)
    trace.span(root)["endTimeUnixNano"] = str(max(int(s["endTimeUnixNano"]) for s in trace.spans[1:]) if len(trace.spans) > 1 else now)
    summary = []
    for role in ("review", "rework"):
        folder = os.path.join(args.traces, f"trace-{role}")
        if os.path.isdir(folder) and role in found:
            jid, step = found[role]
            add_agent(trace, folder, role, step or jid, 3 if step else 2, summary)

    resource = {"service.name": "bun2too-factory", "service.namespace": "bun2too", "vcs.repository.name": args.repo}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload(trace.spans, resource), f)

    endpoint = os.environ.get("OTLP_ENDPOINT", "")
    exported, args.export_note = False, "No trace backend is set (FACTORY_OTLP_ENDPOINT), so the trace is only in the `trace` artifact. See docs/factory.md#tracing."
    if endpoint:
        try:
            export(trace, endpoint, os.environ.get("OTLP_HEADERS", ""), resource)
            exported = True
        except Exception as e:  # tracing never fails the run
            args.export_note = f"Sending the trace to the backend failed ({type(e).__name__}); it is in the `trace` artifact."
            print(f"::warning::{args.export_note}", file=sys.stderr)
    write_summary(trace, summary, args, exported)
    print(f"trace_id={trace.trace_id} spans={len(trace.spans)} exported={exported}")


if __name__ == "__main__":
    main()
