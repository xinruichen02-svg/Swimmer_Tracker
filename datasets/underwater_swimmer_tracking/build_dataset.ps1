[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot 'videos'),
    [string]$CacheDirectory = (Join-Path $PSScriptRoot '_source_cache'),
    [switch]$KeepSourceFiles
)

$ErrorActionPreference = 'Stop'

function Resolve-Executable {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    return $null
}

$ytDlp = Resolve-Executable 'yt-dlp'
if (-not $ytDlp) {
    throw '未找到 yt-dlp。请先运行: python -m pip install yt-dlp'
}

$ffmpeg = Resolve-Executable 'ffmpeg'
if (-not $ffmpeg) {
    try {
        $ffmpeg = (& python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())').Trim()
    } catch {
        $ffmpeg = $null
    }
}
if (-not $ffmpeg -or -not (Test-Path -LiteralPath $ffmpeg)) {
    throw '未找到 FFmpeg。请将 ffmpeg 加入 PATH，或运行: python -m pip install imageio-ffmpeg'
}

New-Item -ItemType Directory -Force -Path $OutputDirectory, $CacheDirectory | Out-Null

$manifestPath = Join-Path $PSScriptRoot 'manifest.csv'
$clips = Import-Csv -LiteralPath $manifestPath
$sources = $clips | Group-Object source_group | ForEach-Object { $_.Group[0] }

foreach ($source in $sources) {
    $base = Join-Path $CacheDirectory $source.source_group
    $existing = Get-ChildItem -LiteralPath $CacheDirectory -File |
        Where-Object { $_.BaseName -eq $source.source_group -and $_.Extension -notin @('.part', '.ytdl', '.json') } |
        Select-Object -First 1

    if (-not $existing) {
        Write-Host "下载来源 $($source.source_group)..."
        $args = @(
            '--no-playlist',
            '--format', 'bv*+ba/b',
            '--merge-output-format', 'mp4',
            '--extractor-args', 'generic:impersonate',
            '--output', "$base.%(ext)s",
            $source.source_url
        )
        & $ytDlp @args
        if ($LASTEXITCODE -ne 0) { throw "下载失败: $($source.source_url)" }
    }
}

foreach ($clip in $clips) {
    $sourceFile = Get-ChildItem -LiteralPath $CacheDirectory -File |
        Where-Object { $_.BaseName -eq $clip.source_group -and $_.Extension -notin @('.part', '.ytdl', '.json') } |
        Select-Object -First 1
    if (-not $sourceFile) { throw "缺少来源文件: $($clip.source_group)" }

    $output = Join-Path $OutputDirectory $clip.filename
    Write-Host "生成 $($clip.filename)..."
    & $ffmpeg -hide_banner -loglevel error -y `
        -ss $clip.start_seconds -i $sourceFile.FullName -t $clip.duration_seconds `
        -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p `
        -movflags +faststart $output
    if ($LASTEXITCODE -ne 0) { throw "生成失败: $($clip.filename)" }
}

if (-not $KeepSourceFiles) {
    Get-ChildItem -LiteralPath $CacheDirectory -File | Remove-Item -Force
    Remove-Item -LiteralPath $CacheDirectory -Force -ErrorAction SilentlyContinue
}

Write-Host "完成：$($clips.Count) 段视频已生成到 $OutputDirectory"

