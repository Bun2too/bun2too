# Rules and their enforcers

A rule repeated twice becomes a check (the Retro role in the root `docs/factory.md`). Each row pairs a rule from `AGENTS.md` with the strongest thing that enforces it. Prefer the higher rows of this ladder: architecture, then types, then lint and CI, then tests, then review, with docs last.

| Rule                           | Enforcer                                                                                                                                                                                   | Level                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------- |
| Parse at the boundary          | `IntakeRequest` Zod/Pydantic types; handlers accept parsed types only                                                                                                                      | types                |
| Contracts change in one place  | `pnpm contracts:check` diffs exported JSON Schema vs `schema/`; `test_contract_parity.py` validates fixtures on both sides                                                                 | CI                   |
| One state machine              | `CaseStatus` transitions table + `IllegalTransition`; `test_case_machine.py` covers every edge                                                                                             | types + tests        |
| Idempotent external writes     | `TicketPort.ensure_ticket` is the only create path; `test_connectors.py` calls it twice and asserts one ticket                                                                             | architecture + tests |
| Agents propose, code disposes  | Specialists return `proposed_actions` only; `policy.assess` alone picks the outcome. Phase 3 adds `ActionPort.execute(action, PolicyDecision)` so write actions need a policy value to run | architecture         |
| Customer text is data          | `as_untrusted().render()` wraps every customer message; `test_policy.py` proves the wrapper cannot be closed early; injection rows in `evals/`                                             | tests + evals        |
| Tenant config is data          | `test_structure.py` fails if a tenant slug from `tenants/` appears in `src/`; every `tenants/*.yaml` is parsed by `TenantConfig` in tests                                                  | tests                |
| Trace everything               | `build_graph` raises if a node function lacks `@traced_node`                                                                                                                               | architecture         |
| Models via config              | Ruff `flake8-tidy-imports` banned-api on `langchain_anthropic` and `langchain.chat_models` imports outside `llm.py`                                                                        | lint                 |
| No narration comments          | Addy's `code-simplification` and `code-reviewer` during `factory-review`                                                                                                                   | review               |
| Formatting                     | Biome + Ruff format via hooks and Hygiene task                                                                                                                                             | lint                 |
| No secrets                     | gitleaks in CI; root `.claude/settings.json` denies reads of `.env*` and `*.tfvars`; the guard hook blocks edits                                                                           | CI + harness         |
| Deploys only through CI        | root `.claude/settings.json` denies `terraform apply` and `railway up`; `support-prod` environment needs approval                                                                          | harness + CI         |
| Railway config per environment | `railway.tftest.hcl` asserts that qa runs live (no `RELAY_OFFLINE`), that `dev` is rejected, and the secret split between gateway and agents                                                                                     | tests                |

When a review finding recurs, add a row here in the same PR as its new enforcer.
