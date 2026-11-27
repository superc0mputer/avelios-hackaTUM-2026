#!/usr/bin/env bash
# Rebuilds the patient from Epic's preset. No MetaHuman assets live in Git.
#   unreal/build.sh            build whatever is missing
#   unreal/build.sh --clean    delete the generated content and rebuild
#   unreal/build.sh --run      build if needed, then open the patient window
# Options: UE_ROOT=<engine folder>  VIP_PRESET=<Epic preset name>
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
project_dir="$here/VIPPatient"
project="$project_dir/VIPPatient.uproject"
content="$project_dir/Content"
logs="$project_dir/Saved/BuildLogs"
UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.8}"
export VIP_PRESET="${VIP_PRESET:-Walter}"

die() { echo "ERROR: $*" >&2; exit 1; }

clean=0 run=0
for arg in "$@"; do
  case "$arg" in
    --clean) clean=1 ;;
    --run) run=1 ;;
    *) die "unknown option $arg" ;;
  esac
done

case "$(uname -s)" in
  Darwin)
    editor="$UE_ROOT/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor" ;;
  *) die "only tested on macOS. On other systems run the three scripts in VIPPatient/Scripts from the editor." ;;
esac
[ -x "$editor" ] || die "Unreal Engine 5.8 not found at '$UE_ROOT' (set UE_ROOT)."
presets="$UE_ROOT/Engine/Plugins/MetaHuman/MetaHumanCharacter/Content/Optional/Presets"
[ -f "$presets/$VIP_PRESET.uasset" ] || die "preset '$VIP_PRESET' not found. Install 'MetaHuman Creator Core Data' via Epic Games Launcher > 5.8 > Options."
[[ "$project" != *" "* ]] || die "move the repository to a path without spaces."

# Unreal limits file paths to 260 characters; the deepest generated asset needs about 120
[ "${#project_dir}" -le 130 ] || die "path too long (${#project_dir} characters). Clone the repository to a shorter path."

[ "$clean" = 1 ] && rm -rf "$content/Patient" "$content/MetaHumans"
mkdir -p "$logs"

stage() {  # stage <script name> <file it must produce>
  local name="$1" output="$2" log="$logs/$1.log"
  if [ -f "$output" ]; then echo "== $name: already built"; return; fi
  echo "== $name: running (several minutes), log: $log"
  "$editor" "$project" -ExecutePythonScript="$project_dir/Scripts/$name.py" \
    -nosplash -unattended -stdout -FullStdOutLogOutput > "$log" 2>&1 || true
  # the editor exits 0 even when a script fails, so check the marker
  if ! grep -q "VIP: STAGE OK" "$log" || [ ! -f "$output" ]; then
    grep -E "VIP:|LogPython: Error" "$log" | tail -15 >&2 || true
    rm -f "$output"
    die "$name failed, see $log"
  fi
  echo "== $name: done"
}

stage build_character "$content/Patient/MHC_Patient.uasset"
stage assemble "$content/MetaHumans/MHC_Patient/Face/SKM_MHC_Patient_FaceMesh.uasset"
stage build_scene "$content/Patient/ConsultationRoom.umap"

echo "Patient ready."
if [ "$run" = 1 ]; then
  "$editor" "$project" -game -windowed -resx=1280 -resy=720 -stdout -FullStdOutLogOutput > "$logs/game.log" 2>&1
else
  echo "Show it:  unreal/build.sh --run"
fi
