"""
tests/test_backend_offline.py
------------------------------
Test KHÔNG cần MongoDB, API key hay internet: chạy RunManager.execute() (đường FastAPI)
từ đầu đến cuối với DB giả (trong bộ nhớ) + LLM giả + dữ liệu arXiv giả, rồi kiểm tra
mọi file kết quả (paper.pdf, paper.tex, hình, bảng...) đã được lưu đúng.

Chạy:  python -m unittest tests.test_backend_offline -v
"""
import asyncio
import re
import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.arxiv_search import Paper  # noqa: E402


# ----------------------------------------------------------------- DB giả trong bộ nhớ
def _match(doc, flt):
    return all(doc.get(k) == v for k, v in flt.items())


class FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def insert_many(self, docs):
        self.docs.extend(dict(d) for d in docs)

    async def delete_many(self, flt):
        self.docs = [d for d in self.docs if not _match(d, flt)]

    async def find_one(self, flt):
        return next((d for d in self.docs if _match(d, flt)), None)

    async def update_one(self, flt, update, upsert=False):
        for d in self.docs:
            if _match(d, flt):
                d.update(update.get("$set", {}))
                return
        if upsert:
            new = dict(flt)
            new.update(update.get("$set", {}))
            self.docs.append(new)


class FakeDB:
    def __init__(self):
        for name in ("runs", "papers", "hypotheses", "sections", "reviews", "files", "stages"):
            setattr(self, name, FakeCollection())


FAKE_DB = FakeDB()
_fake_module = types.ModuleType("backend.db")
_fake_module.db = FAKE_DB
_fake_module.now_utc = lambda: datetime.now(timezone.utc)
sys.modules["backend.db"] = _fake_module  # thay module DB thật (motor/MongoDB) bằng bản giả

from backend.run_manager import RunManager  # noqa: E402
from src.config import AppConfig, LLMConfig, OutputConfig, ResearchConfig  # noqa: E402


# ----------------------------------------------------------------- LLM giả
class FakeLLM:
    async def complete(self, system, user, temperature=None):
        await asyncio.sleep(0)
        keys = re.findall(r"\[([a-z0-9]+)\]", user)
        cite = f" \\cite{{{keys[0]}}}" if keys else ""
        return (f"**Nền tảng.** Đây là văn bản mẫu để kiểm thử, PEFT $\\geq$ baseline & hơn thế (giảm 50% tham số){cite}.\n"
                "- điểm thứ nhất\n- điểm thứ hai")

    async def complete_json(self, system, user, temperature=0.2, retries=2):
        low = user.lower()
        if '"approach"' in low:
            return [{"key": k, "approach": "Low-rank adapters", "limitation": "English-only evaluation"}
                    for k in re.findall(r"key:\s*(\S+)", user)]
        if '"baseline"' in low:
            return [{"hypothesis": "H1", "baseline": "Full fine-tuning", "metric": "F1", "dataset": "VLSP 2016"}]
        if "json list of strings" in low:
            return ["Data Collection", "Model Design", "Training", "Evaluation"]
        return None


FAKE_PAPERS = [
    Paper(title=f"Fake Paper {i + 1}: Parameter-Efficient Methods", authors=[f"Author{i + 1} Nguyen", "Second Author"],
          abstract="Low-rank adapters, parameter-efficient fine-tuning and evaluation.",
          url=f"http://arxiv.org/abs/2000.0000{i}", published=f"{2019 + i}-01-01", arxiv_id=f"2000.0000{i}")
    for i in range(5)
]


class BackendOfflineTest(unittest.IsolatedAsyncioTestCase):
    async def test_execute_end_to_end(self):
        cfg = AppConfig(
            llm=LLMConfig(model="fake", temperature=0.7, max_tokens=1000),
            research=ResearchConfig(topic="Test", num_papers=5, max_hypotheses=2),
            output=OutputConfig(dir="", latex_template="templates/paper.tex.j2"),
            api_key="fake-key-xxxxxxxxxxxxxxxxxxxxxxxx", base_url="http://fake.local/v1",
        )
        req = SimpleNamespace(topic="Tinh chỉnh hiệu quả tham số cho tiếng Việt", num_papers=5,
                              max_hypotheses=2, model="fake")

        manager = RunManager()
        run = await manager.create_run(req.topic, req)

        with patch("backend.run_manager.LLMClient", return_value=FakeLLM()), \
             patch("src.agents.literature.search_arxiv_async", return_value=FAKE_PAPERS):
            await manager.execute(run, req, cfg)

        self.assertEqual(run.status, "done", f"Run lỗi: {run.error}")

        files = {d["name"]: d for d in FAKE_DB.files.docs if d["run_id"] == run.run_id}
        for name in ("paper.pdf", "paper.tex", "references.bib", "paper_bundle.zip", "review.md"):
            self.assertIn(name, files, f"Thiếu file {name}")

        pdf = files["paper.pdf"]["content"]
        self.assertTrue(pdf.startswith(b"%PDF"), "paper.pdf không phải PDF hợp lệ")
        self.assertGreater(len(pdf), 20_000, "PDF quá nhỏ — có thể thiếu hình/bảng")
        self.assertEqual(files["paper.pdf"]["content_type"], "application/pdf")

        figs = [n for n in files if n.startswith("fig_")]
        self.assertGreaterEqual(len(figs), 2, f"Cần ≥2 hình, thấy {figs}")

        run_doc = await FAKE_DB.runs.find_one({"_id": run.run_id})
        self.assertTrue(run_doc["compile_ok"])
        self.assertEqual(run_doc["compile_engine"], "reportlab")
        self.assertEqual(len([s for s in FAKE_DB.sections.docs if s["run_id"] == run.run_id]), 6)

        # Không còn mã LaTeX thô trong nội dung hiển thị
        for s in FAKE_DB.sections.docs:
            self.assertNotIn("\\textbf", s["content"])
        print(f"\n✓ Backend end-to-end OK — PDF {len(pdf) // 1024} KB, hình: {figs}")


if __name__ == "__main__":
    unittest.main()
