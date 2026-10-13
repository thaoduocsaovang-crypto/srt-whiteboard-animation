$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root '.venv-kokoro'
$python = Join-Path $envPath 'Scripts\python.exe'
$sourcePath = Join-Path $root '.kokoro-vietnamese-source'
$revision = 'a249afe5555aec6c435165c2f61ec0f71284812f'

if (-not (Test-Path $python)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Cần cài Python 3.10+ x64 để thiết lập Kokoro-Vietnamese.' }
    # Prefer versions that have stable PyTorch Windows wheels.  `py -0p`
    # marks the default interpreter with `*`, so do not parse its columns.
    $basePython = $null
    foreach ($version in @('3.12', '3.11', '3.13', '3.10')) {
        $candidate = & py "-$version" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path $candidate)) {
            $basePython = "$candidate".Trim()
            break
        }
    }
    if (-not $basePython) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Không có Python 3.10–3.13 x64 và Windows không có winget để tự cài.' }
        & winget install --exact --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $basePython = & py '-3.12' -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $basePython) { throw 'Không thể tự cài Python 3.12 x64.' }
        $basePython = "$basePython".Trim()
    }
    & $basePython -m venv $envPath
}

if (-not (Test-Path $python)) { throw 'Không tạo được môi trường Python cho Kokoro-Vietnamese.' }
if (-not (Test-Path (Join-Path $sourcePath '.git'))) {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) { throw 'Không có Git và Windows không có winget để tự cài.' }
        & winget install --exact --id Git.Git --silent --accept-package-agreements --accept-source-agreements
        $env:Path += ';' + (Join-Path ${env:ProgramFiles} 'Git\cmd')
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Không thể tự cài Git.' }
    }
    & git clone --depth 1 https://github.com/iamdinhthuan/Kokoro-Vietnamese.git $sourcePath
    if ($LASTEXITCODE -ne 0) { throw 'Không tải được mã nguồn Kokoro-Vietnamese từ GitHub.' }
}
& git -C $sourcePath fetch --depth 1 origin $revision
if ($LASTEXITCODE -ne 0) { throw 'Không tải được bản Kokoro-Vietnamese đã ghim.' }
& git -C $sourcePath checkout --detach $revision
if ($LASTEXITCODE -ne 0) { throw 'Không thể ghim Kokoro-Vietnamese về phiên bản đã kiểm tra.' }

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Không cập nhật được pip.' }
& $python -m pip install --upgrade 'transformers>=4.48,<5'
if ($LASTEXITCODE -ne 0) { throw 'Không cài được transformers phù hợp.' }
& $python -m pip install -e $sourcePath
if ($LASTEXITCODE -ne 0) { throw 'Cài Kokoro-Vietnamese thất bại. Xem log phía trên, kiểm tra kết nối rồi chạy lại.' }
& $python -c "from kokoro_vietnamese import KokoroVietnamese, list_voices; print('Kokoro-Vietnamese import OK:', ', '.join(list_voices()))"
if ($LASTEXITCODE -ne 0) { throw 'Kokoro-Vietnamese đã cài nhưng không thể import; kiểm tra lỗi phụ thuộc.' }
Write-Host 'Hoàn tất. Lần đầu tạo audio, Kokoro-Vietnamese sẽ tải model từ Hugging Face.' -ForegroundColor Green
