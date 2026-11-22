#!/usr/bin/env bash
# Push one product's subtree from origin/main to its mirror's main, as a lead agent's app
# (AGENTS.md rules 15 and 17). Fast-forward only, never forced.
#   scripts/sync-mirror.sh <claude|codex> <prefix> [--release]
# Mirrors whose main deploys production (crew-team, website) need --release, which an
# agent passes only when the owner has said to release that product.
set -euo pipefail
usage() { echo "usage: $0 <claude|codex> <bun2too-support-agent|bun2too-crew-team|bun2too-website> [--release]" >&2; exit 2; }
[ $# -eq 2 ] || [ $# -eq 3 ] || usage
agent=$1 prefix=$2 release=${3:-}
case "$prefix" in
  bun2too-support-agent) deploys_prod=no ;;
  bun2too-crew-team | bun2too-website) deploys_prod=yes ;;
  *) usage ;;
esac
[ -z "$release" ] || [ "$release" = --release ] || usage
cd "$(git rev-parse --show-toplevel)"
url="https://github.com/Bun2too/$prefix.git"

git fetch -q origin main
git fetch -q "$url" main
mirror=$(git rev-parse FETCH_HEAD)
split=$(git subtree split -q --prefix="$prefix" origin/main)
ahead=$(git rev-list --count "$mirror..$split")
if [ "$ahead" = 0 ]; then
  echo "sync-mirror: $prefix mirror is up to date at ${split:0:7}"
  exit 0
fi
git merge-base --is-ancestor "$mirror" "$split" || {
  echo "sync-mirror: the $prefix mirror has commits the monorepo lacks. Pull them in first (docs/sop/subtrees.md), then sync again." >&2
  exit 1
}
if [ "$deploys_prod" = yes ] && [ "$release" != --release ]; then
  echo "sync-mirror: $prefix is $ahead commit(s) behind, and its main deploys production. Ask the owner, then rerun with --release." >&2
  exit 3
fi
scripts/as-agent.sh "$agent" git push -q "$url" "${split}:refs/heads/main"
echo "sync-mirror: pushed $ahead commit(s) of $prefix to its mirror (${mirror:0:7}..${split:0:7})"
