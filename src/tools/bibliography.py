"""Tạo BibTeX key/entry thật từ metadata arXiv và kiểm soát \\cite của LLM."""
from __future__ import annotations

import re
import unicodedata

from src.tools.arxiv_search import Paper
from src.tools.latex_utils import latex_escape

_STOP = {"a", "an", "the", "of", "on", "for", "and", "in", "to", "with", "towards",
         "toward", "via", "using", "from", "by", "is", "are", "at", "as"}

_CITE_RE = re.compile(r"\\cite[a-z]*\*?\{([^}]*)\}")


def _ascii(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def assign_keys(papers: list[Paper]) -> list[Paper]:
    """Gán key dạng `lastname2024word` (duy nhất, chỉ gồm a-z0-9)."""
    used: set[str] = set()
    for p in papers:
        last = _ascii(p.authors[0].split()[-1]) if p.authors else "anon"
        last = re.sub(r"[^a-z0-9]", "", last.lower()) or "anon"
        words = [w for w in re.findall(r"[a-z0-9]+", _ascii(p.title).lower()) if w not in _STOP]
        base = f"{last}{p.year or ''}{words[0] if words else ''}"
        key, n = base, 0
        while key in used:
            n += 1
            key = f"{base}{chr(ord('a') + (n - 1) % 26)}"
        used.add(key)
        p.key = key
    return papers


def protect_title(title: str) -> str:
    """Các style .bst (abbrv/plain/IEEEtran) hạ chữ thường tiêu đề -> bọc từ viết tắt/CamelCase trong {} để giữ nguyên
    (BERT, LoRA, PyTorch, GPT-4...). Từ đầu tiên của tiêu đề không cần bọc."""
    out = []
    for i, w in enumerate(title.split(" ")):
        core = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", w)
        has_inner_upper = any(c.isupper() for c in core[1:])
        has_digit = any(c.isdigit() for c in core)
        if core and (has_inner_upper or (has_digit and any(c.isalpha() for c in core))) :
            w = w.replace(core, "{" + core + "}", 1)
        elif i > 0 and core.isupper() and len(core) > 1:
            w = w.replace(core, "{" + core + "}", 1)
        out.append(w)
    return " ".join(out)


def _bib_escape(s: str) -> str:
    """Escape cho field BibTeX nhưng GIỮ dấu {} do protect_title chèn."""
    protected = []

    def hold(m):
        protected.append(m.group(1))
        return f"\x00{len(protected) - 1}\x00"

    s = re.sub(r"\{([^{}]*)\}", hold, s)
    s = latex_escape(s)
    return re.sub(r"\x00(\d+)\x00", lambda m: "{" + latex_escape(protected[int(m.group(1))]) + "}", s)


def to_bibtex(papers: list[Paper]) -> str:
    """Sinh references.bib: @article / @inproceedings / preprint arXiv, kèm DOI + URL."""
    entries = []
    for p in papers:
        authors = " and ".join(latex_escape(a) for a in p.authors) or "Anonymous"
        if p.more_authors:
            authors += " and others"
        title = _bib_escape(protect_title(p.title))
        venue = latex_escape(p.venue) if p.venue else ""
        if p.kind == "conference" and venue:
            etype, vfield = "inproceedings", ("booktitle", venue)
        elif p.venue and p.kind != "preprint":
            etype, vfield = "article", ("journal", venue)
        else:
            etype = "article"
            vfield = ("journal", f"arXiv preprint arXiv:{p.arxiv_id}" if p.arxiv_id else "Preprint")
        fields = [
            f"  author = {{{authors}}}",
            f"  title = {{{title}}}",
            f"  {vfield[0]} = {{{vfield[1]}}}",
            f"  year = {{{p.year}}}",
        ]
        if p.doi:
            fields.append(f"  doi = {{{p.doi}}}")
        if p.arxiv_id and p.kind != "preprint":
            fields.append(f"  note = {{arXiv:{p.arxiv_id}}}")
        link = p.url or (f"https://doi.org/{p.doi}" if p.doi else "")
        if link and not p.doi:
            fields.append(f"  url = {{{link}}}")
        entries.append("@" + etype + "{" + p.key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")


def ieee_author(name: str) -> str:
    """'Xiangnan He' -> 'X. He' (dùng cho PDF ReportLab; LaTeX do abbrv.bst tự xử lý)."""
    parts = [x for x in re.split(r"\s+", name.strip()) if x]
    if len(parts) < 2:
        return name.strip()
    inits = " ".join(f"{x[0]}." for x in parts[:-1] if x[0].isalpha())
    return f"{inits} {parts[-1]}"


def extract_cites(text: str) -> set[str]:
    keys: set[str] = set()
    for m in _CITE_RE.finditer(text):
        keys.update(k.strip() for k in m.group(1).split(",") if k.strip())
    return keys


def strip_unknown_cites(text: str, valid: set[str]) -> tuple[str, list[str]]:
    """Loại các key không tồn tại khỏi \\cite{...} (chống LLM bịa trích dẫn)."""
    removed: list[str] = []

    def repl(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
        good = [k for k in keys if k in valid]
        removed.extend(k for k in keys if k not in valid)
        if not good:
            return ""
        return m.group(0).split("{")[0] + "{" + ",".join(good) + "}"

    new = re.sub(r"(?:[ \t]|~)*" + _CITE_RE.pattern, repl, text)
    # giữ khoảng trắng trước cite hợp lệ
    new = re.sub(r"(\w)(\\cite)", r"\1 \2", new)
    return new, removed
