# SOP: product subtrees

Each product folder is a git subtree. The monorepo is the source of truth. Each product's own GitHub repo is a **mirror** that receives `main` from here.

| Prefix                   | Mirror remote          | Mirror repo                                   |
| ------------------------ | ---------------------- | --------------------------------------------- |
| `bun2too-support-agent/` | `bun2too-support-agent` | `Bun2too/bun2too-support-agent`              |
| `bun2too-crew-team/`             | `bun2too-crew-team`            | `Bun2too/bun2too-crew-team`                   |
| `bun2too-website/`       | `bun2too-website`      | `Bun2too/bun2too-website`                     |

## Rules

1. Work happens in the monorepo. Do not commit to a mirror directly. If someone did, pull it in (below) before the next push.
2. One product per commit, so the split history stays readable.
3. Pushing to a mirror can trigger that mirror's own deploy pipeline. The website mirror deploys **prod** from `main`. Sync is manual for that reason.

## Push monorepo changes to a mirror

Run Actions → `subtree-sync` with the prefix, or locally:

```sh
git subtree push --prefix=bun2too-crew-team bun2too-crew-team main
```

A rejected push means the mirror moved on. Pull first, then push again. Never force-push a mirror.

## Pull mirror changes into the monorepo

```sh
git fetch bun2too-crew-team
git subtree pull --prefix=bun2too-crew-team bun2too-crew-team main -m "chore(bun2too-crew-team): sync from mirror"
```

Resolve conflicts in the monorepo and commit them as part of the merge.

## Add a new product

```sh
git subtree add --prefix=<product> <remote-or-path> main
```

Then add a row to the root `AGENTS.md` map, a path filter in `.github/workflows/ci.yml`, and a remote row above.
