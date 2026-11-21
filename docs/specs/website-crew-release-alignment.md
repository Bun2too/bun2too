# Draft: website and crew release alignment

Status: **draft for owner review; not approved for implementation**. Scope is the website and marketing crew release paths. This follows accepted [ADR 0003](../adr/0003-trunk-based-development.md), [ADR 0005](../adr/0005-factory-review-loop-merges-product-prs.md) and root [AGENTS.md](../../AGENTS.md) rules 9–12. The current request authorizes context reconciliation, not deployment or CI permission changes.

## Problem and evidence

Root `.github/workflows/ci.yml` runs offline website/crew checks. Their nested workflows are mirror release definitions, not automatically executed monorepo workflows. Website `ci-cd.yml` and crew `deploy.yml` still map environment branches and launch paid candidate/judge evaluations on pushes. Subtree sync to a mirror's main can therefore begin paid production-candidate work. That conflicts with root rule 12's person-requested spend boundary.

Both product workflows gate main releases through `agent-production-review`. Root rule 9 names `support-prod`; the release SOP currently describes Relay. An explicit mapping or policy clarification is needed rather than guessing that one environment protects every product. Remote reviewer rules and independent host auto-deploy paths were not inspected.

## Required outcome

Release a reviewed main commit through dev, QA and a human-approved production stage, with paid evaluation tied to an explicit bounded request. Preserve the existing component, trajectory, deterministic and human gates. Never publish a fixture build or substitute a different candidate model to lower evaluation costs.

## Acceptance criteria for the implementation ticket

1. Offline PR/push checks remain secret-free and perform no paid model inference. Paid factory and product-evaluation triggers are listed and have a person-requested entry point with bounded continuation, attempts and spend controls. An ordinary push, schedule or subtree synchronization alone cannot authorize paid evaluation.
2. Promotion uses one identified main commit without dev/qa merge-forward branches. Dev runs component evaluations; QA runs trajectory and observed-component evaluations; production requires both suites for the exact candidate plus recorded human approval. Every relevant dimension remains at least 0.5; missing evidence, failed guards and provider/judge failures block release.
3. Reports record source SHA and the evaluated prompt/model/configuration/dataset identity without secret values. Define when an earlier report may be reused and which changes invalidate it. A code SHA alone is insufficient when model or runtime configuration changes.
4. The owner approves explicit GitHub environment mappings for website, crew and Relay, including required reviewers and the relationship to root rule 9. Scorecard/notes remain configurable through the existing policy; optional scorecards never mean optional human approval. Generated reports must describe the selected scorecard policy accurately; the current crew report has an unconditional paste-scorecard instruction. Preserve the owner's approved self-review setting unless explicitly changed.
5. Keep product isolation: distinct Netlify sites, Contentful master for prod and qa for dev/QA; crew QA test destinations/state/volumes; no production subscriber or Facebook side effects from evaluations. Dev crew validation must not accidentally target QA infrastructure.
6. Each promotion records revision, destination, evaluation report digest, approval and smoke evidence. Packaging checks cover website browser/assets/functions; crew checks cover its actual deployment and n8n activation. Provider acceptance and inbox delivery remain separate evidence.
7. Define source-build versus immutable-artifact guarantees honestly. Crew's current GHCR publication is an archive; Railway rebuilds source. Do not claim digest promotion without implementing and verifying it.
8. Provide an approved rollback path preserving inquiry storage, SQLite publication claims, n8n state/encryption keys, consent and retention. Failure after publication is reported as such; it is not an automatic rollback.

## Decisions still needed

- Which person-requested release/evaluation entry point and budget limits should each product use?
- Should the website and crew gain product-specific production approval environments, or adopt another explicit mapping consistent with root policy?
- Will release execution move into root reusable workflows, or remain in mirrors with a documented promotion contract?
- Which artifact/configuration identity and rollback evidence are required for the first migration slice?

After owner approval, split implementation into small product/root tickets in the [monorepo issue tracker](../agents/issue-tracker.md), with blocking edges and exact acceptance evidence. Factory-path changes need human review; agents do not change CI permissions. No issues, workflows, reviewer settings or remote resources were changed by drafting this spec.
