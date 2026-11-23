import { describe, expect, it } from "vitest";
import { createApp } from "../src/app.js";
import { FakeAgents } from "./fake-agents.js";

const KEY = "test-key";
const setup = () => {
  const agents = new FakeAgents();
  const app = createApp({
    agents,
    tenantKeys: new Map([
      [KEY, "acme"],
      ["other-key", "globex"],
    ]),
    publicUrl: "http://relay.test",
    offline: true,
    pollMs: 1,
  });
  return { app, agents };
};
const headers = (extra: Record<string, string> = {}) => ({
  "content-type": "application/json",
  "x-api-key": KEY,
  ...extra,
});

describe("REST intake", () => {
  it("rejects calls without a tenant key", async () => {
    const { app } = setup();
    const res = await app.request("/v1/intake", { method: "POST", body: "{}" });
    expect(res.status).toBe(401);
  });

  it("requires an Idempotency-Key", async () => {
    const { app } = setup();
    const res = await app.request("/v1/intake", {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ channel: "web_widget", message: "help" }),
    });
    expect(res.status).toBe(400);
  });

  it("returns 422 with issues for an invalid intake", async () => {
    const { app } = setup();
    const res = await app.request("/v1/intake", {
      method: "POST",
      headers: headers({ "idempotency-key": "k1" }),
      body: JSON.stringify({ channel: "fax", message: "help" }),
    });
    expect(res.status).toBe(422);
  });

  it("creates a case once per idempotency key", async () => {
    const { app } = setup();
    const send = () =>
      app.request("/v1/intake", {
        method: "POST",
        headers: headers({ "idempotency-key": "k1" }),
        body: JSON.stringify({ channel: "web_widget", message: "I can't log in" }),
      });
    const first = await send();
    const second = await send();
    expect(first.status).toBe(202);
    expect(second.status).toBe(200);
    expect((await first.json()).caseId).toBe((await second.json()).caseId);
  });

  it("hides another tenant's case", async () => {
    const { app } = setup();
    const created = await app.request("/v1/intake", {
      method: "POST",
      headers: headers({ "idempotency-key": "k1" }),
      body: JSON.stringify({ channel: "web_widget", message: "hello" }),
    });
    const { caseId } = await created.json();
    const res = await app.request(`/v1/cases/${caseId}`, { headers: { "x-api-key": "other-key" } });
    expect(res.status).toBe(404);
  });

  it("streams case events until the case settles", async () => {
    const { app } = setup();
    const created = await app.request("/v1/intake", {
      method: "POST",
      headers: headers({ "idempotency-key": "k1" }),
      body: JSON.stringify({ channel: "web_widget", message: "hello" }),
    });
    const { caseId } = await created.json();
    const res = await app.request(`/v1/cases/${caseId}/events`, { headers: headers() });
    const text = await res.text();
    expect(text).toContain('"status":"received"');
    expect(text).toContain('"status":"resolved"');
  });
});

describe("OpenAPI", () => {
  it("serves the document without a key, pointing at this gateway", async () => {
    const { app } = setup();
    const res = await app.request("/openapi.json");
    expect(res.status).toBe(200);
    const doc = await res.json();
    expect(doc.openapi).toBe("3.1.0");
    expect(doc.servers).toEqual([{ url: "http://relay.test" }]);
    expect(Object.keys(doc.paths)).toEqual(
      expect.arrayContaining(["/v1/intake", "/v1/cases/{id}", "/v1/cases/{id}/messages", "/a2a"]),
    );
  });
});

describe("Customer replies", () => {
  it("returns 409 when the case is not waiting for the customer", async () => {
    const { app } = setup();
    const created = await app.request("/v1/intake", {
      method: "POST",
      headers: headers({ "idempotency-key": "k1" }),
      body: JSON.stringify({ channel: "web_widget", message: "help" }),
    });
    const { caseId } = await created.json();
    const res = await app.request(`/v1/cases/${caseId}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ message: "more detail" }),
    });
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: "not_awaiting_customer" });
  });

  it("accepts a reply while the case awaits the customer", async () => {
    const { app, agents } = setup();
    const created = await app.request("/v1/intake", {
      method: "POST",
      headers: headers({ "idempotency-key": "k1" }),
      body: JSON.stringify({ channel: "web_widget", message: "help" }),
    });
    const { caseId } = await created.json();
    const stored = agents.cases.get(caseId);
    if (stored) agents.cases.set(caseId, { ...stored, status: "awaiting_customer" });
    const res = await app.request(`/v1/cases/${caseId}/messages`, {
      method: "POST",
      headers: headers(),
      body: JSON.stringify({ message: "more detail" }),
    });
    expect(res.status).toBe(202);
  });
});

describe("A2A", () => {
  const rpc = (app: ReturnType<typeof setup>["app"], body: unknown) =>
    app.request("/a2a", { method: "POST", headers: headers(), body: JSON.stringify(body) });

  it("publishes an agent card that points at the JSON-RPC endpoint", async () => {
    const { app } = setup();
    const card = await (await app.request("/.well-known/agent-card.json")).json();
    expect(card.url).toBe("http://relay.test/a2a");
    expect(card.capabilities.streaming).toBe(false);
  });

  it("maps message/send to a case and returns a completed task", async () => {
    const { app } = setup();
    const res = await rpc(app, {
      jsonrpc: "2.0",
      id: 1,
      method: "message/send",
      params: {
        message: { role: "user", messageId: "m-1", parts: [{ kind: "text", text: "webhook 401" }] },
      },
    });
    const body = await res.json();
    expect(body.result.kind).toBe("task");
    expect(body.result.status.state).toBe("completed");
    expect(body.result.artifacts[0].parts[0].text).toContain("knowledge base");
  });

  it("rejects a reply to a task that is not waiting for input", async () => {
    const { app } = setup();
    const message = (messageId: string, taskId?: string) => ({
      jsonrpc: "2.0",
      id: messageId,
      method: "message/send",
      params: {
        message: { role: "user", messageId, taskId, parts: [{ kind: "text", text: "hi" }] },
      },
    });
    const opened = await (await rpc(app, message("m-1"))).json();
    const body = await (await rpc(app, message("m-2", opened.result.id))).json();
    expect(body.error).toEqual({ code: -32602, message: "Task is not waiting for input" });
  });

  it("gets a task by its case id, and reports a missing or unknown one", async () => {
    const { app } = setup();
    const opened = await (
      await rpc(app, {
        jsonrpc: "2.0",
        id: 1,
        method: "message/send",
        params: {
          message: { role: "user", messageId: "m-1", parts: [{ kind: "text", text: "hi" }] },
        },
      })
    ).json();
    const found = await (
      await rpc(app, {
        jsonrpc: "2.0",
        id: 2,
        method: "tasks/get",
        params: { id: opened.result.id },
      })
    ).json();
    expect(found.result).toMatchObject({ kind: "task", id: opened.result.id });
    const missing = await (
      await rpc(app, { jsonrpc: "2.0", id: 3, method: "tasks/get", params: {} })
    ).json();
    expect(missing.error).toEqual({ code: -32602, message: "params.id is required" });
    const unknown = await (
      await rpc(app, { jsonrpc: "2.0", id: 4, method: "tasks/get", params: { id: "nope" } })
    ).json();
    expect(unknown.error).toEqual({ code: -32001, message: "Task not found" });
  });

  it("refuses cancel and streaming, and rejects a bad envelope", async () => {
    const { app } = setup();
    const call = async (body: unknown) => (await rpc(app, body)).json();
    expect(
      (await call({ jsonrpc: "2.0", id: 1, method: "tasks/cancel", params: {} })).error.code,
    ).toBe(-32002);
    expect(
      (await call({ jsonrpc: "2.0", id: 2, method: "message/stream", params: {} })).error.code,
    ).toBe(-32004);
    expect(await call({ jsonrpc: "1.0", id: 3, method: "x" })).toEqual({
      jsonrpc: "2.0",
      id: null,
      error: { code: -32600, message: "Invalid JSON-RPC request" },
    });
  });

  it("returns method-not-found for unknown methods", async () => {
    const { app } = setup();
    const body = await (
      await rpc(app, { jsonrpc: "2.0", id: 2, method: "tasks/resubscribe", params: {} })
    ).json();
    expect(body.error.code).toBe(-32601);
  });
});
