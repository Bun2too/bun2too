#!/usr/bin/env bash
# Make sure one service has exactly one volume at a mount path in one environment.
# Creates it only when none exists; never deletes, replaces or retries a create.
#   ensure-volume.sh <service-id> <environment-id> <mount-path>
# Needs RAILWAY_API_TOKEN and RAILWAY_PROJECT_ID.
set -euo pipefail
service_id=${1:?service id}; environment_id=${2:?environment id}; mount=${3:?mount path}
: "${RAILWAY_API_TOKEN:?}" "${RAILWAY_PROJECT_ID:?}"

gql() {
  curl -fsS https://backboard.railway.com/graphql/v2 \
    -H "Authorization: Bearer $RAILWAY_API_TOKEN" -H 'content-type: application/json' -d "$1"
}

lookup() {
  gql "$(jq -n --arg id "$RAILWAY_PROJECT_ID" '{query:"query($id: String!) { project(id: $id) { volumes { edges { node { id volumeInstances { edges { node { environmentId serviceId mountPath } } } } } } } }", variables:{id:$id}}')" |
    jq -c --arg s "$service_id" --arg e "$environment_id" '
      if .errors then error("cannot read volumes") else . end
      | [.data.project.volumes.edges[].node as $v
         | $v.volumeInstances.edges[].node
         | select(.serviceId == $s and .environmentId == $e)
         | {id: $v.id, mountPath}]'
}

found=$(lookup)
case $(jq length <<<"$found") in
  0) ;;
  1)
    [ "$(jq -r '.[0].mountPath' <<<"$found")" = "$mount" ] || { echo "::error::volume exists at another mount path; migrate it by hand" >&2; exit 1; }
    echo "volume $(jq -r '.[0].id' <<<"$found") already attached at $mount"; exit 0 ;;
  *) echo "::error::several volumes attached to this service; reconcile without deleting data" >&2; exit 1 ;;
esac

created=$(gql "$(jq -n --arg p "$RAILWAY_PROJECT_ID" --arg e "$environment_id" --arg s "$service_id" --arg m "$mount" \
  '{query:"mutation($input: VolumeCreateInput!) { volumeCreate(input: $input) { id } }", variables:{input:{projectId:$p, environmentId:$e, serviceId:$s, mountPath:$m}}}')" |
  jq -r '.data.volumeCreate.id // empty')
[ -n "$created" ] || { echo "::error::volume create not confirmed; inspect Railway before retrying" >&2; exit 1; }
echo "created volume $created at $mount"
