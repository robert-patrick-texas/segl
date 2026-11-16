#!/bin/bash
# The update from a real release to this one, as a site would have it. The
# earlier release is installed from its GitHub release and set up as its
# deploy/OPERATOR.md says, with a board and edits of the site's own. Then its
# own `segl update` installs this version: from the signed files before they
# are published, or from GitHub after (docs/RELEASING.md, publish).
# deploy/debian/real-update-test.sh runs this with `docker exec`.
#
# /deploy is the checkout's deploy/ folder. /t holds previous/, the earlier
# release as downloaded, socket_check.py of the earlier release when it has
# one, and new/, this version's package, SHA256SUMS, and SHA256SUMS.sig.
#
#   SEGL_PREVIOUS  the earlier release's version, as in 0.1.0
#   SEGL_VERSION   this version
#   SEGL_FROM      /t/new to install from the signed files there; empty to
#                  take this version from GitHub
#   SEGL_REPO      the GitHub repository, as in owner/segl
set -uo pipefail
# shellcheck source=deploy/debian/testlib.sh
. /deploy/debian/testlib.sh
: "${SEGL_PREVIOUS:?}" "${SEGL_VERSION:?}" "${SEGL_REPO:?}"
SEGL_FROM=${SEGL_FROM:-}

LOCAL=http://127.0.0.1:8888
SITE=https://dev.example.com
CA=/etc/ssl/certs/ssl-cert-snakeoil.pem
TOML=/opt/segl/etc/segl.toml
UPDATE=/opt/segl/update
SITE_PROXY=/etc/nginx/snippets/segl-proxy.conf
# The earlier release draws with its own client, and this one with this.
OLD_CLIENT=/t/socket_check.py
[ -f "$OLD_CLIENT" ] || OLD_CLIENT=/deploy/debian/socket_check.py
NEW_CLIENT=/deploy/debian/socket_check.py

https() { curl -fsS --cacert "$CA" "$@"; }
healthy() {
    for _ in $(seq 30); do
        [ "$(curl -fsS "$LOCAL/api/v1/health" 2>/dev/null)" = '{"status":"ok"}' ] && return 0
        sleep 1
    done
    return 1
}
served() { curl -fsS "$LOCAL/api/v1/version" 2>/dev/null | sed -n 's/.*"version":"\([^"]*\)".*/\1/p'; }
scene() { https "$SITE/board/api/v1/slots/$1/scene"; }
package_version() { dpkg-query -W -f='${Version}' segl; }
update() { segl update "$@" >/tmp/update.log 2>&1; }
said() { contains "$(cat /tmp/update.log)" "$1"; }
nginx_workers() { pgrep -f "nginx: worker process" | tr '\n' ' '; }
gone() {
    local pid alive
    for _ in $(seq 100); do
        alive=0
        for pid in "$@"; do [ -e "/proc/$pid" ] && alive=1; done
        [ "$alive" = 0 ] && return 0
        sleep 0.1
    done
    return 1
}
show() { sed 's/^/      | /' "$@"; }
# Every line of file $1 is in file $2, in the same order. A merge may add
# lines between them.
kept() {
    awk 'BEGIN { n = 0; i = 0 } NR == FNR { want[n++] = $0; next }
        i < n && $0 == want[i] { i++ } END { exit !(i == n) }' "$1" "$2"
}

section "$SEGL_PREVIOUS, installed from its GitHub release"
mkdir -p /tmp/debs && cp "/t/previous/segl_${SEGL_PREVIOUS}_amd64.deb" /tmp/debs/ && chmod 0644 /tmp/debs/*.deb
check "no segl is installed" test ! -e /opt/segl
check "apt has its package lists" apt_get update
check "$SEGL_PREVIOUS installs with apt" apt_get install "/tmp/debs/segl_${SEGL_PREVIOUS}_amd64.deb"
check "segl --version says $SEGL_PREVIOUS" equals "$(segl --version)" "segl $SEGL_PREVIOUS"
check "its settings point segl update at GitHub" grep -q "^update_url = .*$SEGL_REPO" $TOML

section "a site, as $SEGL_PREVIOUS's deploy/OPERATOR.md says"
check "the unit starts" systemctl enable --now segl.service
check "segl answers" healthy
check "Ubuntu makes the snakeoil certificate" make-ssl-cert generate-default-snakeoil --force-overwrite
install -m 644 /opt/segl/share/nginx/segl-http.conf /etc/nginx/conf.d/segl.conf
install -m 644 /opt/segl/share/nginx/segl-proxy.conf $SITE_PROXY
install -m 644 /opt/segl/share/nginx/segl-board.conf /etc/nginx/snippets/segl-board.conf
install -m 644 /opt/segl/share/nginx/site-board.example.conf /etc/nginx/sites-available/dev.example.com
ln -sf ../sites-available/dev.example.com /etc/nginx/sites-enabled/
# The site's own edits, which the update must keep: a setting with a note of
# its own, and a line in an nginx file.
sed -i 's/^history_limit = .*/# This site keeps more revisions.\nhistory_limit = 80/' $TOML
echo "# This site's own line, kept by every update." >>$SITE_PROXY
check "the site's setting is in place" grep -q '^history_limit = 80$' $TOML
check "segl check passes on the site's settings" segl check
check "nginx -t passes" nginx -t
before=$(nginx_workers)
check "nginx reloads" systemctl reload-or-restart nginx
# shellcheck disable=SC2086
check "the old workers are gone" gone $before
check "segl restarts on the site's settings" systemctl restart segl.service
check "and answers" healthy
check "a slot page comes through nginx" contains "$(https "$SITE/board/s/2")" "window.SEGL_CONFIG"
check "a board is drawn over the WebSocket, through nginx" \
    /opt/segl/venv/bin/python3 "$OLD_CLIENT" wss://dev.example.com/board 2 drawn-before-the-update "$CA"
check "slot 2 has it" contains "$(scene 2)" drawn-before-the-update
check "segl serves $SEGL_PREVIOUS" equals "$(served)" "$SEGL_PREVIOUS"
cp $TOML /tmp/segl.toml.before
cp $SITE_PROXY /tmp/segl-proxy.conf.before

if [ -z "$SEGL_FROM" ]; then
    section "segl update --check, against GitHub"
    update --check
    code=$?
    show /tmp/update.log
    check "it exits with 100: a newer release is out" equals "$code" 100
    check "it names $SEGL_VERSION" said "$SEGL_VERSION"
    section "segl update, from $SEGL_PREVIOUS to $SEGL_VERSION, from GitHub"
    started=$(date +%s)
    update --yes
else
    section "segl update, from $SEGL_PREVIOUS to $SEGL_VERSION, from the signed files"
    started=$(date +%s)
    update --yes --from "$SEGL_FROM"
fi
code=$?
show /tmp/update.log
echo "      (segl update took $(($(date +%s) - started)) seconds)"
check "it exits with 0" equals "$code" 0
check "it says what it did" said "$SEGL_PREVIOUS -> $SEGL_VERSION"
check "the package is $SEGL_VERSION" equals "$(package_version)" "$SEGL_VERSION"
check "segl --version says $SEGL_VERSION" equals "$(segl --version)" "segl $SEGL_VERSION"
check "the unit is active" equals "$(systemctl is-active segl.service)" active
check "it is still enabled" equals "$(systemctl is-enabled segl.service)" enabled
check "segl serves $SEGL_VERSION" equals "$(served)" "$SEGL_VERSION"
check "the API answers through nginx" equals "$(https "$SITE/board/api/v1/health")" '{"status":"ok"}'
check "a slot page comes through nginx" contains "$(https "$SITE/board/s/2")" "window.SEGL_CONFIG"
script=$(https "$SITE/board/s/1" | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -n 1)
check "and the script it names" https -o /dev/null "$SITE/board/$script"
check "slot 2 still has the board drawn before the update" \
    contains "$(scene 2)" drawn-before-the-update
check "a board is drawn after the update" \
    /opt/segl/venv/bin/python3 "$NEW_CLIENT" wss://dev.example.com/board 3 drawn-after-the-update "$CA"
check "slot 3 has it" contains "$(scene 3)" drawn-after-the-update
check "the database is still segl's alone" equals "$(mode /opt/segl/var/segl.sqlite)" "640 segl:segl"
check "every line of the site's settings is still there, in order" kept /tmp/segl.toml.before $TOML
check "with the site's setting and its note" grep -B1 -q '^history_limit = 80$' $TOML
check "segl check passes" segl check
check "every line of the site's nginx file is still there, in order" \
    kept /tmp/segl-proxy.conf.before $SITE_PROXY
check "nginx -t passes" nginx -t
check "the update is recorded" grep -q '"result": "updated"' $UPDATE/last-update.json
echo "      what the update changed in the site's settings and nginx file:"
diff /tmp/segl.toml.before $TOML | show
diff /tmp/segl-proxy.conf.before $SITE_PROXY | show

if [ -z "$SEGL_FROM" ]; then
    section "segl update --check, once more"
    update --check
    code=$?
    show /tmp/update.log
    check "it exits with 0: nothing is newer" equals "$code" 0
    section "the nightly update, turned on as the notes say"
    check "the timer turns on" systemctl enable --now segl-update.timer
    check "a run of it now succeeds" systemctl start segl-update.service
    check "segl still serves $SEGL_VERSION" equals "$(served)" "$SEGL_VERSION"
fi

finish real-update
