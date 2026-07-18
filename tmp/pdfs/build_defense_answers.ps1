$ErrorActionPreference = 'Stop'

$workspace = 'D:\pythonsrc\scripts'
$tempDir = Join-Path $workspace 'tmp\pdfs'
$outputDir = Join-Path $workspace 'output\pdf'
$docxPath = Join-Path $tempDir '答辩问题参考答案_中间稿.docx'
$pdfPath = Join-Path $outputDir '答辩问题参考答案.pdf'
New-Item -ItemType Directory -Force -Path $tempDir, $outputDir | Out-Null

function Color([int]$r, [int]$g, [int]$b) {
    return $r + 256 * $g + 65536 * $b
}

$blue = Color 46 116 181
$darkBlue = Color 31 77 120
$ink = Color 25 36 52
$muted = Color 91 101 115
$lightBlue = Color 232 238 245
$lightGray = Color 244 246 249
$lightGold = Color 255 248 232
$gold = Color 122 90 0
$red = Color 155 28 28
$white = Color 255 255 255

$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Add()

    $section = $doc.Sections.Item(1)
    $section.PageSetup.PaperSize = 2 # US Letter
    $section.PageSetup.Orientation = 0 # Portrait
    $section.PageSetup.TopMargin = 72
    $section.PageSetup.BottomMargin = 72
    $section.PageSetup.LeftMargin = 72
    $section.PageSetup.RightMargin = 72
    $section.PageSetup.HeaderDistance = 35.4
    $section.PageSetup.FooterDistance = 35.4
    $section.PageSetup.DifferentFirstPageHeaderFooter = -1

    $normal = $doc.Styles.Item(-1) # wdStyleNormal
    $normal.Font.Name = 'Calibri'
    $normal.Font.NameFarEast = 'Microsoft YaHei'
    $normal.Font.Size = 10.5
    $normal.Font.Color = $ink
    $normal.ParagraphFormat.Alignment = 0
    $normal.ParagraphFormat.SpaceBefore = 0
    $normal.ParagraphFormat.SpaceAfter = 6
    $normal.ParagraphFormat.LineSpacingRule = 5
    $normal.ParagraphFormat.LineSpacing = 13.2

    $h1 = $doc.Styles.Item(-2) # wdStyleHeading1
    $h1.Font.Name = 'Calibri'
    $h1.Font.NameFarEast = 'Microsoft YaHei'
    $h1.Font.Size = 16
    $h1.Font.Bold = -1
    $h1.Font.Color = $blue
    $h1.ParagraphFormat.SpaceBefore = 18
    $h1.ParagraphFormat.SpaceAfter = 10
    $h1.ParagraphFormat.KeepWithNext = -1

    $h2 = $doc.Styles.Item(-3) # wdStyleHeading2
    $h2.Font.Name = 'Calibri'
    $h2.Font.NameFarEast = 'Microsoft YaHei'
    $h2.Font.Size = 12.5
    $h2.Font.Bold = -1
    $h2.Font.Color = $darkBlue
    $h2.ParagraphFormat.SpaceBefore = 12
    $h2.ParagraphFormat.SpaceAfter = 6
    $h2.ParagraphFormat.KeepWithNext = -1

    $bullet = $doc.Styles.Item(-49) # wdStyleListBullet
    $bullet.Font.Name = 'Calibri'
    $bullet.Font.NameFarEast = 'Microsoft YaHei'
    $bullet.Font.Size = 10.5
    $bullet.Font.Color = $ink
    $bullet.ParagraphFormat.LeftIndent = 27
    $bullet.ParagraphFormat.FirstLineIndent = -13.5
    $bullet.ParagraphFormat.SpaceAfter = 4
    $bullet.ParagraphFormat.LineSpacingRule = 5
    $bullet.ParagraphFormat.LineSpacing = 13.2

    $header = $section.Headers.Item(1).Range
    $header.Text = '滑轨式水下训练跟随机器人  |  答辩参考'
    $header.Font.NameFarEast = 'Microsoft YaHei'
    $header.Font.Name = 'Calibri'
    $header.Font.Size = 8.5
    $header.Font.Color = $muted
    $header.ParagraphFormat.Alignment = 0

    $footer = $section.Footers.Item(1).Range
    $footer.Text = ''
    $footer.Font.NameFarEast = 'Microsoft YaHei'
    $footer.Font.Name = 'Calibri'
    $footer.Font.Size = 8.5
    $footer.Font.Color = $muted
    $footer.ParagraphFormat.Alignment = 2
    $footer.Fields.Add($footer, -1, 'PAGE', $true) | Out-Null

    $firstFooter = $section.Footers.Item(2).Range
    $firstFooter.Text = '内部答辩准备材料  |  2026-07-17'
    $firstFooter.Font.NameFarEast = 'Microsoft YaHei'
    $firstFooter.Font.Name = 'Calibri'
    $firstFooter.Font.Size = 8.5
    $firstFooter.Font.Color = $muted
    $firstFooter.ParagraphFormat.Alignment = 1

    $sel = $word.Selection
    $script:doc = $doc
    $script:sel = $sel
    $script:ink = $ink
    $script:darkBlue = $darkBlue
    $script:lightBlue = $lightBlue
    $script:lightGray = $lightGray

    function Reset-Selection {
        $script:sel.Style = $script:doc.Styles.Item(-1)
        $script:sel.Font.Bold = 0
        $script:sel.Font.Italic = 0
        $script:sel.Font.Color = $script:ink
        $script:sel.ParagraphFormat.Alignment = 0
        $script:sel.ParagraphFormat.LeftIndent = 0
        $script:sel.ParagraphFormat.FirstLineIndent = 0
        $script:sel.ParagraphFormat.SpaceBefore = 0
        $script:sel.ParagraphFormat.SpaceAfter = 6
        $script:sel.ParagraphFormat.LineSpacingRule = 5
        $script:sel.ParagraphFormat.LineSpacing = 13.2
    }

    function Add-Paragraph([string]$text, [string]$style = 'Normal') {
        $styleId = switch ($style) {
            'Heading 1' { -2 }
            'Heading 2' { -3 }
            default { -1 }
        }
        $script:sel.Style = $script:doc.Styles.Item($styleId)
        $script:sel.TypeText($text)
        $script:sel.TypeParagraph()
        Reset-Selection
    }

    function Add-Bullet([string]$text) {
        $script:sel.Style = $script:doc.Styles.Item(-49)
        $script:sel.TypeText($text)
        $script:sel.TypeParagraph()
        Reset-Selection
    }

    function Add-Lead([string]$label, [string]$text, [int]$labelColor = $darkBlue) {
        Reset-Selection
        $script:sel.Font.Bold = -1
        $script:sel.Font.Color = $labelColor
        $script:sel.TypeText($label)
        $script:sel.Font.Bold = 0
        $script:sel.Font.Color = $ink
        $script:sel.TypeText($text)
        $script:sel.TypeParagraph()
        Reset-Selection
    }

    function Add-Callout([string]$label, [string]$text, [int]$fill = $lightBlue, [int]$labelColor = $darkBlue) {
        Reset-Selection
        $start = $script:sel.Start
        $script:sel.Font.Bold = -1
        $script:sel.Font.Color = $labelColor
        $script:sel.TypeText($label)
        $script:sel.Font.Bold = 0
        $script:sel.Font.Color = $ink
        $script:sel.TypeText($text)
        $script:sel.TypeParagraph()
        $range = $script:doc.Range($start, $script:sel.Start - 1)
        $range.ParagraphFormat.LeftIndent = 10
        $range.ParagraphFormat.RightIndent = 10
        $range.ParagraphFormat.SpaceBefore = 5
        $range.ParagraphFormat.SpaceAfter = 8
        $range.Shading.BackgroundPatternColor = $fill
        Reset-Selection
    }

    function Add-Question([string]$text) {
        Reset-Selection
        $start = $script:sel.Start
        $script:sel.Font.Italic = -1
        $script:sel.Font.Color = $muted
        $script:sel.TypeText($text)
        $script:sel.TypeParagraph()
        $range = $script:doc.Range($start, $script:sel.Start - 1)
        $range.ParagraphFormat.LeftIndent = 10
        $range.ParagraphFormat.RightIndent = 10
        $range.ParagraphFormat.SpaceBefore = 0
        $range.ParagraphFormat.SpaceAfter = 10
        $range.Shading.BackgroundPatternColor = $lightGray
        Reset-Selection
    }

    function Add-PageBreak {
        $script:sel.InsertBreak(7)
        Reset-Selection
    }

    # Cover
    for ($i = 0; $i -lt 4; $i++) { $sel.TypeParagraph() }
    $sel.ParagraphFormat.Alignment = 1
    $sel.Font.NameFarEast = 'Microsoft YaHei'
    $sel.Font.Name = 'Calibri'
    $sel.Font.Size = 11
    $sel.Font.Bold = -1
    $sel.Font.Color = $blue
    $sel.TypeText('答辩速查手册')
    $sel.TypeParagraph()
    $sel.Font.Size = 25
    $sel.Font.Bold = -1
    $sel.Font.Color = $ink
    $sel.TypeText('滑轨式水下训练跟随机器人')
    $sel.TypeParagraph()
    $sel.Font.Size = 16
    $sel.Font.Bold = 0
    $sel.Font.Color = $darkBlue
    $sel.TypeText('预设问题参考答案')
    $sel.TypeParagraph()
    $sel.ParagraphFormat.SpaceAfter = 22
    $sel.Font.Size = 10.5
    $sel.Font.Color = $muted
    $sel.TypeText('依据：2026-07-17 最新答辩稿、A1 类参赛作品说明书及当前控制软件实现')
    $sel.TypeParagraph()
    $sel.TypeText('用途：现场口述、追问展开与技术边界核对')
    $sel.TypeParagraph()
    for ($i = 0; $i -lt 4; $i++) { $sel.TypeParagraph() }
    $sel.Font.Size = 11
    $sel.Font.Bold = -1
    $sel.Font.Color = $gold
    $sel.TypeText('答辩原则：讲清已实现，说明待验证，不把预估指标说成实测结果。')
    $sel.TypeParagraph()
    Reset-Selection

    Add-PageBreak
    Add-Paragraph '使用说明与统一口径' 'Heading 1'
    Add-Callout '先给结论：' '本项目目前最扎实的部分是视觉测量、速度解算、APP、安全监督与仿真链路；滑轨安装、水密寿命、缆线拖曳和 2 m/s 真机性能仍属于工程方案或待验证指标。'
    Add-Paragraph '回答方法' 'Heading 2'
    Add-Bullet '先正面回答“能不能、有没有、是否考虑”，不要绕开问题。'
    Add-Bullet '随后说明当前设计依据，再明确尚未完成的试验和下一步验证方法。'
    Add-Bullet '机械问题使用“拟采用、设计为、下一步验证”；软件问题可使用“已经实现、已有测试”。'
    Add-Paragraph '当前已经实现的软件能力' 'Heading 2'
    Add-Bullet '人工 ROI 框选 + CSRT 单目标跟踪，输出目标中心相对画面中心的带时间戳水平偏差。'
    Add-Bullet '对短时间窗内的相对位移进行线性拟合，估算相对速度，再结合电机实际 RPM 估算运动员速度。'
    Add-Bullet 'APP 以约 20 Hz 更新目标，带 RPM 限幅、变化率限制、反馈超时、目标越界和故障锁定。'
    Add-Bullet '独立监督进程和 Arduino 500 ms 看门狗用于失联停车；真实硬件链路仍需按验收流程验证。'
    Add-Callout '高风险表述：' '“识别准确率高于 90%”“最高航速 2 m/s”“连续工作 2 h”在现有材料中属于目标或预估值。没有对应实测数据时，必须明确说“设计目标”，不能说“已经达到”。' $lightGold $gold

    Add-PageBreak
    Add-Paragraph '问题一 | 滑轨方案的工程可行性' 'Heading 1'
    Add-Question '滑轨怎么固定？公共泳池安装和拆卸是否方便？维护成本如何？是否考虑氯、臭氧对滑轨和齿轮的腐蚀？'
    Add-Paragraph '现场建议回答（约 60 秒）' 'Heading 2'
    Add-Paragraph '我们不打算把轨道做成永久破坏池体的基础设施，而是把它定位为训练时段使用的模块化可拆设备。工程化方案是分段轨道快速拼接，由池端或池岸可拆夹具完成纵向定位，水下采用配重、防滑支座承载和限位，原则上不在公共泳池池底打孔。安装后先进行直线度、端部限位和空载低速检查，训练结束后可按相反顺序拆除。'
    Add-Paragraph '维护方面采用模块化思想：轨道、行走轮或齿轮、密封件和电气舱分别检查、更换。材料上优先考虑 316L 不锈钢、POM/PEEK 等工程塑料，并隔离异种金属接触；齿轮尽量不裸露，采用封闭或可冲洗结构。每次使用后用淡水冲洗，定期检查点蚀、涂层、紧固件和齿面磨损。氯和臭氧腐蚀已经纳入材料选择，但目前尚未完成长期浸泡与场馆安装测试，因此我们不会宣称已经通过公共泳池长期验证。'
    Add-Paragraph '追问展开' 'Heading 2'
    Add-Bullet '部署流程：分段运输 → 水下拼接 → 端部定位 → 安装机械限位 → 空载低速试跑 → 投入训练。'
    Add-Bullet '材料策略：316L 仍可能发生氯化物点蚀，因此除选材外还要控制缝隙、隔离异种金属并安排周期检查。'
    Add-Bullet '验证计划：在实际池水中做材料试片浸泡、紧固件循环拆装和满长度轨道直线度测试，再确定维护周期。'
    Add-Callout '诚实边界：' '现有作品说明书明确把“轨道安装方案验证”列为后续工作。答辩时应说方案已经考虑，但公共泳池的快速安装、长期腐蚀和维护成本尚未形成实测结论。' $lightGold $gold
    Add-Lead '一句话收尾：' '我们的目标不是永久改造泳池，而是做成可拆、可维护、对池体无损的训练附件。'

    Add-PageBreak
    Add-Paragraph '问题二 | 滑轨约束下的视觉跟随' 'Heading 1'
    Add-Question '运动员并不严格在一条线上游动。当运动员偏离轨道正上方时，视觉跟随是否仍有效？会不会出现轨道在左、人在右，机器人跟不了？'
    Add-Paragraph '现场建议回答（约 60 秒）' 'Heading 2'
    Add-Paragraph '这个问题需要区分“看得见”和“追得上”。CSRT 跟踪是在图像中完成的，只要运动员仍处于摄像头视场内，即使存在一定横向偏离，目标框仍可以更新；但机器人受滑轨约束，只能控制沿轨道方向的位置，不能主动消除垂直于轨道的横向偏差。因此如果运动员偏离到视场之外，确实会出现物理上无法跟随的情况。系统对此的处理不是盲目追踪，而是目标越出安全区域或跟踪丢失时立即停车并要求重新框选。'
    Add-Paragraph '本方案的适用场景是标准泳道训练。轨道与泳道方向平行布置，通过摄像头视场角、安装距离和安全边界，使正常泳道内的横向摆动落在可视范围内。当前代码只把与轨道方向标定后的图像横轴偏差用于速度解算，另一方向不构成控制自由度。所以本系统不是面向任意二维自由游动，而是利用泳道约束完成单轴稳定伴随。'
    Add-Paragraph '技术依据' 'Heading 2'
    Add-Bullet '人工框选后由 CSRT 逐帧更新目标框；控制量来自目标中心与画面中心的水平偏差。'
    Add-Bullet '偏差连续序列用于求相对速度，单帧偏差本身不会被误当成速度。'
    Add-Bullet '偏差超过画面宽度设定比例、跟踪失败或摄像头断流时，APP 进入故障并请求停车。'
    Add-Callout '不要过度承诺：' '如果评委给出“人在相邻泳道、完全不在镜头内”的极端情况，答案就是“不能跟，这是单轴方案的适用边界”；可扩展方案是更广视场、多相机或可转动云台，但不属于当前已实现功能。' $lightGold $gold
    Add-Lead '一句话收尾：' '轨道解决纵向伴随，视场覆盖正常横向摆动；超出视场则安全停车，而不是假装具备二维追踪能力。'

    Add-PageBreak
    Add-Paragraph '问题三 | 2 m/s 指标、加速与折返' 'Heading 1'
    Add-Question '最高航速 2 m/s 是否足够？启动加速和运动员冲刺时能否跟上？能否覆盖转身折返？'
    Add-Paragraph '现场建议回答（约 60 秒）' 'Heading 2'
    Add-Paragraph '2 m/s 在当前材料中是设计上限和性能预估，不是已经完成的真机实测值。最新阻力分析给出的 2 m/s 本体阻力约为 41 N，因此能否达到该速度不仅取决于电机空载转速，还取决于齿轮传动后的持续牵引力、加速余量、缆线附加阻力以及轨道摩擦。工程上必须让有效牵引力高于阻力并保留安全裕量，再通过分级提速试验确认。'
    Add-Paragraph '对常见训练速度，2 m/s 可以作为覆盖目标；但对于世界级冲刺和启动瞬态，速度上限几乎没有余量，不能仅凭最高速度宣称一定跟得上。启动时可以让机器人预先定位、采用滚动起步，并通过加速度和 RPM 变化率限制避免突加速。对于转身折返，机械上电机和滑轨可双向运动，但当前 CSRT 在翻滚转身、遮挡和方向突变时可能丢失目标，现阶段应按“减速/停车、重新识别或人工重新框选、确认后反向启动”处理，尚不能宣称实现了全自动无缝折返。'
    Add-Paragraph '技术展开' 'Heading 2'
    Add-Bullet '加速度取决于净牵引力：驱动力减去水阻、轨道摩擦和缆线阻力后，才是用于加速的余量。'
    Add-Bullet '当前软件设置目标转速变化率限制，优先防止机械冲击；这与“瞬间追上冲刺”之间存在明确权衡。'
    Add-Bullet '后续折返状态机应包含端区识别、提前减速、方向切换、目标重识别和重新加速。'
    Add-Callout '建议口径：' '把“覆盖世界级冲刺”改为“优先覆盖常见训练速度，2 m/s 为设计目标；极限冲刺和连续转身需要真机牵引力、加速度和重识别试验验证”。' $lightGold $gold
    Add-Lead '一句话收尾：' '2 m/s 是设计目标，不是完成证明；最终要用牵引力、加速度和折返成功率三组数据回答。'

    Add-PageBreak
    Add-Paragraph '问题四 | 定速巡航如何成为配速员' 'Heading 1'
    Add-Question '机器人在水下，运动员游泳时脸朝下，运动员如何感知机器人位置，从而根据配速调整？'
    Add-Paragraph '现场建议回答（约 50 秒）' 'Heading 2'
    Add-Paragraph '评委指出的是当前表述中最需要补全的一环。现有定速巡航已经能提供稳定速度基准，APP 也能把状态显示给岸上的教练，但如果机器人没有给运动员提供可感知的提示，它更准确的定位是“定速水下跟拍平台”，还不能完整发挥配速员作用。'
    Add-Paragraph '工程化方案是在机器人朝向运动员的一侧增加低压防水高亮 LED 光带或位置灯，使运动员在水下通过余光看到移动参考；还可以用颜色表达相对状态，例如绿色表示接近设定配速，红色表示落后、蓝色表示超前。灯具要采用漫射和限亮设计，避免眩光影响动作。岸上 APP 则供教练监控和训练后复盘。当前样机材料没有证明这套运动员反馈界面已经完成，因此答辩时应把它作为配速功能的必要扩展，而不是现有成果。'
    Add-Paragraph '追问展开' 'Heading 2'
    Add-Bullet '“恒定速度”只提供参考信号，“运动员能够感知参考信号”才构成完整配速闭环。'
    Add-Bullet '最简单可靠的感知方式是可视灯光，不依赖水下无线通信，也不会要求运动员佩戴额外设备。'
    Add-Bullet '需要通过不同泳姿、照度、浑浊度和安装位置试验确定可见性与眩光边界。'
    Add-Callout '答辩修正：' '如果 LED 引导尚未装机，不要说运动员“已经能够轻松感知速度”；应说“定速控制已具备，面向运动员的可视反馈是把它升级为配速员的下一步”。' $lightGold $gold
    Add-Lead '一句话收尾：' '定速是配速基础，可感知提示才是配速接口；当前已完成前者，后者拟用水下可视灯光补齐。'

    Add-PageBreak
    Add-Paragraph '问题五 | 零浮力缆的拖曳与防缠绕' 'Heading 1'
    Add-Question '零浮力缆仍会产生阻力。阻力仿真是否考虑缆绳？缆绳如何避免缠绕和干扰运动员？'
    Add-Paragraph '现场建议回答（约 60 秒）' 'Heading 2'
    Add-Paragraph '零浮力只表示缆绳在水中不会明显上浮或下沉，并不等于零阻力。当前 PPT 中约 41 N 的 2 m/s 阻力结果主要针对机器人本体，现有材料没有证明已经把缆绳的分布阻力、弯曲和张力耦合进仿真，因此这一点必须明确承认。下一步应把缆径、浸水长度、来流角度和收放张力加入模型，并通过拖曳试验比较“无缆”和“带缆”的牵引力差值。'
    Add-Paragraph '防缠绕的核心不是只选零浮力线，而是管理缆线走向。方案上让缆线沿轨道侧或池壁的独立导向路径布置，通过岸端收放器或随动滑环保持轻微张力，限制松弛长度；缆线与运动员泳道保持物理隔离，并设置导向环、最小弯曲半径和可快速释放结构。异常张力或收放卡滞应触发停车。这样即使存在缆线，也不会让自由缆段进入运动员活动区域。'
    Add-Paragraph '验证项目' 'Heading 2'
    Add-Bullet '拖曳试验：相同速度下测量本体、带缆本体以及不同放缆长度的牵引力。'
    Add-Bullet '收放试验：往返循环检查堆缆、卡滞、最小弯曲半径和连接器受力。'
    Add-Bullet '安全试验：模拟异常松弛和张力突增，验证导向、快速释放与停车逻辑。'
    Add-Callout '诚实边界：' '当前只能说“采用中性/零浮力缆以降低浮沉干扰”，不能说“缆线对阻力没有影响”或“现有 CFD 已完整考虑缆线”。' $lightGold $gold
    Add-Lead '一句话收尾：' '零浮力解决浮沉，不解决拖曳；真正的安全性来自导向、收放、隔离和张力保护。'

    Add-PageBreak
    Add-Paragraph '问题六 | 水密设计与动密封可靠性' 'Heading 1'
    Add-Question '舵机、齿轮、传动轴等移动部件在水下需要动密封。采用什么方案？可靠性如何保证？是否做过水密测试？'
    Add-Paragraph '现场建议回答（约 60 秒）' 'Heading 2'
    Add-Paragraph '我们的优先原则是减少甚至取消穿舱旋转轴，因为动密封是水下可靠性的薄弱点。最新电路方案已经选用防水电机，并把控制器、降压和通信模块集中在静态水密舱内，外部只保留必要的水密连接。工程化时可以让防水电机和封闭齿轮箱位于舱外，或者采用磁耦合传递扭矩，使主舱以端盖 O 形圈和水密接头等静密封为主。答辩中应统一使用“防水电机驱动”，避免把普通舵机直接裸露入水说成既定方案。'
    Add-Paragraph '如果最终结构仍必须穿舱，则采用机械密封与唇形密封的双重屏障，在两道密封之间设置泄漏监测，并对轴的同轴度、表面粗糙度和磨损周期进行控制。可靠性不能只靠结构图证明，需要依次完成真空保压或气密测试、超过实际工作水深的静水压力测试、长时间浸泡、带载旋转循环、绝缘和漏电测试。现有说明书把水密样机加工和密封测试列为后续路线，因此目前不能声称已经通过长期水密测试。'
    Add-Paragraph '建议测试序列' 'Heading 2'
    Add-Bullet '空舱气密/真空保压：先筛查装配和接头泄漏。'
    Add-Bullet '静水压力与浸泡：按高于实际水深的压力留裕量，检查进水、变形和绝缘。'
    Add-Bullet '动态循环：电机反复正反转并结合温升、停机冷却，观察密封磨损和压力变化。'
    Add-Bullet '电气安全：漏水传感、漏电保护、绝缘电阻和失联停车应独立验证。'
    Add-Callout '诚实边界：' '可以说水密架构和测试方法已经设计，但除非有测试记录，不要说“已经完成水密可靠性验证”。' $lightGold $gold
    Add-Lead '一句话收尾：' '最可靠的动密封是尽量不让主舱存在动密封；剩余风险再用双密封、监测和循环试验控制。'

    Add-PageBreak
    Add-Paragraph '问题七 | 滑轨式方案是否真正创新' 'Heading 1'
    Add-Question '滑轨本身与工厂轨道机器人类似。这个方案的真正创新之处在哪里？'
    Add-Paragraph '现场建议回答（约 60 秒）' 'Heading 2'
    Add-Paragraph '我们认同滑轨机构本身不是原创机械原理，因此不把“发明了滑轨”作为创新主张。项目的创新属于面向游泳训练场景的约束设计和系统集成：利用泳道天然是一维运动场景这一特点，把自由水下机器人的六自由度定位、避障和多推进器协同问题，转化为可重复标定、可安全限位的单轴跟随问题。'
    Add-Paragraph '在这个约束平台上，我们进一步把水下视觉相对位移、短时间窗速度估计、电机速度反馈、定速/视觉双模式、实时视频链路以及目标丢失和失联停车组合成训练闭环。它相对于固定水下相机能够连续伴随，相对于自由航行 ROV 则降低控制复杂度、能耗和运动员附近螺旋桨风险。因此真正的创新点不是某一个零件，而是“针对泳池训练重新选择运动约束，并把感知、控制、通信和安全做成一体化系统”。'
    Add-Paragraph '评委继续追问时' 'Heading 2'
    Add-Bullet '创新类型：场景创新、系统创新和工程集成创新，而不是基础机构发明。'
    Add-Bullet '对比固定相机：连续覆盖范围更大，视角相对稳定，可获得伴随视频和速度状态。'
    Add-Bullet '对比自由 ROV：单轴控制更易验证，轨迹可重复，无需多推进器协同，安全边界更明确。'
    Add-Bullet '后续用数据证明创新价值：同等拍摄任务下比较画面抖动、跟踪丢失率、能耗、部署时间和安全停车成功率。'
    Add-Callout '最稳妥的表述：' '“滑轨是成熟技术，我们的贡献是把它作为泳池约束平台，并与视觉速度估计、双模式巡航和失效安全结合，形成面向训练的完整系统。”' $lightBlue $darkBlue
    Add-Lead '一句话收尾：' '创新不在轨道这个零件，而在用一维约束重构水下跟随问题，并形成可训练、可回传、可安全停车的系统闭环。'

    Add-PageBreak
    Add-Paragraph '最后一页 | 答辩红线与速记' 'Heading 1'
    Add-Paragraph '必须统一的四个口径' 'Heading 2'
    Add-Lead '1. 2 m/s：' '设计目标/预估上限，不是已完成的实测航速。'
    Add-Lead '2. 90% 准确率：' '没有标准数据集和统计结果时，只能称目标指标；当前实现是人工框选后的 CSRT 跟踪。'
    Add-Lead '3. 水密与安装：' '方案和验证流程已考虑，长期水密、公共泳池部署与腐蚀寿命尚待试验。'
    Add-Lead '4. 配速员：' '定速控制已经具备；运动员可感知的灯光反馈尚需补齐。'
    Add-Paragraph '三个加分点' 'Heading 2'
    Add-Bullet '主动承认单轴边界：面向标准泳道训练，不服务任意二维自由游动。'
    Add-Bullet '主动区分位置偏差与相对速度：视觉偏差序列求斜率，不能把单帧像素偏差当速度。'
    Add-Bullet '主动说明失效安全：目标丢失、越界、反馈超时和通信失联都会停车，故障不能自动恢复。'
    Add-Paragraph '遇到没有数据的问题怎么答' 'Heading 2'
    Add-Callout '标准句式：' '“这个问题我们已经纳入设计，但目前还没有足够实测数据支持结论。现阶段采用的是……；下一步会通过……试验，用……指标判断是否达标。在完成验证前，我们不把它作为已实现性能。”'
    Add-Paragraph '20 秒总述' 'Heading 2'
    Add-Paragraph '本项目面向标准泳道水下训练，把自由水下跟随简化为轨道单轴运动；通过摄像头跟踪运动员相对位置变化，结合电机反馈估算运动员速度，并在定速巡航和视觉跟随两种模式下完成伴随拍摄。当前软件闭环和安全逻辑已经形成，机械部署、水密寿命、缆线拖曳和极限速度仍需要真机试验完成工程闭环。'

    $doc.SaveAs2($docxPath, 16)
    $doc.ExportAsFixedFormat($pdfPath, 17, $false, 0, 0, 1, 9999, 0, $true, $true, 1, $true, $true, $false)
    $doc.Close($false)
    $doc = $null
    $word.Quit()
    $word = $null
    Write-Output $pdfPath
}
finally {
    if ($doc -ne $null) {
        try { $doc.Close($false) } catch {}
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($doc)
    }
    if ($word -ne $null) {
        try { $word.Quit() } catch {}
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($word)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
