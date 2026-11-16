import { startTelemetry } from "@relay/telemetry";

const stopTelemetry = startTelemetry("relay-gateway");

const { serve } = await import("@hono/node-server");
const { HttpAgentsClient } = await import("./agents-client.js");
const { createApp } = await import("./app.js");
const { loadConfig } = await import("./config.js");

const config = loadConfig();
const app = createApp({
  agents: new HttpAgentsClient(config.agentsUrl),
  tenantKeys: config.tenantKeys,
  publicUrl: config.publicUrl,
  offline: config.offline,
});

const server = serve({ fetch: app.fetch, port: config.port }, () => {
  console.log(`relay-gateway listening on :${config.port}`);
});

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.on(signal, () => {
    server.close();
    void stopTelemetry().finally(() => process.exit(0));
  });
}
