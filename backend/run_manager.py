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
from src.paper_builder import SECTION_KEYS, PaperInput, build_paper
from src.tools.experiments import ResultsError, ResultsTopicMismatch, load_results
from src.tools.visuals import render_figures

# Thứ tự & % tiến độ của từng giai đoạn — frontend dùng đúng các key này để tô "done".
STAGES = [
    ("literature", 8, "Đang tìm tài liệu tham khảo (Semantic Scholar/OpenAlex/Crossref/arXiv)..."),
    ("hypothesis", 16, "Đang sinh giả thuyết nghiên cứu..."),
    ("writing_abstract", 24, "Đang viết Abstract..."),
    ("writing_intro", 32, "Đang viết Introduction..."),
    ("writing_related", 40, "Đang viết Preliminaries & Related Work..."),
    ("writing_method", 48, "Đang viết Method..."),
    ("writing_expdesign", 56, "Đang viết Experiments (setup & results)..."),
    ("writing_conclusion", 62, "Đang viết Conclusion..."),
    ("figures", 72, "Đang vẽ hình từ dữ liệu thật..."),
    ("tables", 78, "Đang sinh bảng (so sánh & kế hoạch đánh giá)..."),
    ("sanitize", 82, "Đang kiểm tra công thức, trích dẫn & số liệu..."),
    ("render", 88, "Đang xuất mã nguồn LaTeX (hai cột)..."),
    ("compile", 95, "Đang tạo file PDF hai cột..."),
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
    recoverable: bool = False
    error_code: str | None = None
    events: asyncio.Queue = field(default_factory=asyncio.Queue)
    pause_gate: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None

    def __post_init__(self) -> None:
        self.pause_gate.set()


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

    async def pause(self, run_id: str) -> Run | None:
        run = self.get(run_id)
        if not run or run.status not in {"pending", "running"}:
            return None
        run.pause_gate.clear()
        run.status = "paused"
        await db.runs.update_one({"_id": run_id}, {"$set": {"status": "paused", "updated_at": now_utc()}})
        await self._emit(run, {"type": "status", "status": "paused", "message": "Đã tạm dừng sau bước hiện tại."})
        return run

    async def resume(self, run_id: str) -> Run | None:
        run = self.get(run_id)
        if not run or run.status != "paused":
            return None
        run.status = "running"
        run.pause_gate.set()
        await db.runs.update_one({"_id": run_id}, {"$set": {"status": "running", "updated_at": now_utc()}})
        await self._emit(run, {"type": "status", "status": "running", "message": "Đang tiếp tục nghiên cứu."})
        return run

    async def delete(self, run_id: str) -> bool:
        exists = self.get(run_id) or await db.runs.find_one({"_id": run_id})
        if not exists:
            return False
        run = self.runs.pop(run_id, None)
        if run and run.task and not run.task.done():
            run.task.cancel()
        for collection in (db.stages, db.papers, db.hypotheses, db.sections, db.reviews, db.files):
            await collection.delete_many({"run_id": run_id})
        await db.runs.delete_many({"_id": run_id})
        return True

    async def _emit(self, run: Run, event: dict) -> None:
        await run.events.put(event)

    async def _stage(self, run: Run, stage: str, msg: str) -> None:
        await run.pause_gate.wait()
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

    async def _checkpoint_section(self, run: Run, name: str, content: str, order: int) -> None:
        await db.sections.update_one(
            {"run_id": run.run_id, "name": name},
            {"$set": {"run_id": run.run_id, "name": name, "content": content,
                      "order": order, "checkpoint": True, "created_at": now_utc()}},
            upsert=True,
        )

    async def execute(self, run: Run, req, cfg_base: AppConfig) -> None:
        run.task = asyncio.current_task()
        try:
            run.status = "running"
            await db.runs.update_one(
                {"_id": run.run_id}, {"$set": {"status": "running", "updated_at": now_utc()}}
            )
            await self._emit(run, {"type": "status", "status": "running"})

            cfg = AppConfig(
                llm=LLMConfig(model=req.model, temperature=cfg_base.llm.temperature, max_tokens=cfg_base.llm.max_tokens),
                research=ResearchConfig(topic=req.topic, num_papers=req.num_papers, max_hypotheses=req.max_hypotheses),
                output=OutputConfig(dir="", latex_template=cfg_base.paper.template),
                api_key=cfg_base.api_key, base_url=cfg_base.base_url,
                references=cfg_base.references, paper=cfg_base.paper,
            )
            try:
                results = load_results(cfg.paper.results_file, req.topic)
            except ResultsTopicMismatch:
                results = None  # web: nhiều đề tài dùng chung máy chủ -> bỏ qua kết quả của đề tài khác, không bịa
            except ResultsError as e:
                raise RuntimeError(f"results.json không hợp lệ: {e}") from e
            llm = LLMClient(cfg.api_key, cfg.base_url, cfg.llm)
            lit_agent, hyp_agent = LiteratureAgent(llm), HypothesisAgent(llm)
            writer, reviewer = WriterAgent(llm), ReviewerAgent(llm)

            # ---------- 1. Literature ----------
            await self._stage(run, "literature", STAGES[0][2])
            lit = await lit_agent.run(req.topic, req.num_papers, cfg.references)
            papers = lit["papers"]
            valid_keys = [p.key for p in papers]
            report = lit["report"]
            search_notes = [f"{s_}: {n} kết quả" for s_, n in report.per_source.items()]
            if report.failed_sources:
                search_notes.append("không trả về dữ liệu: " + ", ".join(report.failed_sources))

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
                run, "literature", f"Khảo sát xong ({'; '.join(search_notes)})", lit["summaries"],
                gap=lit["research_gap"][:2000], num_papers=len(papers),
                papers=[{"title": p.title, "year": p.year, "url": p.link} for p in papers],
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
            gap = lit["research_gap"]
            raw: dict[str, str] = {}
            await self._stage(run, "writing_abstract", STAGES[2][2])
            raw["abstract"] = await writer.write_abstract(req.topic, gap, hypotheses, results)
            await self._checkpoint_section(run, "abstract", raw["abstract"], 1)
            keywords = await writer.write_keywords(req.topic, raw["abstract"])

            await self._stage(run, "writing_intro", STAGES[3][2])
            raw["introduction"] = await writer.write_introduction(req.topic, gap, hypotheses, valid_keys)
            await self._checkpoint_section(run, "introduction", raw["introduction"], 2)

            await self._stage(run, "writing_related", STAGES[4][2])
            raw["preliminaries"] = await writer.write_preliminaries(hypotheses, gap, valid_keys)
            raw["related_work"] = await writer.write_related_work(lit["summaries"], papers)
            await self._checkpoint_section(run, "preliminaries", raw["preliminaries"], 3)
            await self._checkpoint_section(run, "related_work", raw["related_work"], 9)

            await self._stage(run, "writing_method", STAGES[5][2])
            raw["methodology"] = await writer.write_methodology(hypotheses)
            await self._checkpoint_section(run, "methodology", raw["methodology"], 4)

            await self._stage(run, "writing_expdesign", STAGES[6][2])
            raw["experiments_intro"] = await writer.write_experiments_intro(hypotheses, eval_rows, results)
            raw["experiments_setup"] = await writer.write_experiments_setup(hypotheses, eval_rows, results)
            raw["exp_comparison"] = await writer.write_exp_comparison(hypotheses, eval_rows, results)
            raw["exp_ablation"] = await writer.write_exp_ablation(hypotheses, eval_rows, results)
            raw["exp_sensitivity"] = await writer.write_exp_sensitivity(hypotheses, eval_rows, results)
            for order, name in enumerate(("experiments_intro", "experiments_setup", "exp_comparison", "exp_ablation", "exp_sensitivity"), 5):
                await self._checkpoint_section(run, name, raw[name], order)

            await self._stage(run, "writing_conclusion", STAGES[7][2])
            raw["conclusion"] = await writer.write_conclusion(req.topic, hypotheses, results is not None)
            await self._checkpoint_section(run, "conclusion", raw["conclusion"], 10)
            pipeline_steps = await writer.pipeline_steps(raw["methodology"])

            # ---------- 4. Figures (dữ liệu thật) ----------
            await self._stage(run, "figures", STAGES[8][2])
            figures = await asyncio.to_thread(render_figures, papers, pipeline_steps, results)
            for name, png in figures.items():
                await self._save_file(run, name, png, "image/png")
            await self._stage_done(run, "figures", f"Đã tạo {len(figures)} hình", "\n".join(figures))

            # ---------- 5. Tables (sinh trong paper_builder cùng lúc dựng bài) ----------
            await self._stage(run, "tables", STAGES[9][2])
            await self._stage_done(
                run, "tables",
                "Bảng kết quả dùng số liệu thật từ results.json" if results else
                "Chưa có results.json: bảng kết quả để trống (không bịa số)", "")

            # ---------- 6. Kiểm tra công thức / trích dẫn / số liệu + dựng bài hai cột ----------
            await self._stage(run, "sanitize", STAGES[10][2])
            inp = PaperInput(
                title=req.topic, topic=req.topic, authors=cfg.paper.authors, raw=raw, keywords=keywords,
                papers=papers, comparison_rows=lit["comparison_rows"], eval_rows=eval_rows,
                figures=figures, results=results, template_path=cfg.paper.template,
                related_position=cfg.paper.related_work_position, draft_notice=cfg.paper.draft_notice,
                acknowledgment=cfg.paper.acknowledgment, funding_note=cfg.paper.funding_note,
                bibliometric_figures=cfg.paper.bibliometric_figures, search_notes=search_notes,
            )
            art = await asyncio.to_thread(build_paper, inp)
            warn = " | ".join(art.notes) if art.notes else "Công thức, trích dẫn và số liệu đều hợp lệ."
            await self._stage_done(run, "sanitize", warn[:600], warn)

            sections = [
                {"name": k, "content": art.sections[k], "order": i + 1}
                for i, k in enumerate(SECTION_KEYS)
            ]
            for s_ in sections:
                s_["run_id"] = run.run_id
                s_["created_at"] = now_utc()
            await db.sections.delete_many({"run_id": run.run_id})
            await db.sections.insert_many(sections)

            # ---------- 7. LaTeX ----------
            await self._stage(run, "render", STAGES[11][2])
            await self._save_file(run, "paper.tex", art.tex, "application/x-tex")
            await self._save_file(run, "references.bib", art.bib, "application/x-bibtex")
            await self._save_file(run, "TODO.md", art.todo_md, "text/markdown")
            await self._stage_done(run, "render", "Đã tạo paper.tex", "paper.tex đã lưu")

            # ---------- 8. PDF ----------
            await self._stage(run, "compile", STAGES[12][2])
            await self._save_file(run, "paper.pdf", art.pdf, "application/pdf")
            if art.compile_log:
                await self._save_file(run, "compile_log.txt", art.compile_log, "text/plain")
            await self._save_file(run, "paper_bundle.zip", art.bundle, "application/zip")
            await db.runs.update_one(
                {"_id": run.run_id}, {"$set": {"compile_ok": True, "compile_engine": art.pdf_engine}}
            )
            await self._stage_done(
                run, "compile", f"Đã tạo paper.pdf ({len(art.pdf) // 1024} KB, engine: {art.pdf_engine})",
                "\n".join(art.notes), compile_ok=True,
            )

            # ---------- 9. Self-review ----------
            await self._stage(run, "review", STAGES[13][2])
            review_text = "\n\n".join(f"## {k}\n{v}" for k, v in art.sections.items())
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

        except asyncio.CancelledError:
            return
        except LLMError as e:
            await self._fail(run, str(e), recoverable=e.recoverable, error_code=e.code)
        except Exception as e:  # noqa: BLE001
            await self._fail(run, str(e))

    async def _fail(self, run: Run, message: str, recoverable: bool = False, error_code: str = "pipeline_error") -> None:
        run.status, run.error = "error", message
        run.recoverable, run.error_code = recoverable, error_code
        await db.runs.update_one(
            {"_id": run.run_id}, {"$set": {"status": "error", "error": message,
             "recoverable": recoverable, "error_code": error_code, "updated_at": now_utc()}}
        )
        await self._emit(run, {"type": "error", "error": message,
                               "recoverable": recoverable, "error_code": error_code})

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
