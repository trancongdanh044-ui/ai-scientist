"""Vẽ hình bằng matplotlib từ DỮ LIỆU THẬT (metadata arXiv) + sơ đồ khái niệm.

Nguyên tắc trung thực khoa học: module này KHÔNG tạo biểu đồ "kết quả thí nghiệm" giả.
Chỉ vẽ:
  - fig_trend.png    : số bài báo theo năm (đếm từ kết quả arXiv)
  - fig_terms.png    : các thuật ngữ xuất hiện nhiều nhất trong abstract (đếm thật)
  - fig_pipeline.png : sơ đồ khái niệm quy trình đề xuất (minh hoạ, không phải số liệu)
"""
from __future__ import annotations

import io
import re
import textwrap
import threading
from collections import Counter

import matplotlib

matplotlib.use("Agg")  # backend không cần GUI (chạy được trong server)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

from src.tools.arxiv_search import Paper  # noqa: E402

_PLOT_LOCK = threading.Lock()  # pyplot có state toàn cục -> không an toàn khi chạy song song

NAVY, TEAL, AMBER, GREY = "#1E2761", "#1C7293", "#F2A93B", "#6B7290"

_STOP = set(
    """a an the of on for and in to with from by is are was were be been this that these those
    we our their its it as at or not can may also which such than then into over under between
    using use used based via new approach method methods paper propose proposed present results
    show shows shown model models study work data task tasks performance different however
    while both more most other several across each any all one two three first second
    et al thus therefore has have had how what when where who why will would could should""".split()
)


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _style(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GREY)
    ax.spines["bottom"].set_color(GREY)
    ax.tick_params(colors=GREY, labelsize=9)
    ax.yaxis.grid(True, color="#E3E6F0", linewidth=0.8)
    ax.set_axisbelow(True)


def publication_trend(papers: list[Paper]) -> bytes | None:
    years = Counter(p.year for p in papers if p.year)
    if not years:
        return None
    lo, hi = min(years), max(years)
    xs = list(range(lo, hi + 1))
    ys = [years.get(x, 0) for x in xs]

    fig, ax = plt.subplots(figsize=(6.2, 3.3))
    bars = ax.bar([str(x) for x in xs], ys, color=NAVY, width=0.65)
    for b, v in zip(bars, ys):
        if v:
            ax.text(b.get_x() + b.get_width() / 2, v + 0.05, str(v), ha="center",
                    va="bottom", fontsize=9, color=NAVY)
    ax.set_xlabel("Publication year", fontsize=10, color=GREY)
    ax.set_ylabel("Number of papers", fontsize=10, color=GREY)
    ax.set_ylim(0, max(ys) * 1.25 + 0.5)
    ax.yaxis.get_major_locator().set_params(integer=True)
    if len(xs) > 12:
        ax.tick_params(axis="x", rotation=45)
    _style(ax)
    return _fig_to_png(fig)


def top_terms(papers: list[Paper], k: int = 10) -> bytes | None:
    counts: Counter[str] = Counter()
    for p in papers:
        words = re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", p.abstract.lower())
        counts.update({w for w in words if w not in _STOP})  # đếm số abstract chứa từ
    common = counts.most_common(k)
    if len(common) < 3:
        return None
    labels, vals = zip(*reversed(common))

    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    ax.barh(labels, vals, color=TEAL, height=0.65)
    for i, v in enumerate(vals):
        ax.text(v + 0.05, i, str(v), va="center", fontsize=9, color=TEAL)
    ax.set_xlabel("Number of abstracts containing the term", fontsize=10, color=GREY)
    ax.set_xlim(0, max(vals) * 1.15 + 0.5)
    ax.xaxis.get_major_locator().set_params(integer=True)
    _style(ax)
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color="#E3E6F0", linewidth=0.8)
    return _fig_to_png(fig)


def pipeline_diagram(steps: list[str]) -> bytes | None:
    steps = [s.strip() for s in steps if s and s.strip()][:7]
    if len(steps) < 2:
        return None
    n = len(steps)
    box_w, box_h, gap = 1.7, 0.8, 0.5
    total = n * box_w + (n - 1) * gap
    fig, ax = plt.subplots(figsize=(min(max(total * 0.8, 6.0), 10.0), 1.5))
    ax.set_xlim(-0.2, total + 0.2)
    ax.set_ylim(-0.1, box_h + 0.1)
    ax.axis("off")
    for i, label in enumerate(steps):
        x = i * (box_w + gap)
        color = AMBER if i == n - 1 else NAVY
        ax.add_patch(FancyBboxPatch((x, 0), box_w, box_h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    fc=color, ec="none"))
        ax.text(x + box_w / 2, box_h / 2, textwrap.fill(label, 12), ha="center", va="center",
                fontsize=8, color="white" if i != n - 1 else NAVY, fontweight="bold")
        if i < n - 1:
            ax.add_patch(FancyArrowPatch((x + box_w + 0.04, box_h / 2), (x + box_w + gap - 0.04, box_h / 2),
                                         arrowstyle="-|>", mutation_scale=12, color=GREY, lw=1.4))
    return _fig_to_png(fig)


def render_figures(papers: list[Paper], pipeline_steps: list[str]) -> dict[str, bytes]:
    """Trả về {tên_file: png_bytes}. Hình nào không đủ dữ liệu thì bỏ qua."""
    figs: dict[str, bytes] = {}
    with _PLOT_LOCK:
        return _render_figures_locked(papers, pipeline_steps, figs)


def _render_figures_locked(papers, pipeline_steps, figs):
    for name, fn in (
        ("fig_trend.png", lambda: publication_trend(papers)),
        ("fig_terms.png", lambda: top_terms(papers)),
        ("fig_pipeline.png", lambda: pipeline_diagram(pipeline_steps)),
    ):
        png = fn()
        if png:
            figs[name] = png
    return figs
