# Evals

`intake-golden.jsonl` holds labelled intakes. Each row: `id`, `tenant`, `channel`, `message`, `expected_intent`, `expected_status`. Prefix ids by intent (`k-` knowledge, `i-` identity, `n-` integration, `c-` commerce, `p-` privacy, `x-` adversarial or out-of-scope).

```sh
pnpm eval                      # offline: keyword classifier + knowledge lookup (RELAY_OFFLINE=1)
RELAY_OFFLINE= pnpm eval       # live models from tenants/*.yaml; costs money, needs ANTHROPIC_API_KEY
```

The runner prints intent accuracy, outcome accuracy, misses and a confusion table, and exits 1 if intent accuracy is below `RELAY_EVAL_MIN` (default 0.8). Paste before/after numbers in every PR that changes a prompt, the classifier or policy. Grow the set to 150+ rows before the pilot (execution plan, phase 3).
