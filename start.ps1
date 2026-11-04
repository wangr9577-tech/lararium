$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $PSScriptRoot

$env:KRUSKAL_HOST = "127.0.0.1"
$env:KRUSKAL_LOCAL_NO_PASSWORD = "1"
$env:KRUSKAL_PORT = "18080"
$env:PYTHONIOENCODING = "utf-8"

$pyBin = "$PSScriptRoot\venv\Scripts\python.exe"
if (-not (Test-Path $pyBin)) {
    $pyBin = "python"
}

Write-Host "===================================================" -ForegroundColor Cyan
Write-Host "  正在启动 Kruskal 本地服务..." -ForegroundColor Green
Write-Host "  访问地址: http://127.0.0.1:$($env:KRUSKAL_PORT)" -ForegroundColor Yellow
Write-Host "  数据目录: $PSScriptRoot\backend\data" -ForegroundColor Gray
Write-Host "===================================================" -ForegroundColor Cyan

# 异步延迟 2 秒打开默认浏览器
Start-Job -ScriptBlock {
    Start-Sleep -Seconds 2
    Start-Process "http://127.0.0.1:18080"
} | Out-Null

& $pyBin -m uvicorn app.main:app --app-dir backend --host $env:KRUSKAL_HOST --port $env:KRUSKAL_PORT
