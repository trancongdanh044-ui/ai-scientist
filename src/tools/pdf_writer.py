"""pdf_writer.py — PDF dự phòng HAI CỘT mô phỏng bài mẫu "Neural Collaborative Filtering" (ReportLab).

Dùng khi máy KHÔNG có LaTeX (hoặc LaTeX thất bại). Khi có LaTeX, paper.pdf đến từ
templates/paper_acm.tex.j2 (đẹp hơn, công thức do LaTeX dàn trang). Đường này bắt chước cùng quy tắc:
  - tiêu đề sans đậm căn giữa + tác giả 3 người/hàng (tên, đơn vị, quốc gia, email), thân bài HAI CỘT;
  - ABSTRACT / Keywords ở cột trái; đề mục "1. INTRODUCTION", "3.1 General Framework" (đậm),
    "3.1.1 Tên" (đậm nghiêng); thứ tự mục như bài mẫu (Related Work sau Experiments);
  - công thức hiển thị vẽ thành ảnh (matplotlib mathtext), đánh số (1), (2)... căn phải;
  - "Figure n: ..." dưới hình, "Table n: ..." trên bảng (đậm, sans); trích dẫn [n];
  - REFERENCES đánh số theo thứ tự chữ cái của họ tác giả đầu: "A. B. Author. Title. In VENUE, year.".
"""
from __future__ import annotations

import html
import io
import os
import re
import threading
import unicodedata
from functools import lru_cache

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, FrameBreak, Image, KeepTogether, NextPageTemplate, PageTemplate,
    Paragraph, Preformatted, Spacer, Table, TableStyle,
)

from src.tools.arxiv_search import Paper
from src.tools.bibliography import _CITE_RE, ieee_author

INK = colors.HexColor("#111111")
MUTED = colors.HexColor("#444444")
RULE = colors.HexColor("#222222")
LINK = "#1C4E80"

PAGE_W, PAGE_H = A4
M_LR, M_TOP, M_BOT, GAP = 1.65 * cm, 1.9 * cm, 2.3 * cm, 0.6 * cm
CONTENT_W = PAGE_W - 2 * M_LR
COL_W = (CONTENT_W - GAP) / 2

ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


# --------------------------------------------------------------------------- fonts
_FONTS: dict[str, str] | None = None
_LOCK = threading.Lock()


def _fonts() -> dict[str, str]:
    global _FONTS
    with _LOCK:
        if _FONTS is None:
            _FONTS = _register_fonts()
    return _FONTS


def _register_fonts() -> dict[str, str]:
    fallback = {"body": "Times-Roman", "bold": "Times-Bold", "italic": "Times-Italic",
                "bolditalic": "Times-BoldItalic", "mono": "Courier", "sans": "Helvetica",
                "sansbold": "Helvetica-Bold"}
    try:
        import matplotlib
        d = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
        files = {
            "DejaVuSerif": "DejaVuSerif.ttf", "DejaVuSerif-Bold": "DejaVuSerif-Bold.ttf",
            "DejaVuSerif-Italic": "DejaVuSerif-Italic.ttf",
            "DejaVuSerif-BoldItalic": "DejaVuSerif-BoldItalic.ttf",
            "DejaVuSansMono": "DejaVuSansMono.ttf", "DejaVuSans": "DejaVuSans.ttf",
            "DejaVuSans-Bold": "DejaVuSans-Bold.ttf",
        }
        if not all(os.path.exists(os.path.join(d, f)) for f in files.values()):
            return fallback
        for name, fn in files.items():
            pdfmetrics.registerFont(TTFont(name, os.path.join(d, fn)))
        pdfmetrics.registerFontFamily("DejaVuSerif", normal="DejaVuSerif", bold="DejaVuSerif-Bold",
                                      italic="DejaVuSerif-Italic", boldItalic="DejaVuSerif-BoldItalic")
        return {"body": "DejaVuSerif", "bold": "DejaVuSerif-Bold", "italic": "DejaVuSerif-Italic",
                "bolditalic": "DejaVuSerif-BoldItalic", "mono": "DejaVuSansMono", "sans": "DejaVuSans",
                "sansbold": "DejaVuSans-Bold"}
    except Exception:  # noqa: BLE001 — lỗi font không được làm hỏng việc xuất PDF
        return fallback


def _styles():
    f = _fonts()
    ss = getSampleStyleSheet()
    add = ss.add
    add(ParagraphStyle("PTitle", parent=ss["Title"], fontName=f["sansbold"], fontSize=14.5, leading=18,
                       textColor=INK, alignment=TA_CENTER, spaceAfter=8))
    add(ParagraphStyle("AuthN", parent=ss["Normal"], fontName=f["sans"], fontSize=10.5, leading=13,
                       alignment=TA_CENTER, textColor=INK))
    add(ParagraphStyle("AuthA", parent=ss["Normal"], fontName=f["sans"], fontSize=7.8, leading=9.6,
                       alignment=TA_CENTER, textColor=INK))
    add(ParagraphStyle("AuthE", parent=ss["Normal"], fontName=f["sans"], fontSize=8.6, leading=10.4,
                       alignment=TA_CENTER, textColor=INK))
    add(ParagraphStyle("Foot", parent=ss["Normal"], fontName=f["body"], fontSize=7, leading=8.4,
                       textColor=INK, alignment=TA_JUSTIFY))
    add(ParagraphStyle("Abs", parent=ss["Normal"], fontName=f["body"], fontSize=8.1, leading=10,
                       textColor=INK, alignment=TA_JUSTIFY, spaceAfter=3))
    add(ParagraphStyle("Body", parent=ss["Normal"], fontName=f["body"], fontSize=8.1, leading=10,
                       textColor=INK, alignment=TA_JUSTIFY, spaceAfter=0, firstLineIndent=9))
    add(ParagraphStyle("BodyNI", parent=ss["Body"], firstLineIndent=0))
    add(ParagraphStyle("Bul", parent=ss["Body"], firstLineIndent=0, leftIndent=12, spaceAfter=1.5))
    add(ParagraphStyle("H1", parent=ss["Normal"], fontName=f["bold"], fontSize=10, leading=12,
                       alignment=TA_LEFT, spaceBefore=11, spaceAfter=5, textColor=INK, keepWithNext=True))
    add(ParagraphStyle("H2", parent=ss["Normal"], fontName=f["bold"], fontSize=9.6, leading=11.5,
                       alignment=TA_LEFT, spaceBefore=8, spaceAfter=4, textColor=INK, keepWithNext=True))
    add(ParagraphStyle("H3", parent=ss["Normal"], fontName=f["bolditalic"], fontSize=8.6, leading=10.5,
                       alignment=TA_LEFT, spaceBefore=6, spaceAfter=3, textColor=INK, keepWithNext=True))
    add(ParagraphStyle("Cap", parent=ss["Normal"], fontName=f["sansbold"], fontSize=6.9, leading=8.4,
                       alignment=TA_JUSTIFY, textColor=INK, spaceBefore=3, spaceAfter=8))
    add(ParagraphStyle("CapC", parent=ss["Cap"], alignment=TA_CENTER))
    add(ParagraphStyle("CapT", parent=ss["Cap"], spaceBefore=4, spaceAfter=3))
    add(ParagraphStyle("CapTC", parent=ss["CapT"], alignment=TA_CENTER))
    add(ParagraphStyle("Cell", parent=ss["Normal"], fontName=f["body"], fontSize=6.6, leading=7.9,
                       textColor=INK))
    add(ParagraphStyle("CellH", parent=ss["Cell"], fontName=f["bold"], fontSize=6.0, leading=7.2))
    add(ParagraphStyle("Ref", parent=ss["Normal"], fontName=f["body"], fontSize=7, leading=8.5,
                       textColor=INK, alignment=TA_JUSTIFY, leftIndent=16, firstLineIndent=-16,
                       spaceAfter=2.2))
    add(ParagraphStyle("CodeX", parent=ss["Normal"], fontName=f["mono"], fontSize=6.4, leading=7.6,
                       textColor=INK))
    return ss


# --------------------------------------------------------------------------- math: nội dòng
_X = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def _x(s: str) -> str:
    return re.sub(r"[&<>]", lambda m: _X[m.group(0)], s)


_FUNCS = {"log", "ln", "exp", "sin", "cos", "tan", "tanh", "sinh", "cosh", "max", "min", "sup", "inf",
          "lim", "arg", "det", "dim", "Pr", "softmax", "sigmoid", "ReLU", "argmax", "argmin", "mod"}
_REL = {"leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠", "approx": "≈", "sim": "∼",
        "simeq": "≃", "equiv": "≡", "propto": "∝", "in": "∈", "notin": "∉", "subset": "⊂",
        "subseteq": "⊆", "supset": "⊃", "supseteq": "⊇", "rightarrow": "→", "to": "→",
        "leftarrow": "←", "Rightarrow": "⇒", "Leftarrow": "⇐", "leftrightarrow": "↔", "mapsto": "↦",
        "ll": "≪", "gg": "≫", "implies": "⇒", "iff": "⇔", "perp": "⊥", "mid": "|", "pm": "±",
        "mp": "∓", "times": "×", "cdot": "·", "circ": "∘", "odot": "⊙", "oplus": "⊕", "otimes": "⊗",
        "cup": "∪", "cap": "∩", "setminus": "∖", "wedge": "∧", "vee": "∨"}
_SYM = {"sum": "∑", "prod": "∏", "int": "∫", "infty": "∞", "partial": "∂", "nabla": "∇",
        "forall": "∀", "exists": "∃", "emptyset": "∅", "varnothing": "∅", "ell": "ℓ", "hbar": "ℏ",
        "ldots": "…", "cdots": "⋯", "dots": "…", "vdots": "⋮", "ddots": "⋱", "prime": "′",
        "top": "⊤", "bot": "⊥", "angle": "∠", "star": "⋆", "ast": "∗", "bullet": "•",
        "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
        "Vert": "‖", "lVert": "‖", "rVert": "‖", "vert": "|", "lvert": "|", "rvert": "|",
        "lbrace": "{", "rbrace": "}", "neg": "¬", "R": "ℝ", "E": "𝔼"}
_GREEK = {n: c for n, c in zip(
    "alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi "
    "rho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma "
    "Upsilon Phi Psi Omega".split(),
    "αβγδεεζηθϑικλμνξπρσςτυφφχψωΓΔΘΛΞΠΣΥΦΨΩ")}
_CAL = dict(zip("LHFREBIMPNDAC", "ℒℋℱℛℰℬℐℳ𝒫𝒩𝒟𝒜𝒞"))
_BB = {"R": "ℝ", "N": "ℕ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ", "P": "ℙ", "H": "ℍ"}
_ACCENT = {"hat": "\u0302", "widehat": "\u0302", "tilde": "\u0303", "widetilde": "\u0303",
           "bar": "\u0304", "overline": "\u0304", "vec": "\u20d7", "dot": "\u0307", "ddot": "\u0308"}
_SKIP_CMDS = {"left", "right", "big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl",
              "biggr", "limits", "nolimits", "displaystyle", "textstyle", "nonumber", "notag", "not",
              "hline", "tiny", "small", "bm", "boldsymbol_"}


def _read_arg(s: str, i: int) -> tuple[str, int]:
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return s[i + 1: j], j + 1
            j += 1
        return s[i + 1:], len(s)
    if s[i] == "\\":
        m = re.match(r"\\[A-Za-z]+", s[i:])
        n = len(m.group(0)) if m else 2
        return s[i: i + n], i + n
    return s[i], i + 1


def _m(s: str, ital: bool = True) -> str:
    """LaTeX math -> mini-XML của ReportLab (đã escape). Không bao giờ để lộ dấu '\\'."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)", s[i:])
            if not m:
                nxt = s[i + 1: i + 2]
                i += 2
                if nxt in ",;: ":
                    out.append("\u2009")
                elif nxt == "!":
                    pass
                elif nxt == "\\":
                    out.append(" ")
                elif nxt == "|":
                    out.append("‖")
                elif nxt in "{}%&#_$":
                    out.append(_x(nxt))
                continue
            cmd = m.group(1)
            i += len(m.group(0))
            if cmd in ("left", "right") and i < n and s[i] == ".":
                i += 1
            if cmd in _SKIP_CMDS:
                continue
            if cmd in ("quad", "qquad"):
                out.append("\u2003" * (2 if cmd == "qquad" else 1))
            elif cmd in _FUNCS:
                out.append(cmd if cmd not in ("argmax", "argmin") else ("arg\u2009" + cmd[3:]))
            elif cmd in _GREEK:
                out.append(_GREEK[cmd] if ital else _GREEK[cmd])
            elif cmd in _REL:
                out.append("\u2009" + _REL[cmd] + "\u2009")
            elif cmd in _SYM:
                out.append(_SYM[cmd])
            elif cmd in ("frac", "dfrac", "tfrac", "binom"):
                a, i = _read_arg(s, i)
                b, i = _read_arg(s, i)
                A, B = _m(a, ital), _m(b, ital)
                simple = lambda t: len(re.sub(r"<[^>]+>", "", t)) <= 2  # noqa: E731
                A = A if simple(A) else f"({A})"
                B = B if simple(B) else f"({B})"
                out.append(f"{A}/{B}" if cmd != "binom" else f"({A} {B})")
            elif cmd == "sqrt":
                a, i = _read_arg(s, i)
                out.append("√(" + _m(a, ital) + ")")
            elif cmd in _ACCENT:
                a, i = _read_arg(s, i)
                inner = _m(a, ital)
                plain = re.sub(r"<[^>]+>", "", html.unescape(inner))
                if len(plain) == 1 and plain.isalpha():
                    comp = unicodedata.normalize("NFC", plain + _ACCENT[cmd])
                    out.append(f"<i>{_x(comp)}</i>" if ital and len(comp) == 1 else inner + _ACCENT[cmd])
                else:
                    out.append(inner + _ACCENT[cmd])
            elif cmd in ("mathbf", "textbf", "boldsymbol", "bm", "mathbold"):
                a, i = _read_arg(s, i)
                out.append("<b>" + _m(a, False) + "</b>")
            elif cmd == "mathcal":
                a, i = _read_arg(s, i)
                out.append("".join(_CAL.get(ch, f"<i>{ch}</i>") for ch in a if not ch.isspace()))
            elif cmd == "mathbb":
                a, i = _read_arg(s, i)
                out.append("".join(_BB.get(ch, f"<b>{ch}</b>") for ch in a if not ch.isspace()))
            elif cmd in ("text", "mathrm", "textrm", "operatorname", "mathsf", "mathtt", "textsf",
                         "texttt"):
                a, i = _read_arg(s, i)
                out.append(_m(a, False))
            elif cmd in ("textit", "mathit", "emph"):
                a, i = _read_arg(s, i)
                out.append("<i>" + _m(a, False) + "</i>")
            elif cmd in ("label", "tag", "begin", "end", "hspace", "vspace", "phantom"):
                _, i = _read_arg(s, i)
            else:  # lệnh lạ -> in tên thường, tuyệt đối không in dấu '\'
                out.append(_x(cmd))
        elif c in "^_":
            a, i2 = _read_arg(s, i + 1)
            tag = "super" if c == "^" else "sub"
            inner = _m(a, ital)
            out.append(f"<{tag}>{inner}</{tag}>" if inner else "")
            i = i2
        elif c in "{}":
            i += 1
        elif c.isalpha():
            j = i
            while j < n and s[j].isalpha():
                j += 1
            run = s[i:j]
            out.append(f"<i>{_x(run)}</i>" if ital else _x(run))
            i = j
        elif c == "=":
            out.append("\u2009=\u2009")
            i += 1
        elif c == "~":
            out.append("\u00a0")
            i += 1
        else:
            out.append(_x(c))
            i += 1
    return "".join(out)


def _math_markup(body: str) -> str:
    try:
        return _m(html.unescape(body))
    except Exception:  # noqa: BLE001
        return f"<font face='{_fonts()['mono']}'>{_x(body)}</font>"


# --------------------------------------------------------------------------- math: hiển thị (ảnh)
_MT_REPL = [
    (r"\\label\{[^}]*\}", ""), (r"\\(nonumber|notag|limits|nolimits|displaystyle|textstyle)\b", ""),
    (r"\\(?:text|textrm|textit)\{([^{}]*)\}", r"\\mathrm{\1}"), (r"\\textbf\{([^{}]*)\}", r"\\mathbf{\1}"),
    (r"\\(?:bm|boldsymbol)\{", r"\\mathbf{"), (r"\\operatorname\{([^{}]*)\}", r"\\mathrm{\1}"),
    (r"\\argmax\b", r"\\mathrm{arg\\,max}"), (r"\\argmin\b", r"\\mathrm{arg\\,min}"),
    (r"\\softmax\b", r"\\mathrm{softmax}"), (r"\\sigmoid\b", r"\\mathrm{sigmoid}"),
    (r"\\ReLU\b", r"\\mathrm{ReLU}"), (r"\\(?:dfrac|tfrac)\b", r"\\frac"),
    (r"\\(?:left|right)\.", ""), (r"\\(?:bigl|bigr|Bigl|Bigr|biggl|biggr|big|Big|bigg|Bigg)\b", ""),
    (r"\\(?:lVert|rVert)\b", r"\\Vert"), (r"\\(?:lvert|rvert)\b", "|"), (r"\\\|", r"\\Vert "),
    (r"\\(hat|bar|tilde|vec)\s+([A-Za-z])", r"\\\1{\2}"), (r"\\underbrace\{([^{}]*)\}", r"\1"),
    (r"\\mathbb\{E\}", r"\\mathbb{E}"), (r"&", ""),
]


def _to_mathtext(expr: str) -> str:
    e = expr
    for pat, rep in _MT_REPL:
        e = re.sub(pat, rep, e)
    return e.strip()


@lru_cache(maxsize=256)
def _math_png(expr: str) -> tuple[bytes, float, float] | None:
    """Vẽ 1 dòng công thức thành PNG (matplotlib mathtext). None nếu mathtext không hỗ trợ."""
    try:
        from matplotlib.figure import Figure

        fig = Figure(figsize=(0.1, 0.1))
        fig.text(0, 0, f"${_to_mathtext(expr)}$", fontsize=10)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=300, bbox_inches="tight", pad_inches=0.02, transparent=True)
        data = buf.getvalue()
        w, h = ImageReader(io.BytesIO(data)).getSize()
        return data, w / 300 * 72, h / 300 * 72
    except Exception:  # noqa: BLE001
        return None


def _split_lines(body: str) -> list[str]:
    out, depth, cur, i = [], 0, [], 0
    while i < len(body):
        ch = body[i]
        if body.startswith("\\\\", i) and depth == 0:
            out.append("".join(cur))
            cur, i = [], i + 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


# --------------------------------------------------------------------------- văn bản
_DISPLAY_RE = re.compile(r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?)\}(.*?)\\end\{\1\}", re.S)
_CODE_RE = re.compile(r"```(.*?)```", re.S)


class _Ctx:
    """Trạng thái khi dựng truyện (story): đánh số công thức/bảng/hình và nhãn tham chiếu chéo."""

    def __init__(self, key_to_num: dict[str, int], labels_in: dict[str, str]):
        self.key_to_num = key_to_num
        self.labels_in = labels_in          # nhãn đã biết từ lượt dựng trước
        self.labels: dict[str, str] = {}    # nhãn gặp ở lượt này
        self.eq = 0
        self.tab = 0
        self.fig = 0
        self.sec = 0
        self.sub = 0
        self.subsub = 0


def _inline(raw: str, ctx: _Ctx) -> str:
    # ReportLab không có chú thích cuối trang: \footnote{...} -> " (...)"
    raw = re.sub(r"\\footnote\{((?:[^{}]|\{[^{}]*\})*)\}", r" (\1)", raw)
    s = raw.replace("\\$", "\x05")
    maths: list[str] = []

    def hold(m: re.Match) -> str:
        maths.append(_math_markup(m.group(1)))
        return f"\x06{len(maths) - 1}\x06"

    s = re.sub(r"\$([^$\n]+?)\$", hold, s)
    s = _x(s)

    def cite(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(1).split(",") if k.strip() in ctx.key_to_num]
        if not keys:
            return ""
        nums = sorted({ctx.key_to_num[k] for k in keys})
        inner = ", ".join(f'<link href="#ref{n}" color="{LINK}">{n}</link>' for n in nums)
        return f"[{inner}]"

    s = re.sub(r"\\cite[a-z]*\*?\{([^}]*)\}", cite, s)

    def ref(m: re.Match) -> str:
        val = ctx.labels_in.get(m.group(2).strip(), "?")
        return f"({val})" if m.group(1) == "eq" else val

    s = re.sub(r"\\(eq|auto|)ref\{([^}]*)\}", ref, s)
    s = re.sub(r"\s+([.,;:])", r"\1", s)
    s = re.sub(r"\\(?:textbf|mathbf)\{([^{}]*)\}", r"<b>\1</b>", s)
    s = re.sub(r"\\(?:emph|textit)\{([^{}]*)\}", r"<i>\1</i>", s)
    mono = _fonts()["mono"]
    s = re.sub(r"\\texttt\{([^{}]*)\}", rf"<font face='{mono}'>\1</font>", s)
    s = re.sub(r"\\url\{([^{}]*)\}", rf'<link href="\1" color="{LINK}">\1</link>', s)
    s = s.replace("\\%", "%").replace("\\&amp;", "&amp;").replace("\\_", "_").replace("\\#", "#")
    s = s.replace("\\{", "{").replace("\\}", "}").replace("\\ldots{}", "…").replace("\\ldots", "…")
    s = s.replace("---", "—").replace("--", "–").replace("``", "“").replace("''", "”").replace("~", "\u00a0")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s, flags=re.S)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    s = re.sub(r"`([^`\n]+)`", rf"<font face='{mono}'>\1</font>", s)
    s = re.sub(r"\\(?:begin|end)\{[a-z]+\}", "", s)
    s = re.sub(r"\x06(\d+)\x06", lambda m: maths[int(m.group(1))], s)
    return s.replace("\x05", "$")


def _equation(env: str, body: str, ctx: _Ctx, st) -> list:
    lines = _split_lines(body) if env.rstrip("*") in ("align", "gather", "multline") else [body.strip()]
    rows, styles = [], []
    for ln in lines:
        numbered = not env.endswith("*") and not re.search(r"\\(nonumber|notag)\b", ln)
        label = re.search(r"\\label\{([^}]*)\}", ln)
        num = ""
        if numbered:
            ctx.eq += 1
            num = f"({ctx.eq})"
            if label:
                ctx.labels[label.group(1)] = str(ctx.eq)
        png = _math_png(re.sub(r"\\label\{[^}]*\}", "", ln))
        if png:
            data, w, h = png
            max_w = COL_W - 1.6 * cm
            sc = min(1.0, max_w / w)
            cell = Image(io.BytesIO(data), width=w * sc, height=h * sc)
        else:  # mathtext không hỗ trợ -> hiển thị mã nguồn công thức bằng chữ đơn cách
            cell = Paragraph(_x(re.sub(r"\\label\{[^}]*\}", "", ln)), st["CodeX"])
        rows.append(["", cell, Paragraph(num, st["BodyNI"])])
    t = Table(rows, colWidths=[0.5 * cm, COL_W - 2.0 * cm, 1.5 * cm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"), ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [Spacer(1, 2), t, Spacer(1, 2)]


def _heading(ctx: _Ctx, level: int, text: str, st) -> Paragraph:
    """Đề mục có đánh số tự động: 1. INTRODUCTION / 3.1 General Framework / 3.1.1 Learning NCF."""
    if level == 1:
        ctx.sec += 1
        ctx.sub = ctx.subsub = 0
        return Paragraph(f"{ctx.sec}.&nbsp;&nbsp;{_x(text.upper())}", st["H1"])
    if level == 2:
        ctx.sub += 1
        ctx.subsub = 0
        return Paragraph(f"{ctx.sec}.{ctx.sub}&nbsp;&nbsp;{_inline(text, ctx)}", st["H2"])
    ctx.subsub += 1
    return Paragraph(f"{ctx.sec}.{ctx.sub}.{ctx.subsub}&nbsp;&nbsp;{_inline(text, ctx)}", st["H3"])


def _text_flowables(text: str, ctx: _Ctx, st) -> list:
    text = (text or "").strip()
    text = re.sub(r"\\(begin|end)\{(itemize|enumerate)\}", "", text)
    text = re.sub(r"\\item\s+", "- ", text)
    flows: list = []
    bullets: list[str] = []
    first = True

    def flush():
        for b in bullets:
            flows.append(Paragraph("•&nbsp;&nbsp;" + _inline(b, ctx), st["Bul"]))
        if bullets:
            flows.append(Spacer(1, 2))
        bullets.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        bm = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*\S)\s*$", line)
        if bm:
            bullets.append(bm.group(1))
            continue
        flush()
        hm = re.match(r"^\\(subsection|subsubsection)\{(.*)\}\s*$", line)
        if hm:
            flows.append(_heading(ctx, 2 if hm.group(1) == "subsection" else 3, hm.group(2), st))
            first = True
            continue
        pm = re.match(r"^\\paragraph\{([^}]*)\}\s*(.*)$", line)
        if pm:
            flows.append(Paragraph(f"<b>{_x(pm.group(1))}</b> {_inline(pm.group(2), ctx)}", st["Body"]))
        else:
            flows.append(Paragraph(_inline(line, ctx), st["Body"] if not first else st["BodyNI"]))
        first = False
    flush()
    return flows


def _section_flowables(text: str, ctx: _Ctx, st) -> list:
    """Tách khối công thức hiển thị / khối mã (công thức hỏng) / đoạn văn."""
    flows: list = []
    pos = 0
    pieces = sorted([(m.start(), m.end(), "eq", m) for m in _DISPLAY_RE.finditer(text)]
                    + [(m.start(), m.end(), "code", m) for m in _CODE_RE.finditer(text)])
    for a, b, kind, m in pieces:
        flows += _text_flowables(text[pos:a], ctx, st)
        if kind == "eq":
            flows += _equation(m.group(1), m.group(2), ctx, st)
        else:
            flows.append(Preformatted(m.group(1).strip(), st["CodeX"]))
        pos = b
    flows += _text_flowables(text[pos:], ctx, st)
    return flows


# --------------------------------------------------------------------------- bảng / hình / tham khảo
def _grid_table(headers: list[str], rows: list[list[str]], widths: list[float], st) -> Table:
    data = [[Paragraph(h, st["CellH"]) for h in headers]] + [[Paragraph(c, st["Cell"]) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, RULE), ("LINEBELOW", (0, 0), (-1, 0), 0.4, RULE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.8), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return t


def _grid_from(grid, st, first_frac: float = 0.34) -> Table:
    """(header, rows[(text,bold)]) -> bảng ReportLab; '0.730 ± 0.002†' xuống dòng gọn, ô '--' hiện '–'."""
    header, rows = grid
    body = []
    for r in rows:
        row = []
        for txt, bold in r:
            if txt == "--":
                cell = "–"
            elif " ± " in txt:
                mean, std = txt.split(" ± ", 1)
                cell = f"{_x(mean)}<br/><font size='5.6'>±&nbsp;{_x(std)}</font>"
            else:
                cell = _x(txt)
            row.append(f"<b>{cell}</b>" if bold else cell)
        body.append(row)
    n = len(header)
    first = COL_W * (min(first_frac, 0.26) if n > 4 else first_frac if n > 3 else 0.4)
    other = (COL_W - first) / max(1, n - 1)
    heads = [_x(h) if i == 0 or " " not in h else "<br/>".join(_x(h).rsplit(" ", 1)) for i, h in enumerate(header)]
    return _grid_table(heads, body, [first] + [other] * (n - 1), st)


def _titled_table(ctx: _Ctx, label: str, caption: str, table: Table, st) -> list:
    """Caption PHÍA TRÊN, dạng 'Table n: ...' (đậm, sans) như bài mẫu."""
    ctx.tab += 1
    ctx.labels[label] = str(ctx.tab)
    cap = Paragraph(f"Table {ctx.tab}: {caption}", st["CapT"])
    return [KeepTogether([cap, table, Spacer(1, 8)])]


def _figure(ctx: _Ctx, label: str, png: bytes, caption: str, st, max_h: float = 6.0 * cm) -> list:
    """Caption PHÍA DƯỚI, dạng 'Figure n: ...' (đậm, sans) như bài mẫu."""
    ctx.fig += 1
    ctx.labels[label] = str(ctx.fig)
    r = ImageReader(io.BytesIO(png))
    iw, ih = r.getSize()
    sc = min(COL_W / iw, max_h / ih)
    img = Image(io.BytesIO(png), width=iw * sc, height=ih * sc)
    img.hAlign = "CENTER"
    cap_style = st["CapC"] if len(caption) < 46 else st["Cap"]
    return [KeepTogether([img, Paragraph(f"Figure {ctx.fig}: {caption}", cap_style)])]


def _surname(name: str) -> str:
    parts = name.strip().split()
    return parts[-1].lower() if parts else ""


def _sort_key(p: Paper):
    return (_surname(p.authors[0]) if p.authors else "~", p.year, p.title.lower())


def _ref_markup(p: Paper) -> str:
    """'A. B. Author, C. Author, and D. Author. Title. In VENUE, year.' (như danh mục của bài mẫu)."""
    names = [ieee_author(a) for a in p.authors[:6]]
    if p.more_authors or len(p.authors) > 6:
        authors = ", ".join(names[:3]) + " et al"
    elif len(names) > 2:
        authors = ", ".join(names[:-1]) + ", and " + names[-1]
    elif len(names) == 2:
        authors = " and ".join(names)
    else:
        authors = names[0] if names else "Anon"
    if p.kind == "conference" and p.venue:
        where = f"In {_x(p.venue)}, {p.year}"
    elif p.venue:
        where = f"{_x(p.venue)}, {p.year}"
    else:
        where = (f"arXiv preprint arXiv:{_x(p.arxiv_id)}, {p.year}" if p.arxiv_id else f"{p.year}")
    tail = f" doi:{_x(p.doi)}." if p.doi else (f" {_x(p.url)}" if p.url else "")
    return f"{_x(authors)}. {_x(p.title)}. {where}.{tail}"


def assign_citation_numbers(sections: dict[str, str], papers: list[Paper], order: list[str]) -> dict[str, int]:
    """Số trích dẫn theo THỨ TỰ CHỮ CÁI của họ tác giả đầu (đúng kiểu danh mục của bài mẫu / abbrv.bst)."""
    valid = {p.key: p for p in papers}
    cited: set[str] = set()
    for name in order:
        for m in _CITE_RE.finditer(sections.get(name, "")):
            cited.update(k.strip() for k in m.group(1).split(",") if k.strip() in valid)
    ranked = sorted((valid[k] for k in cited), key=_sort_key)
    return {p.key: i + 1 for i, p in enumerate(ranked)}


# --------------------------------------------------------------------------- dựng tài liệu
def _footer(canvas, doc):
    pass  # bài mẫu không đánh số trang


def build_pdf(
    *, title: str, authors: list[dict], abstract: str, keywords: list[str],
    sections: dict[str, str], papers: list[Paper], comparison_rows: list[dict],
    figures: dict[str, bytes], perf_grid, daggers: bool = False, stats=None, ablation=None,
    sensitivity_param: str = "", related_position: str = "after", funding_note: str = "",
    acknowledgment: str = "", topic: str = "", bibliometric: bool = False,
) -> bytes:
    """Dựng PDF hai cột. `sections`: văn bản chuẩn (đã kiểm tra công thức) theo các khoá
    introduction / preliminaries / methodology / experiments_intro / experiments_setup / exp_comparison /
    exp_ablation / exp_sensitivity / related_work / conclusion."""
    st = _styles()
    order = (["introduction"] + (["related_work"] if related_position == "before" else []) +
             ["preliminaries", "methodology", "experiments_intro", "experiments_setup", "exp_comparison",
              "exp_ablation", "exp_sensitivity"] + (["related_work"] if related_position != "before" else []) +
             ["conclusion"])
    key_to_num = assign_citation_numbers(sections, papers, order)
    by_key = {p.key: p for p in papers}

    def story_and_labels(labels_in: dict[str, str]):
        ctx = _Ctx(key_to_num, labels_in)
        S = lambda k: _section_flowables(sections.get(k, ""), ctx, st)  # noqa: E731
        story: list = []

        # --- tiêu đề + tác giả (trải 2 cột) -> FrameBreak -> ABSTRACT / Keywords ở cột trái
        star = "<super>*</super>" if funding_note else ""
        head: list = [Paragraph(_x(title) + star, st["PTitle"])]
        blocks = []
        for a in authors:
            cell = [Paragraph(_x(a.get("name", "")), st["AuthN"]),
                    Paragraph(_x(a.get("affiliation", "")), st["AuthA"])]
            if a.get("country"):
                cell.append(Paragraph(_x(a["country"]), st["AuthA"]))
            cell.append(Paragraph(_x(a.get("email", "")), st["AuthE"]))
            blocks.append(cell)
        per_row = min(3, max(1, len(blocks)))
        for i in range(0, len(blocks), per_row):
            row = blocks[i:i + per_row]
            row += [""] * (per_row - len(row))
            t = Table([row], colWidths=[CONTENT_W / per_row] * per_row)
            t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4)]))
            head.append(t)
        head_height = 0.0
        for f in head:
            _, h = f.wrap(CONTENT_W, 1000)
            head_height += h + getattr(getattr(f, "style", None), "spaceAfter", 0)
        story.extend(head)
        story.append(FrameBreak())
        story.append(Paragraph("ABSTRACT", st["H1"]))
        story.append(Paragraph(_inline(abstract, ctx), st["Abs"]))
        if keywords:
            story.append(Paragraph("Keywords", st["H2"]))
            story.append(Paragraph(_x(", ".join(keywords)), st["Abs"]))

        def related_block() -> list:
            blk = [_heading(ctx, 1, "Related Work", st)] + S("related_work")
            rows_ = []
            for r in comparison_rows:
                p = by_key.get(r.get("key", ""))
                if p and p.key in key_to_num:
                    rows_.append((key_to_num[p.key], [f"[{key_to_num[p.key]}] {p.year}",
                                                       _x(str(r.get("approach", ""))),
                                                       _x(str(r.get("limitation", "")))]))
            if rows_:
                rows_.sort(key=lambda x: x[0])
                tbl = _grid_table(["Work", "Approach", "Limitation"], [r for _, r in rows_],
                                  [COL_W * 0.16, COL_W * 0.42, COL_W * 0.42], st)
                blk += _titled_table(ctx, "tab:related", "Comparison of the related work discussed above.", tbl, st)
            if bibliometric:
                if figures.get("fig_trend.png"):
                    blk += _figure(ctx, "fig:trend", figures["fig_trend.png"],
                                   f"Retrieved papers per publication year for “{_x(topic)}”.", st)
                if figures.get("fig_terms.png"):
                    blk += _figure(ctx, "fig:terms", figures["fig_terms.png"],
                                   "Most frequent terms across the retrieved abstracts.", st)
            return blk

        story += [_heading(ctx, 1, "Introduction", st)] + S("introduction")
        if related_position == "before":
            story += related_block()
        story += [_heading(ctx, 1, "Preliminaries", st)] + S("preliminaries")
        story += [_heading(ctx, 1, "Method", st)] + S("methodology")
        pipe = figures.get("fig_pipeline_col.png") or figures.get("fig_pipeline.png")
        if pipe:
            story += _figure(ctx, "fig:pipeline", pipe, "Overview of the proposed approach.", st, max_h=9 * cm)

        story += [_heading(ctx, 1, "Experiments", st)] + S("experiments_intro")
        story += [_heading(ctx, 2, "Experimental Settings", st)] + S("experiments_setup")
        if stats:
            story += _titled_table(ctx, "tab:stats", "Statistics of the evaluation datasets.",
                                   _grid_from(stats, st, 0.3), st)
        story.append(_heading(ctx, 2, "Performance Comparison (RQ1)", st))
        cap = "Performance comparison; the best result of each column is in bold."
        if daggers:
            cap += " † The improvement over the compared baselines is statistically significant (p&lt;0.05)."
        story += _titled_table(ctx, "tab:results", cap, _grid_from(perf_grid, st), st)
        if figures.get("fig_results.png"):
            story += _figure(ctx, "fig:results", figures["fig_results.png"],
                             "Performance comparison of the evaluated methods.", st)
        story += S("exp_comparison")
        story.append(_heading(ctx, 2, "Ablation Study (RQ2)", st))
        if ablation:
            story += _titled_table(ctx, "tab:ablation", "Ablation study; the best result of each column is in bold.",
                                   _grid_from(ablation, st, 0.5), st)
        story += S("exp_ablation")
        story.append(_heading(ctx, 2, "Sensitivity Analysis (RQ3)", st))
        if figures.get("fig_sensitivity.png"):
            story += _figure(ctx, "fig:sensitivity", figures["fig_sensitivity.png"],
                             f"Performance w.r.t. {_x(sensitivity_param)}.", st)
        story += S("exp_sensitivity")
        if related_position != "before":
            story += related_block()
        story += [_heading(ctx, 1, "Conclusion and Future Work", st)] + S("conclusion")
        if acknowledgment:
            story += [Paragraph("Acknowledgement", st["H2"]), Paragraph(_inline(acknowledgment, ctx), st["Abs"])]

        if key_to_num:
            story.append(_heading(ctx, 1, "References", st))
            for key, num in sorted(key_to_num.items(), key=lambda x: x[1]):
                p = by_key.get(key)
                if p:
                    story.append(Paragraph(f'<a name="ref{num}"/>[{num}]&nbsp;&nbsp;{_ref_markup(p)}', st["Ref"]))
        return story, ctx.labels, head_height

    # lượt 1: thu nhãn (số công thức/bảng/hình); lượt 2: dựng thật với tham chiếu chéo đã phân giải
    _, labels, _ = story_and_labels({})
    story, _, head_h = story_and_labels(labels)

    note_par = Paragraph("*" + _x(funding_note), st["Foot"]) if funding_note else None
    note_h = (note_par.wrap(COL_W, 200)[1] + 6) if note_par else 0

    def first_page(canvas, doc):
        if note_par:
            canvas.saveState()
            canvas.setStrokeColor(RULE)
            canvas.setLineWidth(0.4)
            canvas.line(M_LR, M_BOT + note_h - 2, M_LR + 3.2 * cm, M_BOT + note_h - 2)
            note_par.drawOn(canvas, M_LR, M_BOT)
            canvas.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=M_LR, rightMargin=M_LR, topMargin=M_TOP,
                          bottomMargin=M_BOT, title=title, author=", ".join(a.get("name", "") for a in authors))
    title_h = head_h + 10
    body_h_first = PAGE_H - M_TOP - M_BOT - title_h - 6
    body_h = PAGE_H - M_TOP - M_BOT

    def frame(x, y, w, h, fid):
        return Frame(x, y, w, h, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id=fid)

    first = [
        frame(M_LR, PAGE_H - M_TOP - title_h, CONTENT_W, title_h, "title"),
        frame(M_LR, M_BOT + note_h, COL_W, body_h_first - note_h, "c1"),
        frame(M_LR + COL_W + GAP, M_BOT, COL_W, body_h_first, "c2"),
    ]
    later = [frame(M_LR, M_BOT, COL_W, body_h, "l1"), frame(M_LR + COL_W + GAP, M_BOT, COL_W, body_h, "l2")]
    doc.addPageTemplates([PageTemplate(id="first", frames=first, onPage=first_page),
                          PageTemplate(id="later", frames=later, onPage=_footer)])
    doc.build([NextPageTemplate("later")] + story)
    return buf.getvalue()
