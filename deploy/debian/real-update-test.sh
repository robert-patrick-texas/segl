#!/bin/bash
# The update from a real release to this one, as a site would have it, in a
# container that boots systemd. The earlier release comes from its GitHub
# release, and its own `segl update` installs this version
# (deploy/debian/real-update.sh). `scripts/release.py publish` runs it twice:
# before the tag, from this version's signed files, and after the release,
# from GitHub (docs/RELEASING.md).
#
# Usage: deploy/debian/real-update-test.sh PREVIOUS_TAG [FOLDER]
#   PREVIOUS_TAG  an earlier GitHub release, such as v0.1.0
#   FOLDER        holds this version's package, SHA256SUMS, and SHA256SUMS.sig,
#                 signed and not yet published: the update installs them with
#                 `segl update --from`. Without it, the update takes this
#                 version from GitHub, as a server does.
# Environment:
#   SEGL_KEEP_CONTAINER  set to anything to leave the container running
#   SEGL_TEST_WAIT       the most seconds to wait for a busy machine, 600 unless set
#
# It needs docker, curl, ssh-keygen, and the host's python3. Nothing of the
# host is installed or changed: the container mounts deploy/ and a folder of
# its own, both read-only.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
previous_tag=${1:?usage: deploy/debian/real-update-test.sh PREVIOUS_TAG [FOLDER]}
folder=${2:-}
previous=${previous_tag#v}
read -r version repo < <(python3 -c '
import tomllib
doc = tomllib.load(open("versions.toml", "rb"))
print(doc["project"]["version"], doc["publish"]["github_repo"])')
# On a machine that is busy with other work, wait for room, and go ahead
# after ten minutes (scripts/capacity.py).
python3 scripts/capacity.py --wait

work=$(mktemp -d)
container=segl-real-update-$$
cleanup() {
    if [ -z "${SEGL_KEEP_CONTAINER:-}" ]; then
        docker rm -f "$container" >/dev/null 2>&1 || true
    else
        echo "real-update: the container is kept: docker exec -it $container bash"
    fi
    rm -rf "$work"
}
trap cleanup EXIT

echo "== $previous_tag from GitHub, then $version from ${folder:-GitHub}"
mkdir -p "$work/previous" "$work/new"
for file in "segl_${previous}_amd64.deb" SHA256SUMS SHA256SUMS.sig; do
    curl -fsSL --retry 3 -o "$work/previous/$file" \
        "https://github.com/$repo/releases/download/$previous_tag/$file"
done
# What a server would check, here, before the container is given it.
(cd "$work/previous" && sha256sum --quiet -c SHA256SUMS)
ssh-keygen -Y verify -f deploy/release-signers -I segl-release -n segl-release \
    -s "$work/previous/SHA256SUMS.sig" <"$work/previous/SHA256SUMS" >/dev/null
# The earlier release draws with its own client, when it had one.
git show "$previous_tag:deploy/debian/socket_check.py" >"$work/socket_check.py" 2>/dev/null ||
    rm -f "$work/socket_check.py"
from=""
if [ -n "$folder" ]; then
    cp "$folder/segl_${version}_amd64.deb" "$folder/SHA256SUMS" "$folder/SHA256SUMS.sig" "$work/new/"
    from=/t/new
fi
chmod -R a+rX "$work"

image=segl-systemd-test
deploy/debian/image.sh "$image" deploy/debian/Containerfile.systemd
docker run --detach --name "$container" --hostname dev.example.com \
    --privileged --cgroupns=private --tmpfs /run --tmpfs /run/lock \
    --volume "$PWD/deploy:/deploy:ro" --volume "$work:/t:ro" \
    "$image" >/dev/null
state=starting
for _ in $(seq 60); do
    state=$(docker exec "$container" systemctl is-system-running 2>/dev/null || true)
    case $state in running | degraded) break ;; esac
    sleep 1
done
case $state in
    running | degraded) ;;
    *)
        echo "real-update: systemd did not come up in the container ($state)" >&2
        exit 1
        ;;
esac
docker exec --env SEGL_PREVIOUS="$previous" --env SEGL_VERSION="$version" \
    --env SEGL_FROM="$from" --env SEGL_REPO="$repo" \
    "$container" bash /deploy/debian/real-update.sh
