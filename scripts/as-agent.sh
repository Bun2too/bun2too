#!/usr/bin/env bash
# Run one command as a lead agent's own GitHub App, so GitHub records the agent, not the
# owner (AGENTS.md rule 15):
#   scripts/as-agent.sh <claude|codex> gh pr create ...
#   scripts/as-agent.sh claude git commit -m "..."
#   scripts/as-agent.sh claude git push origin HEAD:<branch>
# For that one command it sets:
#   - GH_TOKEN: a one-hour installation token for bun2too-<agent>, minted from the app's
#     private key. gh uses it instead of the owner's login.
#   - git author and committer: bun2too-<agent>[bot].
#   - git credentials from that token, with SSH remotes rewritten to HTTPS, so a push is
#     made by the bot and not with the owner's SSH key.
# The key lives outside the repo at ~/.config/bun2too/agents/<agent>.pem (mode 600). Each
# agent uses only its own key. Neither the key, the JWT nor the token is printed or passed
# in a process's argv.
set -euo pipefail

usage() { echo "usage: $0 <claude|codex> <command> [args...]" >&2; exit 2; }
[ $# -ge 2 ] || usage
agent=$1
shift
# App ID, org installation ID, bot user ID. These are public, not secrets.
case "$agent" in
  claude) app_id=5868181 installation_id=184504804 bot_id=359689245 ;;
  codex) app_id=5868247 installation_id=184505544 bot_id=359690649 ;;
  *) usage ;;
esac
slug="bun2too-$agent"
key="$HOME/.config/bun2too/agents/$agent.pem"
[ -r "$key" ] || {
  echo "as-agent: no private key for $slug at $key. The owner generates one (GitHub > Bun2too settings > GitHub Apps > $slug > Private keys) and saves it there with chmod 600." >&2
  exit 1
}

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
now=$(date +%s)
header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$app_id" | b64url)
signature=$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$key" -binary | b64url)
jwt="$header.$payload.$signature"

# The Authorization header goes in on stdin (printf is a shell builtin), never in argv.
response=$(printf 'Authorization: Bearer %s\n' "$jwt" |
  curl -sS --max-time 30 -X POST -H @- -H "Accept: application/vnd.github+json" \
    "https://api.github.com/app/installations/$installation_id/access_tokens")
token=$(jq -r '.token // empty' <<<"$response")
[ -n "$token" ] || {
  echo "as-agent: GitHub refused a token for $slug: $(jq -r '.message // "no message"' <<<"$response")" >&2
  exit 1
}
unset jwt response

export GH_TOKEN="$token" GITHUB_TOKEN="$token"
export GIT_AUTHOR_NAME="$slug[bot]" GIT_COMMITTER_NAME="$slug[bot]"
export GIT_AUTHOR_EMAIL="$bot_id+$slug[bot]@users.noreply.github.com"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
# Command-scope git config: clear inherited credential helpers (the owner's keychain),
# answer with the token instead, and send SSH remotes over HTTPS.
export GIT_CONFIG_COUNT=4
export GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0=
export GIT_CONFIG_KEY_1=credential.helper
export GIT_CONFIG_VALUE_1='!f() { test "$1" = get && printf "username=x-access-token\npassword=%s\n" "$GH_TOKEN"; }; f'
export GIT_CONFIG_KEY_2=url.https://github.com/.insteadOf GIT_CONFIG_VALUE_2=git@github.com:
export GIT_CONFIG_KEY_3=url.https://github.com/.pushInsteadOf GIT_CONFIG_VALUE_3=git@github.com:
exec "$@"
