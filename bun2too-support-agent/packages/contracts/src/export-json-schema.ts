import { readFile, writeFile } from "node:fs/promises";
import { z } from "zod";
import {
  Case,
  CaseEvent,
  CustomerReply,
  IntakeAccepted,
  IntakeCommand,
  IntakeRequest,
} from "./case.js";

const SCHEMAS = { IntakeRequest, IntakeCommand, IntakeAccepted, CustomerReply, Case, CaseEvent };
const dir = new URL("../schema/", import.meta.url);

const render = (schema: z.ZodType) =>
  `${JSON.stringify(z.toJSONSchema(schema, { io: "input" }), null, 2)}\n`;

async function main(mode: string | undefined) {
  const drifted: string[] = [];
  for (const [name, schema] of Object.entries(SCHEMAS)) {
    const file = new URL(`${name}.schema.json`, dir);
    const next = render(schema);
    if (mode === "write") {
      await writeFile(file, next);
      continue;
    }
    const current = await readFile(file, "utf8").catch(() => "");
    if (current !== next) drifted.push(name);
  }
  if (drifted.length > 0) {
    console.error(
      `Contract drift in ${drifted.join(", ")}. Run pnpm contracts:export and update relay_agents/contracts.py.`,
    );
    process.exit(1);
  }
}

await main(process.argv[2]);
