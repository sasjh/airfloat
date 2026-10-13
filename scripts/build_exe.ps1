# 打包 AirFloat 为 Windows 免安装版（onedir）。
#
# 为什么要用脚本而不是直接 pyinstaller：
#   如果 PATH 里恰好有别的程序附带的 icuuc.dll（例如某些运行时的 poppler），
#   PyInstaller 会把它打进 _internal\ 根层，而那份 ICU 与 PySide6 的 Qt6Core
#   符号对不上，exe 一启动就报：
#     DLL load failed while importing QtWidgets: 找不到指定的程序。
#   脚本先把 PATH 里的「外来 ICU」剔掉再打包，最后校验产物干净。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1 -DeployTo "C:\Users\zyh\Desktop\AirFloat程序"

param(
    [string]$DeployTo = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1) 清理 PATH：剔掉「自带 icuuc.dll 且不在系统目录下」的目录
$kept = @()
$dropped = @()
foreach ($p in ($env:PATH -split ';')) {
    if (-not $p) { continue }
    $hasOwnIcu = (Test-Path (Join-Path $p 'icuuc.dll')) -and
                 (-not $p.StartsWith($env:SystemRoot, [StringComparison]::OrdinalIgnoreCase))
    if ($hasOwnIcu) { $dropped += $p } else { $kept += $p }
}
if ($dropped.Count -gt 0) {
    Write-Host "已从 PATH 剔除会污染打包的目录：" -ForegroundColor Yellow
    $dropped | ForEach-Object { Write-Host "  $_" }
}
$env:PATH = ($kept -join ';')

# 2) 打包
Write-Host "开始打包 ..." -ForegroundColor Cyan
pyinstaller --clean --noconfirm --windowed --onedir --name AirFloat `
    --collect-all pillow_heif --collect-all PIL --paths src_py src_py/main.py
if ($LASTEXITCODE -ne 0) { throw "pyinstaller 失败，exit=$LASTEXITCODE" }

# 3) 校验：_internal 根层不得出现外来 ICU（会让 Qt6Core 加载失败）
$out = Join-Path $root 'dist\AirFloat'
$stray = Get-ChildItem (Join-Path $out '_internal') -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^(icuuc|icuin|icudt.*)\.dll$' } |
    Where-Object { $_.Name -notlike '*.pyd' }
if ($stray) {
    $stray | ForEach-Object { Write-Host "  发现外来 ICU：$($_.Name) ($($_.VersionInfo.FileVersion))" -ForegroundColor Red }
    throw "打包被污染：_internal 里出现了 icuuc/icudt，exe 会启动失败。请检查 PATH 后重试。"
}
Write-Host "校验通过：_internal 无外来 ICU。" -ForegroundColor Green

# 4) 可选：部署到指定目录（镜像覆盖，保留目标里的 AirFloat数据）
if ($DeployTo) {
    New-Item -ItemType Directory -Force -Path $DeployTo | Out-Null
    robocopy $out $DeployTo /MIR /XD (Join-Path $DeployTo 'AirFloat数据') /NFL /NDL /NP /NJH | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy 失败，exit=$LASTEXITCODE" }
    Write-Host "已部署到：$DeployTo" -ForegroundColor Green
}

Write-Host "打包完成：$out\AirFloat.exe" -ForegroundColor Green
