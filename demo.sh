#!/usr/bin/env bash
# The whole demo on one machine, with one command:
#   voice server + teacher page (localhost) + tunnel for ElevenLabs + the Unreal patient.
#
#   ./demo.sh              everything; opens the teacher page
#   ./demo.sh --no-unreal  without the MetaHuman (the voice then plays in the browser)
#
# Needs engine/.env with OPENAI_API_KEY, ENGINE_API_KEY, ELEVENLABS_API_KEY and
# ELEVENLABS_AGENT_ID (see engine/.env.example), and for the MetaHuman a built patient
# (unreal/build.sh; set UE_ROOT if Unreal is not in the default place).
# Ctrl+C stops everything. Logs: .demo/logs/
set -euo pipefail

root="$(cd "$(dirname "$0")" && pwd)"
logs="$root/.demo/logs"
tools="$root/.demo/tools"
env_file="$root/engine/.env"
venv="$root/engine/.venv"
# The teacher page expects the voice server on 8787 (teacher-ui/static/app.js)
VOICE_PORT=8787
PAGE_PORT=8765
CLOUDFLARED_VERSION=2026.11.2

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "== $*"; }

unreal=1
for arg in "$@"; do
  case "$arg" in
    --no-unreal) unreal=0 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) die "unknown option $arg (try --help)" ;;
  esac
done
[ "$(uname -s)" = Darwin ] || [ "$unreal" = 0 ] || die "the MetaHuman runs on macOS only here; use --no-unreal"

# --- keys -------------------------------------------------------------------------
[ -f "$env_file" ] || die "engine/.env is missing: cp engine/.env.example engine/.env and fill in the keys"
env_value() { grep -E "^$1=" "$env_file" | tail -1 | cut -d= -f2- | tr -d '"'"'"' \r' || true; }
for name in OPENAI_API_KEY ENGINE_API_KEY ELEVENLABS_API_KEY ELEVENLABS_AGENT_ID; do
  # ENGINE_API_KEY is required: the tunnel is public, and without it anyone could use the OpenAI key
  [ -n "$(env_value "$name")" ] || die "$name is not set in engine/.env"
done

# --- MetaHumans built? (building them takes long and needs an Epic sign-in) ----------
if [ "$unreal" = 1 ]; then
  content="$root/unreal/VIPPatient/Content"
  # Same files unreal/build.sh checks for each patient in patients.json
  presets="$(python3 -c 'import json, sys; print(" ".join(p["preset"] for p in json.load(open(sys.argv[1]))["patients"]))' \
    "$root/unreal/VIPPatient/Scripts/patients.json")" || die "cannot read unreal/VIPPatient/Scripts/patients.json"
  missing=""
  for preset in $presets; do
    [ -f "$content/Patient/Characters/MHC_$preset.uasset" ] \
      && [ -f "$content/MetaHumans/MHC_$preset/Face/SKM_MHC_${preset}_FaceMesh.uasset" ] || missing="$missing $preset"
  done
  [ -z "$missing" ] || die "these MetaHumans are not built yet:$missing.
  Build them once from a Terminal on this Mac: unreal/build.sh  (about 10 minutes per patient;
  Epic may ask you to sign in). Or start without the MetaHuman: ./demo.sh --no-unreal"
fi

# --- ports ------------------------------------------------------------------------
port_free() { ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
for port in "$VOICE_PORT" "$PAGE_PORT"; do
  port_free "$port" || die "port $port is already in use (an earlier demo still running?)"
done

# --- Python environment -----------------------------------------------------------
mkdir -p "$logs" "$tools"
if [ ! -x "$venv/bin/python" ]; then
  say "creating the Python environment (first run only)"
  # Resolve symlinks first: a venv made through a link to a uv-managed Python cannot find
  # the standard library ("No module named 'encodings'")
  python="$(python3 -c 'import os, sys; print(os.path.realpath(sys.executable)) if sys.version_info >= (3, 10) else None')" \
    || die "python3 not found; install Python 3.10 or newer"
  [ -n "$python" ] || die "python3 is older than 3.10; install a newer Python"
  "$python" -m venv "$venv" || { rm -rf "$venv"; die "creating $venv failed"; }
fi
requirements="$root/engine/requirements.txt $root/teacher-ui/requirements.txt"
stamp="$venv/.demo-requirements"
# shellcheck disable=SC2086
if ! cat $requirements | cmp -s - "$stamp"; then
  say "installing Python packages"
  # shellcheck disable=SC2086
  "$venv/bin/pip" install -q $(printf -- '-r %s ' $requirements) > "$logs/pip.log" 2>&1 \
    || die "pip install failed, see $logs/pip.log"
  # shellcheck disable=SC2086
  cat $requirements > "$stamp"
fi

# --- cloudflared ------------------------------------------------------------------
cloudflared="$(command -v cloudflared || true)"
if [ -z "$cloudflared" ]; then
  cloudflared="$tools/cloudflared"
  if [ ! -x "$cloudflared" ]; then
    say "downloading cloudflared $CLOUDFLARED_VERSION"
    base="https://github.com/cloudflare/cloudflared/releases/download/$CLOUDFLARED_VERSION"
    case "$(uname -s)-$(uname -m)" in
      Darwin-arm64) curl -fsSL "$base/cloudflared-darwin-arm64.tgz" | tar -xz -C "$tools" ;;
      Darwin-x86_64) curl -fsSL "$base/cloudflared-darwin-amd64.tgz" | tar -xz -C "$tools" ;;
      Linux-x86_64) curl -fsSL -o "$cloudflared" "$base/cloudflared-linux-amd64" ;;
      Linux-aarch64) curl -fsSL -o "$cloudflared" "$base/cloudflared-linux-arm64" ;;
      *) die "no cloudflared download for $(uname -sm); install it yourself" ;;
    esac
    chmod +x "$cloudflared"
  fi
fi

# --- start everything -------------------------------------------------------------
pids=""
servers=""
cleanup() {
  trap - EXIT INT TERM
  echo
  say "stopping"
  for pid in $pids; do
    pkill -TERM -P "$pid" 2>/dev/null || true   # children, e.g. the Unreal editor under build.sh
    kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM

wait_for() {  # wait_for <seconds> <description> <command...>
  local seconds="$1" what="$2"; shift 2
  local i
  for i in $(seq "$seconds"); do
    "$@" > /dev/null 2>&1 && return 0
    sleep 1
  done
  die "$what did not come up, see $logs/"
}

say "voice server on 127.0.0.1:$VOICE_PORT"
(cd "$root/engine" && exec "$venv/bin/uvicorn" voice_server:app --host 127.0.0.1 --port "$VOICE_PORT") \
  > "$logs/voice_server.log" 2>&1 &
pids="$pids $!"
servers="$servers $!"
wait_for 30 "the voice server" curl -fs "http://127.0.0.1:$VOICE_PORT/health"

say "teacher page on http://localhost:$PAGE_PORT"
(cd "$root/teacher-ui" && TEACHER_UI_HOST=127.0.0.1 TEACHER_UI_PORT="$PAGE_PORT" \
  VOICE_SERVER_URL="http://127.0.0.1:$VOICE_PORT" exec "$venv/bin/python" server.py) \
  > "$logs/teacher_ui.log" 2>&1 &
pids="$pids $!"
servers="$servers $!"
wait_for 15 "the teacher page" curl -fs "http://127.0.0.1:$PAGE_PORT/"

say "public tunnel for ElevenLabs"
"$cloudflared" tunnel --no-autoupdate --url "http://127.0.0.1:$VOICE_PORT" > "$logs/tunnel.log" 2>&1 &
pids="$pids $!"
servers="$servers $!"
tunnel_url() { grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$logs/tunnel.log" | head -1; }
has_tunnel_url() { [ -n "$(tunnel_url)" ]; }
wait_for 30 "the tunnel address" has_tunnel_url
url="$(tunnel_url)"
tunnel_registered() { grep -q "Registered tunnel connection" "$logs/tunnel.log"; }
wait_for 30 "the tunnel connection" tunnel_registered
# A new quick-tunnel name takes a few seconds to appear in DNS. Ask Cloudflare's resolver
# directly: the system resolver caches the early "no such name" answer for minutes.
doh=""
curl --help all 2>/dev/null | grep -q -- --doh-url && doh="--doh-url https://1.1.1.1/dns-query"
# shellcheck disable=SC2086
tunnel_up() { curl -fs --max-time 5 $doh "$url/health"; }
wait_for 60 "the tunnel ($url)" tunnel_up
"$venv/bin/python" "$root/engine/point_agent.py" "$url/v1"

if [ "$unreal" = 1 ]; then
  say "MetaHuman patient (log: $logs/unreal.log)"
  VIP_SERVER="ws://127.0.0.1:$VOICE_PORT/ws/unreal" "$root/unreal/build.sh" --run > "$logs/unreal.log" 2>&1 &
  pids="$pids $!"
  unreal_pid=$!
fi

page="http://localhost:$PAGE_PORT"
if command -v open > /dev/null; then open "$page"; elif command -v xdg-open > /dev/null; then xdg-open "$page" || true; fi
echo
echo "Ready: $page  (Ctrl+C stops everything)"
[ "$unreal" = 1 ] && echo "The patient window opens in about a minute; the page mutes itself once it is connected."

# Stay up until Ctrl+C or a server dies. Closing the Unreal window keeps the servers running.
while true; do
  for pid in $servers; do
    kill -0 "$pid" 2>/dev/null || die "a server stopped unexpectedly, see $logs/"
  done
  if [ "$unreal" = 1 ] && [ -n "${unreal_pid:-}" ] && ! kill -0 "$unreal_pid" 2>/dev/null; then
    grep -q "Patient ready" "$logs/unreal.log" || echo "The patient did not start, see $logs/unreal.log"
    echo "The patient window is closed; the servers keep running (Ctrl+C stops them)."
    unreal_pid=""
  fi
  sleep 2
done
