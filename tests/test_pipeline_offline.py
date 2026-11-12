"""
tests/test_pipeline_offline.py
-------------------------------
Dry-run KHÔNG cần API key, KHÔNG cần internet — dùng FakeLLM + dữ liệu tài liệu giả để kiểm tra
TOÀN BỘ pipeline mới: tìm tài liệu -> viết -> kiểm tra công thức -> bài báo HAI CỘT (IEEEtran) ->
PDF. Kiểm tra cả các cam kết trung thực: không bịa số liệu thực nghiệm, không trích dẫn bịa.

Chạy:  python -m unittest tests.test_pipeline_offline -v
"""
import asyncio
import json
import re
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AppConfig, LLMConfig, OutputConfig, PaperConfig, ResearchConfig  # noqa: E402
from src.orchestrator import Orchestrator  # noqa: E402
from src.tools.arxiv_search import Paper  # noqa: E402
from src.tools.pdf_compiler import detect_engine  # noqa: E402

FAKE_PAPERS = [
    Paper(
        title=f"Fake Paper {i + 1}: Parameter-Efficient Methods for BERT",
        authors=[f"Author{i + 1} Nguyen", "Second Author"],
        abstract=("This fake abstract discusses low-rank adapters, parameter-efficient fine-tuning, "
                  "and evaluation for language understanding tasks."),
        url=f"https://doi.org/10.1000/fake.{i}", published=f"{2021 + i % 4}-01-01",
        doi=f"10.1000/fake.{i}", venue="Proc. Fake Conf." if i % 2 else "Journal of Fake Results",
        kind="conference" if i % 2 else "journal", citations=10 * i, source="semanticscholar",
    )
    for i in range(5)
]

METHOD_TEXT = (
    "**Problem Formulation.** Let $\\mathbf{x}\\in\\mathbb{R}^{d}$ be an input and $\\hat{y}$ the prediction.\n"
    "$$\\hat{y} = \\sigma(\\mathbf{w}^{T}\\mathbf{x} + b) \\label{eq:model}$$\n"
    "**Training Objective.**\n"
    "\\begin{equation}\n\\mathcal{L} = -\\sum_{i} y_i \\log \\hat{y}_i + (1-y_i)\\log(1-\\hat{y}_i) \\label{eq:loss}\n\\end{equation}\n"
    "A broken one: $\\frac{a}{b$ and \\[ x = \\unknowncmd{y} \\]. See Eq.~\\eqref{eq:loss} and Eq.~\\eqref{eq:ghost}."
)


class FakeLLM:
    """Giả lập LLMClient — KHÔNG gọi mạng. Cố tình sinh nội dung 'xấu' để kiểm tra các lưới chắn."""

    async def complete(self, system, user, temperature=None):
        await asyncio.sleep(0)
        m = re.search(r"(?:ONLY these keys|never invent a new one):\s*([\w, ]+)", user)
        key = ",".join(k.strip() for k in m.group(1).split(",") if k.strip()) if m else ""
        cite = f" \\cite{{{key}}}" if key else ""
        cite_bad = " \\cite{madeup2099}"
        if "'Method' section" in user:
            return METHOD_TEXT
        if "'Preliminaries' section" in user:
            return ("We first formalize the problem.\n## Problem Formulation\nLet $x$ be an input.\n"
                    "\\begin{equation}\ny = f(x) \\label{eq:prelim}\n\\end{equation}\n"
                    f"## Existing Solutions and Their Limitations\nThe standard approach is limited.{cite}")
        if "opening of the 'Experiments'" in user:
            return ("The experiments answer three research questions.\nRQ1 Is it better?\nRQ2 Is each part useful?\n"
                    "RQ3 Is it robust? In what follows, we present the settings.")
        if "'4.1 Experimental Settings'" in user:
            return ("**Datasets.** We will use a corpus of 55,187 users and 1,500,809 interactions.\n"
                    "**Evaluation Protocols.** We will report accuracy.")
        if "answering RQ" in user or "will be answered" in user:
            return ("Table~\\ref{tab:results} fixes the layout. Our method reaches 0.93 accuracy and a 87.5% gain. "
                    "RQ1 is answered by the table.")
        if "ONE paragraph abstract" in user:
            return "We study efficient adaptation and obtain a 31.4% speedup on benchmarks."
        return (f"**Background.** Placeholder scientific text covering PEFT approaches \\u2265 baselines & more"
                f" costing $5 and $10 per run.{cite}{cite_bad}\n1. first\n2. second\n3. third")

    async def complete_json(self, system, user, temperature=0.2, retries=2):
        low = user.lower()
        if '"approach"' in low:
            keys = re.findall(r"key:\s*(\S+)", user)
            return [{"key": k, "approach": "Low-rank adapters", "limitation": "English-only eval"} for k in keys]
        if '"baseline"' in low:
            return [{"hypothesis": "H1", "baseline": "Full fine-tuning",
                     "metric": "F1 & accuracy", "dataset": "VLSP 2016"}]
        if "search queries" in low:
            return ["low rank adaptation", "parameter efficient transformers"]
        if "index terms" in low:
            return ["PEFT", "LoRA", "Vietnamese NLP", "Fine-tuning"]
        if "json list of strings" in low:
            return ["Data Collection", "Model Design", "Training", "Evaluation"]
        return None


def make_cfg(tmp_dir: Path, results_file: str = "no_such_results.json", position: str = "after") -> AppConfig:
    return AppConfig(
        llm=LLMConfig(model="fake-model", temperature=0.7, max_tokens=2000),
        research=ResearchConfig(topic="Test Topic", num_papers=5, max_hypotheses=2),
        output=OutputConfig(dir=str(tmp_dir), latex_template="templates/paper_ieee.tex.j2"),
        api_key="fake-key-for-offline-test-xxxxxxxx", base_url="http://fake.local/v1",
        paper=PaperConfig(results_file=results_file, related_work_position=position),
    )


async def run_pipeline(cfg: AppConfig):
    orch = Orchestrator(cfg)
    for agent in (orch.lit, orch.hyp, orch.writer, orch.reviewer):
        agent.llm = FakeLLM()

    async def fake_search(queries, num, min_year, sources=None, per_query=12):
        from src.tools.scholar_search import SearchReport
        return list(FAKE_PAPERS), SearchReport(per_source={"semanticscholar": 5}, min_year=min_year)

    with patch("src.agents.literature.search_literature", side_effect=fake_search):
        await orch.run()


class PipelineOfflineTest(unittest.IsolatedAsyncioTestCase):
    def _tmp(self, prefix):
        d = Path(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d

    async def test_full_pipeline_without_results(self):
        tmp = self._tmp("ai_sci_")
        await run_pipeline(make_cfg(tmp))
        tex = (tmp / "paper.tex").read_text(encoding="utf-8")
        bib = (tmp / "references.bib").read_text(encoding="utf-8")
        todo = (tmp / "TODO.md").read_text(encoding="utf-8")

        # --- bố cục như bài mẫu NCF: hai cột, mục đánh số Ả Rập, thứ tự mục ---
        self.assertIn("\\documentclass[10pt,a4paper,twocolumn]{article}", tex)
        self.assertNotIn("IEEEtran", tex)
        for sec in ("Preliminaries", "Method", "Experiments", "Experimental Settings", "Performance Comparison (RQ1)",
                    "Ablation Study (RQ2)", "Sensitivity Analysis (RQ3)", "Related Work", "Conclusion and Future Work"):
            self.assertIn(sec, tex)
        order = [tex.index(x) for x in ("\\section{Introduction}", "\\section{Preliminaries}", "\\section{Method}",
                                        "\\section{Experiments}", "\\section{Related Work}",
                                        "\\section{Conclusion and Future Work}")]
        self.assertEqual(order, sorted(order))                 # Related Work SAU Experiments
        self.assertIn("\\subsection{Problem Formulation}", tex)
        self.assertIn("\\begin{keywords}", tex)
        self.assertIn("\\bibliographystyle{abbrv}", tex)

        # --- KHÔNG có dòng Draft/TBD/placeholder trên bài báo ---
        for bad in ("TBD", "Draft", "draft:"):
            self.assertNotIn(bad, tex)
        self.assertIn("results.json", todo)

        # --- công thức: chuẩn hoá thành equation đánh số; công thức hỏng bị thay, không làm vỡ bài ---
        self.assertGreaterEqual(tex.count("\\begin{equation}"), 3)
        self.assertNotIn("$$", tex)
        self.assertNotIn("\\unknowncmd{y} \\]", tex)
        self.assertIn("\\texttt{", tex)
        self.assertNotIn("eq:ghost", tex)
        self.assertIn("\\$5 and \\$10", tex)

        # --- trung thực: không trích dẫn bịa, không số liệu bịa ---
        self.assertNotIn("madeup2099", tex)
        for fake in ("55,187", "87.5", "31.4"):
            self.assertNotIn(fake, tex)

        # --- tham khảo có DOI, đúng loại bài ---
        self.assertIn("@inproceedings{", bib)
        self.assertIn("@article{", bib)
        self.assertRegex(bib, r"doi = \{10\.1000/fake\.\d\}")
        self.assertIn("\\cite{", tex)

        pdf = (tmp / "paper.pdf").read_bytes()
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 20_000)
        with zipfile.ZipFile(tmp / "paper_bundle.zip") as z:
            self.assertIn("paper.tex", z.namelist())
            self.assertIn("references.bib", z.namelist())

    async def test_results_json_is_used_and_numbers_guarded(self):
        tmp = self._tmp("ai_sci_res_")
        rj = tmp / "results.json"
        rj.write_text(json.dumps({
            "datasets": ["VLSP 2016"], "metrics": ["Accuracy", "F1"], "seeds": 5,
            "methods": [
                {"name": "Full fine-tuning", "scores": {"VLSP 2016": {"Accuracy": {"mean": 0.912, "std": 0.004}, "F1": 0.905}}},
                {"name": "Proposed", "proposed": True, "scores": {"VLSP 2016": {"Accuracy": {"mean": 0.930, "std": 0.003}, "F1": 0.921}}},
            ],
            "significance": [{"dataset": "VLSP 2016", "metric": "Accuracy", "baseline": "Full fine-tuning",
                              "test": "paired t-test", "p": 0.004}],
            "ablation": {"dataset": "VLSP 2016", "variants": [
                {"name": "Full model", "scores": {"Accuracy": 0.930}}, {"name": "w/o adapter", "scores": {"Accuracy": 0.901}}]},
            "sensitivity": {"parameter": "rank r", "metric": "Accuracy", "values": [2, 4, 8],
                            "series": [{"name": "Proposed", "values": [0.90, 0.92, 0.93]}]},
            "dataset_stats": [{"name": "VLSP 2016", "fields": {"Train": 12000, "Test": 3000}}],
            "setup": {"hardware": "1x RTX 3090", "seeds": 3},
        }), encoding="utf-8")
        await run_pipeline(make_cfg(tmp / "out", str(rj)))
        out = tmp / "out"
        tex = (out / "paper.tex").read_text(encoding="utf-8")
        self.assertIn("0.930 $\\pm$ 0.003", tex)           # mean ± std THẬT
        self.assertIn("$^{\\dagger}$", tex)                # có kiểm định -> dấu †
        self.assertIn("tab:ablation", tex)
        self.assertIn("tab:stats", tex)
        self.assertIn("Statistics of the evaluation datasets", tex)
        self.assertIn("fig_sensitivity.png", tex)
        for name in ("fig_results.png", "fig_sensitivity.png"):
            self.assertTrue((out / name).exists())
        for fake in ("87.5", "TBD"):
            self.assertNotIn(fake, tex)                   # số bịa bị xoá, không có TBD

    async def test_results_of_another_topic_are_refused(self):
        tmp = self._tmp("ai_sci_topic_")
        rj = tmp / "results.json"
        rj.write_text(json.dumps({
            "topic": "A Totally Different Topic", "datasets": ["D"], "metrics": ["A"],
            "methods": [{"name": "M", "scores": {"D": {"A": 0.5}}}]}), encoding="utf-8")
        with self.assertRaises(SystemExit):          # CLI: dừng, không ghép số của đề tài khác vào bài
            await run_pipeline(make_cfg(tmp / "out", str(rj)))

    async def test_related_work_before_option(self):
        tmp = self._tmp("ai_sci_pos_")
        await run_pipeline(make_cfg(tmp, position="before"))
        tex = (tmp / "paper.tex").read_text(encoding="utf-8")
        self.assertLess(tex.index("\\section{Related Work}"), tex.index("\\section{Preliminaries}"))

    async def test_pdf_created_without_latex(self):
        """Máy KHÔNG có LaTeX: PDF hai cột ReportLab vẫn phải được tạo đầy đủ."""
        tmp = self._tmp("ai_sci_nolatex_")
        with patch("src.paper_builder.detect_engine", return_value=None):
            await run_pipeline(make_cfg(tmp))
        data = (tmp / "paper.pdf").read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 20_000)
        self.assertTrue((tmp / "paper.tex").exists())

    @unittest.skipUnless(detect_engine(), "Máy chưa cài LaTeX")
    async def test_latex_pdf_has_two_columns(self):
        import subprocess
        tmp = self._tmp("ai_sci_tex_")
        await run_pipeline(make_cfg(tmp))
        self.assertTrue((tmp / "paper.pdf").read_bytes().startswith(b"%PDF"))
        if shutil.which("pdftotext"):
            txt = subprocess.run(["pdftotext", "-layout", str(tmp / "paper.pdf"), "-"], capture_output=True,
                                 text=True).stdout
            self.assertIn("1. INTRODUCTION", txt)         # đề mục kiểu bài mẫu
            self.assertIn("ABSTRACT", txt)
            self.assertNotIn("TBD", txt)
            self.assertNotIn("Draft", txt)
        log = (tmp / "compile_log.txt").read_text(encoding="utf-8", errors="ignore")
        self.assertNotIn("Undefined control sequence", log)   # biên dịch SẠCH lỗi, không chỉ "ra được PDF"
        self.assertNotIn("not set up for use with LaTeX", log)


if __name__ == "__main__":
    unittest.main()
