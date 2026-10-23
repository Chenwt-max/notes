param([switch]$NoExtract)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $root 'release-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$asset = $manifest.portable
function ChildFile([string]$name) {
    if ([IO.Path]::GetFileName($name) -ne $name) { throw '文件名越界。' }
    return Join-Path $root $name
}
$zip = ChildFile $asset.file
if (Test-Path -LiteralPath $zip) {
    if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) { throw '已有 ZIP 校验不符，未覆盖。请先移走这个文件。' }
} else {
    foreach ($part in $asset.parts) {
        $path = ChildFile $part.file
        if (-not (Test-Path -LiteralPath $path)) { throw "缺少分卷：$($part.file)" }
        if ((Get-Item -LiteralPath $path).Length -ne $part.bytes -or (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $part.sha256) { throw "分卷损坏：$($part.file)" }
    }
    $temporary = "$zip.assembling"
    $output = [IO.File]::Create($temporary)
    try {
        foreach ($part in $asset.parts) {
            Write-Host "合并 $($part.file)"
            $inputPart = [IO.File]::OpenRead((ChildFile $part.file))
            try { $inputPart.CopyTo($output) } finally { $inputPart.Dispose() }
        }
    } finally { $output.Dispose() }
    if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) { throw '合并后的 ZIP 校验失败，未解压。' }
    Move-Item -LiteralPath $temporary -Destination $zip
}
if (-not $NoExtract) {
    $destination = Join-Path $root 'notes-portable-1.0.0-rc.1'
    if (Test-Path -LiteralPath $destination) { throw '目标解压目录已存在。为保护已有资料，请把 ZIP 解压到另一个空目录。' }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::ExtractToDirectory($zip,$destination)
    Write-Host "校验并解压完成：$destination"
}
