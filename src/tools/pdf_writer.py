"""
pdf_writer.py — "PDF Service": ghép nội dung + hình + bảng + trích dẫn thành 1 file PDF
hoàn chỉnh bằng ReportLab (THUẦN PYTHON, không cần cài LaTeX/MiKTeX/pdflatex).

Đây là đường PDF CHÍNH (luôn chạy được, không phụ thuộc binary ngoài). Đường LaTeX
(pdf_compiler.py + templates/paper.tex.j2) vẫn giữ lại làm lựa chọn PHỤ cho ai cần
file .tex thật để nộp tạp chí/hội nghị hoặc chỉnh sửa trên Overleaf.

Input: text thô từ WriterAgent (có **bold**, - bullet, \\cite{key}, $math$) — cùng
định dạng trung gian đã dùng cho đường LaTeX, nên KHÔNG cần sửa gì ở agents/writer.py.

Font: nhúng DejaVu Sans (có sẵn trong gói matplotlib, không cần cài thêm) để hiển thị đúng
TIẾNG VIỆT có dấu và ký hiệu toán (ℝ, Δ, ≪, ≥...). Nếu không tìm thấy font -> fallback Helvetica.
"""
from __future__ import annotations

import io
import os
import re
import threading

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether,
    NextPageTemplate, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from src.tools.arxiv_search import Paper
from src.tools.bibliography import _CITE_RE

NAVY = colors.HexColor("#1E2761")
AMBER = colors.HexColor("#F2A93B")
INK = colors.HexColor("#22273A")
MUTED = colors.HexColor("#6B7290")
ROW_ALT = colors.HexColor("#F3F5FB")

PAGE_W, PAGE_H = A4
MARGIN = 2.1 * cm
CONTENT_W = PAGE_W - 2 * MARGIN

SECTION_TITLES = {
    "introduction": "1. Introduction",
    "related_work": "2. Related Work",
    "methodology": "3. Methodology",
    "experimental_design": "4. Experimental Design",
    "conclusion": "5. Conclusion",
}
SECTION_ORDER = ["abstract", "introduction", "related_work", "methodology",
                  "experimental_design", "conclusion"]

FIGURE_AFTER = {"related_work": ["fig_trend.png", "fig_terms.png"], "methodology": ["fig_pipeline.png"]}
TABLE_AFTER = {"related_work": "comparison", "experimental_design": "eval_plan"}


# --------------------------------------------------------------------------- fonts
_FONTS: dict[str, str] | None = None
_FONT_LOCK = threading.Lock()


def _setup_fonts() -> dict[str, str]:
    """Đăng ký font Unicode 1 lần. Trả về dict tên font: regular/bold/italic/mono."""
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    with _FONT_LOCK:
        if _FONTS is None:
            _FONTS = _register_fonts()
    return _FONTS


def _register_fonts() -> dict[str, str]:
    global _FONTS
    fallback = {"regular": "Helvetica", "bold": "Helvetica-Bold",
                "italic": "Helvetica-Oblique", "mono": "Courier"}
    try:
        import matplotlib
        d = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        files = {
            "DejaVuSans": "DejaVuSans.ttf",
            "DejaVuSans-Bold": "DejaVuSans-Bold.ttf",
            "DejaVuSans-Oblique": "DejaVuSans-Oblique.ttf",
            "DejaVuSans-BoldOblique": "DejaVuSans-BoldOblique.ttf",
            "DejaVuSansMono": "DejaVuSansMono.ttf",
        }
        if not all(os.path.exists(os.path.join(d, f)) for f in files.values()):
            return fallback
        for name, fn in files.items():
            pdfmetrics.registerFont(TTFont(name, os.path.join(d, fn)))
        pdfmetrics.registerFontFamily(
            "DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold",
            italic="DejaVuSans-Oblique", boldItalic="DejaVuSans-BoldOblique",
        )
        return {"regular": "DejaVuSans", "bold": "DejaVuSans-Bold",
                "italic": "DejaVuSans-Oblique", "mono": "DejaVuSansMono"}
    except Exception:  # noqa: BLE001 — mọi lỗi font đều fallback, không được làm hỏng việc xuất PDF
        return fallback


# --------------------------------------------------------------------------- styles
def _styles():
    f = _setup_fonts()
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("PaperTitle", parent=ss["Title"], fontName=f["bold"],
                           fontSize=18, leading=23, textColor=NAVY, spaceAfter=6, alignment=TA_CENTER))
    ss.add(ParagraphStyle("Author", parent=ss["Normal"], fontName=f["regular"],
                           fontSize=10.5, textColor=MUTED, alignment=TA_CENTER, spaceAfter=3))
    ss.add(ParagraphStyle("Meta", parent=ss["Normal"], fontName=f["italic"],
                           fontSize=8.5, leading=11.5, textColor=MUTED, alignment=TA_CENTER, spaceAfter=14))
    ss.add(ParagraphStyle("H1", parent=ss["Heading1"], fontName=f["bold"],
                           fontSize=13, textColor=NAVY, spaceBefore=16, spaceAfter=8, keepWithNext=True))
    ss.add(ParagraphStyle("AbstractHead", parent=ss["Heading2"], fontName=f["bold"],
                           fontSize=11, textColor=NAVY, spaceBefore=6, spaceAfter=6, alignment=TA_CENTER))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontName=f["regular"],
                           fontSize=9.5, leading=14.5, textColor=INK, alignment=TA_JUSTIFY, spaceAfter=7))
    ss.add(ParagraphStyle("PaperBullet", parent=ss["Body"], spaceAfter=3, leftIndent=14,
                           bulletIndent=0, spaceBefore=1))
    ss.add(ParagraphStyle("Caption", parent=ss["Normal"], fontName=f["regular"], fontSize=8.2,
                           leading=10.5, textColor=MUTED, alignment=TA_CENTER, spaceBefore=5, spaceAfter=14))
    ss.add(ParagraphStyle("TableCell", parent=ss["Normal"], fontName=f["regular"], fontSize=7.8,
                           leading=10.5, textColor=INK))
    ss.add(ParagraphStyle("TableHead", parent=ss["Normal"], fontName=f["bold"], fontSize=8,
                           leading=10.5, textColor=colors.white))
    ss.add(ParagraphStyle("Ref", parent=ss["Normal"], fontName=f["regular"], fontSize=8.3,
                           leading=12, textColor=INK, spaceAfter=5, leftIndent=16, firstLineIndent=-16))
    return ss


# --------------------------------------------------------------------------- escape + markup
_XML_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def _xesc(s: str) -> str:
    return re.sub(r"[&<>]", lambda m: _XML_ESC[m.group(0)], s)


_MATH_CMDS = {
    r"\geq": "&#8805;", r"\leq": "&#8804;", r"\approx": "&#8776;", r"\neq": "&#8800;",
    r"\rightarrow": "&#8594;", r"\to": "&#8594;", r"\leftarrow": "&#8592;",
    r"\leftrightarrow": "&#8596;", r"\times": "&#215;", r"\pm": "&#177;",
    r"\infty": "&#8734;", r"\in": "&#8712;", r"\sim": "&#8764;", r"\cdot": "&#183;",
    r"\sum": "&#8721;", r"\sqrt": "&#8730;", r"\ldots": "&#8230;", r"\cdots": "&#8943;",
    r"\alpha": "&#945;", r"\beta": "&#946;", r"\gamma": "&#947;", r"\delta": "&#948;",
    r"\epsilon": "&#949;", r"\theta": "&#952;", r"\lambda": "&#955;", r"\mu": "&#956;",
    r"\sigma": "&#963;", r"\phi": "&#966;", r"\omega": "&#969;", r"\Delta": "&#916;",
    r"\Sigma": "&#931;", r"\Omega": "&#937;", r"\pi": "&#960;", r"\tau": "&#964;",
    r"\mathbb{R}": "&#8477;", r"\mathbb{N}": "&#8469;", r"\mathbb{Z}": "&#8484;",
    r"\ll": "&#8810;", r"\gg": "&#8811;",
}
_MATH_SYMBOLS = {
    "≥": "&#8805;", "≤": "&#8804;", "≈": "&#8776;", "≠": "&#8800;", "→": "&#8594;",
    "←": "&#8592;", "×": "&#215;", "±": "&#177;", "∞": "&#8734;", "°": "&#176;",
    "∈": "&#8712;", "∼": "&#8764;", "µ": "&#956;", "μ": "&#956;", "α": "&#945;",
    "β": "&#946;", "γ": "&#947;", "δ": "&#948;", "θ": "&#952;", "λ": "&#955;",
    "σ": "&#963;", "–": "&#8211;", "—": "&#8212;", "…": "&#8230;",
}


def _math_plain(expr: str) -> str:
    """Chuyển nội dung $...$ sang text thường: lệnh LaTeX -> ký tự Unicode, ^/_ -> chỉ số trên/dưới."""
    for cmd, ent in sorted(_MATH_CMDS.items(), key=lambda kv: -len(kv[0])):
        expr = expr.replace(cmd, ent)
    expr = re.sub(r"\^\{?(-?[\w&#;]+)\}?", r"<super>\1</super>", expr)
    expr = re.sub(r"_\{?(-?[\w&#;]+)\}?", r"<sub>\1</sub>", expr)
    return expr.replace("{", "").replace("}", "").replace("\\", "")


def _inline_markup(seg: str) -> str:
    """markdown-ish (ĐÃ escape sẵn, có thể đã chèn thẻ <link> hợp lệ) -> ReportLab mini-XML.
    LƯU Ý: không được gọi _xesc() ở đây — phải escape TRƯỚC khi chèn <link> trích dẫn,
    nếu không thẻ vừa chèn sẽ bị escape lần 2 thành text thô (xem _para())."""
    mono = _setup_fonts()["mono"]
    seg = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", seg, flags=re.S)
    seg = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", seg)
    seg = re.sub(r"`([^`\n]+)`", rf"<font face='{mono}'>\1</font>", seg)
    seg = re.sub(r"\$([^$\n]+?)\$", lambda m: _math_plain(m.group(1)), seg)
    for sym, ent in _MATH_SYMBOLS.items():
        seg = seg.replace(sym, ent)
    return seg


def _make_cite_replacer(key_to_num: dict[str, int]):
    def repl(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(1).split(",") if k.strip() in key_to_num]
        if not keys:
            return ""
        nums = sorted({key_to_num[k] for k in keys})
        inner = ",".join(f'<link href="#ref{n}" color="#1C7293">{n}</link>' for n in nums)
        return f"<font color='#1C7293'>[{inner}]</font>"
    return repl


def _section_flowables(text: str, key_to_num: dict[str, int], styles) -> list:
    """Chuyển 1 section (raw text từ WriterAgent) -> list[Flowable] cho ReportLab."""
    text = (text or "").strip()
    text = re.sub(r"\\(begin|end)\{(itemize|enumerate|abstract)\}", "", text)
    text = re.sub(r"\\item\s+", "- ", text)
    cite_repl = _make_cite_replacer(key_to_num)

    flows: list = []
    bullet_buf: list[str] = []

    def _para(s: str) -> str:
        s = _xesc(s)  # escape & < > TRƯỚC — để thẻ <link> chèn ở bước sau không bị escape lại
        s = re.sub(r"\\cite[a-z]*\*?\{([^}]*)\}", cite_repl, s)
        s = re.sub(r"\s+([.,;:])", r"\1", s)  # citation bị xoá (key lạ) không để lại khoảng trắng thừa
        return _inline_markup(s)

    def flush_bullets():
        if bullet_buf:
            for b in bullet_buf:
                flows.append(Paragraph(f"&#8226;&nbsp;&nbsp;{_para(b)}", styles["PaperBullet"]))
            flows.append(Spacer(1, 3))
            bullet_buf.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        bm = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*\S)\s*$", line)
        if bm:
            bullet_buf.append(bm.group(1))
            continue
        flush_bullets()
        pm = re.match(r"^\\paragraph\{([^}]*)\}\s*(.*)$", line)
        if pm:
            flows.append(Paragraph(f"<b>{_xesc(pm.group(1))}.</b> {_para(pm.group(2))}", styles["Body"]))
            continue
        hm = re.match(r"^#{1,6}\s*(.+?)\s*$", line)
        if hm:
            flows.append(Paragraph(f"<b>{_para(hm.group(1))}</b>", styles["Body"]))
            continue
        flows.append(Paragraph(_para(line), styles["Body"]))
    flush_bullets()
    return flows



# --------------------------------------------------------------------------- tiền xử lý text thô
_SECTION_WORDS = {"abstract", "introduction", "related work", "methodology", "methods", "method",
                  "experimental design", "experiments", "conclusion", "conclusions"}


def prepare_raw_section(text: str, valid_keys: set[str]) -> str:
    """Làm sạch nhẹ text thô của LLM cho đường PDF: bỏ <think>, code fence, tiêu đề trùng tên
    section, và XOÁ mọi \\cite{key} không hợp lệ (chống trích dẫn bịa)."""
    from src.tools.bibliography import strip_unknown_cites

    t = (text or "").replace("\r\n", "\n")
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"^```[a-zA-Z]*\s*$", "", t, flags=re.M)
    t = re.sub(r"\\(begin|end)\{abstract\}", "", t)
    t = re.sub(r"^\s*\\section\*?\{[^}]*\}\s*$", "", t, flags=re.M)
    kept = []
    for line in t.split("\n"):
        bare = re.sub(r"^[#\s*]+|[*:\s]+$", "", line).lower()
        if bare in _SECTION_WORDS:
            continue
        kept.append(line)
    t = "\n".join(kept)
    t, _removed = strip_unknown_cites(t, valid_keys)
    return re.sub(r"\n{3,}", "\n\n", t).strip()

# --------------------------------------------------------------------------- citation numbering
def assign_citation_numbers(sections: dict[str, str], valid_keys: set[str]) -> dict[str, int]:
    """Đánh số trích dẫn [1],[2].. theo ĐÚNG thứ tự xuất hiện lần đầu trong bài (chuẩn khoa học).

    LƯU Ý: không dùng bibliography.extract_cites() ở đây vì hàm đó trả về set (không giữ
    thứ tự) — phải quét tuần tự bằng finditer() để thứ tự số trích dẫn khớp với văn bản."""
    key_to_num: dict[str, int] = {}
    for name in SECTION_ORDER:
        for m in _CITE_RE.finditer(sections.get(name, "")):
            for key in (k.strip() for k in m.group(1).split(",")):
                if key in valid_keys and key not in key_to_num:
                    key_to_num[key] = len(key_to_num) + 1
    return key_to_num


# --------------------------------------------------------------------------- tables
def _wrap_table(headers: list[str], rows: list[list[str]], col_widths: list[float], styles) -> Table:
    head = [Paragraph(_xesc(h), styles["TableHead"]) for h in headers]
    body = [[Paragraph(_xesc(c), styles["TableCell"]) for c in r] for r in rows]
    data = [head] + body
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 0.6, MUTED),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


def _comparison_table(papers: list[Paper], rows: list[dict], key_to_num: dict[str, int], styles) -> Table | None:
    by_key = {p.key: p for p in papers}
    out = []
    for r in rows:
        p = by_key.get(r.get("key", ""))
        if p is None or p.key not in key_to_num:
            continue
        out.append((key_to_num[p.key], [f"[{key_to_num[p.key]}]", str(p.year or "—"),
                                         r.get("approach", ""), r.get("limitation", "")]))
    if not out:
        return None
    out.sort(key=lambda x: x[0])
    rest = CONTENT_W - 2.8 * cm
    return _wrap_table(["Ref", "Year", "Approach", "Limitation"], [r for _, r in out],
                       [1.3 * cm, 1.5 * cm, rest * 0.52, rest * 0.48], styles)


def _eval_table(rows: list[dict], styles) -> Table | None:
    if not rows:
        return None
    out = [[r.get("hypothesis", ""), r.get("baseline", ""), r.get("metric", ""), r.get("dataset", "")]
           for r in rows]
    w = CONTENT_W / 4
    return _wrap_table(["Hyp.", "Baseline", "Metric", "Dataset"], out, [w * 0.6, w * 1.3, w * 1.1, w], styles)


# --------------------------------------------------------------------------- figures
def _figure_flowable(png_bytes: bytes, caption: str, styles, max_w: float = CONTENT_W, max_h: float = 7.5 * cm):
    reader = ImageReader(io.BytesIO(png_bytes))
    iw, ih = reader.getSize()
    scale = min(max_w / iw, max_h / ih)
    img = Image(io.BytesIO(png_bytes), width=iw * scale, height=ih * scale)
    img.hAlign = "CENTER"
    return KeepTogether([img, Paragraph(caption, styles["Caption"])])


# --------------------------------------------------------------------------- page chrome
def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(_setup_fonts()["regular"], 8)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(PAGE_W / 2, 1.2 * cm, str(doc.page))
    canvas.restoreState()


def _footer_first(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(AMBER)
    canvas.rect(0, PAGE_H - 0.35 * cm, PAGE_W, 0.35 * cm, stroke=0, fill=1)
    canvas.restoreState()
    _footer(canvas, doc)


# --------------------------------------------------------------------------- main entry
def build_pdf(
    title: str,
    topic: str,
    sections: dict[str, str],
    papers: list[Paper],
    comparison_rows: list[dict],
    eval_rows: list[dict],
    figures: dict[str, bytes],
    author: str = "Automated Research System",
) -> bytes:
    """Ghép toàn bộ nội dung + hình + bảng + trích dẫn thành 1 file PDF hoàn chỉnh.
    Trả về bytes PDF — KHÔNG cần cài LaTeX/pdflatex/tectonic."""
    styles = _styles()
    valid_keys = {p.key for p in papers}
    key_to_num = assign_citation_numbers(sections, valid_keys)

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                           topMargin=1.6 * cm, bottomMargin=1.8 * cm, title=title, author=author)
    frame = Frame(MARGIN, 1.8 * cm, CONTENT_W, PAGE_H - 1.6 * cm - 1.8 * cm, id="main")
    doc.addPageTemplates([
        PageTemplate(id="first", frames=[frame], onPage=_footer_first),
        PageTemplate(id="later", frames=[frame], onPage=_footer),
    ])

    story: list = [NextPageTemplate("later")]
    story.append(Paragraph(_xesc(title), styles["PaperTitle"]))
    story.append(Paragraph(_xesc(author), styles["Author"]))
    story.append(Paragraph(
        "Literature-based research proposal — generated with assistance from an automated "
        "research-writing system. No experiments were executed; no empirical results are reported.",
        styles["Meta"],
    ))

    story.append(Paragraph("ABSTRACT", styles["AbstractHead"]))
    story += _section_flowables(sections.get("abstract", ""), key_to_num, styles)
    story.append(Spacer(1, 8))

    fig_no = 0
    for name in SECTION_ORDER[1:]:
        if name not in sections:
            continue
        story.append(Paragraph(SECTION_TITLES.get(name, name.title()), styles["H1"]))
        story += _section_flowables(sections[name], key_to_num, styles)

        table_kind = TABLE_AFTER.get(name)
        if table_kind == "comparison":
            t = _comparison_table(papers, comparison_rows, key_to_num, styles)
            if t:
                story += [Spacer(1, 4), t, Paragraph(
                    "Table 1. Comparison of related work discussed above "
                    "(approach/limitation summarized from each paper's abstract).", styles["Caption"])]
        elif table_kind == "eval_plan":
            t = _eval_table(eval_rows, styles)
            if t:
                story += [Spacer(1, 4), t, Paragraph(
                    "Table 2. Proposed evaluation protocol. No empirical results are reported "
                    "in this manuscript.", styles["Caption"])]

        for fig_name in FIGURE_AFTER.get(name, []):
            if fig_name in figures:
                fig_no += 1  # đánh số động: hình nào bị bỏ (thiếu dữ liệu) thì số không bị nhảy cóc
                text = {
                    "fig_trend.png": f"Number of retrieved papers per publication year for "
                                     f"\u201c{_xesc(topic)}\u201d (counts from arXiv metadata).",
                    "fig_terms.png": "Most frequent terms across the abstracts of the retrieved papers.",
                    "fig_pipeline.png": "Overview of the proposed research pipeline (conceptual diagram).",
                }.get(fig_name, fig_name)
                story += [Spacer(1, 2), _figure_flowable(figures[fig_name], f"Figure {fig_no}. {text}", styles)]

    if key_to_num:
        story.append(Paragraph("References", styles["H1"]))
        by_key = {p.key: p for p in papers}
        for key, num in sorted(key_to_num.items(), key=lambda x: x[1]):
            p = by_key.get(key)
            if not p:
                continue
            authors = ", ".join(p.authors[:4]) + (" et al." if p.more_authors else "")
            story.append(Paragraph(
                f'<a name="ref{num}"/>[{num}] {_xesc(authors)}. <i>{_xesc(p.title)}</i>. '
                f'{p.year}. <link href="{_xesc(p.url)}" color="#1C7293">{_xesc(p.url)}</link>',
                styles["Ref"],
            ))

    doc.build(story)
    return buf.getvalue()
