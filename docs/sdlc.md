# Agentic SDLC

Bun2too builds software with a harness: agents do most of the work inside fixed phases, and people step in at a few named gates. The phases and their skills come from Addy Osmani's [agent-skills](https://github.com/addyosmani/agent-skills). Matt Pocock's [skills](https://github.com/mattpocock/skills) and Lauren Tan's [pstack](https://github.com/cursor/plugins/tree/main/pstack) overlap with it heavily. Where they overlap, Addy's version wins. Two of Matt's skills fill gaps Addy does not cover. pstack is not installed; its two ideas Addy lacks are written into our own docs.

Decision record: [ADR 0002](adr/0002-addy-agent-skills-lifecycle.md).

## Lifecycle

```
DEFINE ──▶ PLAN ──▶ BUILD ──▶ VERIFY ──▶ REVIEW ──▶ SHIP
 /spec     /plan    /build    /test      factory-   /ship
           /to-tickets                   review     (CI/CD: dev → qa → prod)
   ▲ gate 1                                  ▲ gate 2         ▲ gate 3
 spec approved                           PR merged         prod approved
```

| Phase  | Primary (Addy)                                                                                   | Complement                                                                                       | Exit evidence                                                                                 |
| ------ | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| Define | `/spec`: `interview-me`, `idea-refine`, `spec-driven-development`, `constraint-driven-development` | Matt `/grill-with-docs` when glossary terms or ADRs change                                       | `SPEC.md` in the product, or an issue labelled `spec`, approved by a person (**gate 1**)      |
| Plan   | `/plan`: `planning-and-task-breakdown`                                                           | Matt `/to-tickets` publishes each task as a GitHub issue with `Blocked by #n` edges             | Tasks under half a day each, each with acceptance criteria and a named test seam             |
| Build  | `/build`: `incremental-implementation`, `test-driven-development`, `context-engineering`, `source-driven-development`, `api-and-interface-design`, `frontend-ui-engineering` | Product skills such as `add-specialist` and `add-tenant`                                         | One slice per commit, each green on the product's check command                              |
| Verify | `/test`: `debugging-and-error-recovery`, `browser-testing-with-devtools`                         | Shared `verifier` agent running the product's verify skill (for example `verify-relay`)          | Commands and outputs from the running system; trace IDs where available                      |
| Review | `code-review-and-quality` (`code-reviewer`), `security-and-hardening` (`security-auditor`), `code-simplification`, `performance-optimization` | Shared `spec-reviewer` agent, kept separate from the code review in its own fresh context        | One PR comment ending `VERDICT: PASS` or `VERDICT: FAIL`; PASS with green CI merges, factory PRs included (**gate 2**)              |
| Ship   | `/ship`: `git-workflow-and-versioning`, `ci-cd-and-automation`, `shipping-and-launch`, `observability-and-instrumentation`, `documentation-and-adrs`, `deprecation-and-migration` | Matt `/pr` for the PR body; [environments SOP](sop/environments-and-release.md)                  | Deploy records for dev and qa; prod approved by a person (**gate 3**); a tested rollback       |

`/build auto` runs plan and build after one approval. Use it only for tickets already labelled `ready-for-agent`.

## Where the three skill sets overlap

| Concern                     | Addy (used)                                       | Matt                    | pstack                                      | Our decision                                                                                                   |
| --------------------------- | ------------------------------------------------- | ----------------------- | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| Clarify the ask             | `interview-me`, `idea-refine`                      | `grilling`, `grill-with-docs` | `interrogate`                              | Addy. Matt's `grill-with-docs` only when it should update `GLOSSARY.md` or write an ADR                        |
| Write the spec              | `spec-driven-development` (`/spec`)               | `to-spec`               | (none)                                      | Addy                                                                                                           |
| Break down work             | `planning-and-task-breakdown` (`/plan`)           | `to-tickets`            | (none)                                      | Addy plans; Matt's `to-tickets` publishes the plan as GitHub issues                                           |
| Test-first                  | `test-driven-development`                         | `tdd`                   | (none)                                      | Addy                                                                                                           |
| Code review                 | `code-review-and-quality` (five axes)             | two-axis `code-review`  | (none)                                      | Addy's reviewer plus Matt's idea of a separate spec axis (`spec-reviewer`)                                    |
| Comment hygiene             | `code-simplification`                             | (none)                  | `no-comments`                               | Addy                                                                                                           |
| Prove it works              | "verification is non-negotiable", `/test`         | (none)                  | "Prove It Works"                            | Addy plus each product's verify skill                                                                          |
| Encode lessons in structure | `documentation-and-adrs`                          | (none)                  | "Encode Lessons in Structure"               | Kept: each product's `enforcement.md` ladder and the Retro role ([factory.md](factory.md))                    |
| Never block on a person     | (none)                                            | software-factory runs   | "Never Block on the Human"                  | Kept: a run finishes and labels `ready-for-human`; the person's later label starts a new run                 |
| PR body                     | `shipping-and-launch` checklist                   | `pr`                    | (none)                                      | Matt's `pr` format inside Addy's ship checklist                                                               |

## Human gates

People act at four points. Everything between them runs without waiting.

1. **Spec approved:** the issue gets `ready-for-agent`, or the `SPEC.md` PR merges.
2. **PR merged:** after `VERDICT: PASS` and green CI.
3. **Prod approved:** the `support-prod` environment approval in the deploy run.
4. **Unresolved:** anything labelled `ready-for-human`, such as a review loop that ran out, a missing credential, or a product judgment.

## Definition of done

Addy's `references/definition-of-done.md`, plus:

- The product's check command passes (`pnpm check`, `scripts/verify_marketing.py`, `npm test` and the rest of the product's list).
- The behaviour is proved by the product's verify skill, with evidence in the PR body.
- Docs, `GLOSSARY.md` and ADRs are updated in the same PR when a term or decision changed.
- For deployable products, the change reached dev and qa through the pipeline, and its smoke checks passed.
