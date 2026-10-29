from src.agents.base import BaseAgent
from src.tools.arxiv_search import Paper


class WriterAgent(BaseAgent):
    name = "WriterAgent"
    system_prompt = (
        "You are an academic writer. Write in formal scientific English. "
        "Use LaTeX-friendly plain text (you may use **bold**, bullet lists with '-', "
        "and $...$ for inline math). Do not add markdown code fences. "
        "NEVER invent a citation key that was not explicitly given to you — "
        "if you are not given any valid keys, do not use \\cite at all."
    )

    async def write_abstract(self, topic: str, gap: str, hypotheses: str) -> str:
        user = (
            f"Topic: {topic}\n\nGap:\n{gap}\n\nHypotheses:\n{hypotheses}\n\n"
            "Write a 180-word abstract with: background, gap, proposed approach, "
            "expected contribution. This is a literature-based proposal — no experiments "
            "were run, so do not state any result numbers. No citations in the abstract."
        )
        return await self.llm.complete(self.system_prompt, user, temperature=0.5)

    async def write_introduction(self, topic: str, gap: str, hypotheses: str, keys: list[str]) -> str:
        cite_rule = (
            f"If you cite prior work, use \\cite{{key}} with ONLY these keys: {', '.join(keys)}."
            if keys else "Do not use \\cite at all in this section (no valid keys available)."
        )
        user = (
            f"Topic: {topic}\n\nGap:\n{gap}\n\nHypotheses:\n{hypotheses}\n\n"
            "Write an Introduction section (400-500 words) with 3 paragraphs: "
            f"context, problem + gap, contributions (bullet list). {cite_rule}"
        )
        return await self.llm.complete(self.system_prompt, user)

    async def write_related_work(self, summaries: str, papers: list[Paper]) -> str:
        keys = ", ".join(p.key for p in papers)
        user = (
            f"Summaries of related papers (tagged by [key]):\n{summaries}\n\n"
            f"Valid citation keys — use EXACTLY these, never invent a new one: {keys}\n\n"
            "Write a Related Work section (~400 words). Group papers by theme. "
            "Cite every paper you discuss using \\cite{key}. "
            "End with a short paragraph pointing to the research gap."
        )
        return await self.llm.complete(self.system_prompt, user)

    async def write_methodology(self, hypotheses: str) -> str:
        user = (
            f"Hypotheses:\n{hypotheses}\n\n"
            "Write a Methodology section (~500 words) describing: problem formulation, "
            "proposed method, and the overall procedure (data -> model/method -> evaluation). "
            "Use math notation with $...$ where helpful. Write in proposed/future tense "
            "(e.g. 'we design...', 'the method will...') — no experiments were executed yet."
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

    async def write_experimental_design(self, hypotheses: str, eval_rows: list[dict]) -> str:
        if eval_rows:
            plan = "\n".join(
                f"- {r.get('hypothesis', '?')}: baseline = {r.get('baseline', '?')}, "
                f"metric = {r.get('metric', '?')}, dataset = {r.get('dataset', '?')}"
                for r in eval_rows
            )
        else:
            plan = "(structured plan unavailable — derive a reasonable one from the hypotheses)"
        user = (
            f"Hypotheses:\n{hypotheses}\n\nProposed evaluation plan:\n{plan}\n\n"
            "Write an 'Experimental Design' section (~250 words) explaining HOW each "
            "hypothesis would be tested: baselines, metrics, datasets, and comparison "
            "procedure. IMPORTANT: no experiments have been executed — write entirely in "
            "future/proposed tense ('we will evaluate...', 'we plan to compare...') and "
            "do NOT state any numeric results, percentages, or scores."
        )
        return await self.llm.complete(self.system_prompt, user, temperature=0.4)

    async def write_conclusion(self, topic: str, hypotheses: str) -> str:
        user = (
            f"Topic: {topic}\nHypotheses:\n{hypotheses}\n\n"
            "Write a Conclusion (~200 words): summary of the proposed contribution, "
            "limitations (including that no experiments were run yet), and 2-3 future "
            "work directions."
        )
        return await self.llm.complete(self.system_prompt, user)
