import type { Case, CaseEvent, IntakeAccepted, IntakeCommand } from "@relay/contracts";
import type { AgentsClient } from "../src/agents-client.js";

export class FakeAgents implements AgentsClient {
  readonly cases = new Map<string, Case>();
  readonly events = new Map<string, CaseEvent[]>();
  private readonly byKey = new Map<string, string>();

  async submitIntake(command: IntakeCommand): Promise<IntakeAccepted> {
    const key = `${command.tenant}:${command.idempotencyKey}`;
    const existing = this.byKey.get(key);
    if (existing) return { caseId: existing, status: "received", traceId: "t-1", created: false };
    const id = `case-${this.cases.size + 1}`;
    const now = new Date().toISOString();
    this.byKey.set(key, id);
    this.cases.set(id, {
      id,
      tenant: command.tenant,
      status: "resolved",
      channel: command.intake.channel,
      createdAt: now,
      updatedAt: now,
      traceId: "t-1",
      classification: null,
      tickets: [],
      resolution: {
        kind: "auto_resolved",
        message: "Answered from the knowledge base.",
        citations: ["kb-1"],
      },
      pendingQuestion: null,
    });
    this.events.set(id, [
      {
        seq: 0,
        caseId: id,
        at: now,
        status: "received",
        actor: "gateway",
        reason: "intake",
        data: {},
      },
      {
        seq: 1,
        caseId: id,
        at: now,
        status: "resolved",
        actor: "knowledge_agent",
        reason: "answered",
        data: {},
      },
    ]);
    return { caseId: id, status: "received", traceId: "t-1", created: true };
  }

  async getCase(tenant: string, caseId: string): Promise<Case | null> {
    const found = this.cases.get(caseId);
    return found && found.tenant === tenant ? found : null;
  }

  async listEvents(tenant: string, caseId: string, afterSeq: number): Promise<CaseEvent[]> {
    if (!(await this.getCase(tenant, caseId))) return [];
    return (this.events.get(caseId) ?? []).filter((e) => e.seq > afterSeq);
  }

  async reply(tenant: string, caseId: string): Promise<Case | null> {
    return this.getCase(tenant, caseId);
  }
}
