"""WriterAgent — viết từng phần theo văn phong/bố cục của một bài báo hội nghị (kiểu ACM/IEEE,
mẫu tham chiếu: "Neural Collaborative Filtering", WWW 2017):

  1 Introduction (4 đoạn + danh sách 3 đóng góp) -> 2 Preliminaries -> 3 Method ->
  4 Experiments (RQ1..RQ3; 4.1 Experimental Settings; 4.2 Performance Comparison; 4.3 Ablation;
  4.4 Sensitivity) -> 5 Related Work -> 6 Conclusion and Future Work.

Nguyên tắc trung thực: hệ thống không chạy thí nghiệm. Khi KHÔNG có results.json, phần
Experiments viết ở thì tương lai và cấm nêu số; khi CÓ results.json, LLM chỉ được bình luận
trên đúng số liệu thật được đưa vào prompt (và bị lưới chắn số liệu kiểm tra lại sau đó).
"""
from src.agents.base import BaseAgent
from src.tools.arxiv_search import Paper
from src.tools.experiments import ExperimentResults, summarize_for_prompt

STYLE = (
    "You are an academic writer producing a conference paper in the style of ACM/IEEE venues "
    "(WWW, SIGIR, ICASSP). Write precise, formal English in the active voice ('we propose', "
    "'we adopt'); define every symbol at first use; prefer concrete statements over hype.\n"
    "FORMAT RULES (the text is typeset with LaTeX, a broken formula breaks the paper):\n"
    "- Inline math: $...$. Display math ONLY as \\begin{equation} ... \\end{equation} (or align) "
    "with \\label{eq:short-name}. Never use $$...$$ or \\[...\\].\n"
    "- Use only standard amsmath/amssymb commands (\\frac, \\sum, \\mathbf, \\mathcal, \\hat, \\odot, "
    "\\text, \\log, \\argmax...). Every \\left needs a matching \\right. No Unicode math symbols. "
    "Escape nothing yourself except by using LaTeX commands.\n"
    "- Sub-headings: a line '## Title' (subsection) or '### Title' (sub-subsection), WITHOUT numbers "
    "(numbering is automatic); never write section-level '# ' headings. For run-in headings write "
    "**Datasets.** at the start of a paragraph. Bullet lines start with '- ', numbered lines with '1. '.\n"
    "- URLs (datasets, code) go in a footnote: \\footnote{\\url{https://...}} — only URLs you were given.\n"
    "- Refer to equations as Eq.~\\eqref{eq:name} ONLY for labels you defined yourself.\n"
    "- NEVER invent a citation key that was not explicitly given to you. If you are not given any "
    "valid keys, do not use \\cite at all."
)


class WriterAgent(BaseAgent):
    name = "WriterAgent"
    system_prompt = STYLE

    # ------------------------------------------------------------------ front matter
    async def write_abstract(self, topic: str, gap: str, hypotheses: str,
                             results: ExperimentResults | None = None) -> str:
        if results:
            res_rule = (
                "Real experimental results are available (below). You MAY state one headline finding, "
                "using ONLY numbers from this table:\n" + summarize_for_prompt(results)
            )
        else:
            res_rule = (
                "No experiments were run, so do not state any result numbers; describe the planned "
                "evaluation instead."
            )
        user = (
            f"Topic: {topic}\n\nGap:\n{gap}\n\nHypotheses:\n{hypotheses}\n\n"
            "Write ONE paragraph abstract of 150-190 words: background, gap, proposed approach, "
            f"evaluation. {res_rule} No citations, no formulas, no line breaks."
        )
        return await self.llm.complete(self.system_prompt, user, temperature=0.5)

    async def write_keywords(self, topic: str, abstract: str) -> list[str]:
        user = (
            f"Topic: {topic}\nAbstract: {abstract}\n\nGive 4-6 index terms (keywords) as in a "
            "conference paper, each 1-3 words. Reply ONLY with a JSON list of strings."
        )
        try:
            data = await self.llm.complete_json(self.system_prompt, user)
        except Exception:  # noqa: BLE001
            data = None
        kws = [str(k).strip().rstrip(".") for k in data if str(k).strip()] if isinstance(data, list) else []
        return kws[:6] or [w for w in topic.split() if len(w) > 3][:5]

    # ------------------------------------------------------------------ body
    async def write_introduction(self, topic: str, gap: str, hypotheses: str, keys: list[str]) -> str:
        cite_rule = (
            f"Cite prior work with \\cite{{key}} using ONLY these keys: {', '.join(keys)}."
            if keys else "Do not use \\cite at all in this section (no valid keys available)."
        )
        user = (
            f"Topic: {topic}\n\nGap:\n{gap}\n\nHypotheses:\n{hypotheses}\n\n"
            "Write the Introduction (420-520 words) in four parts, like a top-tier conference paper:\n"
            "1) context and why the problem matters; 2) what existing approaches do and where they fall short "
            "(cite them); 3) what this paper does and the key idea (no result numbers); 4) one sentence "
            "'The main contributions of this work are as follows.' followed by exactly three numbered "
            f"lines (1. 2. 3.) listing the contributions. {cite_rule}"
        )
        return await self.llm.complete(self.system_prompt, user)

    async def write_related_work(self, summaries: str, papers: list[Paper]) -> str:
        keys = ", ".join(p.key for p in papers)
        user = (
            f"Summaries of related papers (tagged by [key]):\n{summaries}\n\n"
            f"Valid citation keys — use EXACTLY these, never invent a new one: {keys}\n\n"
            "Write the Related Work section (380-450 words). Group papers by theme in 3-4 paragraphs, "
            "state how each group differs from our approach, and cite EVERY paper you discuss using "
            "\\cite{key} (several keys allowed: \\cite{a,b}). Use a bold run-in heading per group "
            "(e.g. **Parameter-efficient adaptation.**). End with a short paragraph pointing to the "
            "research gap this paper addresses."
        )
        return await self.llm.complete(self.system_prompt, user)

    async def write_preliminaries(self, hypotheses: str, gap: str, keys: list[str]) -> str:
        cite_rule = (f"Cite existing solutions with \\cite{{key}} using ONLY these keys: {', '.join(keys)}."
                     if keys else "Do not use \\cite in this section.")
        user = (
            f"Hypotheses:\n{hypotheses}\n\nResearch gap:\n{gap}\n\n"
            "Write the 'Preliminaries' section (330-420 words, no section heading). Open with one sentence: "
            "'We first formalize the problem and discuss existing solutions ...'. Then two subsections using "
            "'## ' headings: '## Problem Formulation' (notation, input/output, the formal definition with at "
            "least one numbered display equation) and '## Existing Solutions and Their Limitations' (how the "
            "standard approach works, with one equation if natural, then its limitation that motivates our "
            f"method). {cite_rule}"
        )
        return await self.llm.complete(self.system_prompt, user)

    async def write_methodology(self, hypotheses: str) -> str:
        user = (
            f"Hypotheses:\n{hypotheses}\n\n"
            "Write the 'Method' section (520-640 words, no section heading) with 2-3 subsections using "
            "'## ' headings (e.g. '## General Framework', '## Proposed Model', '## Learning'; a '### ' "
            "sub-subsection is allowed once). Include AT LEAST THREE numbered display equations "
            "(\\begin{equation}...\\end{equation} with \\label{eq:...}), refer to them as Eq.~\\eqref{...}, "
            "and explain every symbol right after each equation. Present the method as proposed; do not "
            "claim any empirical performance."
        )
        return await self.llm.complete(self.system_prompt, user)

    async def pipeline_steps(self, methodology: str) -> list[str]:
        """4-6 tên bước ngắn gọn để vẽ sơ đồ pipeline (Hình minh hoạ, không phải kết quả)."""
        user = (
            f"Methodology:\n{methodology}\n\n"
            "Summarize this methodology as 4 to 6 short pipeline stage names "
            "(2-4 words each), in execution order. "
            'Reply ONLY with a JSON list of strings, e.g. '
            '["Data Collection", "Model Design", "Training", "Evaluation"].'
        )
        data = await self.llm.complete_json(self.system_prompt, user)
        if not isinstance(data, list):
            return []
        return [str(s).strip() for s in data if str(s).strip()][:6]

    # ------------------------------------------------------------------ experiments
    def _plan_block(self, eval_rows: list[dict]) -> str:
        if not eval_rows:
            return "(structured plan unavailable — derive a reasonable one from the hypotheses)"
        return "\n".join(
            f"- {r.get('hypothesis', '?')}: baseline = {r.get('baseline', '?')}, "
            f"metric = {r.get('metric', '?')}, dataset = {r.get('dataset', '?')}"
            for r in eval_rows
        )

    async def write_experiments_intro(self, hypotheses: str, eval_rows: list[dict],
                                      results: ExperimentResults | None = None) -> str:
        tense = ("The experiments have been run; use past tense." if results else
                 "No experiment has been executed: use future tense and state NO numbers.")
        user = (
            f"Hypotheses:\n{hypotheses}\n\nEvaluation plan:\n{self._plan_block(eval_rows)}\n\n{tense}\n"
            "Write the opening of the 'Experiments' section (no heading, 90-130 words): one sentence "
            "saying the experiments aim to answer three research questions, then EXACTLY three lines "
            "'RQ1 Do our proposed methods outperform the state-of-the-art baselines?' style — each line "
            "starts with 'RQ1', 'RQ2', 'RQ3' followed by a question derived from the hypotheses (RQ1: "
            "comparison with baselines; RQ2: contribution of each component / ablation; RQ3: sensitivity to "
            "key hyper-parameters or model size). End with one sentence: 'In what follows, we first present "
            "the experimental settings, followed by answering the above three research questions.'"
        )
        return await self.llm.complete(self.system_prompt, user, temperature=0.3)

    async def write_experiments_setup(self, hypotheses: str, eval_rows: list[dict],
                                      results: ExperimentResults | None = None) -> str:
        if results:
            urls = (results.setup or {}).get("dataset_urls") or {}
            facts = (
                f"Datasets: {', '.join(results.datasets)}\nMetrics: {', '.join(results.metrics)}\n"
                f"Methods: {', '.join(str(m['name']) for m in results.methods)}\n"
                f"Seeds: {results.seeds or 'not stated'}\nDataset URLs (put each in a footnote): {urls or 'none'}\n"
                f"Setup facts (the ONLY source for implementation details): {results.setup or 'none given'}\n"
                f"Dataset statistics table is Table~\\ref{{tab:stats}}" + (" (exists)." if results.dataset_stats else " (absent: do not refer to it).")
            )
            tense = "The experiments HAVE been run; use past tense and ONLY the facts above."
        else:
            facts = f"Proposed evaluation plan:\n{self._plan_block(eval_rows)}"
            tense = ("IMPORTANT: no experiment has been executed. Write entirely in future tense "
                     "('we will ...') and state NO numbers (no sizes, rates, counts or scores) and no URLs.")
        user = (
            f"Hypotheses:\n{hypotheses}\n\n{facts}\n\n{tense}\n"
            "Write the content of '4.1 Experimental Settings' (300-400 words, no heading) as four bold run-in "
            "paragraphs: **Datasets.** (what they are and why chosen), **Evaluation Protocols.** (data split, "
            "number of runs/seeds, and each metric defined with a numbered display equation when it has a "
            "closed form), **Baselines.** (at least four, each in 1-2 sentences, cite only given keys), "
            "**Parameter Settings.** (optimizer, batch size, learning rate, search protocol on the validation "
            "set, hardware, software versions)."
        )
        return await self.llm.complete(self.system_prompt, user, temperature=0.4)

    async def _write_rq(self, rq: str, title: str, hypotheses: str, eval_rows: list[dict],
                        results: ExperimentResults | None, available: bool, refs: str) -> str:
        if results and not available:
            return f"{title} are not reported in this version of the paper."
        if results:
            user = (
                f"Hypotheses:\n{hypotheses}\n\nREAL results (the ONLY numbers you may use):\n"
                f"{summarize_for_prompt(results)}\n\n"
                f"Write the discussion answering {rq} ({title}), 150-230 words, no heading, past tense. Refer to "
                f"{refs}. Compare ONLY through the numbers above; mention significance only if "
                "the tests above report it; finish with 2-3 conclusion sentences grounded in the numbers. "
                "Do not invent numbers or claims."
            )
        else:
            user = (
                f"Hypotheses:\n{hypotheses}\n\nPlanned evaluation:\n{self._plan_block(eval_rows)}\n\n"
                f"No experiment has been executed. Write 60-90 words (no heading) in future tense on how "
                f"{rq} ({title}) will be answered and what result tables/figures will be used ({refs}). "
                "State NO numbers and NO findings and NO conclusions."
            )
        return await self.llm.complete(self.system_prompt, user, temperature=0.3)

    async def write_exp_comparison(self, hypotheses, eval_rows, results=None) -> str:
        return await self._write_rq("RQ1", "Performance comparison with the baselines", hypotheses, eval_rows,
                                    results, True, "Table~\\ref{tab:results}")

    async def write_exp_ablation(self, hypotheses, eval_rows, results=None) -> str:
        return await self._write_rq("RQ2", "Ablation study", hypotheses, eval_rows, results,
                                    bool(results and results.has_ablation()), "Table~\\ref{tab:ablation}")

    async def write_exp_sensitivity(self, hypotheses, eval_rows, results=None) -> str:
        return await self._write_rq("RQ3", "Sensitivity analysis", hypotheses, eval_rows, results,
                                    bool(results and results.has_sensitivity()), "Figure~\\ref{fig:sensitivity}")

    async def write_conclusion(self, topic: str, hypotheses: str, has_results: bool = False) -> str:
        status = (
            "Experiments were run (see Results); summarize them qualitatively without new numbers."
            if has_results else
            "State plainly that the experimental evaluation is still to be carried out."
        )
        user = (
            f"Topic: {topic}\nHypotheses:\n{hypotheses}\n\n"
            "Write 'Conclusion and Future Work' (200-250 words, no heading): summary of the contribution, "
            f"limitations ({status}), and 2-3 concrete future directions. No new numbers."
        )
        return await self.llm.complete(self.system_prompt, user)
