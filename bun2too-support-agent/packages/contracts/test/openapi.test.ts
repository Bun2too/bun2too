import { describe, expect, it } from "vitest";
import { openApiDocument } from "../src/index.js";

describe("openApiDocument", () => {
  const doc = openApiDocument("https://relay.example");

  it("is an OpenAPI 3.1 document for the given server", () => {
    expect(doc.openapi).toBe("3.1.0");
    expect(doc.servers).toEqual([{ url: "https://relay.example" }]);
    expect(openApiDocument().servers).toEqual([{ url: "http://localhost:8787" }]);
  });

  it("describes every gateway route", () => {
    expect(Object.keys(doc.paths).sort()).toEqual([
      "/.well-known/agent-card.json",
      "/a2a",
      "/healthz",
      "/openapi.json",
      "/v1/cases/{id}",
      "/v1/cases/{id}/events",
      "/v1/cases/{id}/messages",
      "/v1/intake",
    ]);
  });

  it("embeds the wire contracts as component schemas without $schema", () => {
    const { schemas } = doc.components;
    expect(Object.keys(schemas).sort()).toEqual([
      "Case",
      "CaseEvent",
      "CustomerReply",
      "Error",
      "IntakeAccepted",
      "IntakeRequest",
    ]);
    for (const schema of Object.values(schemas)) expect(schema).not.toHaveProperty("$schema");
    expect(schemas.IntakeRequest).toMatchObject({ required: ["channel", "message"] });
  });

  it("points every $ref at a defined component", () => {
    const refs = JSON.stringify(doc.paths).match(/#\/components\/schemas\/\w+/g) ?? [];
    expect(refs.length).toBeGreaterThan(0);
    for (const ref of refs)
      expect(doc.components.schemas).toHaveProperty(ref.split("/").at(-1) ?? "");
  });

  it("requires a tenant key except on the public discovery routes", () => {
    expect(doc.security).toEqual([{ apiKey: [] }, { bearer: [] }]);
    for (const path of ["/healthz", "/.well-known/agent-card.json", "/openapi.json"]) {
      expect(doc.paths[path as keyof typeof doc.paths]).toMatchObject({ get: { security: [] } });
    }
  });
});
