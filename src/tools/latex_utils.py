"""Tiện ích LaTeX: escape ký tự đặc biệt, làm sạch output của LLM và XỬ LÝ CÔNG THỨC an toàn.

Vấn đề gốc (khiến PDF lỗi công thức): LLM trộn nhiều kiểu công thức ($..$, $$..$$, \\[..\\],
\\(..\\), môi trường equation/align), dùng lệnh không tồn tại, thiếu/dư ngoặc, ký tự %,&,#
trong công thức, hoặc ký hiệu $ tiền tệ bị hiểu nhầm là công thức.

Quy trình mới (mọi công thức đều đi qua):
  1. TRÍCH công thức ra khỏi văn bản (thay bằng placeholder @@M<i>@@) -> các bước
     escape/markdown không thể làm hỏng công thức, và dòng "- \\log p" không bị nhầm là bullet.
  2. CHUẨN HOÁ: mọi công thức hiển thị -> \\begin{equation|align}..\\end{..} (được đánh số),
     công thức nội dòng -> $..$; sửa %, #, &, \\mathbb{1}...
  3. KIỂM TRA: biên dịch thử từng công thức bằng pdflatex (nếu máy có), nếu không thì kiểm tra
     tĩnh (ngoặc, \\left/\\right, \\begin/\\end, lệnh lạ). Công thức hỏng -> thay bằng văn bản
     thuần (\\texttt) thay vì làm vỡ cả bài báo; danh sách được ghi vào TODO.md.
  4. Tham chiếu \\ref/\\eqref tới nhãn không tồn tại bị loại bỏ (tránh "??" trong PDF).
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

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
    "⊙": r"$\odot$", "∇": r"$\nabla$", "∂": r"$\partial$", "ℓ": r"$\ell$",
    "\u2212": "-",
}
_MATH_MAP = {k: v.strip("$") for k, v in _TEXT_MAP.items() if v.startswith("$")}
_MATH_MAP.update({"−": "-", "\u2212": "-", "\u00a0": " ", "\u200b": "", "\ufeff": "",
                  "–": "-", "—": "-", "’": "'", "‘": "'"})


def normalize_unicode(s: str, math: bool = False) -> str:
    table = _MATH_MAP if math else _TEXT_MAP
    out: list[str] = []
    for ch in s:
        if ch in table:
            out.append(table[ch])
        elif ord(ch) < 0x180 or ch in "\n\t":
            out.append(ch)  # Latin-1 / Latin Extended-A: T1 + utf8 xử lý được
        else:
            base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
            out.append(base if all(ord(c) < 0x180 for c in base) else "")
    return "".join(out)


# ---------------------------------------------------------------- tiền khai báo công thức dùng chung
# Dùng CHUNG cho template bài báo và cho bộ kiểm tra công thức -> "qua được kiểm tra" nghĩa là
# "biên dịch được trong bài thật".
MATH_PREAMBLE = r"""\usepackage{amsmath,amssymb,bm}
\DeclareMathOperator*{\argmax}{arg\,max}
\DeclareMathOperator*{\argmin}{arg\,min}
\DeclareMathOperator{\softmax}{softmax}
\DeclareMathOperator{\sigmoid}{sigmoid}
\DeclareMathOperator{\ReLU}{ReLU}
\providecommand{\E}{\mathbb{E}}
\providecommand{\R}{\mathbb{R}}"""

_KNOWN_CMDS = set("""
alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi varpi
rho varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma
Upsilon Phi Psi Omega sum prod int oint lim limsup liminf max min sup inf arg argmax argmin log ln exp
sin cos tan tanh sinh cosh softmax sigmoid ReLU Pr det dim ker mod bmod pmod gcd leq geq le ge neq ne
approx sim simeq equiv propto in notin ni subset subseteq supset supseteq cup cap setminus times cdot
circ odot oplus otimes pm mp ll gg to rightarrow leftarrow Rightarrow Leftarrow leftrightarrow
Leftrightarrow mapsto implies iff forall exists nabla partial infty emptyset varnothing ldots cdots
vdots ddots dots ell hbar prime top bot perp mid vert Vert lvert rvert lVert rVert lfloor rfloor lceil
rceil langle rangle quad qquad frac dfrac tfrac sqrt binom left right big Big bigg Bigg bigl bigr Bigl
Bigr biggl biggr overline underline hat widehat tilde widetilde bar vec dot ddot text textbf textit
textrm mathrm mathbf mathit mathcal mathbb mathsf mathtt boldsymbol bm operatorname begin end label tag
nonumber notag substack overset underset stackrel limits nolimits displaystyle textstyle cases matrix
pmatrix bmatrix vmatrix aligned array hline lbrace rbrace E R Re Im wedge vee neg lnot land lor
bigcup bigcap bigoplus bigotimes angle triangle star ast bullet dagger ddagger sqcup uplus
cdotp colon lessim gtrsim lesssim not phantom hspace vspace mbox hphantom vphantom smash tiny small
""".split())

# ---------------------------------------------------------------- trích công thức
_MATH_TOKEN_RE = re.compile(
    r"(?P<env>\\begin\{(?P<name>equation\*?|align\*?|gather\*?|multline\*?|eqnarray\*?|displaymath)\}"
    r"(?P<envbody>.*?)\\end\{(?P=name)\})"
    r"|(?P<dd>\$\$(?P<ddbody>.+?)\$\$)"
    r"|(?P<br>\\\[(?P<brbody>.+?)\\\])"
    r"|(?P<pa>\\\((?P<pabody>.+?)\\\))"
    r"|(?P<inl>(?<![\\$])\$(?!\$)(?P<inbody>[^$\n]+?)(?<!\\)\$(?!\$))",
    re.S,
)
_PH_RE = re.compile(r"@@M(\d+)@@")
_INNER_ENV_RE = re.compile(r"\\begin\{(\w+\*?)\}.*?\\end\{\1\}", re.S)


@dataclass
class MathItem:
    kind: str            # "inline" | "display"
    body: str
    env: str = "equation"
    ok: bool = True
    reason: str = ""

    def tex(self) -> str:
        if self.kind == "inline":
            return f"${self.body}$"
        return f"\\begin{{{self.env}}}\n{self.body}\n\\end{{{self.env}}}"


@dataclass
class Prepared:
    text: str                                   # văn bản chứa placeholder @@M<i>@@
    items: list[MathItem] = field(default_factory=list)


def _looks_like_math(body: str) -> bool:
    b = body.strip()
    if not b:
        return False
    # "$5 and $10" (tiền tệ): chữ số rồi cách rồi một từ, không có toán tử
    if re.match(r"^\d[\d,\.]*\s+[A-Za-z]{2,}\b", b) and not re.search(r"[\\^_=<>+*/{}]", b):
        return False
    return True


def _fix_math_body(body: str, inline: bool) -> str:
    b = normalize_unicode(body, math=True).strip()
    b = re.sub(r"(?<!\\)%", r"\\%", b)
    b = re.sub(r"(?<!\\)#", r"\\#", b)
    if inline:
        b = re.sub(r"(?<!\\)&", r"\\&", b)
        b = re.sub(r"\\label\{[^}]*\}", "", b)
    b = b.replace(r"\mathbb{1}", r"\mathbf{1}").replace(r"\mathds{1}", r"\mathbf{1}")
    b = re.sub(r"\n\s*\n", "\n", b)          # dòng trống trong công thức = lỗi "Missing $"
    return b.strip()


def _display_env(body: str, requested: str | None) -> tuple[str, str]:
    """Chọn môi trường hiển thị phù hợp -> (env, body)."""
    star = "*" if requested and requested.endswith("*") else ""
    base = (requested or "equation").rstrip("*")
    if base == "eqnarray":
        body = body.replace("&=&", "&=")
        base = "align"
    if base in ("displaymath", "equation"):
        base = "equation"
    outer = _INNER_ENV_RE.sub("", body)
    multiline = ("\\\\" in outer) or ("&" in re.sub(r"\\&", "", outer))
    if multiline and base == "equation":
        base = "align"
    return base + star, body


def extract_math(text: str) -> Prepared:
    items: list[MathItem] = []

    def repl(m: re.Match) -> str:
        if m.group("env"):
            name = m.group("name")
            env, body = _display_env(_fix_math_body(m.group("envbody"), False), name)
            items.append(MathItem("display", body, env))
        elif m.group("dd") or m.group("br"):
            raw = m.group("ddbody") or m.group("brbody")
            env, body = _display_env(_fix_math_body(raw, False), None)
            items.append(MathItem("display", body, env))
        else:
            raw = m.group("pabody") if m.group("pa") else m.group("inbody")
            if not _looks_like_math(raw):
                return "\\$" + raw + "\\$"
            items.append(MathItem("inline", _fix_math_body(raw, True)))
        return f"@@M{len(items) - 1}@@"

    return Prepared(_MATH_TOKEN_RE.sub(repl, text), items)


# ---------------------------------------------------------------- kiểm tra công thức
def _static_check(it: MathItem) -> str:
    b = it.body
    if not b.strip():
        return "công thức rỗng"
    depth = 0
    for i, ch in enumerate(b):
        if ch == "\\" and i + 1 < len(b):
            continue
        if i > 0 and b[i - 1] == "\\":
            continue
        depth += (ch == "{") - (ch == "}")
        if depth < 0:
            return "ngoặc } thừa"
    if depth != 0:
        return "thiếu ngoặc }"
    if len(re.findall(r"\\left\b", b)) != len(re.findall(r"\\right\b", b)):
        return "\\left/\\right không cân"
    begins = re.findall(r"\\begin\{(\w+\*?)\}", b)
    ends = re.findall(r"\\end\{(\w+\*?)\}", b)
    if sorted(begins) != sorted(ends):
        return "\\begin/\\end không khớp"
    unknown = {c for c in re.findall(r"\\([A-Za-z]+)", b) if c not in _KNOWN_CMDS}
    if unknown:
        return "lệnh không hỗ trợ: " + ", ".join(sorted(unknown)[:3])
    return ""


def _latex_engine() -> list[str] | None:
    if shutil.which("pdflatex"):
        return ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape", "doc.tex"]
    if shutil.which("tectonic"):
        return ["tectonic", "doc.tex"]
    return None


def _snippet(it: MathItem) -> str:
    if it.kind == "inline":
        return f"\\par ${it.body}$"
    body = re.sub(r"\\label\{[^}]*\}", "", it.body)
    return f"\\par \\begin{{{it.env}}}{body}\\end{{{it.env}}}"


def _compile_snippets(snips: list[str]) -> bool:
    cmd = _latex_engine()
    if not cmd:
        return True
    doc = (
        "\\documentclass{article}\n" + MATH_PREAMBLE + "\n\\begin{document}\n"
        + "\n".join(s.replace("\n", " ") for s in snips) + "\n\\end{document}\n"
    )
    with tempfile.TemporaryDirectory(prefix="mathchk_") as tmp:
        (Path(tmp) / "doc.tex").write_text(doc, encoding="utf-8")
        try:
            r = subprocess.run(cmd, cwd=tmp, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60)
            return r.returncode == 0 and (Path(tmp) / "doc.pdf").exists()
        except Exception:  # noqa: BLE001
            return True  # không kiểm tra được -> không chặn (đã có kiểm tra tĩnh)


_CACHE: dict[str, bool] = {}


def _key(it: MathItem) -> str:
    return hashlib.sha1(it.tex().encode("utf-8")).hexdigest()


def validate_items(items: list[MathItem]) -> list[MathItem]:
    """Đánh dấu it.ok=False cho công thức không biên dịch được. Trả về danh sách công thức hỏng."""
    todo: list[MathItem] = []
    for it in items:
        reason = _static_check(it)
        if reason and (_latex_engine() is None or not reason.startswith("lệnh không hỗ trợ")):
            it.ok, it.reason = False, reason
        elif _key(it) in _CACHE:
            it.ok = _CACHE[_key(it)]
            it.reason = "" if it.ok else "LaTeX không biên dịch được"
        else:
            todo.append(it)
    if todo and _latex_engine():
        if _compile_snippets([_snippet(i) for i in todo]):
            for it in todo:
                _CACHE[_key(it)] = True
        else:  # có công thức hỏng -> kiểm tra riêng từng cái để biết cái nào
            def one(it: MathItem) -> bool:
                return _compile_snippets([_snippet(it)])

            with ThreadPoolExecutor(max_workers=4) as ex:
                for it, good in zip(todo, ex.map(one, todo)):
                    _CACHE[_key(it)] = good
                    if not good:
                        it.ok, it.reason = False, "LaTeX không biên dịch được"
    return [i for i in items if not i.ok]


# ---------------------------------------------------------------- text <-> LaTeX
_PROTECT_RE = re.compile(r"\\(?:cite[a-z]*|ref|eqref|label|textbf|emph|url)\{[^{}]*\}")
_SECTION_NAMES = {
    "abstract", "introduction", "related work", "methodology", "methods", "method",
    "experimental design", "experiments", "experiments and results", "conclusion",
    "conclusions", "proposed evaluation protocol", "experimental setup", "experimental settings",
    "results and discussion", "conclusion and future work", "preliminaries", "keywords",
}
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$")


def _bullets_to_lists(text: str) -> str:
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


def _fix_text(seg: str) -> str:
    holders: list[str] = []

    def hold(m: re.Match) -> str:
        holders.append(m.group(0))
        return f"\x00{len(holders) - 1}\x00"

    seg = _PROTECT_RE.sub(hold, seg)
    seg = re.sub(r"(?<!\\)([%&#$])", r"\\\1", seg)
    seg = re.sub(r"(?<!\\)_", r"\\_", seg)
    seg = re.sub(r"(?<!\\)\^", r"\\textasciicircum{}", seg)
    seg = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", seg, flags=re.S)
    seg = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\\emph{\1}", seg)
    seg = re.sub(r"`([^`\n]+)`", r"\\texttt{\1}", seg)
    seg = re.sub(r'"([^"\n]+)"', r"``\1''", seg)
    seg = normalize_unicode(seg, math=False)
    return re.sub(r"\x00(\d+)\x00", lambda m: holders[int(m.group(1))], seg)


_TEXT_CMDS = {
    "textbf", "textit", "emph", "texttt", "textsc", "cite", "citep", "citet", "ref", "eqref", "autoref", "label",
    "url", "footnote", "paragraph", "subsection", "subsubsection", "item", "begin", "end", "ldots", "textbackslash",
    "textasciitilde", "textasciicircum", "textbullet", "textperiodcentered", "dots", "textquotesingle",
    "centering", "noindent", "par", "newline", "hspace", "vspace", "bigskip", "medskip", "smallskip", "quad", "qquad",
    "small", "footnotesize", "large", "normalsize", "bfseries", "itshape", "ttfamily", "sffamily", "rmfamily",
}


def _decode_unicode_escapes(text: str) -> str:
    """'\\u2265' (mã Unicode thô do LLM sinh ra) -> '≥' (sau đó normalize_unicode đổi thành lệnh toán)."""
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)


_TEXT_MATH_SYMBOLS = set("""alpha beta gamma delta epsilon varepsilon zeta eta theta lambda mu nu xi pi rho sigma tau phi chi psi omega
Gamma Delta Theta Lambda Xi Pi Sigma Phi Psi Omega leq geq le ge neq approx sim times cdot pm to rightarrow leftarrow
infty in subset subseteq cup cap ell nabla partial""".split())


def _neutralize_unknown_commands(text: str, items: list[MathItem]) -> str:
    """Lệnh LaTeX lạ trong VĂN BẢN THƯỜNG (do LLM bịa/gõ nhầm) làm hỏng cả bài -> bỏ dấu '\\', giữ tên."""
    def repl(m: re.Match) -> str:
        name = m.group(1)
        if name in _TEXT_CMDS:
            return m.group(0)
        if name in _TEXT_MATH_SYMBOLS:      # ký hiệu toán gõ giữa văn bản: \\geq -> công thức nội dòng
            items.append(MathItem("inline", m.group(0)))
            return f"@@M{len(items) - 1}@@"
        return name

    return re.sub(r"(?<!\\)\\([A-Za-z]+)", repl, text)


def _balance_braces(text: str) -> str:
    out, depth, i = [], 0, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            out.append(text[i: i + 2])
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


def _drop_unknown_refs(text: str, known: set[str]) -> str:
    def repl(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(2).split(",")]
        return m.group(0) if all(k in known for k in keys) else ""

    t = re.sub(r"((?:Eq\.|Eqs\.|Equation|Fig\.|Figure|Table|Section|Sec\.)\s*~?\s*)?"
               r"\\(?:eq|auto)?ref\{([^}]*)\}", repl, text)
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"[ \t]+([.,;:])", r"\1", t)
    return re.sub(r"[ \t]{2,}", " ", t)


def prepare_text(text: str, valid_keys: set[str] | None) -> tuple[Prepared, list[str]]:
    """Làm sạch thô 1 section -> Prepared (text + công thức đã trích). Chưa escape."""
    from src.tools.bibliography import strip_unknown_cites

    t = (text or "").replace("\r\n", "\n").strip()
    t = re.sub(r"<think>.*?</think>", "", t, flags=re.S)
    t = re.sub(r"^```[a-zA-Z]*\s*$", "", t, flags=re.M)
    t = re.sub(r"\\(begin|end)\{abstract\}", "", t)
    t = re.sub(r"^\s*\\section\*?\{[^}]*\}\s*$", "", t, flags=re.M)
    removed: list[str] = []
    if valid_keys is not None:
        t, removed = strip_unknown_cites(t, valid_keys)
    prep = extract_math(t)

    def _heading(m: re.Match) -> str:
        level = len(m.group(1))
        title = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", m.group(2).strip(" *:"))  # bỏ số mục LLM tự gõ ("2.1 ...")
        if title.lower() in _SECTION_NAMES:
            return ""
        cmd = "subsection" if level <= 2 else "subsubsection" if level == 3 else "paragraph"
        return f"\\{cmd}{{{title}}}"

    s = re.sub(r"^\s*(#{1,6})\s*(.+?)\s*$", _heading, prep.text, flags=re.M)
    s = re.sub(r"^\s*\**(" + "|".join(re.escape(n) for n in _SECTION_NAMES) + r")\**:?\s*$",
               "", s, flags=re.M | re.I)
    prep.text = s
    return prep, removed


@dataclass
class ProcessResult:
    preps: dict[str, Prepared]
    removed_cites: list[str]
    bad_math: list[MathItem]


def process_sections(sections: dict[str, str], valid_keys: set[str] | None,
                     extra_labels: set[str] | None = None, validate: bool = True) -> ProcessResult:
    preps: dict[str, Prepared] = {}
    removed_all: list[str] = []
    for name, text in sections.items():
        p, removed = prepare_text(text, valid_keys)
        preps[name] = p
        removed_all += removed
    all_items = [it for p in preps.values() for it in p.items]
    bad = validate_items(all_items) if validate else []
    known = set(extra_labels or set())
    for p in preps.values():
        known.update(re.findall(r"\\label\{([^}]*)\}", p.text))
        for it in p.items:
            if it.ok:
                known.update(re.findall(r"\\label\{([^}]*)\}", it.body))
    for p in preps.values():
        p.text = _drop_unknown_refs(p.text, known)
    return ProcessResult(preps, removed_all, bad)


def _restore(text: str, items: list[MathItem], fmt: str) -> str:
    def repl(m: re.Match) -> str:
        it = items[int(m.group(1))]
        if fmt == "latex":
            if it.ok:
                return it.tex()
            raw = latex_escape(it.body.replace("\n", " "))
            if it.kind == "inline":
                return f"\\texttt{{{raw}}}"
            return f"\n\\begin{{quote}}\\small\\texttt{{{raw}}}\\end{{quote}}\n"
        return it.tex() if it.ok else (f"`{it.body}`" if it.kind == "inline" else f"\n```{it.body}```\n")

    return _PH_RE.sub(repl, text)


def render_latex(prep: Prepared) -> str:
    """Prepared -> LaTeX an toàn để biên dịch."""
    t = _neutralize_unknown_commands(_decode_unicode_escapes(prep.text), prep.items)
    t = _bullets_to_lists(t)
    t = _fix_text(t)
    t = _balance_braces(t)
    t = _restore(t, prep.items, "latex")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def render_canonical(prep: Prepared) -> str:
    """Prepared -> văn bản chuẩn (công thức đã kiểm tra) cho đường PDF ReportLab."""
    t = _restore(prep.text, prep.items, "canon")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def clean_section(text: str, valid_keys: set[str] | None = None) -> tuple[str, list[str]]:
    """API cũ (tương thích ngược): 1 section -> (latex, cite_bị_loại)."""
    res = process_sections({"s": text}, valid_keys)
    return render_latex(res.preps["s"]), res.removed_cites
