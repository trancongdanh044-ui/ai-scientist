"""Tìm tài liệu tham khảo THẬT, GẦN ĐÂY từ nhiều nguồn học thuật.

Nguồn (đều có API công khai, không cần khoá; khoá là tuỳ chọn để tăng hạn mức):
  - Semantic Scholar Graph API  (env SEMANTIC_SCHOLAR_API_KEY – tuỳ chọn)
  - OpenAlex                    (env OPENALEX_MAILTO – tuỳ chọn, vào "polite pool")
  - Crossref                    (env CROSSREF_MAILTO – tuỳ chọn)
  - arXiv                       (preprint)

Quy trình: chạy nhiều truy vấn song song -> gộp & khử trùng lặp (DOI / tiêu đề chuẩn hoá)
-> lọc theo năm -> xếp hạng (độ liên quan + trích dẫn + độ mới) -> chọn top-N.
Mỗi bài trả về đều đến từ chỉ mục học thuật và có DOI hoặc URL/arXiv ID kiểm chứng được;
KHÔNG có bài nào do LLM tự nghĩ ra.
"""
from __future__ import annotations

import asyncio
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import date

from src.tools.arxiv_search import MAX_AUTHORS, Paper, _search_sync as _arxiv_sync

USER_AGENT = "ai-scientist/1.0 (academic research tool)"
TIMEOUT = 25


# ----------------------------------------------------------------------------- HTTP
def _http_get_json(url: str, params: dict | None = None, headers: dict | None = None,
                   retries: int = 2) -> dict | None:
    """GET JSON có retry/backoff. Trả về None nếu thất bại (caller tự xử lý)."""
    import requests  # import trễ để test không cần cài

    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    h.update(headers or {})
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=h, timeout=TIMEOUT)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:  # noqa: BLE001 — mạng chập chờn không được làm hỏng cả pipeline
            time.sleep(1.0 * (attempt + 1))
    return None


# ----------------------------------------------------------------------------- helpers
def norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (t or "").lower())


def norm_doi(d: str | None) -> str:
    d = (d or "").strip().lower()
    d = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", d)
    return d


def _strip_tags(s: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", s or "").split())


def _kind_from(type_str: str, venue: str) -> str:
    t = (type_str or "").lower()
    v = (venue or "").lower()
    if any(k in t for k in ("proceedings", "conference")) or any(
        k in v for k in ("proceedings", "conference", "workshop", "symposium")
    ):
        return "conference"
    if any(k in t for k in ("journal", "article")) and "preprint" not in t:
        return "journal"
    if "arxiv" in v or "preprint" in t or "repository" in t or not venue:
        return "preprint"
    return "journal"


def _mk(title, authors, abstract, url, year, **kw) -> Paper | None:
    title = " ".join((title or "").split())
    if not title or not year:
        return None
    authors = [a.strip() for a in authors if a and a.strip()]
    return Paper(
        title=title,
        authors=authors[:MAX_AUTHORS],
        more_authors=len(authors) > MAX_AUTHORS,
        abstract=" ".join((abstract or "").split()),
        url=url or "",
        published=f"{int(year)}-01-01" if not kw.get("published") else kw.pop("published"),
        **{k: v for k, v in kw.items() if k != "published"},
    )


# ----------------------------------------------------------------------------- sources
def _semantic_scholar(query: str, limit: int, min_year: int) -> list[Paper]:
    headers = {}
    if os.getenv("SEMANTIC_SCHOLAR_API_KEY"):
        headers["x-api-key"] = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
    data = _http_get_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={
            "query": query, "limit": limit, "year": f"{min_year}-",
            "fields": "title,authors,year,abstract,venue,externalIds,citationCount,url,"
                      "publicationTypes,publicationDate",
        },
        headers=headers,
    )
    out: list[Paper] = []
    for r in (data or {}).get("data", []) or []:
        ext = r.get("externalIds") or {}
        venue = (r.get("venue") or "").strip()
        types = " ".join(r.get("publicationTypes") or [])
        doi = norm_doi(ext.get("DOI"))
        arx = ext.get("ArXiv") or ""
        p = _mk(
            r.get("title"), [a.get("name", "") for a in r.get("authors") or []],
            r.get("abstract"), r.get("url") or (f"https://arxiv.org/abs/{arx}" if arx else ""),
            r.get("year"), doi=doi, venue=venue if "arxiv" not in venue.lower() else "",
            kind=_kind_from(types, venue), citations=int(r.get("citationCount") or 0),
            source="semanticscholar", arxiv_id=arx,
            published=(r.get("publicationDate") or None),
        )
        if p:
            out.append(p)
    return out


def _openalex_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def _openalex(query: str, limit: int, min_year: int) -> list[Paper]:
    params = {
        "search": query, "per-page": limit,
        "filter": f"from_publication_date:{min_year}-01-01,type:article|preprint|proceedings-article",
    }
    if os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    data = _http_get_json("https://api.openalex.org/works", params=params)
    out: list[Paper] = []
    for r in (data or {}).get("results", []) or []:
        loc = r.get("primary_location") or {}
        src = (loc.get("source") or {})
        venue = (src.get("display_name") or "").strip()
        doi = norm_doi(r.get("doi"))
        authors = [((a.get("author") or {}).get("display_name") or "") for a in r.get("authorships") or []]
        arx = ""
        m = re.search(r"arxiv\.org/(?:abs|pdf)/([\w./-]+?)(?:v\d+)?$", loc.get("landing_page_url") or "")
        if m:
            arx = m.group(1)
        p = _mk(
            r.get("title") or r.get("display_name"), authors,
            _openalex_abstract(r.get("abstract_inverted_index")),
            loc.get("landing_page_url") or (f"https://doi.org/{doi}" if doi else ""),
            r.get("publication_year"), doi=doi,
            venue=venue if "arxiv" not in venue.lower() else "",
            kind=_kind_from(str(src.get("type") or r.get("type") or ""), venue),
            citations=int(r.get("cited_by_count") or 0), source="openalex", arxiv_id=arx,
            published=(r.get("publication_date") or None),
        )
        if p:
            out.append(p)
    return out


def _crossref(query: str, limit: int, min_year: int) -> list[Paper]:
    params = {
        "query.bibliographic": query, "rows": limit,
        "filter": f"from-pub-date:{min_year}-01,type:journal-article,type:proceedings-article",
        "select": "DOI,title,author,issued,container-title,type,abstract,"
                  "is-referenced-by-count,URL",
    }
    if os.getenv("CROSSREF_MAILTO"):
        params["mailto"] = os.environ["CROSSREF_MAILTO"]
    data = _http_get_json("https://api.crossref.org/works", params=params)
    out: list[Paper] = []
    for r in ((data or {}).get("message") or {}).get("items", []) or []:
        parts = ((r.get("issued") or {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts and parts[0] else None
        title = (r.get("title") or [""])[0]
        venue = (r.get("container-title") or [""])[0]
        authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in r.get("author") or []]
        p = _mk(
            title, authors, _strip_tags(r.get("abstract", "")), r.get("URL") or "",
            year, doi=norm_doi(r.get("DOI")), venue=venue,
            kind="conference" if r.get("type") == "proceedings-article" else "journal",
            citations=int(r.get("is-referenced-by-count") or 0), source="crossref",
        )
        if p:
            out.append(p)
    return out


def _arxiv(query: str, limit: int, min_year: int) -> list[Paper]:
    try:
        papers = _arxiv_sync(query, limit)
    except Exception:  # noqa: BLE001
        return []
    for p in papers:
        p.source, p.kind = "arxiv", "preprint"
    return [p for p in papers if p.year >= min_year]


SOURCES = {
    "semanticscholar": _semantic_scholar,
    "openalex": _openalex,
    "crossref": _crossref,
    "arxiv": _arxiv,
}


# ----------------------------------------------------------------------------- merge + rank
def _merge_into(base: Paper, other: Paper) -> Paper:
    """Gộp 2 bản ghi cùng một bài: giữ trường đầy đủ nhất."""
    if not base.abstract and other.abstract:
        base.abstract = other.abstract
    if not base.doi and other.doi:
        base.doi = other.doi
    if not base.arxiv_id and other.arxiv_id:
        base.arxiv_id = other.arxiv_id
    if not base.venue and other.venue:
        base.venue, base.kind = other.venue, other.kind
    base.citations = max(base.citations, other.citations)
    if len(other.authors) > len(base.authors):
        base.authors, base.more_authors = other.authors, other.more_authors
    if not base.url and other.url:
        base.url = other.url
    return base


@dataclass
class SearchReport:
    per_source: dict[str, int] = field(default_factory=dict)
    failed_sources: list[str] = field(default_factory=list)
    candidates: int = 0
    min_year: int = 0


def merge_and_rank(batches: list[tuple[str, list[Paper]]], min_year: int,
                   top_n: int) -> list[Paper]:
    """batches: [(source, ranked_list)] -> danh sách đã khử trùng lặp + xếp hạng."""
    by_id: dict[str, Paper] = {}
    score: dict[str, float] = {}
    this_year = date.today().year

    def ident(p: Paper) -> str:
        return ("doi:" + p.doi) if p.doi else ("t:" + norm_title(p.title))

    alias: dict[str, str] = {}
    for _src, papers in batches:
        for rank, p in enumerate(papers):
            if p.year < min_year:
                continue
            keys = [ident(p), "t:" + norm_title(p.title)]
            canon = next((alias[k] for k in keys if k in alias), None)
            if canon is None:
                canon = keys[0]
                by_id[canon] = p
                score[canon] = 0.0
            else:
                by_id[canon] = _merge_into(by_id[canon], p)
            for k in keys:
                alias[k] = canon
            score[canon] += 1.0 / (rank + 3)  # reciprocal-rank fusion

    ranked = []
    for k, p in by_id.items():
        recency = max(0, p.year - min_year) / max(1, this_year - min_year)
        s = score[k] + 0.04 * math.log1p(p.citations) + 0.05 * recency
        if not p.abstract:
            s -= 0.5  # không có abstract thì không tóm tắt được -> chỉ lấy khi thiếu bài
        if p.kind != "preprint":
            s += 0.03  # ưu tiên bài đã qua bình duyệt một chút
        ranked.append((s, p))
    ranked.sort(key=lambda x: -x[0])
    out = []
    for _s, p in ranked:
        if not (p.doi or p.arxiv_id or p.url):
            continue  # bắt buộc có nguồn kiểm chứng được
        out.append(p)
        if len(out) >= top_n:
            break
    return out


async def search_literature(
    queries: list[str], num_papers: int, min_year: int,
    sources: list[str] | None = None, per_query: int = 12,
) -> tuple[list[Paper], SearchReport]:
    """Tìm đa nguồn, đa truy vấn. Không bao giờ ném lỗi mạng: nguồn hỏng chỉ bị ghi vào report."""
    sources = [s for s in (sources or list(SOURCES)) if s in SOURCES]
    report = SearchReport(min_year=min_year)
    jobs: list[tuple[str, asyncio.Future]] = []
    for qi, q in enumerate(queries):
        for s in sources:
            if s == "arxiv" and qi >= 2:  # arXiv giới hạn tốc độ -> chỉ 2 truy vấn đầu
                continue
            jobs.append((s, asyncio.create_task(
                asyncio.to_thread(SOURCES[s], q, per_query, min_year))))
    batches: list[tuple[str, list[Paper]]] = []
    for s, t in jobs:
        try:
            res = await t
        except Exception:  # noqa: BLE001
            res = []
        report.per_source[s] = report.per_source.get(s, 0) + len(res)
        batches.append((s, res))
    report.failed_sources = [s for s in sources if report.per_source.get(s, 0) == 0]
    report.candidates = sum(len(b) for _, b in batches)
    return merge_and_rank(batches, min_year, num_papers), report
