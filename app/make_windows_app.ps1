# Builds the download for judges: one folder (and zip) that runs the whole VIP patient on a
# Windows PC without Unreal, Python or any of our keys. Users enter their own OpenAI and
# ElevenLabs keys on first start.
#
#   powershell -ExecutionPolicy Bypass -File app\make_windows_app.ps1            folder + zip
#   powershell -ExecutionPolicy Bypass -File app\make_windows_app.ps1 -NoZip     folder only
#
# Needs: the packaged patient (unreal\package.ps1) and Python 3.12 on this PC (for pip).
# Output: dist\VIPPatient-Windows\ and dist\VIPPatient-Windows.zip
# The result contains Epic assets: share it privately, never commit or publish it.
param([switch]$NoZip)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Fail($message) { Write-Host "ERROR: $message" -ForegroundColor Red; exit 1 }
function Say($message) { Write-Host "== $message" }

$repo = Split-Path $PSScriptRoot -Parent
$package = Join-Path $repo "unreal\VIPPatient\Saved\Package\Windows"
$dist = Join-Path $repo "dist"
$out = Join-Path $dist "VIPPatient-Windows"
$cache = Join-Path $dist ".cache"
$pyVersion = "3.12.10"
$pyTag = "312"

if (-not (Test-Path (Join-Path $package "VIPPatient.exe"))) {
    Fail "no packaged patient at $package. Run: powershell -ExecutionPolicy Bypass -File unreal\package.ps1"
}

# A full Python of the same version installs the packages for the bundled one
$hostPython = $null
foreach ($candidate in @(
    (Join-Path $repo "engine\.venv\Scripts\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python$pyTag\python.exe"))) {
    if (Test-Path $candidate) { $hostPython = $candidate; break }
}
if (-not $hostPython) { Fail "Python $pyVersion not found (winget install Python.Python.3.12)." }
$hostVersion = (& $hostPython -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ($hostVersion -ne "3.12") { Fail "need Python 3.12 to install packages, found $hostVersion at $hostPython" }

if (Test-Path $out) { Remove-Item -Recurse -Force $out }
New-Item -ItemType Directory -Force $out, $cache | Out-Null

# --- Python (the official embeddable build: no installer, nothing written outside the folder)
$embedZip = Join-Path $cache "python-$pyVersion-embed-amd64.zip"
if (-not (Test-Path $embedZip)) {
    Say "downloading Python $pyVersion (embeddable) from python.org"
    Invoke-WebRequest "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-amd64.zip" -OutFile $embedZip -UseBasicParsing
}
$python = Join-Path $out "runtime\python"
Expand-Archive $embedZip -DestinationPath $python
# The ._pth file is the bundled Python's whole search path (it ignores PYTHONPATH and the user's setup)
Set-Content -Encoding ascii (Join-Path $python "python$pyTag._pth") @"
python$pyTag.zip
.
Lib\site-packages
..\..\app\engine
..\..\app\teacher-ui
import site
"@

Say "installing the engine's packages into the bundled Python"
$site = Join-Path $python "Lib\site-packages"
& $hostPython -m pip install --quiet --disable-pip-version-check --only-binary=:all: --target $site `
    -r (Join-Path $repo "engine\requirements.txt") -r (Join-Path $repo "teacher-ui\requirements.txt")
if ($LASTEXITCODE) { Fail "pip install failed" }

# --- our code (no .env, no virtual environment, no tests)
Say "copying the engine, the page and the cases"
$app = Join-Path $out "app"
New-Item -ItemType Directory -Force (Join-Path $app "engine"), (Join-Path $app "teacher-ui"), (Join-Path $app "cases") | Out-Null
Copy-Item (Join-Path $repo "engine\*.py") (Join-Path $app "engine")
foreach ($folder in "prompts", "data") {
    Copy-Item -Recurse (Join-Path $repo "engine\$folder") (Join-Path $app "engine\$folder")
}
Copy-Item (Join-Path $repo "teacher-ui\server.py") (Join-Path $app "teacher-ui")
Copy-Item -Recurse (Join-Path $repo "teacher-ui\static") (Join-Path $app "teacher-ui\static")
Copy-Item (Join-Path $repo "cases\*.json") (Join-Path $app "cases")
Copy-Item (Join-Path $PSScriptRoot "launcher.py") $app
# the app's look: the website on top of the patient
New-Item -ItemType Directory -Force (Join-Path $app "hud") | Out-Null
foreach ($file in "page_server.py", "hud.css", "hud.js") { Copy-Item (Join-Path $PSScriptRoot "hud\$file") (Join-Path $app "hud") }
Get-ChildItem $app -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# --- the patient window and Microsoft's C++ runtime installer (redistributable)
Say "copying the patient window (about 2.5 GB)"
robocopy $package (Join-Path $out "Patient") /E /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Fail "copying the patient failed (robocopy $LASTEXITCODE)" }
$ueRoot = $env:UE_ROOT
if (-not $ueRoot) { $ueRoot = Join-Path $env:ProgramFiles "Epic Games\UE_5.8" }
$redist = Join-Path $ueRoot "Engine\Extras\Redist\en-us\vc_redist.x64.exe"
if (Test-Path $redist) {
    New-Item -ItemType Directory -Force (Join-Path $out "redist") | Out-Null
    Copy-Item $redist (Join-Path $out "redist")
} else {
    Write-Host "note: vc_redist.x64.exe not found (set `$env:UE_ROOT); PCs without the C++ runtime will need it"
}

# --- the app itself: one .exe with its own window, built with the C# compiler that comes with Windows.
# It shows the page with WebView2 (part of Windows); Microsoft's SDK for it is downloaded once and
# checked against a fixed checksum.
$webViewVersion = "1.0.4370.26"
$webViewHash = "1C0DACAC84B70109B3FD42F90C53A0BA942ABC3A87590D7A4E0CCD86E4A06CF4"
$webViewZip = Join-Path $cache "microsoft.web.webview2.$webViewVersion.zip"
if (-not (Test-Path $webViewZip)) {
    Say "downloading the WebView2 SDK $webViewVersion from nuget.org"
    Invoke-WebRequest "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$webViewVersion/microsoft.web.webview2.$webViewVersion.nupkg" -OutFile $webViewZip -UseBasicParsing
}
if ((Get-FileHash $webViewZip -Algorithm SHA256).Hash -ne $webViewHash) { Fail "unexpected content in $webViewZip; delete it and try again" }
$webView = Join-Path $cache "webview2-$webViewVersion"
if (-not (Test-Path $webView)) { Expand-Archive $webViewZip -DestinationPath $webView }
foreach ($file in "lib\net462\Microsoft.Web.WebView2.Core.dll", "lib\net462\Microsoft.Web.WebView2.WinForms.dll",
                  "runtimes\win-x64\native\WebView2Loader.dll") {
    Copy-Item (Join-Path $webView $file) $out
}
Copy-Item (Join-Path $webView "LICENSE.txt") (Join-Path $out "WebView2-LICENSE.txt")

Say "building Start VIP Patient.exe"
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $csc)) { Fail "C# compiler not found at $csc (.NET Framework 4 is part of Windows 10 and 11)" }
# Same icon as the patient
Add-Type -AssemblyName System.Drawing
$icon = Join-Path $cache "VIPPatient.ico"
$iconStream = [System.IO.File]::Create($icon)
[System.Drawing.Icon]::ExtractAssociatedIcon((Join-Path $out "Patient\VIPPatient.exe")).Save($iconStream)
$iconStream.Close()
& $csc /nologo /optimize /target:winexe /platform:x64 "/win32icon:$icon" `
    "/win32manifest:$(Join-Path $PSScriptRoot 'StartVIPPatient.manifest')" "/out:$(Join-Path $out 'Start VIP Patient.exe')" `
    /r:System.Windows.Forms.dll /r:System.Drawing.dll `
    "/r:$(Join-Path $out 'Microsoft.Web.WebView2.Core.dll')" "/r:$(Join-Path $out 'Microsoft.Web.WebView2.WinForms.dll')" `
    (Join-Path $PSScriptRoot "StartVIPPatient.cs")
if ($LASTEXITCODE) { Fail "building Start VIP Patient.exe failed" }
Copy-Item (Join-Path $PSScriptRoot "README.txt") $out

# Check that the bundled Python finds everything before shipping it (without starting a server)
$env:VOICE_SERVER_NO_AUTOLOAD = "1"
& (Join-Path $python "python.exe") -c "import fastapi, uvicorn, openai, jsonschema, voice_server, keystore, eleven_agent; print('bundled Python OK')"
$importCode = $LASTEXITCODE
Remove-Item Env:VOICE_SERVER_NO_AUTOLOAD
if ($importCode) { Fail "the bundled Python cannot import the engine" }

$size = (Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1GB
Say ("folder ready: {0} ({1:N1} GB)" -f $out, $size)

if (-not $NoZip) {
    $zip = "$out.zip"
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Say "zipping (several minutes)"
    # Windows' own tar writes zip64, which large files need
    Push-Location $dist
    tar.exe -a -c -f (Split-Path $zip -Leaf) (Split-Path $out -Leaf)
    $code = $LASTEXITCODE
    Pop-Location
    if ($code) { Fail "zipping failed" }
    Say ("zip ready: {0} ({1:N1} GB)" -f $zip, ((Get-Item $zip).Length / 1GB))
}
