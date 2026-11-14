#!/bin/bash
# Make the packages of the test releases from the package under test, for
# deploy/debian/systemd-test.sh. deploy/debian/package-test.sh runs this in a
# plain ubuntu:26.04 container, for its dpkg-deb, and signs the results.
#
# Usage: test-releases.sh PACKAGE VERSION OWNER
#   PACKAGE   the file name of the package under test, in /w/release
#   VERSION   its version
#   OWNER     uid:gid to give what is written
# /w/keys/signers lists the test's release key. Each release goes to
# /w/<version>/segl_<version>_amd64.deb.
#
# Every test release is the package under test with a few files changed:
#   9.0.1   the version, and the release signers: it trusts the test's key
#   9.0.2   also a new statement in the package's segl-proxy.conf
#   9.0.3   9.0.2 with a server that does not start
#   9.0.4   9.0.2 with a change to the line of segl-proxy.conf that the test's
#           site edits, so the two cannot be merged
#   9.0.5   9.0.2 again, for the nightly update
set -euo pipefail

name=$1 base=$2 owner=$3
PROXY=opt/segl/share/nginx/segl-proxy.conf

edit() {
    # edit FILE SED-SCRIPT: change a file, and fail if nothing changed.
    local before
    before=$(sha256sum <"$1")
    sed -i "$2" "$1"
    [ "$(sha256sum <"$1")" != "$before" ] || {
        echo "test-releases: nothing changed in $1 for: $2" >&2
        exit 1
    }
}

variant() {
    # variant VERSION FROM: a copy of the tree FROM, at that version.
    local version=$1 tree=/tmp/$1 toml
    cp -a "$2" "$tree"
    edit "$tree/DEBIAN/control" "s/^Version: .*/Version: $version/"
    # `segl --version` and the version route read this copy of versions.toml.
    toml=$(echo "$tree"/opt/segl/venv/lib/python3.*/site-packages/segl/versions.toml)
    edit "$toml" "0,/^version = \".*\"/s//version = \"$version\"/"
    cp /w/keys/signers "$tree/opt/segl/share/release-signers"
}

pack() {
    # pack VERSION: the tree as a package. dpkg checks files against md5sums.
    local version=$1 tree=/tmp/$1
    (cd "$tree" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' |
        sort -z | xargs -0 md5sum >DEBIAN/md5sums)
    mkdir -p "/w/$version"
    dpkg-deb --root-owner-group -Zzstd -b "$tree" "/w/$version/segl_${version}_amd64.deb" >/dev/null
}

dpkg-deb -R "/w/release/$name" /tmp/base
grep -q "^Version: $base\$" /tmp/base/DEBIAN/control

variant 9.0.1 /tmp/base
pack 9.0.1

variant 9.0.2 /tmp/9.0.1
edit "/tmp/9.0.2/$PROXY" 's/^proxy_connect_timeout 5s;$/&\nproxy_next_upstream_tries 2;/'
pack 9.0.2

variant 9.0.3 /tmp/9.0.2
# A second `serve` replaces the first. The other commands still run, so the
# package installs and checks out, and only the service fails.
cat >>"$(echo /tmp/9.0.3/opt/segl/venv/lib/python3.*/site-packages/segl/cli.py)" <<'EOF'


def serve(config):
    raise SystemExit("segl: broken on purpose by the package test")
EOF
pack 9.0.3

variant 9.0.4 /tmp/9.0.2
edit "/tmp/9.0.4/$PROXY" 's/^client_max_body_size 52m;$/client_max_body_size 64m;/'
pack 9.0.4

variant 9.0.5 /tmp/9.0.2
pack 9.0.5

chown -R "$owner" /w
