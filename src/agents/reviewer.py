from src.agents.base import BaseAgent


class ReviewerAgent(BaseAgent):
    name = "ReviewerAgent"
    system_prompt = (
        "You are a strict but fair peer reviewer for a top AI conference. "
        "Evaluate clarity, novelty, rigor, and reproducibility. "
        "Explicitly flag any sentence that reports a result/number without an experiment "
        "having been run, and any citation that looks suspicious."
    )

    async def run(self, paper_latex: str) -> str:
        user = (
            "Review the following paper draft. Provide:\n"
            "1. Summary\n"
            "2. Strengths (3 bullets)\n"
            "3. Weaknesses (3 bullets)\n"
            "4. Questions to authors (2-3)\n"
            "5. Any factual/citation red flags you notice\n"
            "6. Score (1-10) with justification\n\n"
            "Paper draft:\n\n" + paper_latex
        )
        return await self.llm.complete(self.system_prompt, user, temperature=0.3)
