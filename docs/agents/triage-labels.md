# Triage labels

| Role            | Label             | Meaning                                                         |
| --------------- | ----------------- | --------------------------------------------------------------- |
| needs-triage    | `needs-triage`    | New; the Explore role has not judged it yet                     |
| needs-info      | `needs-info`      | Waiting on the reporter                                         |
| ready-for-agent | `ready-for-agent` | Clear enough for the Implement role                             |
| ready-for-human | `ready-for-human` | Needs a person: judgment, credentials, or a capped loop ran out |
| wontfix         | `wontfix`         | Out of scope                                                    |

Product labels: `area:support-agent`, `area:crew-team`, `area:website`, `area:root`.

Factory bookkeeping labels (not triage roles): `agent-review`, `rework-1`, `rework-2`, `rework-3`, `spec`, `ratchet`, `retro`.

`gh pr edit --add-label` fails when a label does not exist, which stops the workflow that applies it. The rework workflow creates `rework-<n>` and `ready-for-human` itself. Create the rest once per repository (re-running is safe):

```sh
for l in needs-triage needs-info ready-for-agent ready-for-human wontfix \
         area:support-agent area:crew-team area:website area:root \
         agent-review rework-1 rework-2 rework-3 spec ratchet retro; do
  gh label create "$l" -R Bun2too/bun2too --force
done
```
