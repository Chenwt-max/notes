$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop 'notes.lnk'
$legacyPath = Join-Path $desktop '课间.lnk'
$shell = New-Object -ComObject WScript.Shell
$arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $PSScriptRoot 'start-app.ps1') + '"'
$previousArguments = $arguments.Replace(' -ExecutionPolicy Bypass','')
if (Test-Path -LiteralPath $path) {
    $existing = $shell.CreateShortcut($path)
    if ($existing.Arguments -notin @($arguments,$previousArguments)) { throw '桌面上已有其他程序的 notes 快捷方式，未覆盖。' }
}
if ((Test-Path -LiteralPath $legacyPath) -and -not (Test-Path -LiteralPath $path)) {
    $legacy = $shell.CreateShortcut($legacyPath)
    if ($legacy.Arguments -in @($arguments,$previousArguments)) { Move-Item -LiteralPath $legacyPath -Destination $path }
}
$shortcut = $shell.CreateShortcut($path)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $project
$shortcut.Description = 'notes · 一键启动本地课程笔记'
$shortcut.IconLocation = (Join-Path $PSScriptRoot 'notes-desktop-mint-20261021.ico') + ',0'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Output "桌面快捷方式已更新：$path"

