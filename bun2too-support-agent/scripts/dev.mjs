import { spawn } from "node:child_process";

const env = {
  RELAY_TENANT_KEYS: "dev-bun2too-key:bun2too",
  RELAY_AGENTS_URL: "http://localhost:8000",
  ...process.env,
};

const children = [
  spawn("uv", ["run", "--directory", "services/agents", "python", "-m", "relay_agents"], {
    env,
    stdio: "inherit",
  }),
  spawn("pnpm", ["--filter", "@relay/gateway", "start"], { env, stdio: "inherit" }),
];

const stop = () => {
  for (const child of children) child.kill("SIGTERM");
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
for (const child of children) child.on("exit", (code) => code && code !== 0 && stop());
