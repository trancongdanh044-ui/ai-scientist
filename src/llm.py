"""LLM client async-first (dùng cho cả CLI lẫn FastAPI backend).

Client này tương thích OpenAI API (`openai` SDK) nên có thể trỏ tới BẤT KỲ nhà
cung cấp nào có endpoint kiểu OpenAI-compatible: Groq, Cerebras, OpenRouter,
Google Gemini (qua lớp tương thích), hay chính OpenAI/Azure — chỉ cần đổi
OPENAI_BASE_URL + OPENAI_API_KEY + model trong .env/config.yaml, không cần sửa code.
Xem README mục "Chọn nhà cung cấp LLM" để so sánh các lựa chọn miễn phí.
"""
from __future__ import annotations

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import LLMConfig
from src.tools.jsonutil import parse_json_loose

_RETRYABLE = (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)


class LLMError(RuntimeError):
    """Lỗi LLM đã được diễn giải dễ hiểu (thay vì để lộ traceback SDK thô)."""


class LLMClient:
    def __init__(self, api_key: str, base_url: str, config: LLMConfig):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=90.0)
        self.config = config
        self.base_url = base_url

    def _friendly_error(self, e: Exception) -> LLMError:
        if isinstance(e, APIStatusError):
            if e.status_code == 401:
                return LLMError(
                    f"API key bị từ chối (401) bởi {self.base_url}. "
                    "Kiểm tra lại OPENAI_API_KEY trong .env có đúng và còn hạn không."
                )
            if e.status_code == 404:
                return LLMError(
                    f"Model '{self.config.model}' không tồn tại ở {self.base_url} (404). "
                    "Kiểm tra lại tên model trong config.yaml/.env."
                )
            if e.status_code == 429:
                return LLMError(
                    "Vượt giới hạn miễn phí của nhà cung cấp (429 rate limit). "
                    "Đợi một lát rồi thử lại, giảm số bài báo, hoặc đổi sang nhà cung cấp khác."
                )
        return LLMError(f"Lỗi gọi LLM ({type(e).__name__}): {e}")

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=20),
        reraise=True,
    )
    async def complete(self, system: str, user: str, temperature: float | None = None) -> str:
        try:
            resp = await self.client.chat.completions.create(
                model=self.config.model,
                temperature=temperature if temperature is not None else self.config.temperature,
                max_tokens=self.config.max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except _RETRYABLE:
            raise
        except Exception as e:  # noqa: BLE001
            raise self._friendly_error(e) from e

        text = resp.choices[0].message.content or ""
        return text.strip()

    async def complete_json(
        self, system: str, user: str, temperature: float | None = 0.2, retries: int = 2
    ):
        """Gọi LLM và ép kết quả thành JSON (list/dict). Trả về None nếu vẫn không parse được
        sau `retries` lần (caller nên coi None/[] là 'không có dữ liệu', không phải lỗi致命)."""
        strict_system = system + "\nYou must reply with ONLY valid JSON, no prose, no markdown fence."
        prompt = user
        last: str = ""
        for attempt in range(retries + 1):
            last = await self.complete(strict_system, prompt, temperature=temperature)
            data = parse_json_loose(last)
            if data is not None:
                return data
            prompt = (
                user
                + "\n\nYour previous reply could not be parsed as JSON:\n"
                + last[:500]
                + "\nReply again with ONLY valid JSON (no prose, no code fence)."
            )
        return None
