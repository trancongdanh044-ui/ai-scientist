from src.agents.base import BaseAgent
from src.tools.arxiv_search import Paper, search_arxiv_async
from src.tools.bibliography import assign_keys


class LiteratureAgent(BaseAgent):
    name = "LiteratureAgent"
    system_prompt = (
        "You are a senior researcher conducting a literature review. "
        "Be precise, concise, and identify research gaps clearly. "
        "Only discuss papers that were actually provided to you; never invent papers."
    )

    async def run(self, topic: str, num_papers: int) -> dict:
        papers = await search_arxiv_async(topic, num_papers)
        if not papers:
            raise RuntimeError(
                f"Không tìm thấy bài báo nào trên arXiv cho chủ đề: '{topic}'. "
                "Hãy thử một chủ đề cụ thể hơn hoặc dùng thuật ngữ tiếng Anh phổ biến hơn."
            )
        papers = assign_keys(papers)

        summaries = await self._summarize(papers)
        gap = await self._find_gap(topic, summaries)
        rows = await self._comparison_rows(papers)

        return {
            "papers": papers,
            "summaries": summaries,
            "research_gap": gap,
            "comparison_rows": rows,
        }

    async def _summarize(self, papers: list[Paper]) -> str:
        block = "\n\n".join(
            f"[{p.key}] Title: {p.title}\nAuthors: {', '.join(p.authors)}\n"
            f"Year: {p.year}\nAbstract: {p.abstract}\nURL: {p.url}"
            for p in papers
        )
        user = (
            "Summarize the following papers. For each, give 1-2 sentences on "
            "the core method and 1 sentence on limitations. Refer to each paper "
            f"by its [key] tag.\n\n{block}"
        )
        return await self.llm.complete(self.system_prompt, user)

    async def _find_gap(self, topic: str, summaries: str) -> str:
        user = (
            f"Research topic: {topic}\n\n"
            f"Summaries of related work:\n{summaries}\n\n"
            "Identify 2-3 concrete research gaps. Each gap must be specific, "
            "testable, and not trivially solved."
        )
        return await self.llm.complete(self.system_prompt, user)

    async def _comparison_rows(self, papers: list[Paper]) -> list[dict]:
        """Sinh dữ liệu có cấu trúc cho Bảng 1 (So sánh công trình liên quan)."""
        listing = "\n".join(f"- key: {p.key} | title: {p.title}" for p in papers)
        user = (
            "For EACH paper below, describe its core approach (max 12 words) and its "
            f"main limitation (max 12 words).\n{listing}\n\n"
            'Reply ONLY with a JSON list of objects: '
            '{"key": "<exact key given above>", "approach": "...", "limitation": "..."}.'
        )
        data = await self.llm.complete_json(self.system_prompt, user)
        valid = {p.key for p in papers}
        if not isinstance(data, list):
            return []
        return [r for r in data if isinstance(r, dict) and r.get("key") in valid]
