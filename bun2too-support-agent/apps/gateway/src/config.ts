import { z } from "zod";

const Env = z.object({
  RELAY_GATEWAY_PORT: z.coerce.number().int().positive().default(8787),
  RELAY_AGENTS_URL: z.url().default("http://localhost:8000"),
  RELAY_PUBLIC_URL: z.url().default("http://localhost:8787"),
  RELAY_TENANT_KEYS: z.string().min(1),
  RELAY_OFFLINE: z.string().optional(),
});

export interface GatewayConfig {
  port: number;
  agentsUrl: string;
  publicUrl: string;
  tenantKeys: ReadonlyMap<string, string>;
  offline: boolean;
}

export function parseTenantKeys(raw: string): ReadonlyMap<string, string> {
  const entries = raw.split(",").map((pair) => {
    const [key, tenant] = pair.trim().split(":");
    if (!key || !tenant)
      throw new Error("RELAY_TENANT_KEYS must look like key:tenant,key2:tenant2");
    return [key, tenant] as const;
  });
  return new Map(entries);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): GatewayConfig {
  const parsed = Env.parse(env);
  return {
    port: parsed.RELAY_GATEWAY_PORT,
    agentsUrl: parsed.RELAY_AGENTS_URL,
    publicUrl: parsed.RELAY_PUBLIC_URL,
    tenantKeys: parseTenantKeys(parsed.RELAY_TENANT_KEYS),
    offline: parsed.RELAY_OFFLINE === "1",
  };
}
