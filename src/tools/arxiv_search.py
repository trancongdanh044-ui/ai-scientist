"""Tìm bài báo trên arXiv (thư viện `arxiv` là sync -> bọc bằng asyncio.to_thread)."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass


@dataclass
class Paper:
    title: str
    authors: list[str]
    abstract: str
    url: str
    published: str
    key: str = ""            # BibTeX key, gán bởi bibliography.assign_keys()
    arxiv_id: str = ""
    more_authors: bool = False

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "url": self.url,
            "published": self.published,
            "key": self.key,
            "arxiv_id": self.arxiv_id,
            "more_authors": self.more_authors,
        }

    @property
    def year(self) -> int:
        try:
            return int(self.published[:4])
        except (ValueError, TypeError):
            return 0


MAX_AUTHORS = 8


def _search_sync(query: str, max_results: int) -> list[Paper]:
    import arxiv  # import trễ: cho phép test không cần cài arxiv

    client = arxiv.Client(page_size=max_results, delay_seconds=3, num_retries=3)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    papers: list[Paper] = []
    seen: set[str] = set()
    for r in client.results(search):
        arxiv_id = re.sub(r"v\d+$", "", r.get_short_id())
        if arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        authors = [a.name for a in r.authors]
        papers.append(
            Paper(
                title=" ".join(r.title.split()),
                authors=authors[:MAX_AUTHORS],
                more_authors=len(authors) > MAX_AUTHORS,
                abstract=" ".join(r.summary.split()),
                url=r.entry_id,
                published=r.published.strftime("%Y-%m-%d"),
                arxiv_id=arxiv_id,
            )
        )
    return papers


async def search_arxiv_async(query: str, max_results: int = 8) -> list[Paper]:
    papers = await asyncio.to_thread(_search_sync, query, max_results)
    if not papers:
        # Query dài đôi khi không có kết quả -> thử lại với 5 từ đầu
        short = " ".join(query.split()[:5])
        if short and short != query:
            papers = await asyncio.to_thread(_search_sync, short, max_results)
    return papers


def search_arxiv(query: str, max_results: int = 8) -> list[Paper]:
    """Bản sync (giữ tương thích ngược)."""
    return _search_sync(query, max_results)
