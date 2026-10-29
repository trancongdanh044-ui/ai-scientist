import asyncio
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator

from backend.db import db, now_utc
from src.agents.hypothesis import HypothesisAgent
from src.agents.literature import LiteratureAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.writer import WriterAgent
from src.config import AppConfig, LLMConfig, OutputConfig, ResearchConfig
from src.llm import LLMClient, LLMError
from src.tools.bibliography import assign_keys, to_bibtex
from src.tools.latex_render import render_latex_to_string
from src.tools.latex_utils import clean_section, latex_escape
from src.tools.pdf_compiler import build_bundle, compile_pdf, detect_engine
from src.tools.pdf_writer import build_pdf, prepare_raw_section
from src.tools.tables import eval_plan_table, related_work_table
from src.tools.visuals import render_figures

# Thứ tự & % tiến độ của từng giai đoạn — frontend dùng đúng các key này để tô "done".
STAGES = [
    ("literature", 8, "Đang tìm & khảo sát bài báo trên arXiv..."),
    ("hypothesis", 16, "Đang sinh giả thuyết nghiên cứu..."),
    ("writing_abstract", 24, "Đang viết Abstract..."),
    ("writing_intro", 32, "Đang viết Introduction..."),
    ("writing_related", 40, "Đang viết Related Work..."),
    ("writing_method", 48, "Đang viết Methodology..."),
    ("writing_expdesign", 56, "Đang viết Experimental Design..."),
    ("writing_conclusion", 62, "Đang viết Conclusion..."),
    ("figures", 72, "Đang vẽ hình từ dữ liệu arXiv thật..."),
    ("tables", 78, "Đang sinh bảng (so sánh & kế hoạch đánh giá)..."),
    ("sanitize", 82, "Đang kiểm tra & làm sạch trích dẫn..."),
    ("render", 88, "Đang xuất mã nguồn LaTeX..."),
    ("compile", 95, "Đang tạo file PDF (ReportLab)..."),
    ("review", 100, "Đang tự bình duyệt (self-review)..."),
]
_STAGE_PCT = {s: p for s, p, _ in STAGES}


@dataclass
class Run:
    run_id: str
    topic: str
    status: str = "pending"
    stage: str = ""
    progress: int = 0
    error: str | None = None
    events: asyncio.Queue = field(default_factory=asyncio.Queue)


class RunManager:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}

    async def create_run(self, topic: str, req) -> Run:
        run_id = uuid.uuid4().hex[:12]
        run = Run(run_id=run_id, topic=topic)
        self.runs[run_id] = run

        await db.runs.insert_one({
            "_id": run_id, "topic": topic, "status": "pending", "stage": "", "progress": 0,
            "error": None, "model": req.model, "num_papers": req.num_papers,
            "max_hypotheses": req.max_hypotheses, "compile_ok": None,
            "created_at": now_utc(), "updated_at": now_utc(),
        })
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    async def _emit(self, run: Run, event: dict) -> None:
        await run.events.put(event)

    async def _stage(self, run: Run, stage: str, msg: str) -> None:
        progress = _STAGE_PCT.get(stage, run.progress)
        run.stage, run.progress = stage, progress
        await db.runs.update_one(
            {"_id": run.run_id},
            {"$set": {"stage": stage, "progress": progress, "updated_at": now_utc()}},
        )
        await db.stages.insert_one({
            "run_id": run.run_id, "stage": stage, "status": "running",
            "progress": progress, "message": msg, "ts": now_utc(),
        })
        await self._emit(run, {"type": "stage", "stage": stage, "progress": progress, "message": msg})

    async def _stage_done(self, run: Run, stage: str, message: str, preview: str = "", **extra) -> None:
        await db.stages.insert_one({
            "run_id": run.run_id, "stage": stage, "status": "done",
            "progress": run.progress, "message": message, "preview": preview[:5000], "ts": now_utc(),
        })
        await db.runs.update_one(
            {"_id": run.run_id}, {"$set": {"progress": run.progress, "updated_at": now_utc()}}
        )
        await self._emit(run, {"type": "stage_done", "stage": stage, "preview": preview[:2000], **extra})

    async def _save_file(self, run: Run, name: str, content, content_type: str) -> None:
        size = len(content) if isinstance(content, (bytes, bytearray)) else len(content.encode("utf-8"))
        await db.files.update_one(
            {"run_id": run.run_id, "name": name},
            {"$set": {
                "run_id": run.run_id, "name": name, "content": content,
                "content_type": content_type, "size": size, "created_at": now_utc(),
            }},
            upsert=True,
        )

    async def execute(self, run: Run, req, cfg_base: AppConfig) -> None:
        try:
            run.status = "running"
            await db.runs.update_one(
                {"_id": run.run_id}, {"$set": {"status": "running", "updated_at": now_utc()}}
            )
            await self._emit(run, {"type": "status", "status": "running"})

            cfg = AppConfig(
                llm=LLMConfig(model=req.model, temperature=cfg_base.llm.temperature, max_tokens=cfg_base.llm.max_tokens),
                research=ResearchConfig(topic=req.topic, num_papers=req.num_papers, max_hypotheses=req.max_hypotheses),
                output=OutputConfig(dir="", latex_template=cfg_base.output.latex_template),
                api_key=cfg_base.api_key, base_url=cfg_base.base_url,
            )
            llm = LLMClient(cfg.api_key, cfg.base_url, cfg.llm)
            lit_agent, hyp_agent = LiteratureAgent(llm), HypothesisAgent(llm)
            writer, reviewer = WriterAgent(llm), ReviewerAgent(llm)

            # ---------- 1. Literature ----------
            await self._stage(run, "literature", STAGES[0][2])
            lit = await lit_agent.run(req.topic, req.num_papers)
            papers = lit["papers"]
            valid_keys = [p.key for p in papers]

            await db.papers.update_one(
                {"run_id": run.run_id},
                {"$set": {
                    "run_id": run.run_id, "topic": req.topic,
                    "papers": [p.to_dict() for p in papers],
                    "summaries": lit["summaries"], "research_gap": lit["research_gap"],
                    "comparison_rows": lit["comparison_rows"], "created_at": now_utc(),
                }},
                upsert=True,
            )
            await self._stage_done(
                run, "literature", "Khảo sát xong", lit["summaries"],
                gap=lit["research_gap"][:2000], num_papers=len(papers),
                papers=[{"title": p.title, "year": p.year, "url": p.url} for p in papers],
            )

            # ---------- 2. Hypothesis ----------
            await self._stage(run, "hypothesis", STAGES[1][2])
            hypotheses = await hyp_agent.run(req.topic, lit["research_gap"], req.max_hypotheses)
            eval_rows = await hyp_agent.eval_plan(hypotheses)
            await db.hypotheses.update_one(
                {"run_id": run.run_id},
                {"$set": {"run_id": run.run_id, "content": hypotheses, "eval_rows": eval_rows, "created_at": now_utc()}},
                upsert=True,
            )
            await self._stage_done(run, "hypothesis", "Đã sinh giả thuyết", hypotheses)

            # ---------- 3. Writing ----------
            await self._stage(run, "writing_abstract", STAGES[2][2])
            abstract = await writer.write_abstract(req.topic, lit["research_gap"], hypotheses)

            await self._stage(run, "writing_intro", STAGES[3][2])
            introduction = await writer.write_introduction(req.topic, lit["research_gap"], hypotheses, valid_keys)

            await self._stage(run, "writing_related", STAGES[4][2])
            related_work = await writer.write_related_work(lit["summaries"], papers)

            await self._stage(run, "writing_method", STAGES[5][2])
            methodology = await writer.write_methodology(hypotheses)

            await self._stage(run, "writing_expdesign", STAGES[6][2])
            experimental_design = await writer.write_experimental_design(hypotheses, eval_rows)

            await self._stage(run, "writing_conclusion", STAGES[7][2])
            conclusion = await writer.write_conclusion(req.topic, hypotheses)
            pipeline_steps = await writer.pipeline_steps(methodology)

            # ---------- 4. Figures (dữ liệu thật) ----------
            await self._stage(run, "figures", STAGES[8][2])
            figures = await asyncio.to_thread(render_figures, papers, pipeline_steps)
            for name, png in figures.items():
                await self._save_file(run, name, png, "image/png")
            await self._stage_done(run, "figures", f"Đã tạo {len(figures)} hình", "\n".join(figures))

            # ---------- 5. Tables ----------
            await self._stage(run, "tables", STAGES[9][2])
            table_related = related_work_table(papers, lit["comparison_rows"])
            table_eval = eval_plan_table(eval_rows)
            await self._stage_done(run, "tables", "Đã tạo bảng", "")

            # ---------- 6. Sanitize (chống trích dẫn bịa) ----------
            await self._stage(run, "sanitize", STAGES[10][2])
            removed_all: list[str] = []
            clean = {}
            raw = {
                "abstract": abstract, "introduction": introduction, "related_work": related_work,
                "methodology": methodology, "experimental_design": experimental_design, "conclusion": conclusion,
            }
            for key, text in raw.items():
                c, removed = clean_section(text, set(valid_keys))
                clean[key] = c
                removed_all += removed
            pdf_sections = {k: prepare_raw_section(v, set(valid_keys)) for k, v in raw.items()}
            warn = f"Đã loại {len(removed_all)} trích dẫn không hợp lệ: {sorted(set(removed_all))}" if removed_all else "Không có trích dẫn bịa."
            await self._stage_done(run, "sanitize", warn, warn)

            sections = [
                {"name": "abstract", "content": pdf_sections["abstract"], "order": 1},
                {"name": "introduction", "content": pdf_sections["introduction"], "order": 2},
                {"name": "related_work", "content": pdf_sections["related_work"], "order": 3},
                {"name": "methodology", "content": pdf_sections["methodology"], "order": 4},
                {"name": "experimental_design", "content": pdf_sections["experimental_design"], "order": 5},
                {"name": "conclusion", "content": pdf_sections["conclusion"], "order": 6},
            ]
            for s in sections:
                s["run_id"] = run.run_id
                s["created_at"] = now_utc()
            await db.sections.delete_many({"run_id": run.run_id})
            await db.sections.insert_many(sections)

            # ---------- 7. Render LaTeX ----------
            await self._stage(run, "render", STAGES[11][2])
            bib_content = to_bibtex(papers)
            context = {
                "title": latex_escape(req.topic), "author": "Automated Research System",
                "query": latex_escape(req.topic),
                "abstract": clean["abstract"], "introduction": clean["introduction"],
                "related_work": clean["related_work"], "methodology": clean["methodology"],
                "experimental_design": clean["experimental_design"], "conclusion": clean["conclusion"],
                "table_related": table_related, "table_eval": table_eval,
                "fig_trend": "fig_trend.png" in figures, "fig_terms": "fig_terms.png" in figures,
                "fig_pipeline": "fig_pipeline.png" in figures, "has_bib": bool(papers),
            }
            tex_content = render_latex_to_string(cfg.output.latex_template, context)
            await self._save_file(run, "paper.tex", tex_content, "application/x-tex")
            await self._save_file(run, "references.bib", bib_content, "application/x-bibtex")
            await self._stage_done(run, "render", "Đã tạo paper.tex", "paper.tex đã lưu")

            # ---------- 8. PDF chính (ReportLab, luôn chạy được) + PDF phụ từ LaTeX ----------
            await self._stage(run, "compile", STAGES[12][2])
            pdf_bytes = await asyncio.to_thread(
                build_pdf, req.topic, req.topic, pdf_sections, papers,
                lit["comparison_rows"], eval_rows, figures,
            )
            await self._save_file(run, "paper.pdf", pdf_bytes, "application/pdf")
            await db.runs.update_one(
                {"_id": run.run_id}, {"$set": {"compile_ok": True, "compile_engine": "reportlab"}}
            )

            latex_pdf = None
            latex_note = "Chưa cài LaTeX nên bỏ qua paper_latex.pdf (không ảnh hưởng paper.pdf)."
            if detect_engine():
                result = await compile_pdf(tex_content, bib_content, figures)
                if result.ok:
                    latex_pdf = result.pdf
                    await self._save_file(run, "paper_latex.pdf", latex_pdf, "application/pdf")
                    latex_note = f"Có thêm bản PDF từ LaTeX ({result.engine}): paper_latex.pdf"
                else:
                    await self._save_file(run, "compile_log.txt", result.log or "(no log)", "text/plain")
                    latex_note = "Bản PDF từ LaTeX không biên dịch được (xem compile_log.txt) — paper.pdf vẫn đầy đủ."
            bundle = build_bundle(tex_content, bib_content, figures, latex_pdf or pdf_bytes)
            await self._save_file(run, "paper_bundle.zip", bundle, "application/zip")
            await self._stage_done(
                run, "compile", f"Đã tạo paper.pdf ({len(pdf_bytes) // 1024} KB). {latex_note}",
                latex_note, compile_ok=True,
            )

            # ---------- 9. Self-review ----------
            await self._stage(run, "review", STAGES[13][2])
            review_text = "\n\n".join(f"## {k}\n{v}" for k, v in pdf_sections.items())
            review = await reviewer.run(review_text)
            await db.reviews.update_one(
                {"run_id": run.run_id},
                {"$set": {"run_id": run.run_id, "content": review, "created_at": now_utc()}},
                upsert=True,
            )
            await self._save_file(run, "review.md", review, "text/markdown")
            await self._stage_done(run, "review", "Đã tự bình duyệt", review)

            run.status = "done"
            run.progress = 100
            await db.runs.update_one(
                {"_id": run.run_id}, {"$set": {"status": "done", "progress": 100, "updated_at": now_utc()}}
            )
            await self._emit(run, {"type": "done", "run_id": run.run_id})

        except LLMError as e:
            await self._fail(run, str(e))
        except Exception as e:  # noqa: BLE001
            await self._fail(run, str(e))

    async def _fail(self, run: Run, message: str) -> None:
        run.status, run.error = "error", message
        await db.runs.update_one(
            {"_id": run.run_id}, {"$set": {"status": "error", "error": message, "updated_at": now_utc()}}
        )
        await self._emit(run, {"type": "error", "error": message})

    async def stream(self, run_id: str) -> AsyncIterator[dict]:
        run = self.get(run_id)
        if not run:
            yield {"type": "error", "error": "run not found"}
            return
        while True:
            event = await run.events.get()
            yield event
            if event["type"] in ("done", "error"):
                break
