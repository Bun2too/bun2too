import { z } from "zod";
import { Case, CaseEvent, CustomerReply, IntakeAccepted, IntakeRequest } from "./case.js";

const ErrorBody = z.object({
  error: z.string().describe("Machine-readable error code, for example `unauthorized`."),
  issues: z.array(z.unknown()).optional().describe("Validation issues, on 422 only."),
});

const component = (schema: z.ZodType, io: "input" | "output") => {
  const { $schema: _, ...rest } = z.toJSONSchema(schema, { io }) as Record<string, unknown>;
  return rest;
};

const ref = (name: string) => ({ $ref: `#/components/schemas/${name}` });
const json = (name: string) => ({ "application/json": { schema: ref(name) } });
const error = (description: string) => ({ description, content: json("Error") });

const caseId = {
  name: "id",
  in: "path",
  required: true,
  description: "The case ID returned by `POST /v1/intake`.",
  schema: { type: "string" },
};

/** The OpenAPI 3.1 document for the gateway, built from the wire contracts so it cannot drift. */
export function openApiDocument(serverUrl = "http://localhost:8787") {
  return {
    openapi: "3.1.0",
    info: {
      title: "Relay Support Intake API",
      version: "0.1.0",
      description:
        "Hand Relay a customer problem and get a tracked support case. Relay classifies it, opens one Jira issue and one ServiceNow record, then resolves it, asks the customer one question, or escalates it to a person. Status values settle at `resolved`, `awaiting_customer`, `escalated` or `rejected`. Agents can use the same flow over A2A (`/.well-known/agent-card.json`, `POST /a2a`).",
    },
    servers: [{ url: serverUrl }],
    security: [{ apiKey: [] }, { bearer: [] }],
    tags: [
      { name: "cases", description: "Open and follow support cases" },
      { name: "meta", description: "Health, discovery and this document" },
    ],
    paths: {
      "/v1/intake": {
        post: {
          tags: ["cases"],
          operationId: "createIntake",
          summary: "Open a support case",
          description:
            "Opens a case and starts the agents in the background. The same `Idempotency-Key` always returns the same case (200, `created: false`) and never opens a second set of tickets.",
          parameters: [
            {
              name: "Idempotency-Key",
              in: "header",
              required: true,
              description:
                "Unique per customer submission, at most 200 characters. Reuse it when retrying.",
              schema: { type: "string", maxLength: 200 },
            },
          ],
          requestBody: { required: true, content: json("IntakeRequest") },
          responses: {
            "202": { description: "Case opened", content: json("IntakeAccepted") },
            "200": {
              description: "Retry of an earlier intake; the existing case",
              content: json("IntakeAccepted"),
            },
            "400": error("`idempotency_key_required`: header missing or longer than 200"),
            "401": error("`unauthorized`: missing or unknown tenant key"),
            "422": error("`invalid_intake`: the body failed validation; see `issues`"),
            "503": error("`agents_unavailable`: try again with the same Idempotency-Key"),
          },
        },
      },
      "/v1/cases/{id}": {
        get: {
          tags: ["cases"],
          operationId: "getCase",
          summary: "Get a case",
          parameters: [caseId],
          responses: {
            "200": { description: "The case", content: json("Case") },
            "401": error("`unauthorized`"),
            "404": error("`not_found`: no such case for this tenant"),
          },
        },
      },
      "/v1/cases/{id}/messages": {
        post: {
          tags: ["cases"],
          operationId: "replyToCase",
          summary: "Answer the case's pending question",
          description:
            "Only when the case is `awaiting_customer`. The agents resume the same case and tickets.",
          parameters: [caseId],
          requestBody: { required: true, content: json("CustomerReply") },
          responses: {
            "202": { description: "Reply accepted; the case resumes", content: json("Case") },
            "401": error("`unauthorized`"),
            "404": error("`not_found`"),
            "409": error("`not_awaiting_customer`: the case is not waiting for a reply"),
            "422": error("`invalid_reply`"),
          },
        },
      },
      "/v1/cases/{id}/events": {
        get: {
          tags: ["cases"],
          operationId: "streamCaseEvents",
          summary: "Stream the case's events (Server-Sent Events)",
          description:
            "Sends every `CaseEvent` as an SSE message named `case_event` whose data is the event JSON and whose id is its `seq`. The stream ends after a settled status or after 120 seconds; reconnect or poll `GET /v1/cases/{id}` to continue.",
          parameters: [caseId],
          responses: {
            "200": {
              description: "An event stream",
              content: { "text/event-stream": { schema: ref("CaseEvent") } },
            },
            "401": error("`unauthorized`"),
            "404": error("`not_found`"),
          },
        },
      },
      "/a2a": {
        post: {
          tags: ["cases"],
          operationId: "a2aRpc",
          summary: "A2A JSON-RPC 2.0 endpoint (protocol 0.3.0)",
          description:
            "Methods: `message/send` (opens a case, or answers one when `message.taskId` is set) and `tasks/get`. A task's `id` is the case ID. `metadata.relayStatus` and `metadata.tickets` carry Relay's status and ticket links. Errors use JSON-RPC error objects with HTTP 200.",
          requestBody: {
            required: true,
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  required: ["jsonrpc", "id", "method", "params"],
                  properties: {
                    jsonrpc: { const: "2.0" },
                    id: { type: ["string", "number", "null"] },
                    method: { enum: ["message/send", "tasks/get"] },
                    params: { type: "object" },
                  },
                },
              },
            },
          },
          responses: {
            "200": { description: "A JSON-RPC response" },
            "401": error("`unauthorized`"),
          },
        },
      },
      "/healthz": {
        get: {
          tags: ["meta"],
          operationId: "health",
          summary: "Liveness",
          security: [],
          responses: { "200": { description: "`{ ok: true, service, offline }`" } },
        },
      },
      "/.well-known/agent-card.json": {
        get: {
          tags: ["meta"],
          operationId: "agentCard",
          summary: "A2A agent card",
          security: [],
          responses: { "200": { description: "The A2A agent card" } },
        },
      },
      "/openapi.json": {
        get: {
          tags: ["meta"],
          operationId: "openApi",
          summary: "This document",
          security: [],
          responses: { "200": { description: "OpenAPI 3.1 document" } },
        },
      },
    },
    components: {
      securitySchemes: {
        apiKey: {
          type: "apiKey",
          in: "header",
          name: "x-api-key",
          description: "A tenant key issued by the Relay operator. Server-side only.",
        },
        bearer: { type: "http", scheme: "bearer", description: "The same tenant key." },
      },
      schemas: {
        IntakeRequest: component(IntakeRequest, "input"),
        IntakeAccepted: component(IntakeAccepted, "output"),
        CustomerReply: component(CustomerReply, "input"),
        Case: component(Case, "output"),
        CaseEvent: component(CaseEvent, "output"),
        Error: component(ErrorBody, "output"),
      },
    },
  };
}
