"""
tests/test_pipeline_offline.py
-------------------------------
Dry-run KHÔNG cần API key, KHÔNG cần internet — dùng FakeLLM (trả lời mẫu cố định)
+ dữ liệu arXiv giả để kiểm tra TOÀN BỘ pipeline (agent -> hình -> bảng -> LaTeX ->
biên dịch PDF) chạy đúng, trước khi bạn tốn phí API thật.

Đặc biệt hữu ích để kiểm tra server/máy đã cài LaTeX đúng chưa (nếu có tectonic/
latexmk/pdflatex, test sẽ kiểm tra luôn file PDF được tạo ra và có kích thước hợp lý).

Chạy:  python -m unittest tests.test_pipeline_offline -v
  hoặc: python tests/test_pipeline_offline.py
"""
import asyncio
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AppConfig, LLMConfig, OutputConfig, ResearchConfig  # noqa: E402
from src.orchestrator import Orchestrator  # noqa: E402
from src.tools.arxiv_search import Paper  # noqa: E402
from src.tools.pdf_compiler import detect_engine  # noqa: E402

FAKE_PAPERS = [
    Paper(
        title=f"Fake Paper {i + 1}: Parameter-Efficient Methods",
        authors=[f"Author{i + 1} Nguyen", "Second Author"],
        abstract=(
            "This fake abstract discusses low-rank adapters, parameter-efficient "
            "fine-tuning, and evaluation for language understanding tasks."
        ),
        url=f"http://arxiv.org/abs/2000.0000{i}",
        published=f"{2020 + i}-01-01",
        arxiv_id=f"2000.0000{i}",
    )
    for i in range(5)
]


class FakeLLM:
    """Giả lập LLMClient — KHÔNG gọi mạng, trả lời mẫu cố định đủ để chạy hết pipeline."""

    async def complete(self, system, user, temperature=None):
        await asyncio.sleep(0)
        return (
            "**Background.** This is placeholder scientific text for offline testing, "
            "covering PEFT approaches \u2265 baselines & more (50% fewer params).\n"
            "- first point\n- second point"
        )

    async def complete_json(self, system, user, temperature=0.2, retries=2):
        low = user.lower()
        if '"approach"' in low:
            keys = re.findall(r"key:\s*(\S+)", user)
            return [{"key": k, "approach": "Low-rank adapters", "limitation": "English-only eval"} for k in keys]
        if '"baseline"' in low:
            return [{"hypothesis": "H1", "baseline": "Full fine-tuning",
                      "metric": "F1 & accuracy", "dataset": "VLSP 2016"}]
        if "json list of strings" in low:
            return ["Data Collection", "Model Design", "Training", "Evaluation"]
        return None


class PipelineOfflineTest(unittest.IsolatedAsyncioTestCase):
    async def test_full_pipeline_produces_outputs(self):
        tmp_dir = Path(tempfile.mkdtemp(prefix="ai_scientist_test_"))
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)

        cfg = AppConfig(
            llm=LLMConfig(model="fake-model", temperature=0.7, max_tokens=2000),
            research=ResearchConfig(topic="Test Topic", num_papers=5, max_hypotheses=2),
            output=OutputConfig(dir=str(tmp_dir), latex_template="templates/paper.tex.j2"),
            api_key="fake-key-for-offline-test-xxxxxxxx",
            base_url="http://fake.local/v1",
        )

        orch = Orchestrator(cfg)
        fake = FakeLLM()
        for agent in (orch.lit, orch.hyp, orch.writer, orch.reviewer):
            agent.llm = fake  # thay LLM thật bằng bản giả — không tốn API, không cần mạng

        with patch("src.agents.literature.search_arxiv_async", return_value=FAKE_PAPERS):
            await orch.run()

        tex = tmp_dir / "paper.tex"
        bib = tmp_dir / "references.bib"
        self.assertTrue(tex.exists(), "paper.tex phải được tạo")
        self.assertTrue(bib.exists(), "references.bib phải được tạo")
        self.assertGreater(bib.stat().st_size, 0, "references.bib không được rỗng")
        self.assertIn("\\cite{", tex.read_text(encoding="utf-8"))

        for fig in ("fig_trend.png", "fig_pipeline.png"):
            self.assertTrue((tmp_dir / fig).exists(), f"{fig} phải được tạo (vẽ từ dữ liệu arXiv thật)")

        # PDF CHÍNH (ReportLab) phải LUÔN có, không phụ thuộc LaTeX đã cài hay chưa
        pdf = tmp_dir / "paper.pdf"
        self.assertTrue(pdf.exists(), "paper.pdf phải luôn được tạo (ReportLab, không cần LaTeX)")
        data = pdf.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"), "paper.pdf không phải PDF hợp lệ")
        self.assertGreater(len(data), 20_000, "PDF quá nhỏ — có thể thiếu hình/bảng")
        print(f"\n✓ paper.pdf hợp lệ: {len(data)} bytes (ReportLab)")

        # PDF PHỤ từ LaTeX: chỉ kiểm tra nếu máy có cài trình biên dịch
        if detect_engine():
            self.assertTrue((tmp_dir / "paper_latex.pdf").exists(),
                            "Máy có LaTeX nhưng không tạo được paper_latex.pdf — xem compile_log.txt")
            print("✓ paper_latex.pdf (bản phụ từ LaTeX) cũng được tạo")
        else:
            print("ℹ Máy chưa cài LaTeX — bỏ qua paper_latex.pdf (không ảnh hưởng paper.pdf).")

    async def test_pdf_still_created_without_latex(self):
        """Tình huống máy KHÔNG cài LaTeX/MiKTeX: paper.pdf (ReportLab) vẫn phải được tạo đầy đủ."""
        tmp_dir = Path(tempfile.mkdtemp(prefix="ai_scientist_nolatex_"))
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        cfg = AppConfig(
            llm=LLMConfig(model="fake-model", temperature=0.7, max_tokens=2000),
            research=ResearchConfig(topic="Test Topic", num_papers=5, max_hypotheses=2),
            output=OutputConfig(dir=str(tmp_dir), latex_template="templates/paper.tex.j2"),
            api_key="fake-key-for-offline-test-xxxxxxxx", base_url="http://fake.local/v1",
        )
        orch = Orchestrator(cfg)
        for agent in (orch.lit, orch.hyp, orch.writer, orch.reviewer):
            agent.llm = FakeLLM()

        with patch("src.agents.literature.search_arxiv_async", return_value=FAKE_PAPERS), \
             patch("src.orchestrator.detect_engine", return_value=None):
            await orch.run()

        self.assertTrue((tmp_dir / "paper.pdf").read_bytes().startswith(b"%PDF"))
        self.assertFalse((tmp_dir / "paper_latex.pdf").exists(), "Không có LaTeX thì không có paper_latex.pdf")
        self.assertTrue((tmp_dir / "paper.tex").exists(), "Vẫn xuất paper.tex để dùng Overleaf")
        print("\n✓ Không có LaTeX: paper.pdf vẫn được tạo bình thường")


if __name__ == "__main__":
    unittest.main()
