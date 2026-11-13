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
#
# The container is given every tracked file, and every untracked file git
# does not ignore, so work in progress builds too. On a clean tree that is
# the commit. SOURCE_DATE_EPOCH is the commit's time.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
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
trap 'rm -rf "$stage"' EXIT
git ls-files -z --cached --others --exclude-standard |
    while IFS= read -r -d '' path; do
        # A tracked file deleted in the work tree is not built.
        if [ -e "$path" ]; then printf '%s\0' "$path"; fi
    done |
    tar --null --files-from=- --create --file="$stage/source.tar"
cp deploy/debian/build.sh "$stage/build.sh"

rm -f "$out_dir/segl_${version}_amd64.deb"
docker build --quiet --tag "$image" - <deploy/debian/Containerfile >/dev/null

mounts=()
if [ -n "$uv_cache" ]; then mounts+=(--volume "$uv_cache:/root/.cache/uv"); fi
if [ -n "$npm_cache" ]; then mounts+=(--volume "$npm_cache:/root/.npm"); fi
docker run --rm \
    --volume "$stage:/in:ro" --volume "$out_dir:/out" "${mounts[@]}" \
    --env SEGL_VERSION="$version" --env SOURCE_DATE_EPOCH="$epoch" \
    --env HOST_UID="$(id -u)" --env HOST_GID="$(id -g)" \
    "$image" bash ${SEGL_BUILD_TRACE:+-x} /in/build.sh

echo "build-deb: $out_dir/segl_${version}_amd64.deb"
