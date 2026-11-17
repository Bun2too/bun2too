import test from "node:test";
import assert from "node:assert/strict";
import { candidateEnvironment } from "./adapter.mjs";

test("candidate process receives generation routes without judge, publishing or subscriber credentials", () => {
  const safe = { LLM_MODEL: "openai/fixture", LLM_MODEL_EDITOR: "openai/fixture-review", OPENAI_API_KEY: "fixture-provider", OPENAI_BASE_URL: "https://provider.example.invalid", MODEL_ROUTING_ENABLED: "true" };
  const privateSettings = { FACEBOOK_PAGE_ACCESS_TOKEN: "fixture-page", SUPPORT_SES_SMTP_PASSWORD: "fixture-smtp", AUTH0_CLIENT_SECRET: "fixture-identity", RAILWAY_API_TOKEN: "fixture-deployment", AI_EVAL_JUDGE_API_KEY: "fixture-judge", MARKETING_RUNTIME_CONFIG: "{}", CREWAI_STORAGE_DIR: "/must-not-use-existing-state" };
  assert.deepEqual(candidateEnvironment({ ...safe, ...privateSettings }), safe);
});
