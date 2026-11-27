#!/bin/bash
# Build segl_<version>_amd64.deb in a clean ubuntu:26.04 container, in the
# form of Sunstone's packaging/build-deb.sh. It needs docker, git, and the
# host's python3 (3.11 or newer), which reads the version.
#
# Usage: deploy/debian/build-deb.sh [OUTPUT_DIR]        (default: dist)
# Environment:
#   BUILDER_IMAGE   tag for the builder image (default: segl-deb-builder)
#   SEGL_UV_CACHE, SEGL_NPM_CACHE
#                   docker volumes that keep uv's and npm's downloads between
#                   builds. Set one empty to do without it. Every download is
#                   checked against a hash, so a cache cannot change the result.
#   SEGL_BUILD_TRACE
#                   set to anything to trace the build inside the container.
#   SEGL_TEST_WAIT  the most seconds to wait for a machine that is busy with
#                   other work, 600 unless set. 0 does not wait.
#
# The container is given every tracked file, and every untracked file git
# does not ignore, so work in progress builds too. On a clean tree that is
# the commit. SOURCE_DATE_EPOCH is the commit's time.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
# On a machine that is busy with other work, wait for room, and go ahead
# after ten minutes (scripts/capacity.py). package-test.sh has waited already.
[ -n "${SEGL_CAPACITY_WAITED:-}" ] || python3 scripts/capacity.py --wait
out_dir=${1:-dist}
mkdir -p "$out_dir"
out_dir=$(cd "$out_dir" && pwd)
image=${BUILDER_IMAGE:-segl-deb-builder}
uv_cache=${SEGL_UV_CACHE-segl-uv-cache}
npm_cache=${SEGL_NPM_CACHE-segl-npm-cache}

# versions.toml is the only version list (D2-020). A Debian version is the
# same text while it is three plain numbers. Anything else needs a mapping
# that does not exist yet, so the build stops.
version=$(python3 -c '
import re, sys, tomllib
version = tomllib.load(open("versions.toml", "rb"))["project"]["version"]
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    sys.exit(f"build-deb: versions.toml has version {version!r}; it must be MAJOR.MINOR.PATCH")
print(version)')
epoch=$(git log -1 --format=%ct)

stage=$(mktemp -d)
build=segl-deb-build-$$
trap 'rm -rf "$stage"; docker rm -f "$build" >/dev/null 2>&1 || true' EXIT
# A stop ends the script, and the EXIT trap removes $stage and the build's
# container. The build runs in the background, since `docker run` hands a
# stop to its container instead of ending, and bash's `wait` returns at once.
# Its folders are bind mounts that must exist: a container that starts after
# the trap then fails, where a --volume would make the folder again, as root.
trap 'exit 130' INT
trap 'exit 143' TERM
git ls-files -z --cached --others --exclude-standard |
    while IFS= read -r -d '' path; do
        # A tracked file deleted in the work tree is not built.
        if [ -e "$path" ]; then printf '%s\0' "$path"; fi
    done |
    tar --null --files-from=- --create --file="$stage/source.tar"
cp deploy/debian/build.sh "$stage/build.sh"

rm -f "$out_dir/segl_${version}_amd64.deb"
deploy/debian/image.sh "$image" deploy/debian/Containerfile

# Every path the build prints is inside the container. Its /opt/segl is the
# container's own: nothing on this host is installed or changed.
echo "==> building in a clean ubuntu:26.04 container: the paths below are inside it"
mounts=()
if [ -n "$uv_cache" ]; then mounts+=(--volume "$uv_cache:/root/.cache/uv"); fi
if [ -n "$npm_cache" ]; then mounts+=(--volume "$npm_cache:/root/.npm"); fi
docker run --rm --name "$build" \
    --mount "type=bind,source=$stage,target=/in,readonly" \
    --mount "type=bind,source=$out_dir,target=/out" "${mounts[@]}" \
    --env SEGL_VERSION="$version" --env SOURCE_DATE_EPOCH="$epoch" \
    --env HOST_UID="$(id -u)" --env HOST_GID="$(id -g)" \
    "$image" bash ${SEGL_BUILD_TRACE:+-x} /in/build.sh &
wait $!

echo "build-deb: $out_dir/segl_${version}_amd64.deb"
