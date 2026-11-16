type Settled = "awaiting_customer" | "escalated" | "resolved" | "rejected";
const SETTLED = new Set<string>(["awaiting_customer", "escalated", "resolved", "rejected"]);

interface CaseView {
  id: string;
  status: string;
  resolution: { message: string } | null;
  pendingQuestion: string | null;
}

const STATUS_TEXT: Record<Settled, string> = {
  resolved: "Here's what we found:",
  escalated: "A specialist on our team has your case and will follow up.",
  awaiting_customer: "We need one more detail from you:",
  rejected: "We couldn't open a case for this request.",
};

const template = document.createElement("template");
template.innerHTML = `
<style>
  :host { --relay-primary: #10211c; --relay-accent: #d0ed9a; --relay-surface: #fbfaf5; --relay-ink: #13261f;
    display: block; font: 15px/1.5 system-ui, sans-serif; color: var(--relay-ink); }
  form { display: grid; gap: 10px; padding: 16px; background: var(--relay-surface); border-radius: 12px; }
  label { font-weight: 600; }
  textarea { min-height: 96px; padding: 10px; border: 1px solid #c9ccbd; border-radius: 8px; font: inherit; resize: vertical; }
  button { justify-self: start; padding: 10px 16px; border: 0; border-radius: 8px; background: var(--relay-primary); color: var(--relay-accent); font: inherit; font-weight: 600; cursor: pointer; }
  button:focus-visible, textarea:focus-visible { outline: 3px solid var(--relay-accent); outline-offset: 2px; }
  button[disabled] { opacity: .6; cursor: progress; }
  [role="status"] { white-space: pre-wrap; }
</style>
<form part="form">
  <label for="relay-message">How can we help?</label>
  <textarea id="relay-message" name="message" required maxlength="8000"></textarea>
  <button type="submit">Send</button>
  <div role="status" aria-live="polite"></div>
</form>`;

export class RelaySupport extends HTMLElement {
  static observedAttributes = ["endpoint", "publishable-key"];

  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({ mode: "open" });
    root.append(template.content.cloneNode(true));
    root.querySelector("form")?.addEventListener("submit", (event) => {
      event.preventDefault();
      void this.submit(root);
    });
  }

  private async submit(root: ShadowRoot) {
    const endpoint = this.getAttribute("endpoint");
    const key = this.getAttribute("publishable-key");
    const textarea = root.querySelector("textarea");
    const button = root.querySelector("button");
    const status = root.querySelector('[role="status"]');
    if (!endpoint || !key || !textarea || !button || !status) return;

    button.disabled = true;
    status.textContent = "Sending…";
    const headers = { "content-type": "application/json", "x-api-key": key };
    try {
      const created = await fetch(new URL("/v1/intake", endpoint), {
        method: "POST",
        headers: { ...headers, "idempotency-key": crypto.randomUUID() },
        body: JSON.stringify({ channel: "web_widget", message: textarea.value }),
      });
      if (!created.ok) throw new Error(`intake failed: ${created.status}`);
      const { caseId } = (await created.json()) as { caseId: string };
      status.textContent = `Case ${caseId} opened. Working on it…`;
      const settled = await this.waitForSettled(endpoint, headers, caseId);
      const lead = STATUS_TEXT[settled.status as Settled] ?? "";
      status.textContent = [
        lead,
        settled.pendingQuestion ?? settled.resolution?.message ?? "",
        `Reference: ${caseId}`,
      ]
        .filter(Boolean)
        .join("\n\n");
      this.dispatchEvent(
        new CustomEvent("relay:case", { detail: settled, bubbles: true, composed: true }),
      );
    } catch {
      status.textContent = "We couldn't send your message. Please try again in a moment.";
    } finally {
      button.disabled = false;
    }
  }

  private async waitForSettled(
    endpoint: string,
    headers: Record<string, string>,
    caseId: string,
  ): Promise<CaseView> {
    for (let attempt = 0; attempt < 60; attempt++) {
      const res = await fetch(new URL(`/v1/cases/${caseId}`, endpoint), { headers });
      const view = (await res.json()) as CaseView;
      if (SETTLED.has(view.status)) return view;
      await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error("case did not settle");
  }
}

if (!customElements.get("relay-support")) customElements.define("relay-support", RelaySupport);
