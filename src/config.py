import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class LLMConfig:
    model: str
    temperature: float
    max_tokens: int


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
class AppConfig:
    llm: LLMConfig
    research: ResearchConfig
    output: OutputConfig
    api_key: str
    base_url: str


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

    if "api.groq.com" in base_url and not api_key.startswith("gsk_"):
        raise ValueError("Groq requires an OPENAI_API_KEY beginning with 'gsk_'.")

    if "api.openai.com" in base_url and api_key.startswith("gsk_"):
        raise ValueError(
            "A Groq key cannot be used with api.openai.com. "
            "Set OPENAI_BASE_URL=https://api.groq.com/openai/v1 or use an OpenAI key."
        )

    return AppConfig(
        llm=LLMConfig(**raw["llm"]),
        research=ResearchConfig(**raw["research"]),
        output=OutputConfig(**raw["output"]),
        api_key=api_key,
        base_url=base_url,
    )
