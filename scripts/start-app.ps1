param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$url = 'http://127.0.0.1:8765'
$data = Join-Path $project 'data'
$mutex = [System.Threading.Mutex]::new($false, 'Local\KejianLectureNotes8765')
$locked = $false
$expectedVersion = '1.0.0-rc.1'
$sha = [System.Security.Cryptography.SHA256]::Create()
$identity = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($project.ToLowerInvariant())))).Replace('-','').ToLowerInvariant().Substring(0,24)
$sha.Dispose()

function Test-AppReady {
    try {
        $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 1
        if ($health.ok -ne $true -or $health.local_only -ne $true -or $health.instance -ne $identity -or $health.version -ne $expectedVersion) {
            throw '端口 8765 已被其他目录、版本或程序占用。请先关闭对应实例。'
        }
        return $true
    } catch {
        if ($_.Exception.Message -like '端口*') { throw }
        return $false
    }
}

try {
    try {
        $locked = $mutex.WaitOne(60000)
    } catch [System.Threading.AbandonedMutexException] {
        $locked = $true
    }
    if (-not $locked) { throw '另一个启动进程仍在等待，请稍后再试。' }

    if (-not (Test-AppReady)) {
        $probe = [System.Net.Sockets.TcpClient]::new()
        try { $probe.Connect('127.0.0.1',8765); throw '端口 8765 已被其他程序占用，无法启动 notes。' }
        catch [System.Net.Sockets.SocketException] {} finally { $probe.Dispose() }
        $python = Join-Path $project '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath (Join-Path $project 'portable.json')) { $python = Join-Path $project 'runtime\core\python.exe' }
        if (-not (Test-Path -LiteralPath $python)) {
            if (Test-Path -LiteralPath (Join-Path $project 'portable.json')) {
                throw '便携运行环境不完整，请保留已有数据并重新解压完整便携包。'
            }
            throw "未找到运行环境，请先运行：$project\安装环境.ps1"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $project 'frontend\dist\index.html'))) {
            throw '未找到网页构建文件，请先运行安装环境.ps1。'
        }
        New-Item -ItemType Directory -Path $data -Force | Out-Null
        $stderr = Join-Path $data 'server-launch.stderr.log'
        $server = Start-Process -FilePath $python -ArgumentList @(
            '-X', 'utf8', '-m', 'lecture_notes.app'
        ) -WorkingDirectory $project -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $data 'server-launch.stdout.log') `
            -RedirectStandardError $stderr
        Set-Content -LiteralPath (Join-Path $data 'background-server.pid') -Value $server.Id -Encoding Ascii

        $deadline = [DateTime]::UtcNow.AddSeconds(45)
        while (-not (Test-AppReady)) {
            $server.Refresh()
            if ($server.HasExited -or [DateTime]::UtcNow -ge $deadline) {
                $detail = (Get-Content -LiteralPath $stderr -Tail 8 -ErrorAction SilentlyContinue) -join "`r`n"
                throw "本地服务未能就绪。日志：$stderr`r`n`r`n$detail"
            }
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $NoBrowser) { Start-Process $url }
} catch {
    if ($NoBrowser) { Write-Error $_.Exception.Message; exit 1 }
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $_.Exception.Message, 'notes 启动失败',
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
