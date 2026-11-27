# 执行一个 .sql 文件到数据平台的 MySQL
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\run_sql.ps1 sql\dwd\ddl.sql
#   powershell -ExecutionPolicy Bypass -File scripts\run_sql.ps1 sql\dwd\fact_order.sql
#
# 支持相对路径，会先切到项目根目录再执行。

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$File
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent

Push-Location $projectRoot
try {
    if (-not (Test-Path $File)) {
        Write-Host "找不到文件: $File" -ForegroundColor Red
        exit 1
    }

    Write-Host "执行 $File ..." -ForegroundColor Cyan
    Get-Content $File -Raw -Encoding utf8 |
        docker compose exec -T mysql mysql -uroot -proot123 --default-character-set=utf8mb4

    if ($LASTEXITCODE -ne 0) {
        Write-Host "执行失败，退出码 $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }
    Write-Host "完成" -ForegroundColor Green
}
finally {
    Pop-Location
}
