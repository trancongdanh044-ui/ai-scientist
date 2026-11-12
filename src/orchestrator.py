import asyncio
from pathlib import Path

from rich.console import Console

from src.agents.hypothesis import HypothesisAgent
from src.agents.literature import LiteratureAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.writer import WriterAgent
from src.config import AppConfig
from src.llm import LLMClient, LLMError
from src.paper_builder import PaperInput, build_paper
from src.tools.experiments import ResultsError, load_results
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
        cfg = self.cfg
        topic = cfg.research.topic
        out_dir = Path(cfg.output.dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        console.rule(f"[bold cyan]Topic: {topic}")

        # số liệu thực nghiệm THẬT (tuỳ chọn). Sai định dạng -> báo lỗi rõ ràng rồi dừng.
        try:
            results = load_results(cfg.paper.results_file, topic)
        except ResultsError as e:
            console.print(f"[bold red]Lỗi results.json:[/bold red] {e}")
            raise SystemExit(1) from e
        console.log(
            "Có results.json -> bảng kết quả dùng số liệu thật." if results else
            "Chưa có results.json -> phần Experiments là KẾ HOẠCH, ô kết quả để trống (không bịa số)."
        )

        try:
            console.log("[1/7] Tìm tài liệu tham khảo (Semantic Scholar / OpenAlex / Crossref / arXiv)...")
            lit = await self.lit.run(topic, cfg.research.num_papers, cfg.references)
        except LLMError as e:
            console.print(f"[bold red]Lỗi LLM:[/bold red] {e}")
            raise SystemExit(1) from e

        papers = lit["papers"]
        report = lit["report"]
        search_notes = [f"{s}: {n} kết quả" for s, n in report.per_source.items()]
        if report.failed_sources:
            search_notes.append("không trả về dữ liệu: " + ", ".join(report.failed_sources))
        console.log(f"   {len(papers)} bài từ năm {lit['min_year']} trở lại · " + "; ".join(search_notes))
        valid_keys = [p.key for p in papers]
        (out_dir / "literature.md").write_text(
            f"# Summaries\n\n{lit['summaries']}\n\n# Research Gap\n\n{lit['research_gap']}", encoding="utf-8")

        console.log("[2/7] Sinh giả thuyết...")
        hypotheses = await self.hyp.run(topic, lit["research_gap"], cfg.research.max_hypotheses)
        eval_rows = await self.hyp.eval_plan(hypotheses)
        (out_dir / "hypotheses.md").write_text(hypotheses, encoding="utf-8")

        console.log("[3/7] Viết các phần (bố cục & văn phong như bài mẫu NCF)...")
        w = self.writer
        gap = lit["research_gap"]
        raw = {
            "abstract": await w.write_abstract(topic, gap, hypotheses, results),
            "introduction": await w.write_introduction(topic, gap, hypotheses, valid_keys),
            "preliminaries": await w.write_preliminaries(hypotheses, gap, valid_keys),
            "methodology": await w.write_methodology(hypotheses),
            "experiments_intro": await w.write_experiments_intro(hypotheses, eval_rows, results),
            "experiments_setup": await w.write_experiments_setup(hypotheses, eval_rows, results),
            "exp_comparison": await w.write_exp_comparison(hypotheses, eval_rows, results),
            "exp_ablation": await w.write_exp_ablation(hypotheses, eval_rows, results),
            "exp_sensitivity": await w.write_exp_sensitivity(hypotheses, eval_rows, results),
            "related_work": await w.write_related_work(lit["summaries"], papers),
            "conclusion": await w.write_conclusion(topic, hypotheses, results is not None),
        }
        keywords = await w.write_keywords(topic, raw["abstract"])
        pipeline_steps = await w.pipeline_steps(raw["methodology"])

        console.log("[4/7] Vẽ hình (dữ liệu thật) ...")
        figures = await asyncio.to_thread(render_figures, papers, pipeline_steps, results)
        for name, png in figures.items():
            (out_dir / name).write_bytes(png)

        console.log("[5/7] Kiểm tra công thức, trích dẫn, số liệu & dựng bài báo hai cột...")
        inp = PaperInput(
            title=topic, topic=topic, authors=cfg.paper.authors, raw=raw, keywords=keywords,
            papers=papers, comparison_rows=lit["comparison_rows"], eval_rows=eval_rows,
            figures=figures, results=results, template_path=cfg.paper.template,
            related_position=cfg.paper.related_work_position, draft_notice=cfg.paper.draft_notice,
            acknowledgment=cfg.paper.acknowledgment, funding_note=cfg.paper.funding_note,
            bibliometric_figures=cfg.paper.bibliometric_figures, search_notes=search_notes,
        )
        art = await asyncio.to_thread(build_paper, inp)
        for n in art.notes:
            console.print(f"[yellow]• {n}[/yellow]")

        console.log("[6/7] Ghi file...")
        (out_dir / "paper.pdf").write_bytes(art.pdf)
        (out_dir / "paper.tex").write_text(art.tex, encoding="utf-8")
        (out_dir / "references.bib").write_text(art.bib, encoding="utf-8")
        (out_dir / "paper_bundle.zip").write_bytes(art.bundle)
        (out_dir / "TODO.md").write_text(art.todo_md, encoding="utf-8")
        if art.compile_log:
            (out_dir / "compile_log.txt").write_text(art.compile_log, encoding="utf-8")
        console.print(f"[green]✓ paper.pdf ({len(art.pdf) // 1024} KB, engine: {art.pdf_engine})[/green]")

        console.log("[7/7] Tự bình duyệt (self-review)...")
        review_text = "\n\n".join(f"## {k}\n{v}" for k, v in art.sections.items())
        review = await self.reviewer.run(review_text)
        (out_dir / "review.md").write_text(review, encoding="utf-8")

        console.rule("[bold green]Done")
        console.print(f"Outputs saved to: [bold]{out_dir.resolve()}[/bold]")
        console.print("Xem [bold]TODO.md[/bold] để biết những gì cần tự kiểm tra/điền.")
