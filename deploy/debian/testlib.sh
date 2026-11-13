# Helpers for the package test inside the container, in the form of
# Sunstone's packaging/container/testlib.sh. Sourced, not run. Each check
# prints PASS or FAIL. A failure is counted and the run goes on, so one run
# reports every problem.
# shellcheck shell=bash

export DEBIAN_FRONTEND=noninteractive
failures=0
checks=0

pass() { printf 'PASS  %s\n' "$*"; }
fail() {
    printf 'FAIL  %s\n' "$*"
    failures=$((failures + 1))
}
check() {
    local what=$1
    shift
    checks=$((checks + 1))
    if "$@" >/dev/null 2>&1; then pass "$what"; else fail "$what"; fi
}
section() { printf '\n== %s\n' "$*"; }
equals() { [ "$1" = "$2" ]; }
contains() { case $1 in *"$2"*) return 0 ;; *) return 1 ;; esac; }
lacks() { ! contains "$1" "$2"; }
mode() { stat -c '%a %U:%G' "$1"; }

apt_get() {
    # apt's own progress is noise. Show it only when apt fails.
    if ! apt-get -o Dpkg::Use-Pty=0 -y "$@" >/tmp/apt.log 2>&1; then
        cat /tmp/apt.log
        return 1
    fi
}

finish() {
    section "summary"
    if [ "$failures" -gt 0 ]; then
        echo "$1: $failures of $checks checks FAILED"
        exit 1
    fi
    echo "$1: all $checks checks passed"
}
