#!/usr/bin/env bash
# ============================================================================
# tunnel_to_processor.sh — open a long-lived SSH tunnel to the M3 processor.
#
#   Usage:
#     ./tunnel_to_processor.sh open  user@processor.host [REMOTE_PORT] [LOCAL_PORT]
#     ./tunnel_to_processor.sh close user@processor.host [LOCAL_PORT]
#     ./tunnel_to_processor.sh status
#
#   Defaults:
#     REMOTE_PORT = 8443  (where the processor's WSGI app listens on its loopback)
#     LOCAL_PORT  = 18000 + (sha256(processor.host) mod 1000)
#                   (deterministic per-host, lets multiple tunnels coexist)
#
#   What 'open' does:
#     ssh -fNT -o ExitOnForwardFailure=yes \
#         -o ServerAliveInterval=30 \
#         -L LOCAL_PORT:127.0.0.1:REMOTE_PORT user@host
#     and writes the SSH PID to /tmp/a81-tunnel-<sha8>.pid
#
#   What 'close' does:
#     reads the PID file and kills the SSH process; removes the PID file.
#
#   Trust model:
#     SSH provides authenticated transport. The processor's WSGI app
#     should bind 127.0.0.1 only — never a public interface — so SSH
#     is the only path in. Verify the host key on first connect; SSH
#     known_hosts pins it for subsequent connections.
#
#   After 'open', point EdgeClient at http://127.0.0.1:LOCAL_PORT:
#     export A81_REMOTE_TRANSPORT=ssh-tunnel
#     export A81_REMOTE_URL=http://127.0.0.1:LOCAL_PORT
# ============================================================================

set -euo pipefail

PIDFILE_DIR="${A81_TUNNEL_DIR:-/tmp}"

# ── helpers ─────────────────────────────────────────────────────
_host_hash() {
  # Stable 8-char hash of the target so we can name PID files per-host.
  printf '%s' "$1" | shasum -a 256 | cut -c1-8
}

_default_local_port() {
  # 18000 + (host_hash % 1000) — deterministic, collision-resistant for typical fleets.
  local hash="$1"
  local n
  n=$(printf '%d' "0x$(printf '%s' "$hash" | cut -c1-4)")
  echo $((18000 + (n % 1000)))
}

_pidfile() {
  echo "$PIDFILE_DIR/a81-tunnel-$(_host_hash "$1").pid"
}

# ── commands ────────────────────────────────────────────────────
cmd_open() {
  local target="${1:-}"
  local remote_port="${2:-8443}"
  local hash; hash="$(_host_hash "$target")"
  local local_port="${3:-$(_default_local_port "$hash")}"

  if [[ -z "$target" ]]; then
    echo "usage: $0 open user@processor.host [REMOTE_PORT] [LOCAL_PORT]" >&2
    exit 64
  fi

  local pidfile; pidfile="$(_pidfile "$target")"
  if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo "tunnel already open: pid=$(cat "$pidfile") local_port=$local_port" >&2
    echo "$local_port"
    return 0
  fi

  # -f  daemonize after auth
  # -N  no remote command
  # -T  no PTY
  # -o ExitOnForwardFailure=yes  fail loudly if the port is taken on the server
  # -o ServerAliveInterval=30    keepalives so a NAT/firewall doesn't silently drop us
  ssh -fNT \
      -o ExitOnForwardFailure=yes \
      -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 \
      -L "${local_port}:127.0.0.1:${remote_port}" \
      "$target"

  # Find the ssh process we just spawned. macOS pgrep doesn't accept all
  # GNU flags; we filter manually.
  local pid
  pid="$(pgrep -f "ssh.*-L ${local_port}:127.0.0.1:${remote_port} ${target}" | head -1 || true)"
  if [[ -z "$pid" ]]; then
    echo "warning: could not locate SSH PID for tunnel; PID file not written" >&2
  else
    echo "$pid" > "$pidfile"
  fi

  echo "tunnel open: ${target} -> 127.0.0.1:${local_port} (remote :${remote_port})  pid=${pid:-?}"
  echo "Set:"
  echo "  export A81_REMOTE_TRANSPORT=ssh-tunnel"
  echo "  export A81_REMOTE_URL=http://127.0.0.1:${local_port}"
  # Print the local port on stdout's last line for scripted callers.
  echo "$local_port"
}

cmd_close() {
  local target="${1:-}"
  if [[ -z "$target" ]]; then
    echo "usage: $0 close user@processor.host" >&2
    exit 64
  fi
  local pidfile; pidfile="$(_pidfile "$target")"
  if [[ ! -f "$pidfile" ]]; then
    echo "no tunnel PID file for $target ($pidfile)" >&2
    return 1
  fi
  local pid; pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "closed tunnel pid=$pid for $target"
  else
    echo "stale PID file (pid=$pid not running); cleaning up"
  fi
  rm -f "$pidfile"
}

cmd_status() {
  shopt -s nullglob
  local found=0
  for f in "$PIDFILE_DIR"/a81-tunnel-*.pid; do
    found=1
    local pid; pid="$(cat "$f")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "alive  $f  pid=$pid"
    else
      echo "stale  $f  pid=$pid"
    fi
  done
  [[ $found -eq 0 ]] && echo "no tunnels recorded under $PIDFILE_DIR"
}

# ── dispatch ────────────────────────────────────────────────────
case "${1:-}" in
  open)   shift; cmd_open  "$@" ;;
  close)  shift; cmd_close "$@" ;;
  status) shift; cmd_status      ;;
  ""|-h|--help)
    sed -n '4,30p' "$0"
    ;;
  *)
    echo "unknown command: $1" >&2
    exit 64
    ;;
esac
