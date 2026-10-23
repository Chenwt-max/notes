param([switch]$Quiet)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$recordPath = Join-Path $project 'data\server-instance.json'
try {
    if (-not (Test-Path -LiteralPath $recordPath)) { throw '没有此目录的受管理实例。其他程序和旧版服务不会被结束。' }
    $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
    $health = Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 3
    $sha = [Security.Cryptography.SHA256]::Create()
    $expected = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($project.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,24)
    $sha.Dispose()
    if ($health.instance -ne $expected -or $record.instance -ne $expected -or $record.version -ne $health.version) { throw '实例归属不一致；不会结束其他程序。' }
    @{nonce=$record.nonce} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $project 'data\stop-request.json') -Encoding UTF8
    $deadline = [DateTime]::UtcNow.AddSeconds(75)
    while (Test-Path -LiteralPath $recordPath) {
        if ([DateTime]::UtcNow -gt $deadline) { throw '检查点停止尚未完成；请查看 data 中的日志，未强制结束进程。' }
        Start-Sleep -Milliseconds 500
    }
} catch {
    if ($Quiet) { Write-Error $_.Exception.Message; exit 1 }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'notes 停止') | Out-Null
    exit 1
}
