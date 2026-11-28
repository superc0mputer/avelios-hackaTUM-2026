# Windows version of package.sh. NEVER run or syntax-checked yet.
# Packages the patient as a standalone Windows app that runs without Unreal installed.
#   powershell -ExecutionPolicy Bypass -File unreal\package.ps1
# Output: unreal\VIPPatient\Saved\Package\Windows (contains Epic assets: never publish it)
$ErrorActionPreference = "Stop"

$projectDir = Join-Path $PSScriptRoot "VIPPatient"
$log = Join-Path $projectDir "Saved\BuildLogs\package.log"

& (Join-Path $PSScriptRoot "build.ps1")
if ($LASTEXITCODE) { exit $LASTEXITCODE }

$ueRoot = $env:UE_ROOT
if (-not $ueRoot) {
    $key = "HKLM:\SOFTWARE\EpicGames\Unreal Engine\5.8"
    if (Test-Path $key) { $ueRoot = (Get-ItemProperty $key).InstalledDirectory }
}
if (-not $ueRoot) { $ueRoot = Join-Path $env:ProgramFiles "Epic Games\UE_5.8" }

Write-Host "== packaging (several minutes), log: $log"
$uat = Join-Path $ueRoot "Engine\Build\BatchFiles\RunUAT.bat"
& $uat BuildCookRun "-project=$(Join-Path $projectDir 'VIPPatient.uproject')" -noP4 -utf8output `
    -platform=Win64 -clientconfig=Development -build -cook -map=/Game/Patient/ConsultationRoom `
    -stage -pak -package -archive "-archivedirectory=$(Join-Path $projectDir 'Saved\Package')" *> $log
if (-not (Select-String -Path $log -SimpleMatch "BUILD SUCCESSFUL" -Quiet)) {
    Select-String -Path $log -Pattern "Error:|error " | Select-Object -Last 15 | ForEach-Object { Write-Host $_.Line }
    Write-Host "ERROR: packaging failed, see $log" -ForegroundColor Red
    exit 1
}
Write-Host "Packaged: $(Join-Path $projectDir 'Saved\Package\Windows')"
