from src.agents.base import BaseAgent


class HypothesisAgent(BaseAgent):
    name = "HypothesisAgent"
    system_prompt = (
        "You are a creative but rigorous scientist. "
        "You propose testable hypotheses with clear variables and metrics."
    )

    async def run(self, topic: str, research_gap: str, max_hypotheses: int) -> str:
        user = (
            f"Topic: {topic}\n\n"
            f"Research gaps:\n{research_gap}\n\n"
            f"Propose up to {max_hypotheses} research hypotheses. "
            "For each hypothesis include:\n"
            "1. Statement (H1, H2, ...)\n"
            "2. Independent variable\n"
            "3. Dependent variable (metric)\n"
            "4. Baseline to compare against\n"
            "5. Expected outcome\n"
            "Be specific and measurable."
        )
        return await self.llm.complete(self.system_prompt, user)

    async def eval_plan(self, hypotheses: str) -> list[dict]:
        """Sinh dữ liệu có cấu trúc cho Bảng 2 (Kế hoạch đánh giá đề xuất).
        KHÔNG được chứa số liệu kết quả — chỉ mô tả baseline/metric/dataset dự kiến."""
        user = (
            f"Hypotheses:\n{hypotheses}\n\n"
            "For each hypothesis (H1, H2, ...), propose how it WOULD be tested. "
            'Reply ONLY with a JSON list of objects: {"hypothesis": "H1", '
            '"baseline": "a specific existing method/model to compare against", '
            '"metric": "a specific, standard evaluation metric", '
            '"dataset": "a real, commonly used public dataset or benchmark name"}. '
            "Do NOT include any result numbers — this is a plan, not a result."
        )
        data = await self.llm.complete_json(self.system_prompt, user)
        return data if isinstance(data, list) else []
