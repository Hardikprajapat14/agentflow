"""Render the markdown report + chart specs to a PDF with ReportLab (no external binaries)."""
import re
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2"]
_REPL = {"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2265": ">=",
         "\u2264": "<=", "\u2192": "->", "\u2022": "-", "\u2026": "...", "\u2248": "~", "\u00d7": "x"}


def _safe(text: str) -> str:
    for k, v in _REPL.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


def _inline(text: str) -> str:
    text = escape(_safe(text))
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", text)


def _chart(spec: dict, width: float = 470, height: float = 210) -> Drawing:
    rows, series = spec["data"], spec["series"][:6]
    d = Drawing(width, height)
    ch = VerticalBarChart() if spec["type"] == "bar" else HorizontalLineChart()
    ch.x, ch.y, ch.width, ch.height = 50, 40, width - 70, height - 55
    ch.data = [[float(r.get(s) or 0) for r in rows] for s in series]
    ch.categoryAxis.categoryNames = [str(r["x"])[:10] for r in rows]
    ch.categoryAxis.labels.angle = 35
    ch.categoryAxis.labels.boxAnchor = "ne"
    ch.categoryAxis.labels.fontSize = 6
    ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.labelTextFormat = "%d"
    for i in range(len(series)):
        c = colors.HexColor(PALETTE[i % len(PALETTE)])
        if spec["type"] == "bar":
            ch.bars[i].fillColor = c
        else:
            ch.lines[i].strokeColor, ch.lines[i].strokeWidth = c, 1.6
    d.add(ch)
    return d


def render_pdf(path: str, title: str, markdown: str, charts: list[dict]) -> None:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10, leading=14)
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=18, textColor=colors.HexColor("#1e3a8a"))
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, textColor=colors.HexColor("#1e40af"), spaceBefore=10)
    h3 = ParagraphStyle("h3", parent=ss["Heading3"], fontSize=11)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=14, bulletIndent=4)
    story = [Paragraph(_inline(title), h1), Spacer(1, 6)]
    lines, i = markdown.splitlines(), 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if ln.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.fullmatch(r"\|[\s:\-|]+\|?", lines[i].strip()):
                    block.append([Paragraph(_inline(c.strip()), body) for c in lines[i].strip().strip("|").split("|")])
                i += 1
            if block:
                width = max(len(r) for r in block)
                block = [r + [Paragraph("", body)] * (width - len(r)) for r in block]
                t = Table(block, repeatRows=1, hAlign="LEFT")
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                                       ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story += [t, Spacer(1, 8)]
            continue
        if ln.startswith("### "):
            story.append(Paragraph(_inline(ln[4:]), h3))
        elif ln.startswith("## "):
            story.append(Paragraph(_inline(ln[3:]), h2))
        elif ln.startswith("# "):
            story.append(Paragraph(_inline(ln[2:]), h2))
        elif re.match(r"^\s*[-*] ", ln):
            story.append(Paragraph(_inline(re.sub(r"^\s*[-*] ", "", ln)), bullet, bulletText="\u2022"))
        elif re.match(r"^\s*\d+[.)] ", ln):
            num = re.match(r"^\s*(\d+)[.)] ", ln).group(1)
            story.append(Paragraph(_inline(re.sub(r"^\s*\d+[.)] ", "", ln)), bullet, bulletText=f"{num}."))
        elif ln.strip():
            story.append(Paragraph(_inline(ln), body))
        i += 1
    for spec in charts:
        story += [Spacer(1, 10), Paragraph(_inline(spec["title"]), h3), _chart(spec)]
        legend = " &nbsp; ".join(f'<font color="{PALETTE[k % 6]}">&#9632;</font> {escape(_safe(str(s)))}'
                                 for k, s in enumerate(spec["series"][:6]))
        story.append(Paragraph(legend, ParagraphStyle("lg", parent=body, fontSize=8)))
    SimpleDocTemplate(path, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                      title=_safe(title), author="AgentFlow").build(story)
