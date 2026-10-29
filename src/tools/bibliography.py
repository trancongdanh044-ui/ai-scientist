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


def to_bibtex(papers: list[Paper]) -> str:
    entries = []
    for p in papers:
        authors = " and ".join(latex_escape(a) for a in p.authors)
        if p.more_authors:
            authors += " and others"
        fields = [
            f"  title = {{{latex_escape(p.title)}}}",
            f"  author = {{{authors}}}",
            f"  year = {{{p.year}}}",
        ]
        if p.arxiv_id:
            fields += [
                f"  eprint = {{{p.arxiv_id}}}",
                "  archivePrefix = {arXiv}",
            ]
        fields.append(f"  howpublished = {{\\url{{{p.url}}}}}")
        entries.append("@misc{" + p.key + ",\n" + ",\n".join(fields) + "\n}")
    return "\n\n".join(entries) + ("\n" if entries else "")


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
