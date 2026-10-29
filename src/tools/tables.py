"""Sinh bảng LaTeX (booktabs + tabularx). Mọi nội dung ô đều được escape."""
from __future__ import annotations

from src.tools.arxiv_search import Paper
from src.tools.latex_utils import latex_escape


def _clip(s: str, n: int) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _table(caption: str, label: str, colspec: str, header: list[str], rows: list[list[str]]) -> str:
    head = " & ".join(f"\\textbf{{{h}}}" for h in header) + r" \\"
    body = "\n".join(" & ".join(r) + r" \\" for r in rows)
    return (
        "\\begin{table}[t]\n\\centering\\small\n"
        f"\\caption{{{caption}}}\n\\label{{{label}}}\n"
        f"\\begin{{tabularx}}{{\\linewidth}}{{{colspec}}}\n\\toprule\n{head}\n\\midrule\n"
        f"{body}\n\\bottomrule\n\\end{{tabularx}}\n\\end{{table}}\n"
    )


def related_work_table(papers: list[Paper], rows: list[dict]) -> str:
    """Bảng 1: so sánh các công trình liên quan (dữ liệu thật từ arXiv + tóm tắt của LLM)."""
    by_key = {p.key: p for p in papers}
    out = []
    for r in rows:
        p = by_key.get(r.get("key", ""))
        if p is None:
            continue
        out.append(
            [
                f"\\cite{{{p.key}}}",
                str(p.year or "--"),
                latex_escape(_clip(r.get("approach", ""), 90)),
                latex_escape(_clip(r.get("limitation", ""), 90)),
            ]
        )
    if not out:
        return ""
    return _table(
        "Comparison of related work retrieved from arXiv.",
        "tab:related",
        "l c X X",
        ["Work", "Year", "Approach", "Limitation"],
        out,
    )


def eval_plan_table(rows: list[dict]) -> str:
    """Bảng 2: kế hoạch đánh giá đề xuất (KHÔNG chứa số liệu kết quả)."""
    out = []
    for r in rows:
        out.append(
            [
                latex_escape(_clip(r.get("hypothesis", ""), 12)),
                latex_escape(_clip(r.get("baseline", ""), 70)),
                latex_escape(_clip(r.get("metric", ""), 60)),
                latex_escape(_clip(r.get("dataset", ""), 60)),
            ]
        )
    if not out:
        return ""
    return _table(
        "Proposed evaluation protocol. No empirical results are reported in this manuscript.",
        "tab:eval",
        "l X X X",
        ["Hyp.", "Baseline", "Metric", "Dataset"],
        out,
    )
