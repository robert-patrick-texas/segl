#!/bin/bash
# Install the package on a clean Ubuntu 26.04 that booted with systemd, put
# nginx in front of it as deploy/OPERATOR.md says, and use it
# (docs/TEST-PLAN.md T-017). Then upgrade, remove, and purge it.
# deploy/debian/package-test.sh runs this with `docker exec`.
#
# /deploy is the checkout's deploy/ folder. /releases holds two packages:
# release/ has the one under test, and upgrade/ has the same package under a
# higher version, for the upgrade. The machine's host name is dev.example.com,
# the name in site-board.example.conf, so the snakeoil certificate Ubuntu
# makes is for that name and curl can check it.
#
#   SEGL_VERSION   the version the package must report
#   SEGL_PYTHON    the Python it must carry, .python-version
#   SEGL_LIBERATION_SHA256
#                  the Liberation Sans it must carry, the checkout's
#                  web/fonts/Liberation/LiberationSans-Regular.woff2
set -uo pipefail
# shellcheck source=deploy/debian/testlib.sh
. /deploy/debian/testlib.sh
: "${SEGL_VERSION:?}" "${SEGL_PYTHON:?}" "${SEGL_LIBERATION_SHA256:?}"

LOCAL=http://127.0.0.1:8888
SITE=https://dev.example.com
CA=/etc/ssl/certs/ssl-cert-snakeoil.pem
TOML=/opt/segl/etc/segl.toml
CODE="Maple River 42"
SECRET="package-test-secret-0123456789-abcdef"

https() { curl -fsS --cacert "$CA" "$@"; }
healthy() {
    # segl answers on its own port within half a minute.
    for _ in $(seq 30); do
        [ "$(curl -fsS "$LOCAL/api/v1/health" 2>/dev/null)" = '{"status":"ok"}' ] && return 0
        sleep 1
    done
    return 1
}
main_pid() { systemctl show -p MainPID --value segl.service; }
restart() {
    # The unit allows five starts in a minute, and this test starts segl
    # more often than a person would. So each restart forgets the earlier ones.
    systemctl reset-failed segl.service 2>/dev/null
    systemctl restart segl.service
}
fingerprint() { openssl x509 -noout -fingerprint -sha256 2>/dev/null; }
nginx_workers() { pgrep -f "nginx: worker process" | tr '\n' ' '; }
gone() {
    # The processes named are gone within ten seconds.
    local pid alive
    for _ in $(seq 100); do
        alive=0
        for pid in "$@"; do [ -e "/proc/$pid" ] && alive=1; done
        [ "$alive" = 0 ] && return 0
        sleep 0.1
    done
    return 1
}
journal() { journalctl -u segl.service --no-pager -o cat; }
as_segl() { setpriv --reuid=segl --regid=segl --clear-groups "$@"; }
scene() { https "$SITE/board/api/v1/slots/$1/scene"; }
installed() { [ "$(dpkg-query -W -f='${Status}' segl 2>/dev/null)" = "install ok installed" ]; }

section "a clean machine"
check "it is Ubuntu 26.04" grep -q 'VERSION_ID="26.04"' /etc/os-release
check "systemd is PID 1" test -d /run/systemd/system
check "it has no Python of its own" test -z "$(command -v python3 python)"
check "no segl is installed" test ! -e /opt/segl

section "install"
# apt's sandbox user must be able to read the package.
mkdir -p /tmp/debs && cp /releases/release/*.deb /releases/upgrade/*.deb /tmp/debs/ && chmod 0644 /tmp/debs/*.deb
check "the package installs with apt" apt_get install "/tmp/debs/segl_${SEGL_VERSION}_amd64.deb"
check "the interpreter is under /opt/segl/python, at the pin" \
    equals "$(/opt/segl/python/bin/python3 --version)" "Python $SEGL_PYTHON"
check "the virtualenv runs that interpreter" \
    equals "$(/opt/segl/venv/bin/python3 -c 'import sys; print(sys.base_prefix)')" /opt/segl/python
check "segl --version says $SEGL_VERSION, from the versions.toml in its package" \
    equals "$(/opt/segl/venv/bin/segl --version)" "segl $SEGL_VERSION"
check "the web application is in /opt/segl/app/web/dist" test -s /opt/segl/app/web/dist/index.html
check "user segl exists, with no shell and home /opt/segl" \
    equals "$(getent passwd segl | cut -d: -f6,7)" "/opt/segl:/usr/sbin/nologin"
check "the settings are created, for root and segl's group alone" \
    equals "$(mode $TOML)" "640 root:segl"
check "they are the example file" cmp $TOML /deploy/segl.toml.example
check "the display names are created" equals "$(mode /opt/segl/etc/display-names.txt)" "644 root:root"
check "they are the packaged list" cmp /opt/segl/etc/display-names.txt /deploy/display-names.txt
check "/opt/segl/etc is root's" equals "$(mode /opt/segl/etc)" "755 root:root"
check "/opt/segl/var is segl's alone" equals "$(mode /opt/segl/var)" "750 segl:segl"
for file in /deploy/nginx/*.conf; do
    check "share/nginx has $(basename "$file")" cmp "$file" "/opt/segl/share/nginx/$(basename "$file")"
done
check "the operator notes are in the documentation folder" \
    cmp /usr/share/doc/segl/OPERATOR.md /deploy/OPERATOR.md
check "so are LICENSE and NOTICE" test -s /usr/share/doc/segl/LICENSE -a -s /usr/share/doc/segl/NOTICE
check "the copyright file names Apache-2.0" grep -q '^License: Apache-2.0$' /usr/share/doc/segl/copyright
DOC=/usr/share/doc/segl
check "the license texts of the bundled npm packages are there, with their list" \
    test -s $DOC/web-licenses/PACKAGES.txt -a -n "$(ls $DOC/web-licenses | grep '^react@')"
check "every package in that list has a folder with a text in it" \
    test "$(find $DOC/web-licenses -mindepth 2 -type f -size +0 -printf '%h\n' | sort -u | wc -l)" \
    = "$(grep -c -E '^\S+ [0-9]' $DOC/web-licenses/PACKAGES.txt)"
check "every font of the canvas has its license text" \
    equals "$(ls $DOC/font-licenses)" "$(ls /opt/segl/app/web/dist/fonts)"
check "Liberation Sans is the file segl ships, not the editor's" equals "$SEGL_LIBERATION_SHA256" \
    "$(sha256sum /opt/segl/app/web/dist/fonts/Liberation/LiberationSans-Regular.woff2 | cut -d' ' -f1)"
check "its license text is the Open Font License, and no other" \
    equals "$(ls $DOC/font-licenses/Liberation)" OFL.txt
check "no font license in the package is the GNU General Public License" \
    bash -c "! grep -r -l 'GNU GENERAL PUBLIC LICENSE' $DOC/font-licenses"
check "every Python package in the virtualenv has its license text" \
    bash -c 'for d in /opt/segl/venv/lib/python3.*/site-packages/*.dist-info; do [ -n "$(ls -A "$d/licenses")" ] || exit 1; done'
check "the interpreter's license is where the copyright file says" \
    bash -c 'test -s /opt/segl/python/lib/python3.*/LICENSE.txt'
check "nothing is enabled on install" equals "$(systemctl is-enabled segl.service)" disabled
check "nothing is started on install" test "$(systemctl is-active segl.service)" != active
check "segl cannot write its program" \
    test -z "$(as_segl find /opt/segl/python /opt/segl/venv /opt/segl/app /opt/segl/etc -writable -print -quit)"

section "the unit"
check "the unit starts, as the operator notes say" systemctl enable --now segl.service
check "segl answers on 127.0.0.1:8888" healthy
check "the unit is active" equals "$(systemctl is-active segl.service)" active
check "it is enabled for the next boot" equals "$(systemctl is-enabled segl.service)" enabled
pid=$(main_pid)
check "it runs as segl" equals "$(ps -o user= -p "$pid")" segl
check "it runs the interpreter in /opt/segl/python" \
    contains "$(readlink "/proc/$pid/exe")" /opt/segl/python/bin/python3
check "it does not answer on the machine's own address" \
    bash -c "! curl -s --max-time 3 http://$(hostname -i | cut -d' ' -f1):8888/api/v1/health"
check "the database is segl's, and nobody else reads it" \
    equals "$(mode /opt/segl/var/segl.sqlite)" "640 segl:segl"
check "the nine slots are there" contains "$(curl -fsS $LOCAL/api/v1/slots/9)" "Workspace 9"

section "nginx, as deploy/OPERATOR.md says, with the snakeoil certificate"
check "Ubuntu makes the snakeoil certificate for this machine" \
    make-ssl-cert generate-default-snakeoil --force-overwrite
install -m 644 /opt/segl/share/nginx/segl-http.conf /etc/nginx/conf.d/segl.conf
install -m 644 /opt/segl/share/nginx/segl-proxy.conf /etc/nginx/snippets/segl-proxy.conf
install -m 644 /opt/segl/share/nginx/segl-board.conf /etc/nginx/snippets/segl-board.conf
install -m 644 /opt/segl/share/nginx/site-board.example.conf /etc/nginx/sites-available/dev.example.com
ln -sf ../sites-available/dev.example.com /etc/nginx/sites-enabled/
check "nginx -t passes" nginx -t
before_reload=$(nginx_workers)
check "nginx reloads" systemctl reload-or-restart nginx
# A reload returns before it is done. Until the workers of the old
# configuration exit, one of them can still answer on port 80, and it knows
# only the default site: a 404 where the new site sends a 301.
# shellcheck disable=SC2086
check "the workers from before the reload are gone" gone $before_reload
page=$(https "$SITE/board/s/1")
check "nginx proxies a TLS request to a slot page" contains "$page" "window.SEGL_CONFIG"
check "the certificate nginx shows is that snakeoil certificate" equals \
    "$(openssl s_client -connect dev.example.com:443 -servername dev.example.com </dev/null 2>/dev/null | fingerprint)" \
    "$(fingerprint <$CA)"
check "it is for this machine's name" \
    contains "$(openssl x509 -noout -subject <$CA)" "dev.example.com"
check "the page is the web application, told that its root is one level up" contains "$page" '"root": "../"'
script=$(printf '%s' "$page" | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -n 1)
check "the page names its script" test -n "$script"
check "the script comes through nginx" https -o /dev/null "$SITE/board/$script"
check "so does a font of the canvas" https -o /dev/null "$SITE/board/fonts/Virgil/Virgil-Regular.woff2"
check "/board goes to /board/" \
    equals "$(https -o /dev/null -w '%{http_code} %{redirect_url}' "$SITE/board")" "301 $SITE/board/"
check "the API answers through nginx" equals "$(https "$SITE/board/api/v1/health")" '{"status":"ok"}'
headers=$(https -D - -o /dev/null "$SITE/board/s/1")
check "the site's HSTS header is on the page" contains "${headers,,}" "strict-transport-security: max-age=31536000"
check "no cookie is set" lacks "${headers,,}" "set-cookie"
check "plain HTTP only sends the browser to HTTPS" \
    equals "$(curl -sS -o /dev/null -w '%{http_code} %{redirect_url}' http://dev.example.com/board/s/1)" \
    "301 $SITE/board/s/1"

section "a board, drawn through nginx with the package's own Python"
check "an element drawn over the WebSocket is saved" \
    /opt/segl/venv/bin/python3 /deploy/debian/socket_check.py wss://dev.example.com/board 2 package-test-1 "$CA"
check "the slot has it" contains "$(scene 2)" package-test-1
check "segl restarts" restart
check "and answers again" healthy
check "the slot still has it" contains "$(scene 2)" package-test-1
check "slot 1 does not" lacks "$(scene 1)" package-test-1

section "a setting segl cannot use"
cp -p $TOML /tmp/segl.toml.good
echo 'base_path = "/board"' >>$TOML
restart 2>/dev/null
sleep 2
check "segl does not start" equals "$(systemctl is-active segl.service)" failed
check "the journal names the key" contains "$(journal)" "base_path"
check "systemd does not start it again" equals "$(systemctl show -p NRestarts --value segl.service)" 0
cp -p /tmp/segl.toml.good $TOML
check "with the file put right, segl starts" restart
check "and answers" healthy

section "access codes, in a file only root and segl's group read"
sed -i "s|^access_codes = .*|access_codes = [\"$CODE\"]|; s|^access_secret = .*|access_secret = \"$SECRET\"|" $TOML
check "the file kept its mode" equals "$(mode $TOML)" "640 root:segl"
check "segl restarts with codes" restart
check "and answers" healthy
check "editing now needs a code" equals "$(https "$SITE/board/api/v1/config")" '{"editRequired":true}'
check "without a pass the WebSocket check may not edit" \
    bash -c "/opt/segl/venv/bin/python3 /deploy/debian/socket_check.py wss://dev.example.com/board 2 package-test-2 $CA 2>&1 | grep -q 'may not edit'"
answer=$(https -X POST -H 'Content-Type: application/json' -H "Origin: $SITE" \
    -d '{"code": "maple.river.42"}' "$SITE/board/api/v1/access")
check "the code, typed another way, buys a pass" contains "$answer" '"pass"'
check "the journal has neither the code nor the secret" \
    bash -c "! journalctl -u segl.service --no-pager -o cat | grep -i -e 'maple' -e '$SECRET'"
cp -p /tmp/segl.toml.good $TOML
restart
check "with no codes again, segl answers" healthy

section "upgrade"
echo "# a line the site added" >>$TOML
before=$(sha256sum $TOML /opt/segl/etc/display-names.txt)
pid=$(main_pid)
systemctl reset-failed segl.service
check "the newer package installs over the old one" \
    apt_get install "/tmp/debs/segl_${SEGL_VERSION}+upgrade_amd64.deb"
check "dpkg has the new version" \
    equals "$(dpkg-query -W -f='${Version}' segl)" "${SEGL_VERSION}+upgrade"
check "segl answers" healthy
check "it was restarted" test "$(main_pid)" != "$pid"
check "it is still enabled" equals "$(systemctl is-enabled segl.service)" enabled
check "the settings and the display names are untouched" \
    equals "$(sha256sum $TOML /opt/segl/etc/display-names.txt)" "$before"
check "the board is still there" contains "$(scene 2)" package-test-1
check "every packaged file is as dpkg installed it" test -z "$(dpkg --verify segl)"

section "stop"
check "segl stops" systemctl stop segl.service
check "the stop was clean" equals "$(systemctl show -p Result --value segl.service)" success
check "it left the database closed: no write-ahead log beside it" \
    test -z "$(ls /opt/segl/var | grep -v -x -e segl.sqlite -e assets)"
restart
check "it starts again" healthy

section "remove and purge"
check "the package removes" apt_get remove segl
check "segl is stopped" test "$(systemctl is-active segl.service)" != active
check "the program is gone" test ! -e /opt/segl/python -a ! -e /opt/segl/venv -a ! -e /opt/segl/app
check "the unit is gone" test ! -e /usr/lib/systemd/system/segl.service
check "the settings are kept" test -s $TOML
check "the boards are kept" test -s /opt/segl/var/segl.sqlite
apt-get -o Dpkg::Use-Pty=0 -y purge segl >/tmp/purge.log 2>&1
status=$?
check "the package purges" equals "$status" 0
check "purge removes the settings" test ! -e /opt/segl/etc
check "purge removes the link that enabled the unit" \
    test ! -e /etc/systemd/system/multi-user.target.wants/segl.service
check "purge keeps the boards, and says so" \
    test -s /opt/segl/var/segl.sqlite -a -n "$(grep 'kept the boards' /tmp/purge.log)"
check "user segl stays, so the boards keep an owner" \
    equals "$(stat -c %U /opt/segl/var/segl.sqlite)" segl
check "the package installs again over what was kept" \
    apt_get install "/tmp/debs/segl_${SEGL_VERSION}_amd64.deb"
restart
check "it starts" healthy
check "and serves the board that was kept" contains "$(scene 2)" package-test-1

finish "systemd-test"
