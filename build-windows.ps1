# MoonLabeler Windows 打包腳本：產生免安裝的 dist\MoonLabeler\MoonLabeler.exe 與對應 zip。
# 用法（在 repo 根目錄）：pwsh -File build-windows.ps1
# 需要 uv；首次執行會建立 .venv 並安裝依賴與 PyInstaller。
# 星曆（JPL DE421 等，約 19 MB）沒快取時會先下載一次，打包後隨 exe 附上，使用者首次啟動不必連網。

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false   # 原生指令的結束碼自己用 $LASTEXITCODE 判斷
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = $PSScriptRoot
Set-Location $repo
$venv = Join-Path $repo ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "建立虛擬環境..."
    uv venv --python 3.12 $venv
}
uv pip install --python $venv -r requirements.txt astropy pyinstaller

# 舊版 OpenCV wheel 連同其內建的媒體解碼器一併移除（與 start-mac.command 相同）。
$legacy = & $python -c "import importlib.metadata as m; names=('opencv-python', 'opencv-contrib-python', 'opencv-python-headless', 'opencv-contrib-python-headless'); installed={d.metadata['Name'].lower() for d in m.distributions()}; print(' '.join(n for n in names if n in installed))"
if ($legacy) { uv pip uninstall --python $venv $legacy.Split(' ') }

# 私有精簡 OpenCV 不在 requirements.txt 裡；缺少時由 setup.py 從原始碼建置
# （需 Visual Studio Build Tools 的「使用 C++ 的桌面開發」，CMake／Ninja 由建置環境自帶）。
& $python -c "from moonlabeler._opencv import cv2; assert hasattr(cv2, 'ximgproc'); assert not hasattr(cv2, 'imread')" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "建置不含影像／影片解碼器的最小 OpenCV（首次約 10–20 分鐘）..."
    uv pip install --python $venv --no-deps .
}

$env:PYTHONUTF8 = "1"
$version = & $python -c "import tomllib, pathlib; print(tomllib.loads(pathlib.Path('pyproject.toml').read_text('utf-8'))['project']['version'])"
Write-Host "MoonLabeler $version"

if (-not (Test-Path ".cache\ephemeris\de421.bsp")) {
    Write-Host "下載 JPL 星曆到 .cache\ephemeris ..."
    New-Item -ItemType Directory -Force ".cache\ephemeris" | Out-Null
    & $python -c "from datetime import datetime, timezone; from pathlib import Path; from moonlabeler.geometry import compute_geometry; compute_geometry(datetime(2026, 1, 1, tzinfo=timezone.utc), Path('.cache/ephemeris'))"
}

New-Item -ItemType Directory -Force "build" | Out-Null
& $python tools\make_icon.py build\moonlabeler.ico

& $python -m PyInstaller --noconfirm --clean MoonLabeler.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失敗（exit $LASTEXITCODE）" }

$zip = Join-Path $repo "dist\MoonLabeler-$version-windows-x64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path (Join-Path $repo "dist\MoonLabeler") -DestinationPath $zip -CompressionLevel Optimal

Write-Host ""
Write-Host "完成：dist\MoonLabeler\MoonLabeler.exe"
Write-Host "壓縮檔：$zip"
