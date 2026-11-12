from datetime import date

from src.agents.base import BaseAgent
from src.config import ReferenceConfig
from src.tools.arxiv_search import Paper, search_arxiv_async
from src.tools.bibliography import assign_keys
from src.tools.scholar_search import SearchReport, search_literature


class LiteratureAgent(BaseAgent):
    name = "LiteratureAgent"
    system_prompt = (
        "You are a senior researcher conducting a literature review. "
        "Be precise, concise, and identify research gaps clearly. "
        "Only discuss papers that were actually provided to you; never invent papers."
    )

    async def make_queries(self, topic: str, n: int) -> list[str]:
        """LLM chỉ sinh TỪ KHOÁ tìm kiếm (không sinh tài liệu) — để phủ rộng chủ đề."""
        user = (
            f"Research topic: {topic}\n\nWrite {n} different short academic search queries "
            "(3-7 words each, English) covering the topic from different angles "
            "(core method, application domain, evaluation/benchmark, recent survey). "
            "Reply ONLY with a JSON list of strings."
        )
        try:
            data = await self.llm.complete_json(self.system_prompt, user)
        except Exception:  # noqa: BLE001 — sinh truy vấn hỏng thì dùng chủ đề gốc
            data = None
        qs = [str(q).strip() for q in data if str(q).strip()] if isinstance(data, list) else []
        out = [topic] + [q for q in qs if q.lower() != topic.lower()]
        return out[: n + 1]

    async def run(self, topic: str, num_papers: int, ref_cfg: ReferenceConfig | None = None) -> dict:
        ref_cfg = ref_cfg or ReferenceConfig()
        min_year = ref_cfg.min_year or (date.today().year - ref_cfg.recent_years)
        queries = await self.make_queries(topic, ref_cfg.num_queries)
        papers, report = await search_literature(
            queries, num_papers, min_year, ref_cfg.sources, ref_cfg.per_query)
        if len(papers) < max(3, num_papers // 2):
            # Mạng/nguồn chính hỏng hoặc quá ít bài mới -> bổ sung bằng arXiv (không giới hạn năm cứng)
            extra = await search_arxiv_async(topic, num_papers)
            have = {p.title.lower() for p in papers}
            papers += [p for p in extra if p.title.lower() not in have][: num_papers - len(papers)]
            report.failed_sources.append("fallback:arxiv")
        if not papers:
            raise RuntimeError(
                f"Không tìm thấy bài báo nào cho chủ đề: '{topic}' (đã thử: {', '.join(ref_cfg.sources)}). "
                "Kiểm tra kết nối mạng, hoặc dùng chủ đề cụ thể hơn / thuật ngữ tiếng Anh phổ biến hơn."
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
            "report": report,
            "queries": queries,
            "min_year": min_year,
        }

    async def _summarize(self, papers: list[Paper]) -> str:
        block = "\n\n".join(
            f"[{p.key}] Title: {p.title}\nAuthors: {', '.join(p.authors)}\n"
            f"Year: {p.year}\nVenue: {p.venue or 'preprint'}\nAbstract: {p.abstract}\nURL: {p.link}"
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
