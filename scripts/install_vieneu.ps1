$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$envPath = Join-Path $root '.venv-vtts'
$python = Join-Path $envPath 'Scripts\python.exe'

if (-not (Test-Path $python)) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Cần cài Python 3.10–3.13 x64 để thiết lập VieNeu-TTS.' }
    $basePython = $null
    foreach ($version in @('3.13', '3.12', '3.11', '3.10')) {
        $candidate = & py "-$version" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path $candidate)) { $basePython = "$candidate".Trim(); break }
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

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Không cập nhật được pip.' }
# CPU-only: install the inference core, not VieNeu's optional Gradio demo UI.
# This keeps the app environment smaller; Preview Desk already supplies its UI.
& $python -m pip install --upgrade --no-deps vieneu
if ($LASTEXITCODE -ne 0) { throw 'Cài VieNeu-TTS thất bại. Kiểm tra kết nối mạng rồi chạy lại.' }
& $python -m pip install --upgrade sea-g2p onnxruntime numpy soundfile soxr kaldi-native-fbank tokenizers huggingface_hub PyYAML
if ($LASTEXITCODE -ne 0) { throw 'Không cài được các phụ thuộc CPU/ONNX của VieNeu-TTS.' }
& $python -c "from vieneu import Vieneu; print('VieNeu-TTS CPU import OK')"
if ($LASTEXITCODE -ne 0) { throw 'VieNeu-TTS đã cài nhưng không thể import; kiểm tra lỗi phụ thuộc.' }
Write-Host 'Hoàn tất VieNeu-TTS (CPU/ONNX). Lần tạo audio đầu tiên sẽ tải model về máy.' -ForegroundColor Green
