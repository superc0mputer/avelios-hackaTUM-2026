#!/usr/bin/env bash
# Rebuilds the patient from Epic's preset. No MetaHuman assets live in Git.
#   unreal/build.sh            build whatever is missing
#   unreal/build.sh --clean    delete the generated content and rebuild
#   unreal/build.sh --run      build if needed, then open the patient window
#   unreal/package.sh          standalone app for people without Unreal
# Patients: unreal/VIPPatient/Scripts/patients.json. Option: UE_ROOT=<engine folder>
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
project_dir="$here/VIPPatient"
project="$project_dir/VIPPatient.uproject"
content="$project_dir/Content"
logs="$project_dir/Saved/BuildLogs"
UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.8}"

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
  MINGW*|MSYS*|CYGWIN*) die "on Windows use unreal\\build.ps1 in PowerShell." ;;
  *) die "only macOS and Windows (build.ps1) are supported." ;;
esac
[ -x "$editor" ] || die "Unreal Engine 5.8 not found at '$UE_ROOT' (set UE_ROOT)."
presets="$UE_ROOT/Engine/Plugins/MetaHuman/MetaHumanCharacter/Content/Optional/Presets"
patients=$(python3 -c 'import json,sys; print(" ".join(p["preset"] for p in json.load(open(sys.argv[1]))["patients"]))' \
  "$project_dir/Scripts/patients.json") || die "cannot read Scripts/patients.json"
for preset in $patients; do
  [ -f "$presets/$preset.uasset" ] || die "preset '$preset' not found. Install 'MetaHuman Creator Core Data' via Epic Games Launcher > 5.8 > Options."
done
[[ "$project" != *" "* ]] || die "move the repository to a path without spaces."

# Unreal limits file paths to 260 characters; the deepest generated asset needs about 120
[ "${#project_dir}" -le 130 ] || die "path too long (${#project_dir} characters). Clone the repository to a shorter path."

[ "$clean" = 1 ] && rm -rf "$content/Patient" "$content/MetaHumans"
mkdir -p "$logs"

stage() {  # stage <script name> <file it must produce> [log name]
  local name="$1" output="$2" log="$logs/${3:-$1}.log"
  if [ -f "$output" ]; then echo "== ${3:-$1}: already built"; return; fi
  echo "== ${3:-$1}: running (several minutes), log: $log"
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

echo "== compiling the C++ module (Source/VIPPatient)"
"$UE_ROOT/Engine/Build/BatchFiles/Mac/Build.sh" VIPPatientEditor Mac Development -project="$project" -waitmutex \
  > "$logs/compile.log" 2>&1 || die "compile failed, see $logs/compile.log"

for preset in $patients; do
  export VIP_PRESET="$preset"
  stage build_character "$content/Patient/Characters/MHC_$preset.uasset" "build_character_$preset"
  stage assemble "$content/MetaHumans/MHC_$preset/Face/SKM_MHC_${preset}_FaceMesh.uasset" "assemble_$preset"
done
# the room and patient table list every patient, so rebuild them when patients.json changes
[ "$project_dir/Scripts/patients.json" -nt "$content/Patient/ConsultationRoom.umap" ] && rm -f "$content/Patient/ConsultationRoom.umap"
stage build_scene "$content/Patient/ConsultationRoom.umap"

echo "Patient ready."
if [ "$run" = 1 ]; then
  "$editor" "$project" -game -windowed -resx=1280 -resy=720 -stdout -FullStdOutLogOutput > "$logs/game.log" 2>&1
else
  echo "Show it:  unreal/build.sh --run"
fi
