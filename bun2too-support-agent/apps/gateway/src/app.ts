import { CustomerReply, IntakeRequest, SETTLED_STATUSES } from "@relay/contracts";
import { annotateActiveSpan, RELAY_ATTR } from "@relay/telemetry";
import { Hono } from "hono";
import { createMiddleware } from "hono/factory";
import { streamSSE } from "hono/streaming";
import { agentCard, handleRpc } from "./a2a.js";
import { type AgentsClient, AgentsUnavailable } from "./agents-client.js";

export interface AppDeps {
  agents: AgentsClient;
  tenantKeys: ReadonlyMap<string, string>;
  publicUrl: string;
  offline: boolean;
  agentName?: string;
  pollMs?: number;
}

type Env = { Variables: { tenant: string } };

export function createApp(deps: AppDeps) {
  const app = new Hono<Env>();
  const pollMs = deps.pollMs ?? 1000;

  app.onError((error, c) => {
    if (error instanceof AgentsUnavailable) return c.json({ error: "agents_unavailable" }, 503);
    return c.json({ error: "internal" }, 500);
  });

  app.get("/healthz", (c) => c.json({ ok: true, service: "relay-gateway", offline: deps.offline }));
  app.get("/.well-known/agent-card.json", (c) =>
    c.json(agentCard(deps.publicUrl, deps.agentName ?? "Relay Support Intake")),
  );

  const authenticate = createMiddleware<Env>(async (c, next) => {
    const bearer = c.req.header("authorization")?.replace(/^Bearer\s+/i, "");
    const key = c.req.header("x-api-key") ?? bearer;
    const tenant = key ? deps.tenantKeys.get(key) : undefined;
    if (!tenant) return c.json({ error: "unauthorized" }, 401);
    c.set("tenant", tenant);
    annotateActiveSpan({ [RELAY_ATTR.tenant]: tenant });
    await next();
  });
  app.use("/v1/*", authenticate);
  app.use("/a2a", authenticate);

  app.post("/v1/intake", async (c) => {
    const idempotencyKey = c.req.header("idempotency-key");
    if (!idempotencyKey || idempotencyKey.length > 200) {
      return c.json({ error: "idempotency_key_required" }, 400);
    }
    const intake = IntakeRequest.safeParse(await c.req.json().catch(() => null));
    if (!intake.success)
      return c.json({ error: "invalid_intake", issues: intake.error.issues }, 422);
    const accepted = await deps.agents.submitIntake({
      tenant: c.var.tenant,
      idempotencyKey,
      intake: intake.data,
    });
    annotateActiveSpan({
      [RELAY_ATTR.caseId]: accepted.caseId,
      [RELAY_ATTR.channel]: intake.data.channel,
    });
    return c.json(accepted, accepted.created ? 202 : 200);
  });

  app.get("/v1/cases/:id", async (c) => {
    const found = await deps.agents.getCase(c.var.tenant, c.req.param("id"));
    return found ? c.json(found) : c.json({ error: "not_found" }, 404);
  });

  app.post("/v1/cases/:id/messages", async (c) => {
    const reply = CustomerReply.safeParse(await c.req.json().catch(() => null));
    if (!reply.success) return c.json({ error: "invalid_reply", issues: reply.error.issues }, 422);
    const updated = await deps.agents.reply(c.var.tenant, c.req.param("id"), reply.data.message);
    return updated ? c.json(updated, 202) : c.json({ error: "not_found" }, 404);
  });

  app.get("/v1/cases/:id/events", async (c) => {
    const tenant = c.var.tenant;
    const caseId = c.req.param("id");
    if (!(await deps.agents.getCase(tenant, caseId))) return c.json({ error: "not_found" }, 404);
    return streamSSE(c, async (stream) => {
      let after = -1;
      const deadline = Date.now() + 120_000;
      while (!stream.aborted && Date.now() < deadline) {
        const events = await deps.agents.listEvents(tenant, caseId, after);
        for (const event of events) {
          after = event.seq;
          await stream.writeSSE({
            id: String(event.seq),
            event: "case_event",
            data: JSON.stringify(event),
          });
        }
        const last = events.at(-1);
        if (last && SETTLED_STATUSES.has(last.status)) break;
        await stream.sleep(pollMs);
      }
    });
  });

  app.post("/a2a", async (c) => {
    const body = await c.req.json().catch(() => null);
    return c.json(await handleRpc(body, c.var.tenant, deps.agents));
  });

  return app;
}
