#!/bin/bash
# The install test, docs/TEST-PLAN.md T-017, in the form of Sunstone's
# packaging/package-test.sh: install the package in an ubuntu:26.04
# container that booted with systemd, put nginx in front of it with the
# deploy/nginx/ files and the snakeoil certificate, use it, then upgrade it,
# update it with `segl update` from a stand-in for GitHub, and remove and
# purge it (deploy/debian/systemd-test.sh). It needs docker, git, the host's
# python3, and, for the test releases, ssh-keygen and openssl.
#
# The update needs releases to install. They are made here from the package
# under test (deploy/debian/test-releases.sh), and signed with a throwaway
# key that those packages trust. The package under test trusts only the
# keys in deploy/release-signers.
#
# Usage: deploy/debian/package-test.sh [DEB]
#   DEB   a package to test. Without it, the script builds one into dist/.
# Environment:
#   SEGL_KEEP_CONTAINER   set to anything to leave the container running
#                         afterwards, to look around in it. The script prints
#                         its name. Remove it with `docker rm -f <name>`.
#   SEGL_TEST_WAIT        the most seconds to wait for a machine that is busy
#                         with other work, 600 unless set. 0 does not wait.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
# On a machine that is busy with other work, wait for room, and go ahead
# after ten minutes (scripts/capacity.py). The build below does not wait again.
python3 scripts/capacity.py --wait
export SEGL_CAPACITY_WAITED=1
# The image the test boots is built meanwhile: it needs nothing of the package.
image=segl-systemd-test
docker build --quiet --tag "$image" - <deploy/debian/Containerfile.systemd >/dev/null &
image_build=$!
version=$(python3 -c '
import tomllib
print(tomllib.load(open("versions.toml", "rb"))["project"]["version"])')
python=$(tr -d '[:space:]' <.python-version)
# The font segl ships in place of the editor's (web/licenses/README.md).
liberation=$(sha256sum web/fonts/Liberation/LiberationSans-Regular.woff2 | cut -d" " -f1)
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
mkdir -p "$work/release" "$work/keys" "$work/pki"
cp "$deb" "$work/release/$name"

# The test's release key, and a key no package trusts.
ssh-keygen -q -t ed25519 -N "" -C package-test -f "$work/keys/release"
ssh-keygen -q -t ed25519 -N "" -C untrusted -f "$work/keys/untrusted"
printf 'segl-release namespaces="segl-release" %s\n' \
    "$(cat "$work/keys/release.pub")" >"$work/keys/signers"

sign() {
    # SHA256SUMS for the package in folder $1, signed with key $2.
    (cd "$1" && sha256sum segl_*_amd64.deb >SHA256SUMS)
    ssh-keygen -q -Y sign -f "$2" -n segl-release "$1/SHA256SUMS"
}

# Releases 9.0.1 to 9.0.5: the package under test at higher versions, each
# with a few files changed.
docker run --rm --volume "$work:/w" --volume "$PWD/deploy/debian:/d:ro" \
    docker.io/library/ubuntu:26.04 bash /d/test-releases.sh "$name" "$version" "$(id -u):$(id -g)"
for release in 9.0.1 9.0.2 9.0.3 9.0.4 9.0.5; do
    sign "$work/$release" "$work/keys/release"
done

# 9.0.2 changed after it was signed, and 9.0.2 signed by the other key.
mkdir -p "$work/tampered" "$work/untrusted"
cp "$work"/9.0.2/* "$work/tampered/"
printf x >>"$work/tampered/segl_9.0.2_amd64.deb"
cp "$work/9.0.2/segl_9.0.2_amd64.deb" "$work/untrusted/"
sign "$work/untrusted" "$work/keys/untrusted"

# A CA the machine does not trust, as a firewall that inspects TLS has, and
# the certificate it issues to the stand-in for GitHub
# (deploy/debian/fake_github.py). In the form of Sunstone's package test.
ec=(-newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes)
printf '%s\n' '[req]' 'distinguished_name = dn' 'prompt = no' '[dn]' 'CN = segl package test CA' \
    '[ext]' 'basicConstraints = critical,CA:TRUE' 'subjectKeyIdentifier = hash' \
    'keyUsage = critical,keyCertSign,cRLSign' >"$work/pki/ca.cnf"
openssl req -x509 -config "$work/pki/ca.cnf" -extensions ext "${ec[@]}" -days 2 \
    -keyout "$work/pki/ca.key" -out "$work/pki/ca.pem" 2>/dev/null
openssl req -new "${ec[@]}" -subj /CN=localhost \
    -keyout "$work/pki/server.key" -out "$work/pki/server.csr" 2>/dev/null
printf '%s\n' 'subjectAltName = DNS:localhost' 'basicConstraints = CA:FALSE' \
    'keyUsage = critical,digitalSignature' 'extendedKeyUsage = serverAuth' \
    'authorityKeyIdentifier = keyid' 'subjectKeyIdentifier = hash' >"$work/pki/server.ext"
openssl x509 -req -in "$work/pki/server.csr" -CA "$work/pki/ca.pem" -CAkey "$work/pki/ca.key" \
    -set_serial 2 -days 2 -extfile "$work/pki/server.ext" -out "$work/pki/server.pem" 2>/dev/null
chmod -R a+rX "$work"

wait "$image_build"
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
    --env SEGL_LIBERATION_SHA256="$liberation" \
    "$container" bash /deploy/debian/systemd-test.sh
