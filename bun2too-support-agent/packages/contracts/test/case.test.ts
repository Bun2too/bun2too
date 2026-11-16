import { describe, expect, it } from "vitest";
import { IntakeRequest } from "../src/index.js";

describe("IntakeRequest", () => {
  it("accepts a minimal widget intake and fills defaults", () => {
    const parsed = IntakeRequest.parse({ channel: "web_widget", message: "  I can't log in  " });
    expect(parsed).toEqual({
      channel: "web_widget",
      message: "I can't log in",
      customer: {},
      metadata: {},
    });
  });

  it("rejects fields the contract does not define", () => {
    const result = IntakeRequest.safeParse({ channel: "email", message: "hi", priority: "urgent" });
    expect(result.success).toBe(false);
  });

  it("rejects an empty message after trimming", () => {
    expect(IntakeRequest.safeParse({ channel: "email", message: "   " }).success).toBe(false);
  });
});
