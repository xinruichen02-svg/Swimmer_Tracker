$ErrorActionPreference = 'Stop'

$workspace = 'D:\pythonsrc\scripts'
$sourceScript = Join-Path $workspace 'tmp\pdfs\build_defense_answers.ps1'
$htmlPath = Join-Path $workspace 'tmp\pdfs\答辩问题参考答案.html'
$docxPath = Join-Path $workspace 'tmp\pdfs\答辩问题参考答案_中间稿.docx'
$pdfPath = Join-Path $workspace 'output\pdf\答辩问题参考答案.pdf'
New-Item -ItemType Directory -Force -Path (Split-Path $htmlPath), (Split-Path $pdfPath) | Out-Null

function ConvertTo-HtmlText([string]$value) {
    return [System.Net.WebUtility]::HtmlEncode($value.Replace("''", "'"))
}

$html = New-Object System.Text.StringBuilder
[void]$html.AppendLine('<!DOCTYPE html>')
[void]$html.AppendLine('<html><head><meta charset="utf-8"><style>')
[void]$html.AppendLine('@page { size: Letter; margin: 0.72in 0.82in 0.70in 0.82in; }')
[void]$html.AppendLine('body { font-family: "Microsoft YaHei", "Microsoft JhengHei", sans-serif; font-size: 10.5pt; line-height: 1.48; color: #192434; }')
[void]$html.AppendLine('p { margin: 0 0 7pt 0; } h1 { font-size: 16pt; color: #2e74b5; margin: 12pt 0 9pt; page-break-after: avoid; }')
[void]$html.AppendLine('h2 { font-size: 12.5pt; color: #1f4d78; margin: 11pt 0 6pt; page-break-after: avoid; }')
[void]$html.AppendLine('ul { margin: 3pt 0 8pt 20pt; padding-left: 12pt; } li { margin: 0 0 4pt 0; }')
[void]$html.AppendLine('.pagebreak { page-break-before: always; } .question { background: #f4f6f9; color: #5b6573; font-style: italic; padding: 8pt 10pt; margin: 0 0 10pt; }')
[void]$html.AppendLine('.callout { background: #e8eef5; padding: 8pt 10pt; margin: 5pt 0 9pt; } .lead { margin-bottom: 7pt; }')
[void]$html.AppendLine('.cover { text-align: center; padding-top: 115pt; } .kicker { color: #2e74b5; font-size: 11pt; font-weight: bold; letter-spacing: 1pt; }')
[void]$html.AppendLine('.title { color: #192434; font-size: 25pt; font-weight: bold; margin: 10pt 0 4pt; } .subtitle { color: #1f4d78; font-size: 16pt; margin-bottom: 24pt; }')
[void]$html.AppendLine('.meta { color: #5b6573; font-size: 10pt; margin: 3pt 0; } .principle { color: #7a5a00; font-size: 11pt; font-weight: bold; margin-top: 88pt; }')
[void]$html.AppendLine('strong { color: #1f4d78; }</style></head><body>')
[void]$html.AppendLine('<div class="cover"><div class="kicker">答辩速查手册</div><div class="title">滑轨式水下训练跟随机器人</div><div class="subtitle">预设问题参考答案</div>')
[void]$html.AppendLine('<p class="meta">依据：2026-07-17 最新答辩稿、A1 类参赛作品说明书及当前控制软件实现</p>')
[void]$html.AppendLine('<p class="meta">用途：现场口述、追问展开与技术边界核对</p>')
[void]$html.AppendLine('<p class="principle">答辩原则：讲清已实现，说明待验证，不把预估指标说成实测结果。</p></div>')

$inList = $false
$contentStarted = $false
foreach ($line in (Get-Content -LiteralPath $sourceScript -Encoding UTF8)) {
    if ($line -match '^\s*Add-PageBreak\s*$') {
        if ($inList) { [void]$html.AppendLine('</ul>'); $inList = $false }
        [void]$html.AppendLine('<div class="pagebreak"></div>')
        $contentStarted = $true
        continue
    }
    if (-not $contentStarted) { continue }

    if ($line -match "^\s*Add-Bullet '((?:[^']|'')*)'\s*$") {
        if (-not $inList) { [void]$html.AppendLine('<ul>'); $inList = $true }
        [void]$html.AppendLine('<li>' + (ConvertTo-HtmlText $matches[1]) + '</li>')
        continue
    }
    if ($inList) { [void]$html.AppendLine('</ul>'); $inList = $false }

    if ($line -match "^\s*Add-Paragraph '((?:[^']|'')*)'(?: '((?:[^']|'')*)')?\s*$") {
        $text = ConvertTo-HtmlText $matches[1]
        $style = $matches[2]
        if ($style -eq 'Heading 1') { [void]$html.AppendLine('<h1>' + $text + '</h1>') }
        elseif ($style -eq 'Heading 2') { [void]$html.AppendLine('<h2>' + $text + '</h2>') }
        else { [void]$html.AppendLine('<p>' + $text + '</p>') }
        continue
    }
    if ($line -match "^\s*Add-Question '((?:[^']|'')*)'\s*$") {
        [void]$html.AppendLine('<div class="question">' + (ConvertTo-HtmlText $matches[1]) + '</div>')
        continue
    }
    if ($line -match "^\s*Add-Callout '((?:[^']|'')*)' '((?:[^']|'')*)'") {
        [void]$html.AppendLine('<div class="callout"><strong>' + (ConvertTo-HtmlText $matches[1]) + '</strong>' + (ConvertTo-HtmlText $matches[2]) + '</div>')
        continue
    }
    if ($line -match "^\s*Add-Lead '((?:[^']|'')*)' '((?:[^']|'')*)'") {
        [void]$html.AppendLine('<p class="lead"><strong>' + (ConvertTo-HtmlText $matches[1]) + '</strong>' + (ConvertTo-HtmlText $matches[2]) + '</p>')
        continue
    }
}
if ($inList) { [void]$html.AppendLine('</ul>') }
[void]$html.AppendLine('</body></html>')
[IO.File]::WriteAllText($htmlPath, $html.ToString(), (New-Object Text.UTF8Encoding($true)))
Write-Output 'HTML_READY'

$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    Write-Output 'WORD_READY'
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.ScreenUpdating = $false
    $word.Options.CheckSpellingAsYouType = $false
    $word.Options.CheckGrammarAsYouType = $false
    $doc = $word.Documents.Open($htmlPath, $false, $false, $false)
    Write-Output 'DOC_OPEN'
    foreach ($section in $doc.Sections) {
        $section.PageSetup.PaperSize = 2
        $section.PageSetup.TopMargin = 52
        $section.PageSetup.BottomMargin = 50
        $section.PageSetup.LeftMargin = 59
        $section.PageSetup.RightMargin = 59
        $section.PageSetup.HeaderDistance = 30
        $section.PageSetup.FooterDistance = 28
        $section.PageSetup.DifferentFirstPageHeaderFooter = -1

        $header = $section.Headers.Item(1).Range
        $header.Text = '滑轨式水下训练跟随机器人  |  答辩参考'
        $header.Font.NameFarEast = 'Microsoft YaHei'
        $header.Font.Size = 8
        $header.Font.Color = 7566195

        $footer = $section.Footers.Item(1).Range
        $footer.Text = ''
        $footer.ParagraphFormat.Alignment = 2
        $footer.Font.NameFarEast = 'Microsoft YaHei'
        $footer.Font.Size = 8
        $footer.Font.Color = 7566195
        $footer.Fields.Add($footer, -1, 'PAGE', $true) | Out-Null

        $firstFooter = $section.Footers.Item(2).Range
        $firstFooter.Text = '内部答辩准备材料  |  2026-07-17'
        $firstFooter.ParagraphFormat.Alignment = 1
        $firstFooter.Font.NameFarEast = 'Microsoft YaHei'
        $firstFooter.Font.Size = 8
        $firstFooter.Font.Color = 7566195
    }
    Write-Output 'PDF_START'
    $doc.ExportAsFixedFormat($pdfPath, 17)
    Write-Output 'PDF_DONE'
    $doc.Close($false)
    $doc = $null
    $word.Quit()
    $word = $null
    Write-Output $pdfPath
}
finally {
    if ($doc -ne $null) { try { $doc.Close($false) } catch {} }
    if ($word -ne $null) { try { $word.Quit() } catch {} }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
