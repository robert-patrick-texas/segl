#!/bin/bash
# The install test, docs/TEST-PLAN.md T-017, in the form of Sunstone's
# packaging/package-test.sh: install the package in an ubuntu:26.04
# container that booted with systemd, put nginx in front of it with the
# deploy/nginx/ files and the snakeoil certificate, use it, then upgrade,
# remove, and purge it (deploy/debian/systemd-test.sh). It needs docker, git,
# and the host's python3.
#
# Usage: deploy/debian/package-test.sh [DEB]
#   DEB   a package to test. Without it, the script builds one into dist/.
# Environment:
#   SEGL_KEEP_CONTAINER   set to anything to leave the container running
#                         afterwards, to look around in it. The script prints
#                         its name. Remove it with `docker rm -f <name>`.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
version=$(python3 -c '
import tomllib
print(tomllib.load(open("versions.toml", "rb"))["project"]["version"])')
python=$(tr -d '[:space:]' <.python-version)
name=segl_${version}_amd64.deb
deb=${1:-}
if [ -z "$deb" ]; then
    deploy/debian/build-deb.sh dist
    deb=dist/$name
fi
[ "$(basename "$deb")" = "$name" ] || {
    echo "package-test: $deb is not $name, the package of versions.toml" >&2
    exit 2
}

work=$(mktemp -d)
container=segl-package-test-$$
cleanup() {
    if [ -n "${SEGL_KEEP_CONTAINER:-}" ]; then
        echo "package-test: kept container $container, and its packages in $work"
        return
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT
mkdir -p "$work/release" "$work/upgrade"
cp "$deb" "$work/release/$name"

# The upgrade: the same package under a higher version, so dpkg upgrades.
docker run --rm --volume "$work:/w" docker.io/library/ubuntu:26.04 bash -c '
    set -e
    dpkg-deb -R "/w/release/'"$name"'" /tmp/x
    sed -i "s/^Version: .*/Version: '"$version"'+upgrade/" /tmp/x/DEBIAN/control
    dpkg-deb --root-owner-group -b /tmp/x "/w/upgrade/segl_'"$version"'+upgrade_amd64.deb" >/dev/null
    chown -R '"$(id -u):$(id -g)"' /w/upgrade'
chmod -R a+rX "$work"

image=segl-systemd-test
docker build --quiet --tag "$image" - <deploy/debian/Containerfile.systemd >/dev/null
# systemd as PID 1 needs a privileged container with a cgroup tree of its
# own. The host name is the one in site-board.example.conf.
docker run --detach --name "$container" --hostname dev.example.com \
    --privileged --cgroupns=private --tmpfs /run --tmpfs /run/lock \
    --volume "$PWD/deploy:/deploy:ro" --volume "$work:/releases:ro" \
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
        echo "package-test: systemd did not come up in the container ($state)" >&2
        exit 1
        ;;
esac
docker exec --env SEGL_VERSION="$version" --env SEGL_PYTHON="$python" \
    "$container" bash /deploy/debian/systemd-test.sh
