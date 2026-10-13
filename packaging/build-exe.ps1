[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$Console
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildRoot = Join-Path $projectRoot 'packaging\_build'
$venv = Join-Path $buildRoot 'venv'
$python = Join-Path $venv 'Scripts\python.exe'
$output = Join-Path $projectRoot 'release'
$specPath = Join-Path $buildRoot ("spec-" + [guid]::NewGuid().ToString('N'))
$uiMode = if ($Console) { '--console' } else { '--windowed' }

if ($Clean -and (Test-Path -LiteralPath $buildRoot)) {
    Remove-Item -LiteralPath $buildRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $buildRoot, $output | Out-Null

if (-not (Test-Path -LiteralPath $python)) {
    py -3.14 -m venv $venv
}

# This isolated environment deliberately leaves the project's .venv untouched.
# Do not force an index lookup on every build.  The first run installs these;
# subsequent offline rebuilds reuse the isolated environment.
& $python -m pip install --disable-pip-version-check pyinstaller numpy opencv-python av pillow

Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --clean --onefile $uiMode `
        --name 'SRT-Whiteboard-Animation' `
        --paths (Join-Path $projectRoot 'scripts') `
        --add-data "$(Join-Path $projectRoot 'assets');assets" `
        --add-data "$(Join-Path $projectRoot 'scripts');scripts" `
        --collect-all av `
        --collect-all cv2 `
        --hidden-import render_stream_whiteboard `
        --hidden-import stream_render `
        --hidden-import merge_scenes `
        --distpath $output `
        --workpath (Join-Path $buildRoot 'work') `
        --specpath $specPath `
        'scripts\desktop_entry.py'
}
finally {
    Pop-Location
}

$exe = Join-Path $output 'SRT-Whiteboard-Animation.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw 'Build did not produce the EXE.' }
Get-FileHash -Algorithm SHA256 -LiteralPath $exe
Write-Host "EXE ready: $exe"
