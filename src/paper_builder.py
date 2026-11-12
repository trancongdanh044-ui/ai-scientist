"""paper_builder.py — dựng bài báo hoàn chỉnh từ nội dung thô của các agent.

Dùng CHUNG cho CLI (src/orchestrator.py) và web (backend/run_manager.py). Các bước:
  1. làm sạch + kiểm tra công thức (biên dịch thử từng công thức) + loại trích dẫn bịa;
  2. lưới chắn số liệu: xoá câu chứa số kết quả KHÔNG có trong results.json;
  3. sinh bảng/hình: thống kê dữ liệu, so sánh hiệu năng (mean ± std, †), ablation, độ nhạy;
  4. xuất paper.tex + references.bib + bundle cho Overleaf (mô phỏng bài mẫu NCF, WWW 2017);
  5. PDF: ưu tiên biên dịch LaTeX; nếu máy không có LaTeX -> PDF hai cột ReportLab;
  6. TODO.md liệt kê mọi thứ cần tự kiểm tra/điền. PDF KHÔNG chứa dòng Draft/TBD/placeholder.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.tools.arxiv_search import Paper
from src.tools.bibliography import to_bibtex
from src.tools.experiments import (
    MISSING, ExperimentResults, ablation_grid, allowed_numbers, count_missing, grid_table_tex,
    performance_grid, placeholder_grid, sensitivity_data, stats_grid, strip_unsupported_numbers,
)
from src.tools.latex_render import render_latex_to_string
from src.tools.latex_utils import (
    MATH_PREAMBLE, ProcessResult, latex_escape, process_sections, render_canonical, render_latex,
)
from src.tools.pdf_compiler import _compile_sync, build_bundle, detect_engine
from src.tools.pdf_writer import build_pdf
from src.tools.tables import related_work_table

# thứ tự khoá nội dung do WriterAgent tạo ra (thứ tự hiển thị do template/pdf_writer quyết định)
SECTION_KEYS = ["abstract", "introduction", "preliminaries", "methodology", "experiments_intro",
                "experiments_setup", "exp_comparison", "exp_ablation", "exp_sensitivity",
                "related_work", "conclusion"]
_GUARDED = {"abstract", "experiments_intro", "experiments_setup", "exp_comparison", "exp_ablation",
            "exp_sensitivity", "conclusion"}
_KNOWN_LABELS = {"tab:related", "tab:stats", "tab:results", "tab:ablation", "fig:trend", "fig:terms",
                 "fig:pipeline", "fig:results", "fig:sensitivity", "sec:experiments"}
DEFAULT_AUTHOR = "Your Name"


@dataclass
class PaperInput:
    title: str
    topic: str
    authors: list[dict]
    raw: dict[str, str]                 # khoá theo SECTION_KEYS
    keywords: list[str]
    papers: list[Paper]
    comparison_rows: list[dict]
    eval_rows: list[dict]
    figures: dict[str, bytes]
    results: ExperimentResults | None
    template_path: str
    related_position: str = "after"
    draft_notice: bool = False
    acknowledgment: str = ""
    funding_note: str = ""
    bibliometric_figures: bool = False
    search_notes: list[str] = field(default_factory=list)


@dataclass
class PaperArtifacts:
    tex: str
    bib: str
    pdf: bytes
    pdf_engine: str                     # "latex" | "reportlab"
    bundle: bytes
    todo_md: str
    sections: dict[str, str]            # văn bản chuẩn (đã kiểm tra) — lưu DB / đưa reviewer
    notes: list[str]                    # thông điệp để in log / hiển thị
    compile_log: str = ""
    latex_class: str = ""


def _authors_tex(authors: list[dict]) -> str:
    """Khối tác giả như bài mẫu: tối đa 3 người mỗi hàng, căn giữa; tên (sans lớn), đơn vị, quốc gia, email."""
    cells = []
    for a in authors:
        lines = []
        if a.get("name"):
            lines.append(f"{{\\large {latex_escape(a['name'])}}}")
        for k in ("affiliation", "country"):
            if a.get(k):
                lines.append(f"{{\\small {latex_escape(a[k])}}}")
        if a.get("email"):
            lines.append(f"{{\\normalsize {latex_escape(a['email'])}}}")
        cells.append("\\parbox[t]{0.31\\textwidth}{\\centering\\sffamily " + " \\\\ ".join(lines) + "}")
    rows = ["\\hspace{0.012\\textwidth}".join(cells[i:i + 3]) for i in range(0, len(cells), 3)]
    return "\\par\\vspace{8pt}".join(rows)


def _tables(inp: PaperInput, perf_grid, daggers: bool) -> dict[str, str]:
    res = inp.results
    t = {"related": related_work_table(inp.papers, inp.comparison_rows), "stats": "", "ablation": ""}
    dnames = ", ".join(res.datasets) if res else ""
    t["results"] = grid_table_tex(
        perf_grid,
        (f"Performance comparison on {latex_escape(dnames)}; the best result of each column is in bold."
         if res else "Performance comparison of the evaluated methods."),
        "tab:results",
        note=("$^{\\dagger}$ The improvement over the compared baselines is statistically significant "
              "($p<0.05$).") if daggers else "")
    if res:
        sg = stats_grid(res)
        if sg:
            t["stats"] = grid_table_tex(sg, "Statistics of the evaluation datasets.", "tab:stats", wide=False)
        ag = ablation_grid(res)
        if ag:
            t["ablation"] = grid_table_tex(
                ag, f"Ablation study{(' on ' + latex_escape(str(res.ablation.get('dataset')))) if res.ablation.get('dataset') else ''}; "
                    "the best result of each column is in bold.", "tab:ablation", wide=False)
    return t


def _render(inp: PaperInput, latex: dict[str, str], tables: dict[str, str]) -> str:
    fig = inp.figures
    sd = sensitivity_data(inp.results) if inp.results else None
    ctx = {
        "math_preamble": MATH_PREAMBLE,
        "title": latex_escape(inp.title), "query": latex_escape(inp.topic),
        "authors_tex": _authors_tex(inp.authors), "funding_note": latex_escape(inp.funding_note),
        "keywords": ", ".join(latex_escape(k) for k in inp.keywords),
        "related_position": inp.related_position, "acknowledgment": latex_escape(inp.acknowledgment),
        **{k: latex.get(k, "") for k in SECTION_KEYS},
        "table_related": tables["related"], "table_stats": tables["stats"],
        "table_results": tables["results"], "table_ablation": tables["ablation"],
        "fig_trend": inp.bibliometric_figures and "fig_trend.png" in fig,
        "fig_terms": inp.bibliometric_figures and "fig_terms.png" in fig,
        "fig_pipeline": "fig_pipeline.png" in fig, "fig_results": "fig_results.png" in fig,
        "fig_sensitivity": "fig_sensitivity.png" in fig,
        "sensitivity_param": latex_escape(sd[0]) if sd else "",
        "has_bib": bool(inp.papers),
    }
    return render_latex_to_string(inp.template_path, ctx)


def build_paper(inp: PaperInput) -> PaperArtifacts:
    notes: list[str] = []
    valid = {p.key for p in inp.papers}

    # 1) làm sạch + kiểm tra công thức + chống trích dẫn bịa
    res: ProcessResult = process_sections(
        {k: inp.raw.get(k, "") for k in SECTION_KEYS}, valid, extra_labels=set(_KNOWN_LABELS))
    if res.removed_cites:
        notes.append(f"Đã loại {len(set(res.removed_cites))} trích dẫn không hợp lệ do model tự bịa: "
                     f"{sorted(set(res.removed_cites))}")
    for it in res.bad_math:
        notes.append(f"Công thức không biên dịch được ({it.reason}) -> thay bằng văn bản: {it.body[:60]}")

    # 2) lưới chắn số liệu
    allowed = allowed_numbers(inp.results)
    removed_sentences: list[str] = []
    emptied: list[str] = []
    for name in sorted(_GUARDED):
        prep = res.preps[name]
        prep.text, removed = strip_unsupported_numbers(prep.text, allowed)
        removed_sentences += [f"[{name}] {s}" for s in removed]
        if removed and not prep.text.strip():
            emptied.append(name)
    if emptied:
        notes.append("Các phần sau rỗng vì toàn bộ câu chứa số liệu không có thật, cần viết lại: " + ", ".join(emptied))
    if removed_sentences:
        notes.append(f"Đã xoá {len(removed_sentences)} câu chứa số liệu không có trong dữ liệu thật.")

    latex = {k: render_latex(p) for k, p in res.preps.items()}
    canon = {k: render_canonical(p) for k, p in res.preps.items()}

    # 3) bảng
    if inp.results:
        perf_grid, daggers = performance_grid(inp.results)
        n_missing = 0
    else:
        perf_grid, daggers = placeholder_grid(inp.eval_rows), False
        n_missing = count_missing(perf_grid)
        notes.append(f"Chưa có results.json: bảng kết quả giữ khung với {n_missing} ô '{MISSING}' (xem TODO.md).")
    tables = _tables(inp, perf_grid, daggers)

    # 4) LaTeX
    bib = to_bibtex(inp.papers)
    tex = _render(inp, latex, tables)
    figures_tex = {k: v for k, v in inp.figures.items() if not k.endswith("_col.png")}

    # 5) PDF
    pdf: bytes | None = None
    engine, log, lclass = "reportlab", "", "article hai cột mô phỏng bài mẫu"
    if detect_engine():
        r = _compile_sync(tex, bib, figures_tex, 240)
        log = r.log
        if r.ok:
            pdf, engine = r.pdf, "latex"
            notes.append(f"PDF biên dịch bằng LaTeX ({r.engine}).")
            if r.errors:
                notes.append("LaTeX báo lỗi nhưng vẫn tạo được PDF: " + "; ".join(r.errors[:3]))
            notes += r.warnings
        else:
            notes.append("LaTeX không tạo được PDF -> dùng PDF hai cột ReportLab. Chi tiết: "
                         + "; ".join(r.errors[:3]))
    if pdf is None:
        pdf = build_pdf(
            title=inp.title, authors=inp.authors, abstract=canon["abstract"], keywords=inp.keywords,
            sections={k: canon[k] for k in SECTION_KEYS if k != "abstract"}, papers=inp.papers,
            comparison_rows=inp.comparison_rows, figures=inp.figures,
            perf_grid=perf_grid, daggers=daggers,
            stats=stats_grid(inp.results) if inp.results else None,
            ablation=ablation_grid(inp.results) if inp.results else None,
            sensitivity_param=(sensitivity_data(inp.results) or ("",))[0] if inp.results else "",
            related_position=inp.related_position, funding_note=inp.funding_note,
            acknowledgment=inp.acknowledgment, topic=inp.topic,
            bibliometric=inp.bibliometric_figures,
        )
        if not detect_engine():
            notes.append("Máy chưa cài LaTeX -> PDF hai cột tạo bằng ReportLab (công thức hiển thị bằng ảnh).")

    bundle = build_bundle(tex, bib, figures_tex, pdf)
    todo = _todo(inp, res, removed_sentences, n_missing, engine, emptied)
    return PaperArtifacts(tex, bib, pdf, engine, bundle, todo, canon, notes, log, lclass)


def _todo(inp: PaperInput, res: ProcessResult, removed_sentences: list[str], n_missing: int,
          engine: str, emptied: list[str] | None = None) -> str:
    L = ["# TODO — những việc bạn cần tự kiểm tra / điền", ""]
    if any(a.get("name") == DEFAULT_AUTHOR for a in inp.authors) or not inp.authors:
        L.append("- [ ] Điền tên tác giả, đơn vị, quốc gia, email trong `config.yaml` (mục `paper.authors`).")
    if inp.results is None:
        L += [
            "- [ ] **Chạy thí nghiệm thật** (xem `experiments/README.md`) để tạo `results.json`, rồi chạy lại. "
            f"Hiện bảng so sánh có {n_missing} ô trống (`{MISSING}`); bảng thống kê dữ liệu, ablation và hình độ nhạy "
            "chưa xuất hiện vì chưa có dữ liệu.",
            "- [ ] Phần Experiments đang là KẾ HOẠCH (thì tương lai): kiểm tra datasets/baselines/metrics có thực sự dùng được, "
            "rồi viết lại thì quá khứ sau khi chạy.",
        ]
    else:
        L.append("- [ ] Đối chiếu lời bình trong 4.2–4.4 với `results.json` (hệ thống đã xoá câu chứa số lạ).")
        if not inp.results.topic:
            L.append("- [ ] `results.json` không ghi tên đề tài nên hệ thống KHÔNG kiểm tra được nó có đúng đề tài này không — "
                     "hãy tự đối chiếu (chạy `run_experiments.py --topic \"...\"` để ghi kèm).")
        if not inp.results.has_ablation():
            L.append("- [ ] `results.json` chưa có `ablation` → mục 4.3 chỉ ghi là chưa báo cáo.")
        if not inp.results.has_sensitivity():
            L.append("- [ ] `results.json` chưa có `sensitivity` → mục 4.4 chỉ ghi là chưa báo cáo.")
        if not inp.results.significance:
            L.append("- [ ] Chưa có `significance` (p-value) → bài không nêu khẳng định về ý nghĩa thống kê.")
    for name in emptied or []:
        L.append(f"- [ ] **Phần `{name}` đang TRỐNG** (mọi câu đều chứa số liệu không có thật) — hãy viết lại thủ công hoặc chạy lại.")
    if removed_sentences:
        L.append("- Các câu bị xoá vì chứa số không có trong dữ liệu thật (xem lại nếu cần ý đó):")
        L += [f"  - {s}" for s in removed_sentences]
    if res.removed_cites:
        L.append(f"- Trích dẫn bịa đã bị loại: {sorted(set(res.removed_cites))}")
    if res.bad_math:
        L.append("- Công thức LaTeX hỏng đã được thay bằng văn bản — hãy viết lại thủ công:")
        L += [f"  - `{it.body[:80]}` ({it.reason})" for it in res.bad_math]
    kinds = {k: sum(1 for p in inp.papers if p.kind == k) for k in ("journal", "conference", "preprint")}
    years = [p.year for p in inp.papers if p.year]
    if years:
        L.append(f"- Tài liệu tham khảo: {len(inp.papers)} bài (năm {min(years)}–{max(years)}; "
                 f"tạp chí {kinds['journal']}, hội nghị {kinds['conference']}, preprint {kinds['preprint']}). "
                 "Mở DOI/URL từng bài để xác minh trước khi nộp.")
    L += [f"- Nguồn tìm kiếm: {n}" for n in inp.search_notes]
    if engine == "reportlab":
        L.append("- PDF hiện là bản dự phòng ReportLab. Để có PDF dàn trang bằng LaTeX: cài LaTeX hoặc upload `paper_bundle.zip` lên Overleaf.")
    return "\n".join(L) + "\n"
