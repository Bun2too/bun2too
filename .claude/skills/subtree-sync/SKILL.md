---
name: subtree-sync
description: Pull changes from a product's mirror repo into the Bun2too monorepo, or prepare a push of monorepo changes to the mirror. Use when someone committed to a mirror, before a mirror deploy, or when adding a new product subtree.
---

# Subtree sync

Follow [docs/sop/subtrees.md](../../../docs/sop/subtrees.md).

1. Confirm the working tree is clean for the prefix: `git status --short <prefix>`. Never stash or discard someone else's work. If the prefix has uncommitted changes, stop and report them.
2. **Pull** (mirror → monorepo):
   - `git fetch <remote>`
   - `git subtree pull --prefix=<prefix> <remote> main -m "chore(<product>): sync from mirror"`
   - Resolve conflicts, run the product's check command, and open a PR.
3. **Push** (monorepo → mirror): agents do not push. Tell the person to run Actions → `subtree-sync` with the prefix, and warn them if the mirror's `main` deploys to production (the website mirror does).
4. Report the commit range synced and the check results.
