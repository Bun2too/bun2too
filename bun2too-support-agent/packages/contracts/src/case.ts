import { z } from "zod";

export const Channel = z.enum(["web_widget", "a2a", "email", "marketplace", "retail"]);
export type Channel = z.infer<typeof Channel>;

export const Intent = z.enum([
  "knowledge",
  "identity",
  "integration",
  "commerce",
  "privacy",
  "other",
]);
export type Intent = z.infer<typeof Intent>;

export const Severity = z.enum(["sev1", "sev2", "sev3", "sev4"]);
export type Severity = z.infer<typeof Severity>;

export const Sentiment = z.enum(["negative", "neutral", "positive"]);

export const CaseStatus = z.enum([
  "received",
  "triaged",
  "ticketed",
  "in_progress",
  "awaiting_customer",
  "escalated",
  "resolved",
  "rejected",
]);
export type CaseStatus = z.infer<typeof CaseStatus>;

export const SETTLED_STATUSES: ReadonlySet<CaseStatus> = new Set([
  "awaiting_customer",
  "escalated",
  "resolved",
  "rejected",
]);

export const TicketSystem = z.enum(["jira", "servicenow"]);
export type TicketSystem = z.infer<typeof TicketSystem>;

export const Customer = z.strictObject({
  id: z.string().min(1).max(200).optional(),
  email: z.email().optional(),
  name: z.string().min(1).max(200).optional(),
  locale: z.string().min(2).max(35).optional(),
});

export const IntakeRequest = z.strictObject({
  channel: Channel,
  message: z.string().trim().min(1).max(8000),
  subject: z.string().trim().min(1).max(300).optional(),
  customer: Customer.default({}),
  metadata: z.record(z.string().max(64), z.string().max(500)).default({}),
});
export type IntakeRequest = z.infer<typeof IntakeRequest>;

export const IntakeCommand = z.strictObject({
  tenant: z.string().regex(/^[a-z0-9-]{2,40}$/),
  idempotencyKey: z.string().min(1).max(200),
  intake: IntakeRequest,
});
export type IntakeCommand = z.infer<typeof IntakeCommand>;

export const CustomerReply = z.strictObject({
  message: z.string().trim().min(1).max(8000),
});
export type CustomerReply = z.infer<typeof CustomerReply>;

export const Classification = z.strictObject({
  intent: Intent,
  severity: Severity,
  sentiment: Sentiment,
  summary: z.string(),
  language: z.string(),
});

export const TicketRef = z.strictObject({
  system: TicketSystem,
  key: z.string(),
  url: z.string(),
});

export const Resolution = z.strictObject({
  kind: z.enum(["auto_resolved", "escalated", "rejected"]),
  message: z.string(),
  citations: z.array(z.string()),
});

export const Case = z.strictObject({
  id: z.string(),
  tenant: z.string(),
  status: CaseStatus,
  channel: Channel,
  createdAt: z.iso.datetime({ offset: true }),
  updatedAt: z.iso.datetime({ offset: true }),
  traceId: z.string(),
  classification: Classification.nullable(),
  tickets: z.array(TicketRef),
  resolution: Resolution.nullable(),
  pendingQuestion: z.string().nullable(),
});
export type Case = z.infer<typeof Case>;

export const CaseEvent = z.strictObject({
  seq: z.number().int().nonnegative(),
  caseId: z.string(),
  at: z.iso.datetime({ offset: true }),
  status: CaseStatus,
  actor: z.string(),
  reason: z.string(),
  data: z.record(z.string(), z.unknown()),
});
export type CaseEvent = z.infer<typeof CaseEvent>;

export const IntakeAccepted = z.strictObject({
  caseId: z.string(),
  status: CaseStatus,
  traceId: z.string(),
  created: z.boolean(),
});
export type IntakeAccepted = z.infer<typeof IntakeAccepted>;
