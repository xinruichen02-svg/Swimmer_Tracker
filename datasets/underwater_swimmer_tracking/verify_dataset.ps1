[CmdletBinding()]
param(
    [string]$VideoDirectory = (Join-Path $PSScriptRoot 'videos')
)

$ErrorActionPreference = 'Stop'
$manifest = Import-Csv -LiteralPath (Join-Path $PSScriptRoot 'manifest.csv')
$failures = [System.Collections.Generic.List[string]]::new()

foreach ($row in $manifest) {
    $path = Join-Path $VideoDirectory $row.filename
    if (-not (Test-Path -LiteralPath $path)) {
        $failures.Add("缺少: $($row.filename)")
        continue
    }
    $file = Get-Item -LiteralPath $path
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($file.Length -ne [long]$row.bytes) {
        $failures.Add("大小不符: $($row.filename)")
    }
    if ($hash -ne $row.sha256) {
        $failures.Add("SHA-256 不符: $($row.filename)")
    }
}

if ($failures.Count -gt 0) {
    $failures | ForEach-Object { Write-Error $_ }
    throw "校验失败：$($failures.Count) 项。若刚从上游重新构建，可能是源文件或编码器版本发生变化。"
}

Write-Host "校验通过：$($manifest.Count) 段视频与 manifest.csv 完全一致。"

