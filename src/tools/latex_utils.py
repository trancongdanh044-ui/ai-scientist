"""Tiện ích LaTeX: escape ký tự đặc biệt & làm sạch output của LLM để biên dịch được.

Lý do cần: LLM hay trả về markdown (**bold**, "- bullet", ```fence```), ký tự Unicode
(≥, →, –, “ ”) và ký tự đặc biệt (%, &, _, #) làm pdflatex báo lỗi.
"""
from __future__ import annotations

import re
import unicodedata

# ---------------------------------------------------------------- escape (text thuần)
_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(s: str) -> str:
    """Escape toàn bộ ký tự đặc biệt (dùng cho caption, ô bảng, title, author...)."""
    s = normalize_unicode(s, math=False)
    return "".join(_ESCAPES.get(c, c) for c in s)


# ---------------------------------------------------------------- unicode
_TEXT_MAP = {
    "–": "--", "—": "---", "−": "-", "‐": "-", "‑": "-",
    "“": "``", "”": "''", "„": ",,", "‘": "`", "’": "'", "′": "'",
    "…": r"\ldots{}", "•": r"\textbullet{}", "·": r"\textperiodcentered{}",
    "\u00a0": "~", "\u200b": "", "\u2009": " ", "\u202f": " ", "\ufeff": "",
    "≥": r"$\geq$", "≤": r"$\leq$", "≈": r"$\approx$", "≠": r"$\neq$",
    "→": r"$\rightarrow$", "←": r"$\leftarrow$", "↔": r"$\leftrightarrow$",
    "×": r"$\times$", "±": r"$\pm$", "∞": r"$\infty$", "°": r"$^{\circ}$",
    "∈": r"$\in$", "∑": r"$\sum$", "√": r"$\sqrt{}$", "∼": r"$\sim$",
    "µ": r"$\mu$", "μ": r"$\mu$", "α": r"$\alpha$", "β": r"$\beta$",
    "γ": r"$\gamma$", "δ": r"$\delta$", "ε": r"$\epsilon$", "θ": r"$\theta$",
    "λ": r"$\lambda$", "σ": r"$\sigma$", "φ": r"$\phi$", "ω": r"$\omega$",
    "Δ": r"$\Delta$", "Σ": r"$\Sigma$", "Ω": r"$\Omega$", "π": r"$\pi$",
    "τ": r"$\tau$", "η": r"$\eta$", "ρ": r"$\rho$", "ψ": r"$\psi$",
    "\u2212": "-",
}
# Trong môi trường math: bỏ dấu $ bao quanh
_MATH_MAP = {k: v.strip("$") for k, v in _TEXT_MAP.items() if v.startswith("$")}
_MATH_MAP.update({"−": "-", "\u2212": "-", "\u00a0": " ", "\u200b": "", "\ufeff": ""})


def normalize_unicode(s: str, math: bool = False) -> str:
    table = _MATH_MAP if math else _TEXT_MAP
    out: list[str] = []
    for ch in s:
        if ch in table:
            out.append(table[ch])
        elif ord(ch) < 0x180 or ch in "\n\t":
            out.append(ch)  # Latin-1 / Latin Extended-A: T1 + utf8 xử lý được
        else:
            # Bỏ dấu (VD tiếng Việt: ệ -> e); ký tự không phân rã được thì bỏ
            base = "".join(
                c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c)
            )
            out.append(base if all(ord(c) < 0x180 for c in base) else "")
    return "".join(out)


# ---------------------------------------------------------------- clean output LLM
_MATH_RE = re.compile(
    r"(\$\$.+?\$\$"
    r"|(?<!\\)\$(?!\s).+?(?<!\\)\$"
    r"|\\\(.+?\\\)"
    r"|\\\[.+?\\\]"
    r"|\\begin\{(equation\*?|align\*?|gather\*?)\}.+?\\end\{\2\})",
    re.S,
)
_PROTECT_RE = re.compile(r"\\(?:cite[a-z]*|ref|eqref|label|textbf|emph|url)\{[^{}]*\}")
_SECTION_NAMES = {
    "abstract", "introduction", "related work", "methodology", "methods", "method",
    "experimental design", "experiments", "experiments and results", "conclusion",
    "conclusions", "proposed evaluation protocol",
}
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$")


def _bullets_to_lists(text: str) -> str:
    """Chuyển các dòng bullet markdown thành itemize/enumerate (nếu chưa có \\item)."""
    if r"\item" in text:
        return text
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        m = _BULLET_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        ordered = bool(re.match(r"^\s*\d+[.)]\s", lines[i]))
        env = "enumerate" if ordered else "itemize"
        items = []
        while i < len(lines) and _BULLET_RE.match(lines[i]):
            items.append(_BULLET_RE.match(lines[i]).group(1))
            i += 1
        out.append(f"\\begin{{{env}}}")
        out.extend(f"\\item {it}" for it in items)
        out.append(f"\\end{{{env}}}")
    return "\n".join(out)


def _fix_text_segment(seg: str) -> str:
    holders: list[str] = []

    def hold(m: re.Match) -> str:
        holders.append(m.group(0))
        return f"\x00{len(holders) - 1}\x00"

    seg = _PROTECT_RE.sub(hold, seg)
    # 1) escape ký tự đặc biệt gốc (TRƯỚC khi chèn các $...$ do normalize_unicode tạo ra)
    seg = re.sub(r"(?<!\\)([%&#$])", r"\\\1", seg)
    seg = re.sub(r"(?<!\\)_", r"\\_", seg)
    seg = re.sub(r"(?<!\\)\^", r"\\textasciicircum{}", seg)
    # 2) markdown -> LaTeX
    seg = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", seg, flags=re.S)
    seg = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", seg)
    seg = re.sub(r"`([^`\n]+)`", r"\\texttt{\1}", seg)
    seg = re.sub(r'"([^"\n]+)"', r"``\1''", seg)
    # 3) unicode -> LaTeX (sau cùng)
    seg = normalize_unicode(seg, math=False)
    return re.sub(r"\x00(\d+)\x00", lambda m: holders[int(m.group(1))], seg)


def _balance_braces(text: str) -> str:
    """Bỏ dấu } thừa và thêm } thiếu (bỏ qua \\{ và \\})."""
    out, depth, i = [], 0, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            if depth == 0:
                i += 1
                continue
            depth -= 1
        out.append(ch)
        i += 1
    return "".join(out) + "}" * depth


def clean_section(text: str, valid_keys: set[str] | None = None) -> tuple[str, list[str]]:
    """Làm sạch 1 section do LLM viết. Trả về (latex_body, danh_sách_cite_bị_loại)."""
    from src.tools.bibliography import strip_unknown_cites

    t = (text or "").replace("\r\n", "\n").strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"^```[a-zA-Z]*\s*$", "", t, flags=re.M)
    t = re.sub(r"\\(begin|end)\{abstract\}", "", t)
    t = re.sub(r"^\s*\\section\*?\{[^}]*\}\s*$", "", t, flags=re.M)

    # Heading markdown -> bỏ (nếu là tên section) hoặc \paragraph
    def _heading(m: re.Match) -> str:
        title = m.group(1).strip(" *:")
        if title.lower() in _SECTION_NAMES:
            return ""
        return f"\\paragraph{{{title}}}"

    t = re.sub(r"^\s*#{1,6}\s*(.+?)\s*$", _heading, t, flags=re.M)
    # Dòng chỉ chứa tên section (VD "Introduction")
    t = re.sub(
        r"^\s*\**(" + "|".join(re.escape(n) for n in _SECTION_NAMES) + r")\**:?\s*$",
        "", t, flags=re.M | re.I,
    )

    removed: list[str] = []
    if valid_keys is not None:
        t, removed = strip_unknown_cites(t, valid_keys)

    t = _bullets_to_lists(t)

    # Tách math / text
    parts, last = [], 0
    for m in _MATH_RE.finditer(t):
        parts.append(_fix_text_segment(t[last : m.start()]))
        parts.append(normalize_unicode(m.group(0), math=True))
        last = m.end()
    parts.append(_fix_text_segment(t[last:]))
    t = "".join(parts)

    t = _balance_braces(t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t, removed
