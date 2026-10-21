# MoonLabeler Windows 打包腳本：產生免安裝的 dist\MoonLabeler\MoonLabeler.exe 與對應 zip。
# 用法（在 repo 根目錄）：pwsh -File build-windows.ps1
# 需要 uv；首次執行會建立 .venv 並安裝依賴與 PyInstaller。
# 星曆（JPL DE421 等，約 19 MB）沒快取時會先下載一次，打包後隨 exe 附上，使用者首次啟動不必連網。

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$repo = $PSScriptRoot
Set-Location $repo
$venv = Join-Path $repo ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "建立虛擬環境..."
    uv venv --python 3.12 $venv
    uv pip install --python $venv -r requirements.txt astropy
}
uv pip install --python $venv pyinstaller

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
