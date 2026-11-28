#!/usr/bin/env bash
# Packages the patient as a standalone macOS app that runs without Unreal installed.
#   unreal/package.sh        build what is missing, then package
# Output: unreal/VIPPatient/Saved/Package/Mac/VIPPatient.app (contains Epic assets: never publish it)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
project_dir="$here/VIPPatient"
UE_ROOT="${UE_ROOT:-/Users/Shared/Epic Games/UE_5.8}"
log="$project_dir/Saved/BuildLogs/package.log"

"$here/build.sh"

echo "== packaging (about 10 minutes the first time), log: $log"
"$UE_ROOT/Engine/Build/BatchFiles/RunUAT.sh" BuildCookRun -project="$project_dir/VIPPatient.uproject" \
  -noP4 -utf8output -platform=Mac -clientconfig=Development -build -cook \
  -map=/Game/Patient/ConsultationRoom -stage -pak -package -archive \
  -archivedirectory="$project_dir/Saved/Package" > "$log" 2>&1 || true
if ! grep -q "BUILD SUCCESSFUL" "$log"; then
  grep -E "Error:|error:" "$log" | tail -15 >&2 || true
  echo "ERROR: packaging failed, see $log" >&2
  exit 1
fi
echo "Packaged: $project_dir/Saved/Package/Mac/VIPPatient.app"
