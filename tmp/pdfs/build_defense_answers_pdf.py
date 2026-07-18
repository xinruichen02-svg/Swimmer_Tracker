from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)


WORKSPACE = Path(r"D:\pythonsrc\scripts")
SOURCE = WORKSPACE / "tmp" / "pdfs" / "build_defense_answers.ps1"
OUTPUT = WORKSPACE / "output" / "pdf" / "答辩问题参考答案.pdf"

BLUE = colors.HexColor("#2E74B5")
DARK_BLUE = colors.HexColor("#1F4D78")
INK = colors.HexColor("#192434")
MUTED = colors.HexColor("#5B6573")
LIGHT_BLUE = colors.HexColor("#E8EEF5")
LIGHT_GRAY = colors.HexColor("#F4F6F9")
LIGHT_GOLD = colors.HexColor("#FFF8E8")
GOLD = colors.HexColor("#7A5A00")


pdfmetrics.registerFont(TTFont("YaHei", r"C:\Windows\Fonts\msyh.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("YaHei-Bold", r"C:\Windows\Fonts\msyhbd.ttc", subfontIndex=0))


class BoxedParagraph(Flowable):
    def __init__(
        self,
        text: str,
        style: ParagraphStyle,
        fill: colors.Color,
        radius: float = 3,
        padding: float = 8,
    ) -> None:
        super().__init__()
        self.paragraph = Paragraph(text, style)
        self.fill = fill
        self.radius = radius
        self.padding = padding
        self.inner_width = 0.0
        self.inner_height = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self.inner_width = max(1, avail_width - 2 * self.padding)
        self.inner_height = self.paragraph.wrap(self.inner_width, avail_height)[1]
        self.width = avail_width
        self.height = self.inner_height + 2 * self.padding
        return self.width, self.height

    def draw(self) -> None:
        self.canv.saveState()
        self.canv.setFillColor(self.fill)
        self.canv.roundRect(0, 0, self.width, self.height, self.radius, fill=1, stroke=0)
        self.paragraph.drawOn(self.canv, self.padding, self.padding)
        self.canv.restoreState()


def esc(value: str) -> str:
    return html.escape(value.replace("''", "'"), quote=False)


styles = getSampleStyleSheet()
body = ParagraphStyle(
    "BodyCN",
    parent=styles["BodyText"],
    fontName="YaHei",
    fontSize=10.3,
    leading=15.0,
    textColor=INK,
    spaceAfter=7,
    wordWrap="CJK",
    splitLongWords=True,
    allowWidows=0,
    allowOrphans=0,
)
h1 = ParagraphStyle(
    "H1CN",
    parent=body,
    fontName="YaHei-Bold",
    fontSize=16,
    leading=21,
    textColor=BLUE,
    spaceBefore=4,
    spaceAfter=10,
    keepWithNext=True,
)
h2 = ParagraphStyle(
    "H2CN",
    parent=body,
    fontName="YaHei-Bold",
    fontSize=12.4,
    leading=17,
    textColor=DARK_BLUE,
    spaceBefore=9,
    spaceAfter=6,
    keepWithNext=True,
)
bullet = ParagraphStyle(
    "BulletCN",
    parent=body,
    leftIndent=22,
    firstLineIndent=-11,
    bulletIndent=3,
    spaceAfter=4,
)
question_style = ParagraphStyle(
    "QuestionCN",
    parent=body,
    fontSize=10.2,
    leading=14.5,
    textColor=MUTED,
    fontName="YaHei",
    spaceAfter=0,
)
callout_style = ParagraphStyle(
    "CalloutCN",
    parent=body,
    fontSize=10.1,
    leading=14.6,
    spaceAfter=0,
)
cover_kicker = ParagraphStyle(
    "CoverKicker",
    parent=body,
    alignment=TA_CENTER,
    fontName="YaHei-Bold",
    fontSize=11,
    leading=16,
    textColor=BLUE,
    spaceAfter=10,
)
cover_title = ParagraphStyle(
    "CoverTitle",
    parent=body,
    alignment=TA_CENTER,
    fontName="YaHei-Bold",
    fontSize=25,
    leading=34,
    textColor=INK,
    spaceAfter=5,
)
cover_subtitle = ParagraphStyle(
    "CoverSubtitle",
    parent=body,
    alignment=TA_CENTER,
    fontName="YaHei",
    fontSize=16,
    leading=22,
    textColor=DARK_BLUE,
    spaceAfter=26,
)
cover_meta = ParagraphStyle(
    "CoverMeta",
    parent=body,
    alignment=TA_CENTER,
    fontSize=9.7,
    leading=14,
    textColor=MUTED,
    spaceAfter=4,
)
cover_principle = ParagraphStyle(
    "CoverPrinciple",
    parent=body,
    alignment=TA_CENTER,
    fontName="YaHei-Bold",
    fontSize=10.8,
    leading=16,
    textColor=GOLD,
)


def draw_page(canvas, doc) -> None:
    width, height = LETTER
    canvas.saveState()
    canvas.setTitle("滑轨式水下训练跟随机器人 - 答辩问题参考答案")
    canvas.setAuthor("答辩准备材料")
    if doc.page == 1:
        canvas.setFont("YaHei", 8)
        canvas.setFillColor(MUTED)
        canvas.drawCentredString(width / 2, 25, "内部答辩准备材料  |  2026-07-17")
    else:
        canvas.setFont("YaHei", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, height - 30, "滑轨式水下训练跟随机器人  |  答辩参考")
        canvas.drawRightString(width - doc.rightMargin, 25, str(doc.page))
    canvas.restoreState()


doc = BaseDocTemplate(
    str(OUTPUT),
    pagesize=LETTER,
    leftMargin=0.80 * inch,
    rightMargin=0.80 * inch,
    topMargin=0.68 * inch,
    bottomMargin=0.62 * inch,
    title="滑轨式水下训练跟随机器人 - 答辩问题参考答案",
    author="答辩准备材料",
)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
doc.addPageTemplates([PageTemplate(id="answers", frames=[frame], onPage=draw_page)])

story: list[Flowable] = [
    Spacer(1, 1.42 * inch),
    Paragraph("答辩速查手册", cover_kicker),
    Paragraph("滑轨式水下训练跟随机器人", cover_title),
    Paragraph("预设问题参考答案", cover_subtitle),
    Paragraph("依据：2026-07-17 最新答辩稿、A1 类参赛作品说明书及当前控制软件实现", cover_meta),
    Paragraph("用途：现场口述、追问展开与技术边界核对", cover_meta),
    Spacer(1, 1.10 * inch),
    Paragraph("答辩原则：讲清已实现，说明待验证，不把预估指标说成实测结果。", cover_principle),
]

paragraph_re = re.compile(r"^\s*Add-Paragraph '((?:[^']|'')*)'(?: '((?:[^']|'')*)')?\s*$")
bullet_re = re.compile(r"^\s*Add-Bullet '((?:[^']|'')*)'\s*$")
question_re = re.compile(r"^\s*Add-Question '((?:[^']|'')*)'\s*$")
callout_re = re.compile(r"^\s*Add-Callout '((?:[^']|'')*)' '((?:[^']|'')*)'")
lead_re = re.compile(r"^\s*Add-Lead '((?:[^']|'')*)' '((?:[^']|'')*)'")

content_started = False
for line in SOURCE.read_text(encoding="utf-8").splitlines():
    if re.match(r"^\s*Add-PageBreak\s*$", line):
        story.append(PageBreak())
        content_started = True
        continue
    if not content_started:
        continue

    match = paragraph_re.match(line)
    if match:
        text, style_name = esc(match.group(1)), match.group(2)
        if style_name == "Heading 1":
            story.append(Paragraph(text, h1))
        elif style_name == "Heading 2":
            story.append(Paragraph(text, h2))
        else:
            story.append(Paragraph(text, body))
        continue

    match = bullet_re.match(line)
    if match:
        story.append(Paragraph(esc(match.group(1)), bullet, bulletText="•"))
        continue

    match = question_re.match(line)
    if match:
        story.append(BoxedParagraph(esc(match.group(1)), question_style, LIGHT_GRAY))
        story.append(Spacer(1, 6))
        continue

    match = callout_re.match(line)
    if match:
        label, text = esc(match.group(1)), esc(match.group(2))
        caution = any(token in label for token in ("诚实", "不要", "修正", "建议口径", "高风险"))
        fill = LIGHT_GOLD if caution else LIGHT_BLUE
        label_color = GOLD if caution else DARK_BLUE
        markup = f'<font name="YaHei-Bold" color="{label_color.hexval()}">{label}</font>{text}'
        story.append(BoxedParagraph(markup, callout_style, fill))
        story.append(Spacer(1, 6))
        continue

    match = lead_re.match(line)
    if match:
        label, text = esc(match.group(1)), esc(match.group(2))
        story.append(Paragraph(f'<font name="YaHei-Bold" color="#1F4D78">{label}</font>{text}', body))

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
doc.build(story)
print(OUTPUT)
