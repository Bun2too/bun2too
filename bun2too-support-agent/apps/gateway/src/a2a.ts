import { type Case, type CaseStatus, IntakeRequest } from "@relay/contracts";
import { z } from "zod";
import { type AgentsClient, NotAwaitingCustomer } from "./agents-client.js";

export const A2A_PROTOCOL_VERSION = "0.3.0";

type TaskState = "submitted" | "working" | "input-required" | "completed" | "rejected";

const STATE: Record<CaseStatus, TaskState> = {
  received: "submitted",
  triaged: "working",
  ticketed: "working",
  in_progress: "working",
  escalated: "working",
  awaiting_customer: "input-required",
  resolved: "completed",
  rejected: "rejected",
};

export function agentCard(publicUrl: string, name: string) {
  return {
    protocolVersion: A2A_PROTOCOL_VERSION,
    name,
    description: "Support intake agent. Send a customer problem; receive a tracked support case.",
    url: new URL("/a2a", publicUrl).toString(),
    preferredTransport: "JSONRPC",
    version: "0.1.0",
    capabilities: { streaming: false, pushNotifications: false, stateTransitionHistory: false },
    defaultInputModes: ["text/plain"],
    defaultOutputModes: ["text/plain"],
    securitySchemes: { apiKey: { type: "apiKey", in: "header", name: "x-api-key" } },
    security: [{ apiKey: [] }],
    skills: [
      {
        id: "support.intake",
        name: "Open a support case",
        description:
          "Classifies the problem, opens Jira and ServiceNow tickets, and resolves or escalates it.",
        tags: ["support", "ticketing"],
        examples: ["The checkout webhook returns 401 since this morning"],
      },
      {
        id: "support.status",
        name: "Track a support case",
        description: "Use tasks/get with the task id returned by message/send.",
        tags: ["support", "status"],
      },
    ],
  };
}

const TextPart = z.object({ kind: z.literal("text"), text: z.string() });
const Message = z.object({
  role: z.literal("user"),
  messageId: z.string().min(1).max(200),
  parts: z.array(z.union([TextPart, z.object({ kind: z.string() }).loose()])).min(1),
  taskId: z.string().optional(),
  contextId: z.string().optional(),
});
const Rpc = z.object({
  jsonrpc: z.literal("2.0"),
  id: z.union([z.string(), z.number(), z.null()]),
  method: z.string(),
  params: z.unknown(),
});

type RpcId = string | number | null;
const ok = (id: RpcId, result: unknown) => ({ jsonrpc: "2.0", id, result });
const fail = (id: RpcId, code: number, message: string) => ({
  jsonrpc: "2.0",
  id,
  error: { code, message },
});

export function toTask(found: Case) {
  const artifacts = found.resolution
    ? [
        {
          artifactId: `${found.id}-resolution`,
          name: found.resolution.kind,
          parts: [{ kind: "text", text: found.resolution.message }],
        },
      ]
    : [];
  return {
    kind: "task",
    id: found.id,
    contextId: found.id,
    status: { state: STATE[found.status], timestamp: found.updatedAt },
    artifacts,
    metadata: { relayStatus: found.status, traceId: found.traceId, tickets: found.tickets },
  };
}

type Rpc = z.infer<typeof Rpc>;
type MessageParams = z.infer<typeof Message>;

const textOf = (message: MessageParams) =>
  message.parts
    .flatMap((p) => (p.kind === "text" && "text" in p ? [String(p.text)] : []))
    .join("\n");

async function answerTask(
  id: RpcId,
  tenant: string,
  taskId: string,
  text: string,
  agents: AgentsClient,
) {
  const updated = await agents.reply(tenant, taskId, text).catch((error) => {
    if (error instanceof NotAwaitingCustomer) return "not_waiting" as const;
    throw error;
  });
  if (updated === "not_waiting") return fail(id, -32602, "Task is not waiting for input");
  return updated ? ok(id, toTask(updated)) : fail(id, -32001, "Task not found");
}

async function openTask(
  id: RpcId,
  tenant: string,
  message: MessageParams,
  text: string,
  agents: AgentsClient,
) {
  const intake = IntakeRequest.safeParse({ channel: "a2a", message: text });
  if (!intake.success) return fail(id, -32602, "message has no usable text part");
  const accepted = await agents.submitIntake({
    tenant,
    idempotencyKey: message.messageId,
    intake: intake.data,
  });
  const created = await agents.getCase(tenant, accepted.caseId);
  return created ? ok(id, toTask(created)) : fail(id, -32603, "Case was not persisted");
}

async function sendMessage({ id, params }: Rpc, tenant: string, agents: AgentsClient) {
  const parsed = z.object({ message: Message }).safeParse(params);
  if (!parsed.success) return fail(id, -32602, "params.message is invalid");
  const { message } = parsed.data;
  const text = textOf(message);
  return message.taskId
    ? answerTask(id, tenant, message.taskId, text, agents)
    : openTask(id, tenant, message, text, agents);
}

async function getTask({ id, params }: Rpc, tenant: string, agents: AgentsClient) {
  const parsed = z.object({ id: z.string() }).safeParse(params);
  if (!parsed.success) return fail(id, -32602, "params.id is required");
  const found = await agents.getCase(tenant, parsed.data.id);
  return found ? ok(id, toTask(found)) : fail(id, -32001, "Task not found");
}

export async function handleRpc(raw: unknown, tenant: string, agents: AgentsClient) {
  const rpc = Rpc.safeParse(raw);
  if (!rpc.success) return fail(null, -32600, "Invalid JSON-RPC request");
  const { id, method } = rpc.data;

  switch (method) {
    case "message/send":
      return sendMessage(rpc.data, tenant, agents);
    case "tasks/get":
      return getTask(rpc.data, tenant, agents);
    case "tasks/cancel":
      return fail(id, -32002, "Support cases cannot be canceled by the client");
    case "message/stream":
      return fail(id, -32004, "Streaming is not supported; use message/send and tasks/get");
    default:
      return fail(id, -32601, `Method not found: ${method}`);
  }
}
