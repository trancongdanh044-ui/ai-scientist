import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class LLMConfig:
    model: str
    temperature: float
    max_tokens: int
    tpm_limit: int = 8000
    rpm_limit: int = 20
    safety_ratio: float = 0.80
    timeout_seconds: float = 90.0
    max_attempts: int = 3
    cache_ttl_seconds: int = 3600


@dataclass
class ResearchConfig:
    topic: str
    num_papers: int
    max_hypotheses: int


@dataclass
class OutputConfig:
    dir: str
    latex_template: str


@dataclass
class ReferenceConfig:
    """Cấu hình tìm tài liệu tham khảo (xem src/tools/scholar_search.py)."""
    sources: list[str] = field(default_factory=lambda: ["semanticscholar", "openalex", "crossref", "arxiv"])
    recent_years: int = 5          # chỉ lấy bài trong N năm gần nhất (tính từ năm hiện tại)
    min_year: int = 0              # >0: ghi đè recent_years bằng năm cụ thể (vd 2021)
    per_query: int = 12
    num_queries: int = 4           # số truy vấn LLM tự sinh từ chủ đề


@dataclass
class PaperConfig:
    """Cấu hình trình bày bài báo (mặc định mô phỏng bài mẫu NCF, WWW 2017)."""
    template: str = "templates/paper_acm.tex.j2"
    authors: list[dict] = field(default_factory=lambda: [
        {"name": "Your Name", "affiliation": "Your University", "country": "Country", "email": "you@example.com"}
    ])
    related_work_position: str = "after"    # "after": sau Experiments (như bài mẫu) | "before": sau Introduction
    results_file: str = "results.json"      # số liệu thực nghiệm THẬT do bạn cung cấp (tuỳ chọn)
    funding_note: str = ""                  # ghi chú tài trợ: dấu * ở tiêu đề + chú thích cuối cột trái trang 1
    acknowledgment: str = ""
    bibliometric_figures: bool = False      # chèn 2 hình thống kê tài liệu (năm xuất bản, từ khoá) vào Related Work
    draft_notice: bool = False              # (tuỳ chọn) in dòng "Draft" lên PDF — mặc định TẮT; cảnh báo nằm ở TODO.md


@dataclass
class AppConfig:
    llm: LLMConfig
    research: ResearchConfig
    output: OutputConfig
    api_key: str
    base_url: str
    references: ReferenceConfig = field(default_factory=ReferenceConfig)
    paper: PaperConfig = field(default_factory=PaperConfig)


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()

    if not api_key:
        raise ValueError("Thiếu OPENAI_API_KEY trong file .env")

    if len(api_key) < 20 or api_key.lower() in {"your_key", "your_api_key"}:
        raise ValueError(
            "OPENAI_API_KEY is invalid. Set it to a complete provider API key."
        )

    if "api.openai.com" in base_url and api_key.startswith("gsk_"):
        raise ValueError(
            "A Groq key cannot be used with api.openai.com. "
            "Set OPENAI_BASE_URL=https://api.groq.com/openai/v1 or use an OpenAI key."
        )

    cfg = AppConfig(
        llm=LLMConfig(**raw["llm"]),
        research=ResearchConfig(**raw["research"]),
        output=OutputConfig(**raw["output"]),
        api_key=api_key,
        base_url=base_url,
        references=ReferenceConfig(**(raw.get("references") or {})),
        paper=PaperConfig(**(raw.get("paper") or {})),
    )
    # config nằm ở thư mục riêng của đề tài (vd topics/ten-de-tai/config.yaml): results.json và outputs/
    # được hiểu là nằm CẠNH file config đó -> mỗi đề tài một bộ kết quả, không lẫn nhau.
    base = Path(path).resolve().parent
    if base != Path.cwd().resolve():
        if not Path(cfg.paper.results_file).is_absolute():
            cfg.paper.results_file = str(base / cfg.paper.results_file)
        if not Path(cfg.output.dir).is_absolute():
            cfg.output.dir = str(base / cfg.output.dir)
    return cfg
