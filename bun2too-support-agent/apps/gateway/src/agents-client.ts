import { Case, CaseEvent, IntakeAccepted, type IntakeCommand } from "@relay/contracts";
import { withTraceHeaders } from "@relay/telemetry";
import { z } from "zod";

export interface AgentsClient {
  submitIntake(command: IntakeCommand): Promise<IntakeAccepted>;
  getCase(tenant: string, caseId: string): Promise<Case | null>;
  listEvents(tenant: string, caseId: string, afterSeq: number): Promise<CaseEvent[]>;
  reply(tenant: string, caseId: string, message: string): Promise<Case | null>;
}

export class AgentsUnavailable extends Error {}
export class NotAwaitingCustomer extends Error {}

const CaseEvents = z.array(CaseEvent);

export class HttpAgentsClient implements AgentsClient {
  constructor(private readonly baseUrl: string) {}

  async submitIntake(command: IntakeCommand): Promise<IntakeAccepted> {
    const body = await this.call("POST", "/runs/intake", command);
    return IntakeAccepted.parse(body);
  }

  async getCase(tenant: string, caseId: string): Promise<Case | null> {
    const body = await this.call("GET", `/tenants/${tenant}/cases/${caseId}`);
    return body === null ? null : Case.parse(body);
  }

  async listEvents(tenant: string, caseId: string, afterSeq: number): Promise<CaseEvent[]> {
    const body = await this.call(
      "GET",
      `/tenants/${tenant}/cases/${caseId}/events?after=${afterSeq}`,
    );
    return body === null ? [] : CaseEvents.parse(body);
  }

  async reply(tenant: string, caseId: string, message: string): Promise<Case | null> {
    const body = await this.call("POST", `/tenants/${tenant}/cases/${caseId}/messages`, {
      message,
    });
    return body === null ? null : Case.parse(body);
  }

  private async call(method: string, path: string, json?: unknown): Promise<unknown> {
    const headers = withTraceHeaders({ "content-type": "application/json" });
    const init: RequestInit = { method, headers, signal: AbortSignal.timeout(10_000) };
    if (json !== undefined) init.body = JSON.stringify(json);
    const response = await fetch(new URL(path, this.baseUrl), init).catch((error: unknown) => {
      throw new AgentsUnavailable(`agents service unreachable: ${String(error)}`);
    });
    if (response.status === 404) return null;
    if (response.status === 409)
      throw new NotAwaitingCustomer("case is not waiting for the customer");
    if (!response.ok) throw new AgentsUnavailable(`agents service returned ${response.status}`);
    return response.json();
  }
}
