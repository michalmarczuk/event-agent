#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project_root=$(CDPATH= cd -- "$script_dir/../.." && pwd)
cd "$project_root"

if [ -z "${TAILSCALE_AUTHKEY:-}" ]; then
    echo "TAILSCALE_AUTHKEY is required" >&2
    exit 1
fi

if [ -z "${TAILSCALE_EXIT_NODE:-}" ]; then
    echo "TAILSCALE_EXIT_NODE is required" >&2
    exit 1
fi

runtime_dir=$(mktemp -d /tmp/event-agent-tailscale.XXXXXX)
tailscale_socket="$runtime_dir/tailscaled.sock"
auth_file="$runtime_dir/authkey"

umask 077
# Userspace networking keeps the production container independent of a kernel
# TUN device while routing browser traffic through the configured exit node.
# The scraper consumes this local SOCKS5 endpoint; API clients keep their
# normal network path unless they are explicitly configured otherwise.
printf '%s' "$TAILSCALE_AUTHKEY" > "$auth_file"
unset TAILSCALE_AUTHKEY

tailscaled \
    --tun=userspace-networking \
    --socks5-server=127.0.0.1:1055 \
    --state=mem: \
    --socket="$tailscale_socket" &
tailscaled_pid=$!

cleanup() {
    rm -f "$auth_file"
    if kill -0 "$tailscaled_pid" 2>/dev/null; then
        kill "$tailscaled_pid" 2>/dev/null || true
        wait "$tailscaled_pid" 2>/dev/null || true
    fi
    rm -rf "$runtime_dir"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

attempt=0
while [ ! -S "$tailscale_socket" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 10 ] || ! kill -0 "$tailscaled_pid" 2>/dev/null; then
        echo "tailscaled failed to become ready" >&2
        exit 1
    fi
    sleep 1
done

echo "Connecting to Tailscale..."
tailscale --socket="$tailscale_socket" up \
    --auth-key="file:$auth_file" \
    --exit-node="$TAILSCALE_EXIT_NODE" \
    --timeout=30s

echo "Tailscale connected"

rm -f "$auth_file"

export SCRAPER_PROXY_URL=socks5://127.0.0.1:1055

echo "Starting event agent..."

# HF production uses the same application entrypoint as the image CMD; the
# wrapper only adds Tailscale/SOCKS setup and a virtual display for Camoufox.
xvfb-run -a -e /dev/stderr \
    python -u -m src.app.daily

echo "Event agent finished"
