import type { Case, CaseEvent } from "@relay/contracts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentsUnavailable, HttpAgentsClient, NotAwaitingCustomer } from "../src/agents-client.js";

const NOW = "2026-11-20T00:00:00.000Z";
const CASE: Case = {
  id: "case-1",
  tenant: "acme",
  status: "resolved",
  channel: "web_widget",
  createdAt: NOW,
  updatedAt: NOW,
  traceId: "t-1",
  classification: null,
  tickets: [],
  resolution: { kind: "auto_resolved", message: "Answered.", citations: ["kb-1"] },
  pendingQuestion: null,
};
const EVENT: CaseEvent = {
  seq: 1,
  caseId: "case-1",
  at: NOW,
  status: "resolved",
  actor: "knowledge_agent",
  reason: "answered",
  data: {},
};

type Call = { url: string; init: RequestInit };
function stubFetch(respond: (call: Call) => Response | Promise<Response>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: URL, init: RequestInit) => {
      const call = { url: String(url), init };
      calls.push(call);
      return respond(call);
    }),
  );
  return calls;
}
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const client = new HttpAgentsClient("http://agents.test");

afterEach(() => vi.unstubAllGlobals());

describe("HttpAgentsClient", () => {
  it("posts the intake command as JSON and parses the acceptance", async () => {
    const calls = stubFetch(() =>
      json({ caseId: "case-1", status: "received", traceId: "t-1", created: true }),
    );
    const command = {
      tenant: "acme",
      idempotencyKey: "idem-1",
      intake: { channel: "web_widget", message: "Help", metadata: {} },
    } as never;
    await expect(client.submitIntake(command)).resolves.toEqual({
      caseId: "case-1",
      status: "received",
      traceId: "t-1",
      created: true,
    });
    expect(calls[0]?.url).toBe("http://agents.test/runs/intake");
    expect(calls[0]?.init.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual(command);
    expect(new Headers(calls[0]?.init.headers).get("content-type")).toBe("application/json");
  });

  it("fetches a case by tenant and id", async () => {
    const calls = stubFetch(() => json(CASE));
    await expect(client.getCase("acme", "case-1")).resolves.toEqual(CASE);
    expect(calls[0]?.url).toBe("http://agents.test/tenants/acme/cases/case-1");
    expect(calls[0]?.init.method).toBe("GET");
    expect(calls[0]?.init.body).toBeUndefined();
  });

  it("returns null for an unknown case and an empty list for its events", async () => {
    stubFetch(() => new Response("", { status: 404 }));
    await expect(client.getCase("acme", "nope")).resolves.toBeNull();
    await expect(client.listEvents("acme", "nope", 0)).resolves.toEqual([]);
    await expect(client.reply("acme", "nope", "hi")).resolves.toBeNull();
  });

  it("lists events after a sequence number", async () => {
    const calls = stubFetch(() => json([EVENT]));
    await expect(client.listEvents("acme", "case-1", 0)).resolves.toEqual([EVENT]);
    expect(calls[0]?.url).toBe("http://agents.test/tenants/acme/cases/case-1/events?after=0");
  });

  it("posts a customer reply and returns the updated case", async () => {
    const calls = stubFetch(() => json(CASE));
    await expect(client.reply("acme", "case-1", "More detail")).resolves.toEqual(CASE);
    expect(calls[0]?.url).toBe("http://agents.test/tenants/acme/cases/case-1/messages");
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual({ message: "More detail" });
  });

  it("raises NotAwaitingCustomer when the case is not waiting for a reply", async () => {
    stubFetch(() => new Response("{}", { status: 409 }));
    await expect(client.reply("acme", "case-1", "hi")).rejects.toBeInstanceOf(NotAwaitingCustomer);
  });

  it("raises AgentsUnavailable on a server error", async () => {
    stubFetch(() => new Response("boom", { status: 503 }));
    await expect(client.getCase("acme", "case-1")).rejects.toThrow(
      new AgentsUnavailable("agents service returned 503"),
    );
  });

  it("raises AgentsUnavailable when the service cannot be reached", async () => {
    stubFetch(() => Promise.reject(new TypeError("fetch failed")));
    await expect(client.getCase("acme", "case-1")).rejects.toBeInstanceOf(AgentsUnavailable);
  });

  it("rejects a response that breaks the contract", async () => {
    stubFetch(() => json({ ...CASE, status: "made-up" }));
    await expect(client.getCase("acme", "case-1")).rejects.toThrow();
  });
});
