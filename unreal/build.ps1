# Windows version of build.sh. Rebuilds the patient from Epic's preset.
#   unreal\build.ps1            build whatever is missing
#   unreal\build.ps1 -Clean     delete the generated content and rebuild
#   unreal\build.ps1 -Run       build if needed, then open the patient window
# Patients: unreal\VIPPatient\Scripts\patients.json. Option: $env:UE_ROOT = engine folder
param(
    [switch]$Clean,
    [switch]$Run
)
$ErrorActionPreference = "Stop"

function Fail($message) {
    Write-Host "ERROR: $message" -ForegroundColor Red
    exit 1
}

$projectDir = Join-Path $PSScriptRoot "VIPPatient"
$project = Join-Path $projectDir "VIPPatient.uproject"
$content = Join-Path $projectDir "Content"
$logs = Join-Path $projectDir "Saved\BuildLogs"

$ueRoot = $env:UE_ROOT
if (-not $ueRoot) {
    # the Epic Games Launcher records the install folder in the registry
    $key = "HKLM:\SOFTWARE\EpicGames\Unreal Engine\5.8"
    if (Test-Path $key) { $ueRoot = (Get-ItemProperty $key).InstalledDirectory }
}
if (-not $ueRoot) { $ueRoot = Join-Path $env:ProgramFiles "Epic Games\UE_5.8" }

$editorCmd = Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$editorGui = Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor.exe"
if (-not (Test-Path $editorCmd)) {
    Fail "Unreal Engine 5.8 not found at '$ueRoot' (set `$env:UE_ROOT)."
}

$patientList = Join-Path $projectDir "Scripts\patients.json"
$patients = (Get-Content -Raw $patientList | ConvertFrom-Json).patients | ForEach-Object { $_.preset }
foreach ($name in $patients) {
    $preset = Join-Path $ueRoot "Engine\Plugins\MetaHuman\MetaHumanCharacter\Content\Optional\Presets\$name.uasset"
    if (-not (Test-Path $preset)) {
        Fail "preset '$name' not found. Install 'MetaHuman Creator Core Data' via Epic Games Launcher > 5.8 > Options."
    }
}

if ($project.Contains(" ")) { Fail "move the repository to a path without spaces." }

# Unreal limits file paths to 260 characters; the deepest generated asset needs about 120
if ($projectDir.Length -gt 130) {
    Fail "path too long ($($projectDir.Length) characters). Clone the repository to a shorter path, e.g. C:\dev."
}

if ($Clean) {
    foreach ($folder in "Patient", "MetaHumans") {
        $path = Join-Path $content $folder
        if (Test-Path $path) { Remove-Item -Recurse -Force $path }
    }
}
New-Item -ItemType Directory -Force $logs | Out-Null

function Invoke-Stage($name, $relativeOutput, $logName = $name) {
    $output = Join-Path $content $relativeOutput
    $log = Join-Path $logs "$logName.log"
    if (Test-Path $output) {
        Write-Host "== ${logName}: already built"
        return
    }
    Write-Host "== ${logName}: running (several minutes), log: $log"
    if (Test-Path $log) { Remove-Item -Force $log }
    $script = Join-Path $projectDir "Scripts\$name.py"
    & $editorCmd $project "-ExecutePythonScript=$script" "-abslog=$log" -nosplash -unattended | Out-Null

    # the editor can exit successfully even when a script fails, so check the marker
    $ok = (Test-Path $log) -and (Select-String -Path $log -SimpleMatch "VIP: STAGE OK" -Quiet)
    if (-not ($ok -and (Test-Path $output))) {
        if (Test-Path $log) {
            Select-String -Path $log -Pattern "VIP:|LogPython: Error" |
                Select-Object -Last 15 | ForEach-Object { Write-Host $_.Line }
        }
        if (Test-Path $output) { Remove-Item -Force $output }
        Fail "$name failed, see $log"
    }
    Write-Host "== ${logName}: done"
}

# our C++ module (Source/VIPPatient) needs Visual Studio 2022 with "Game development with C++"
Write-Host "== compiling the C++ module"
$compileLog = Join-Path $logs "compile.log"
& (Join-Path $ueRoot "Engine\Build\BatchFiles\Build.bat") VIPPatientEditor Win64 Development "-project=$project" -waitmutex *> $compileLog
if ($LASTEXITCODE) { Fail "compile failed, see $compileLog" }

foreach ($name in $patients) {
    $env:VIP_PRESET = $name
    Invoke-Stage "build_character" "Patient\Characters\MHC_$name.uasset" "build_character_$name"
    Invoke-Stage "assemble" "MetaHumans\MHC_$name\Face\SKM_MHC_${name}_FaceMesh.uasset" "assemble_$name"
}
# the room and patient table list every patient, so rebuild them when patients.json changes
$room = Join-Path $content "Patient\ConsultationRoom.umap"
if ((Test-Path $room) -and ((Get-Item $patientList).LastWriteTime -gt (Get-Item $room).LastWriteTime)) {
    Remove-Item -Force $room
}
Invoke-Stage "build_scene" "Patient\ConsultationRoom.umap"

Write-Host "Patient ready."
if ($Run) {
    $serverArg = @()
    if ($env:VIP_SERVER) { $serverArg = @("-VIPServer=$($env:VIP_SERVER)") }
    & $editorGui $project -game -windowed -resx=1280 -resy=720 @serverArg
} else {
    Write-Host "Show it:  unreal\build.ps1 -Run"
}
