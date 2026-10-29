import asyncio
from pathlib import Path

from rich.console import Console

from src.agents.hypothesis import HypothesisAgent
from src.agents.literature import LiteratureAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.writer import WriterAgent
from src.config import AppConfig
from src.llm import LLMClient, LLMError
from src.tools.bibliography import assign_keys, to_bibtex
from src.tools.latex_render import render_latex_to_string
from src.tools.latex_utils import clean_section, latex_escape
from src.tools.pdf_compiler import build_bundle, compile_pdf, detect_engine
from src.tools.pdf_writer import build_pdf, prepare_raw_section
from src.tools.tables import eval_plan_table, related_work_table
from src.tools.visuals import render_figures

console = Console()


class Orchestrator:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        llm = LLMClient(cfg.api_key, cfg.base_url, cfg.llm)
        self.lit = LiteratureAgent(llm)
        self.hyp = HypothesisAgent(llm)
        self.writer = WriterAgent(llm)
        self.reviewer = ReviewerAgent(llm)

    async def run(self) -> None:
        topic = self.cfg.research.topic
        out_dir = Path(self.cfg.output.dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        console.rule(f"[bold cyan]Topic: {topic}")

        try:
            console.log("[1/7] Literature review (arXiv)...")
            lit = await self.lit.run(topic, self.cfg.research.num_papers)
        except LLMError as e:
            console.print(f"[bold red]Lỗi LLM:[/bold red] {e}")
            raise SystemExit(1) from e

        papers = lit["papers"]
        valid_keys = [p.key for p in papers]
        (out_dir / "literature.md").write_text(
            f"# Summaries\n\n{lit['summaries']}\n\n# Research Gap\n\n{lit['research_gap']}",
            encoding="utf-8",
        )

        console.log("[2/7] Hypothesis generation...")
        hypotheses = await self.hyp.run(topic, lit["research_gap"], self.cfg.research.max_hypotheses)
        eval_rows = await self.hyp.eval_plan(hypotheses)
        (out_dir / "hypotheses.md").write_text(hypotheses, encoding="utf-8")

        console.log("[3/7] Writing sections...")
        abstract = await self.writer.write_abstract(topic, lit["research_gap"], hypotheses)
        introduction = await self.writer.write_introduction(topic, lit["research_gap"], hypotheses, valid_keys)
        related_work = await self.writer.write_related_work(lit["summaries"], papers)
        methodology = await self.writer.write_methodology(hypotheses)
        experimental_design = await self.writer.write_experimental_design(hypotheses, eval_rows)
        conclusion = await self.writer.write_conclusion(topic, hypotheses)
        pipeline_steps = await self.writer.pipeline_steps(methodology)

        console.log("[4/7] Vẽ hình (dữ liệu thật từ arXiv) & sinh bảng...")
        figures = render_figures(papers, pipeline_steps)
        for name, png in figures.items():
            (out_dir / name).write_bytes(png)
        table_related = related_work_table(papers, lit["comparison_rows"])
        table_eval = eval_plan_table(eval_rows)

        console.log("[5/7] Làm sạch & kiểm tra trích dẫn...")
        removed_all: list[str] = []
        sections_clean = {}
        for key, text in (
            ("abstract", abstract), ("introduction", introduction),
            ("related_work", related_work), ("methodology", methodology),
            ("experimental_design", experimental_design), ("conclusion", conclusion),
        ):
            clean, removed = clean_section(text, set(valid_keys))
            sections_clean[key] = clean
            removed_all += removed
        if removed_all:
            console.print(
                f"[yellow]⚠ Đã loại {len(removed_all)} trích dẫn không hợp lệ do model tự bịa: "
                f"{sorted(set(removed_all))}[/yellow]"
            )

        console.log("[6/7] Tạo PDF (ReportLab) + xuất mã nguồn LaTeX...")
        # --- PDF CHÍNH: ReportLab, thuần Python, luôn chạy được (không cần cài LaTeX) ---
        raw_sections = {
            "abstract": abstract, "introduction": introduction, "related_work": related_work,
            "methodology": methodology, "experimental_design": experimental_design,
            "conclusion": conclusion,
        }
        pdf_sections = {k: prepare_raw_section(v, set(valid_keys)) for k, v in raw_sections.items()}
        pdf_bytes = build_pdf(
            title=topic, topic=topic, sections=pdf_sections, papers=papers,
            comparison_rows=lit["comparison_rows"], eval_rows=eval_rows, figures=figures,
        )
        (out_dir / "paper.pdf").write_bytes(pdf_bytes)
        console.print(f"[green]✓ Đã tạo paper.pdf ({len(pdf_bytes) // 1024} KB) bằng ReportLab.[/green]")

        # --- Mã nguồn LaTeX (tuỳ chọn): để nộp tạp chí / chỉnh sửa trên Overleaf ---
        bib_content = to_bibtex(papers)
        context = {
            "title": latex_escape(topic),
            "author": "Automated Research System",
            "query": latex_escape(topic),
            **sections_clean,
            "table_related": table_related,
            "table_eval": table_eval,
            "fig_trend": "fig_trend.png" in figures,
            "fig_terms": "fig_terms.png" in figures,
            "fig_pipeline": "fig_pipeline.png" in figures,
            "has_bib": bool(papers),
        }
        tex_content = render_latex_to_string(self.cfg.output.latex_template, context)
        (out_dir / "paper.tex").write_text(tex_content, encoding="utf-8")
        (out_dir / "references.bib").write_text(bib_content, encoding="utf-8")

        latex_pdf = None
        if detect_engine():
            result = await compile_pdf(tex_content, bib_content, figures)
            if result.ok:
                latex_pdf = result.pdf
                (out_dir / "paper_latex.pdf").write_bytes(latex_pdf)
                console.print(f"[green]✓ Bản PDF phụ từ LaTeX ({result.engine}): paper_latex.pdf[/green]")
            else:
                (out_dir / "compile_log.txt").write_text(result.log, encoding="utf-8")
                console.print("[dim]Bản PDF từ LaTeX không biên dịch được (không ảnh hưởng paper.pdf) — xem compile_log.txt[/dim]")
        else:
            console.print("[dim](Chưa cài LaTeX — bỏ qua paper_latex.pdf; paper.pdf vẫn đầy đủ.)[/dim]")
        bundle = build_bundle(tex_content, bib_content, figures, latex_pdf or pdf_bytes)
        (out_dir / "paper_bundle.zip").write_bytes(bundle)

        console.log("[7/7] Tự bình duyệt (self-review)...")
        review_text = "\n\n".join(f"## {k}\n{v}" for k, v in pdf_sections.items())
        review = await self.reviewer.run(review_text)
        (out_dir / "review.md").write_text(review, encoding="utf-8")

        console.rule("[bold green]Done")
        console.print(f"Outputs saved to: [bold]{out_dir.resolve()}[/bold]")
