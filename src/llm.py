"""Reliable async OpenAI-compatible client with conservative Groq budgeting."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import time
from collections import deque
from dataclasses import asdict, dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, InternalServerError

from src.config import LLMConfig
from src.tools.jsonutil import parse_json_loose


class LLMError(RuntimeError):
    """Human-readable error carrying recovery information for the UI."""

    def __init__(self, message: str, *, recoverable: bool = False, code: str = "llm_error"):
        super().__init__(message)
        self.recoverable = recoverable
        self.code = code


@dataclass
class LLMMetrics:
    requests: int = 0
    retries: int = 0
    cache_hits: int = 0
    estimated_input_tokens: int = 0
    output_tokens: int = 0


class _RollingBudget:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.reservations: deque[tuple[float, int]] = deque()

    async def reserve(self, tokens: int, token_limit: int, request_limit: int, window: float = 60.0) -> None:
        if tokens > token_limit:
            raise LLMError(
                f"Yêu cầu cần khoảng {tokens} token, vượt ngân sách {token_limit} token/phút.",
                code="token_budget_exceeded",
            )
        while True:
            async with self.lock:
                now = time.monotonic()
                while self.reservations and now - self.reservations[0][0] >= window:
                    self.reservations.popleft()
                used = sum(amount for _, amount in self.reservations)
                if used + tokens <= token_limit and len(self.reservations) < request_limit:
                    self.reservations.append((now, tokens))
                    return
                wait = max(0.1, window - (now - self.reservations[0][0]) + 0.1)
            await asyncio.sleep(wait)


_BUDGET = _RollingBudget()


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text.encode("utf-8")) + 2) // 3)


def _trim_middle(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    marker = "\n[... context compacted to fit API token budget ...]\n".encode()
    available = max(0, max_bytes - len(marker))
    front = int(available * 0.7)
    return raw[:front].decode("utf-8", "ignore") + marker.decode() + raw[-(available - front):].decode("utf-8", "ignore")


def _compact_context(text: str, max_tokens: int) -> str:
    """Prefer instructions and scientific evidence over arbitrary truncation."""
    if _estimate_tokens(text) <= max_tokens:
        return text
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    important = [
        part for part in paragraphs
        if re.search(r"(^#|hypoth|result|method|citation|doi|must|không|phải|evidence)", part, re.I)
    ]
    ordered: list[str] = []
    for part in paragraphs[:2] + important + paragraphs[-2:]:
        if part not in ordered:
            ordered.append(part)
    compact = "\n\n".join(ordered)
    return compact if _estimate_tokens(compact) <= max_tokens else _trim_middle(compact, max_tokens * 3)


class LLMClient:
    def __init__(self, api_key: str, base_url: str, config: LLMConfig):
        timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", str(config.timeout_seconds)))
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self.config = config
        self.base_url = base_url
        self.is_groq = "api.groq.com" in base_url
        default_tpm = config.tpm_limit if self.is_groq else max(config.tpm_limit, 100000)
        self.tpm_limit = max(1000, int(os.getenv("LLM_TPM_LIMIT", str(default_tpm))))
        ratio = min(0.95, max(0.5, float(os.getenv("LLM_SAFETY_RATIO", str(config.safety_ratio)))))
        self.tpm_budget = max(500, int(self.tpm_limit * ratio))
        self.rpm_limit = max(1, int(os.getenv("LLM_RPM_LIMIT", str(config.rpm_limit))))
        default_output = 1600 if self.is_groq else config.max_tokens
        self.max_output = min(config.max_tokens, int(os.getenv("LLM_MAX_OUTPUT_TOKENS", str(default_output))))
        self.max_attempts = max(1, min(5, int(os.getenv("LLM_MAX_ATTEMPTS", str(config.max_attempts)))))
        self.cache_ttl = max(0, int(os.getenv("LLM_CACHE_TTL_SECONDS", str(config.cache_ttl_seconds))))
        concurrency = max(1, int(os.getenv("LLM_MAX_CONCURRENCY", "1" if self.is_groq else "4")))
        self._request_lock = asyncio.Semaphore(concurrency)
        self._cache: dict[str, tuple[float, str]] = {}
        self.metrics = LLMMetrics()

    def metrics_snapshot(self) -> dict:
        return asdict(self.metrics)

    def _cache_key(self, system: str, user: str, temperature: float) -> str:
        payload = json.dumps([self.config.model, system, user, temperature], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _friendly_error(self, error: Exception) -> LLMError:
        if isinstance(error, APIStatusError):
            if error.status_code == 401:
                return LLMError("API key bị từ chối (401). Hãy kiểm tra OPENAI_API_KEY.", code="unauthorized")
            if error.status_code == 404:
                return LLMError(f"Model '{self.config.model}' không tồn tại tại nhà cung cấp đã cấu hình.", code="model_not_found")
            if error.status_code == 413:
                return LLMError("Yêu cầu vẫn quá lớn sau khi rút gọn. Hãy chia nhỏ tác vụ.", code="request_too_large")
            if error.status_code == 429:
                return LLMError("API vẫn đang giới hạn tốc độ. Có thể tiếp tục lại sau.", recoverable=True, code="rate_limited")
        if isinstance(error, (APIConnectionError, APITimeoutError, InternalServerError)):
            return LLMError("API tạm thời không khả dụng. Có thể tiếp tục lại từ checkpoint.", recoverable=True, code="api_unavailable")
        return LLMError(f"Lỗi gọi LLM ({type(error).__name__}).")

    async def complete(self, system: str, user: str, temperature: float | None = None) -> str:
        actual_temperature = temperature if temperature is not None else self.config.temperature
        cache_key = self._cache_key(system, user, actual_temperature)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] <= self.cache_ttl:
            self.metrics.cache_hits += 1
            return cached[1]

        output_tokens = max(128, self.max_output)
        current_user = user
        for attempt in range(self.max_attempts):
            overhead = _estimate_tokens(system) + 100
            available_input = self.tpm_budget - overhead - output_tokens
            if available_input < 150:
                output_tokens = max(128, min(output_tokens, self.tpm_budget - overhead - 150))
                available_input = self.tpm_budget - overhead - output_tokens
            if available_input < 150:
                raise LLMError("System prompt quá dài so với ngân sách TPM.", code="system_prompt_too_large")
            current_user = _compact_context(current_user, available_input)
            estimated = overhead + _estimate_tokens(current_user) + output_tokens
            await _BUDGET.reserve(estimated, self.tpm_budget, self.rpm_limit)
            try:
                async with self._request_lock:
                    self.metrics.requests += 1
                    self.metrics.estimated_input_tokens += overhead + _estimate_tokens(current_user)
                    response = await self.client.chat.completions.create(
                        model=self.config.model,
                        temperature=actual_temperature,
                        max_tokens=output_tokens,
                        messages=[{"role": "system", "content": system}, {"role": "user", "content": current_user}],
                    )
                result = (response.choices[0].message.content or "").strip()
                usage = getattr(response, "usage", None)
                self.metrics.output_tokens += int(getattr(usage, "completion_tokens", 0) or _estimate_tokens(result))
                if self.cache_ttl:
                    self._cache[cache_key] = (time.monotonic(), result)
                return result
            except APIStatusError as error:
                if error.status_code == 413 and attempt < self.max_attempts - 1:
                    output_tokens = max(128, output_tokens // 2)
                    current_user = _compact_context(current_user, max(150, _estimate_tokens(current_user) // 2))
                elif error.status_code == 429 and attempt < self.max_attempts - 1:
                    retry_after = error.response.headers.get("retry-after", "") if error.response else ""
                    try:
                        delay = min(90.0, max(1.0, float(retry_after)))
                    except (TypeError, ValueError):
                        delay = 10.0 * (attempt + 1)
                    self.metrics.retries += 1
                    await asyncio.sleep(delay + random.uniform(0, 1.0))
                    continue
                else:
                    raise self._friendly_error(error) from error
            except (APIConnectionError, APITimeoutError, InternalServerError) as error:
                if attempt == self.max_attempts - 1:
                    raise self._friendly_error(error) from error
            except Exception as error:
                raise self._friendly_error(error) from error
            self.metrics.retries += 1
            await asyncio.sleep((2 ** attempt) + random.uniform(0, 0.5))
        raise LLMError("Không thể hoàn tất yêu cầu sau số lần thử cho phép.", recoverable=True)

    async def complete_json(self, system: str, user: str, temperature: float | None = 0.2, retries: int = 2):
        strict_system = system + "\nYou must reply with ONLY valid JSON, no prose, no markdown fence."
        prompt = user
        for _ in range(retries + 1):
            last = await self.complete(strict_system, prompt, temperature=temperature)
            data = parse_json_loose(last)
            if data is not None:
                return data
            prompt = user + "\n\nPrevious reply was invalid JSON. Reply with ONLY valid JSON.\n" + last[:250]
        return None
