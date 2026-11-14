#!/bin/bash
# Put /opt/segl together and package it with nfpm, inside the clean builder
# container, in the form of Sunstone's packaging/container/build.sh.
# deploy/debian/build-deb.sh runs it. Do not run it on a host: it installs
# into /opt/segl.
#
# Inputs: /in/source.tar (the tree to build), and:
#   SEGL_VERSION        project.version in versions.toml, e.g. 0.1.0
#   SOURCE_DATE_EPOCH   the commit's time; every packaged file gets it
#   HOST_UID, HOST_GID  owner of the file written to /out
# Output: /out/segl_<version>_amd64.deb
set -euo pipefail

: "${SEGL_VERSION:?}" "${SOURCE_DATE_EPOCH:?}"
export SOURCE_DATE_EPOCH
# One hash seed, so bytecode is the same from build to build, and no stray
# __pycache__ while segl itself runs below. Bytecode is compiled once, last.
export PYTHONHASHSEED=0 PYTHONDONTWRITEBYTECODE=1
export UV_PYTHON_INSTALL_DIR=/build/python UV_NO_PROGRESS=1 UV_LINK_MODE=copy
export npm_config_update_notifier=false

OPT=/opt/segl
PY=$OPT/python/bin/python3
VENV=$OPT/venv
SRC=/build/src
DOC=/build/doc
DEB=/build/out/segl_${SEGL_VERSION}_amd64.deb
PYVER="" # .python-version, e.g. 3.15.2
PYMM=""  # its first two numbers, e.g. 3.15

log() { printf '==> %s\n' "$*"; }
die() {
    printf 'build.sh: %s\n' "$*" >&2
    exit 1
}

unpack_source() {
    mkdir -p "$SRC" /build/out "$OPT" "$DOC"
    tar -xf /in/source.tar -C "$SRC"
    cd "$SRC"
    PYVER=$(tr -d '[:space:]' <.python-version)
    [[ $PYVER =~ ^3\.[0-9]+\.[0-9]+$ ]] ||
        die ".python-version must be an exact version, not '$PYVER'"
    PYMM=${PYVER%.*}
}

install_python() {
    # uv installs python-build-standalone's CPython and checks its checksum.
    log "installing Python $PYVER"
    uv python install --no-bin "$PYVER"
    local found
    found=$(uv python find --managed-python "$PYVER")
    mv "$(dirname "$(dirname "$(readlink -f "$found")")")" "$OPT/python"
    local lib=$OPT/python/lib stdlib=$OPT/python/lib/python$PYMM
    # Tk and IDLE need a display. Headers, the config folder, *-config,
    # pydoc, and libpython serve building and embedding, and every wheel
    # here is binary. The base interpreter's pip goes too, so a package can
    # enter through the virtualenv alone.
    rm -rf "$stdlib"/{idlelib,tkinter,turtledemo,turtle.py} "$stdlib"/lib-dynload/_tkinter.* \
        "$lib"/{tcl,tk,itcl,thread}* "$lib"/lib{tcl,tk}* "$lib/pkgconfig" "$lib"/libpython3* \
        "$stdlib"/config-"$PYMM"-* "$OPT/python/include" "$stdlib"/site-packages/pip* \
        "$OPT/python/bin"/{idle,pip,pydoc}* "$OPT/python/bin"/python*-config
    [ "$("$PY" --version)" = "Python $PYVER" ] || die "$PY is not Python $PYVER"
    # debian/copyright names this file for the interpreter's license.
    [ -s "$stdlib/LICENSE.txt" ] || die "$stdlib/LICENSE.txt is missing"
}

install_venv() {
    log "creating $VENV from uv.lock, with the segl wheel"
    "$PY" -m venv --without-pip "$VENV"
    # A relative link keeps the virtualenv whole wherever /opt/segl is
    # looked at: lintian, an unpacked package. The .gitignore is noise here.
    ln -sfn ../../python/bin/python3 "$VENV/bin/python3"
    rm -f "$VENV/.gitignore"
    # What segl needs to run: no development group, and not segl itself.
    uv export --frozen --no-default-groups --no-emit-project --quiet \
        --format requirements.txt -o /build/requirements.txt
    # The build backend and its own dependencies, the `build` group.
    uv export --frozen --only-group build --no-emit-project --quiet \
        --format requirements.txt -o /build/build-constraints.txt
    # Wheels only, each checked against its hash in uv.lock.
    uv pip install --python "$VENV/bin/python3" --require-hashes --only-binary :all: \
        --no-deps -r /build/requirements.txt
    uv build --wheel --python "$PY" --out-dir /build/wheel \
        --build-constraints /build/build-constraints.txt --require-hashes .
    # --no-cache: a cached wheel of the same name must not stand in for
    # this build's code.
    uv pip install --python "$VENV/bin/python3" --no-deps --no-cache /build/wheel/segl-*.whl
    # uv's own record of the install holds the time, which would make two
    # builds of one commit differ.
    local info
    info=$(echo "$VENV"/lib/python"$PYMM"/site-packages/segl-*.dist-info)
    rm -f "$info/uv_cache.json" "$VENV/.lock"
    sed -i '/\/uv_cache\.json,/d' "$info/RECORD"
}

check_python_licenses() {
    # debian/copyright says each package's license text is in its
    # dist-info/licenses folder. Hold that to what was installed.
    local info missing=""
    for info in "$VENV"/lib/python"$PYMM"/site-packages/*.dist-info; do
        [ -n "$(ls -A "$info/licenses" 2>/dev/null)" ] || missing="$missing $(basename "$info")"
    done
    [ -z "$missing" ] || die "no license text in:$missing"
}

install_web() {
    # The locked packages, with no package's install script run, then the
    # production build. The built files are packaged. Node is not.
    log "building the web application (npm ci --ignore-scripts, npm run build)"
    (
        cd web
        npm ci --ignore-scripts --no-audit --no-fund
        npm run build
        # The license text of every npm package in the build, and of every
        # font. It fails when one has none.
        node scripts/collect-licenses.ts "$DOC/web-licenses" "$DOC/font-licenses"
    )
    mkdir -p "$OPT/app/web"
    cp -R web/dist "$OPT/app/web/dist"
}

install_share() {
    local share=$OPT/share
    install -D -m 0644 -t "$share/nginx" deploy/nginx/*.conf
    install -D -m 0644 deploy/segl.toml.example "$share/segl.toml.example"
    install -D -m 0644 deploy/display-names.txt "$share/display-names.txt"
    # The keys `segl update` trusts a release by.
    install -D -m 0644 deploy/release-signers "$share/release-signers"
    install -D -m 0644 -t "$DOC" deploy/OPERATOR.md LICENSE NOTICE
    write_debian_changelog
}

write_debian_changelog() {
    # Debian policy wants a changelog in its own format. It points at
    # CHANGELOG.md, which stays the one record.
    local maintainer
    maintainer=$(sed -n 's/^maintainer: //p' deploy/debian/nfpm.yaml)
    printf '%s\n' "segl ($SEGL_VERSION) unstable; urgency=medium" "" \
        "  * Release $SEGL_VERSION. The changes are in" \
        "    https://github.com/robert-patrick-texas/segl/blob/main/CHANGELOG.md" "" \
        " -- $maintainer  $(date -u -R -d "@$SOURCE_DATE_EPOCH")" |
        gzip -9 --no-name >/build/changelog.gz
}

smoke_test() {
    # Every extension module and wheel left after the pruning must load.
    log "smoke test: import every extension module and the runtime packages"
    "$VENV/bin/python3" - <<'PY'
import importlib, pathlib, sys
version = f"python{sys.version_info.major}.{sys.version_info.minor}"
dynload = pathlib.Path(sys.base_exec_prefix, "lib", version, "lib-dynload")
names = sorted(p.name.split(".")[0] for p in dynload.glob("*.so"))
assert names, f"no extension modules found in {dynload}"
# Most extensions are built into the interpreter. These cover its static libraries.
builtin = ["ssl", "sqlite3", "ctypes", "zlib", "bz2", "lzma", "decimal", "hashlib"]
wheels = ["pydantic_core._pydantic_core", "websockets.speedups", "uvicorn", "segl.cli"]
for name in [*names, *builtin, *wheels]:
    importlib.import_module(name)
assert sys.base_prefix == "/opt/segl/python", sys.base_prefix
print(f"imported {len(names) + len(builtin) + len(wheels)} modules on Python {sys.version}")
PY
    # The installed package reads its own copy of versions.toml.
    local said
    said=$("$VENV/bin/segl" --version)
    [ "$said" = "segl $SEGL_VERSION" ] || die "the installed segl says '$said', not $SEGL_VERSION"
}

normalize_tree() {
    log "compiling bytecode, and setting modes and times"
    find "$OPT" -name __pycache__ -type d -prune -exec rm -rf {} +
    # A .pyc checked by hash stays good whatever its source's time is, so
    # the times set below cannot make Python write one again at run time.
    # One process, in sorted order: files spread over workers differ from
    # build to build.
    "$PY" -m compileall -q -j 1 --invalidation-mode checked-hash \
        "$OPT/python/lib/python$PYMM" "$VENV/lib/python$PYMM/site-packages"
    chmod -R u+rwX,go+rX,go-w "$OPT" "$DOC"
    # A document is not a program. One npm package ships its license 0755.
    find "$DOC" -type f -exec chmod 0644 {} +
    # A shared library is mapped and never run. dpkg and lintian expect 0644.
    find "$OPT" -type f \( -name '*.so' -o -name '*.so.*' \) -exec chmod a-x {} +
    find "$OPT" "$DOC" /build/changelog.gz \
        -exec touch --no-dereference --date="@$SOURCE_DATE_EPOCH" {} +
}

check_glibc_floor() {
    # The package says libc6 (>= floor). Nothing in it may need a newer one.
    local floor newest
    floor=$(sed -n 's/.*- libc6 (>= \([0-9.]*\)).*/\1/p' deploy/debian/nfpm.yaml)
    [ -n "$floor" ] || die "deploy/debian/nfpm.yaml names no libc6 floor"
    # readelf fails on the many files that are not ELF. Only its output counts.
    newest=$({ find "$OPT" -type f -exec readelf -V --wide {} + 2>/dev/null || true; } |
        grep -oE 'Name: GLIBC_[0-9.]+' | sed 's/Name: GLIBC_//' | sort -uV | tail -n 1)
    [ -n "$newest" ] || die "found no ELF file that needs glibc; is readelf installed?"
    log "newest glibc symbol version needed: $newest (floor in nfpm.yaml: $floor)"
    dpkg --compare-versions "$newest" le "$floor" || die "raise the libc6 floor in nfpm.yaml"
}

verify_unit() {
    log "systemd-analyze verify"
    local out
    out=$(systemd-analyze verify --man=no --recursive-errors=no \
        "$SRC/deploy/systemd/segl.service" "$SRC/deploy/systemd/segl-update.service" \
        "$SRC/deploy/systemd/segl-update.timer" 2>&1) || die "systemd-analyze verify failed: $out"
    [ -z "$out" ] || die "systemd-analyze verify said: $out"
}

package_and_lint() {
    log "nfpm package -> $(basename "$DEB")"
    SEGL_DEB_VERSION=$SEGL_VERSION nfpm package --config deploy/debian/nfpm.yaml \
        --packager deb --target "$DEB"
    log "lintian"
    # lintian warns when root runs it. It only needs to read the package.
    runuser -u nobody -- env HOME=/tmp lintian --fail-on error --tag-display-limit 0 "$DEB"
    cp "$DEB" /out/
    chown "${HOST_UID:-0}:${HOST_GID:-0}" /out/"$(basename "$DEB")"
    log "built $(basename "$DEB") ($(du -h "$DEB" | cut -f1))"
}

unpack_source
install_python
install_venv
check_python_licenses
install_web
install_share
smoke_test
normalize_tree
check_glibc_floor
verify_unit
package_and_lint
