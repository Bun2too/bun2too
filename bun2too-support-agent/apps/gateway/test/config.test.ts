import { describe, expect, it } from "vitest";
import { loadConfig, parseTenantKeys } from "../src/config.js";

describe("parseTenantKeys", () => {
  it("maps each key to its tenant, ignoring spaces around pairs", () => {
    const keys = parseTenantKeys("k1:acme, k2:globex");
    expect([...keys]).toEqual([
      ["k1", "acme"],
      ["k2", "globex"],
    ]);
  });

  it.each(["k1", "k1:", ":acme", "k1:acme,"])("rejects a malformed list %j", (raw) => {
    expect(() => parseTenantKeys(raw)).toThrow(/key:tenant/);
  });
});

describe("loadConfig", () => {
  it("applies the defaults when only the tenant keys are set", () => {
    expect(loadConfig({ RELAY_TENANT_KEYS: "k1:acme" })).toEqual({
      port: 8787,
      agentsUrl: "http://localhost:8000",
      publicUrl: "http://localhost:8787",
      tenantKeys: new Map([["k1", "acme"]]),
      offline: false,
    });
  });

  it("reads every setting from the environment", () => {
    const config = loadConfig({
      RELAY_TENANT_KEYS: "k1:acme",
      RELAY_GATEWAY_PORT: "9000",
      RELAY_AGENTS_URL: "http://agents.internal:8000",
      RELAY_PUBLIC_URL: "https://relay.example.com",
      RELAY_OFFLINE: "1",
    });
    expect(config).toMatchObject({
      port: 9000,
      agentsUrl: "http://agents.internal:8000",
      publicUrl: "https://relay.example.com",
      offline: true,
    });
  });

  it("treats any RELAY_OFFLINE other than 1 as online", () => {
    expect(loadConfig({ RELAY_TENANT_KEYS: "k1:acme", RELAY_OFFLINE: "true" }).offline).toBe(false);
  });

  it.each<[string, NodeJS.ProcessEnv]>([
    ["missing tenant keys", {}],
    ["a negative port", { RELAY_TENANT_KEYS: "k1:acme", RELAY_GATEWAY_PORT: "-1" }],
    ["a bad agents URL", { RELAY_TENANT_KEYS: "k1:acme", RELAY_AGENTS_URL: "not a url" }],
  ])("fails fast on %s", (_why, env) => {
    expect(() => loadConfig(env)).toThrow();
  });
});
