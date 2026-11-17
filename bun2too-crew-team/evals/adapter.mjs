import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
const execute = promisify(execFile);

// Exported for offline tests. Only generation configuration reaches the model
// process; never deployment, Facebook, SMTP, push or Auth0 credentials.
export function candidateEnvironment(source = process.env) {
  const env = Object.fromEntries(Object.entries(source).filter(([key]) =>
    /^(PATH|HOME|TMPDIR|TEMP|SYSTEMROOT|SSL_CERT_FILE|SSL_CERT_DIR|VIRTUAL_ENV|LANG|LC_ALL)$/.test(key) ||
    /^(OPENAI_(?:API_KEY|BASE_URL|API_BASE)|ANTHROPIC_API_KEY|GEMINI_API_KEY|MODEL_ROUTING_ENABLED|ANTHROPIC_PROMPT_CACHE_ENABLED|LLM_(MODEL(?:_[A-Z_]+)?|(?:ROUTINE|COMPLEX)_MODEL|REQUEST_TIMEOUT_SECONDS|REASONING_EFFORT|MAX_COMPLETION_TOKENS|MAX_TOKENS_[A-Z_]+)|AGENT_MAX_EXECUTION_SECONDS)$/.test(key)));
  return env;
}
export async function crewAdapter() {
  if (process.env.MARKETING_RUNTIME_CONFIG) {
    let config;
    try { config = JSON.parse(process.env.MARKETING_RUNTIME_CONFIG); }
    catch { throw new Error("Configure valid MARKETING_RUNTIME_CONFIG JSON for candidate generation"); }
    if (!config || Array.isArray(config) || typeof config !== "object" || Object.values(config).some(value => typeof value !== "string"))
      throw new Error("Configure MARKETING_RUNTIME_CONFIG as an object of strings");
    for (const [key, value] of Object.entries(candidateEnvironment(config)))
      if (!process.env[key]) process.env[key] = value;
    delete process.env.MARKETING_RUNTIME_CONFIG;
  }
  if (!process.env.LLM_MODEL) throw new Error("Configure LLM_MODEL and the candidate provider credentials for evaluations");
  const directory = await mkdtemp(join(tmpdir(), "crew-eval-"));
  return {
    async runCase(example, suite) {
      const destination = join(directory, example.id + ".json");
      try {
        await execute(process.env.AI_EVAL_PYTHON || "python3", ["evals/produce.py", suite, example.id, destination], {
          cwd: process.cwd(), env: candidateEnvironment(), timeout: 3600000, maxBuffer: 1024 * 1024,
        });
        return JSON.parse(await readFile(destination, "utf8"));
      } catch {
        // Never print captured subprocess stdout/stderr or SDK errors.
        throw new Error("Candidate execution failed; inspect the isolated harness");
      }
    },
    async close() { await rm(directory, { recursive: true, force: true }); },
  };
}
