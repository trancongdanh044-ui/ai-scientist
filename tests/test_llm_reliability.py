import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.config import LLMConfig
from src.llm import LLMClient, _compact_context, _estimate_tokens


class LLMReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.previous = {key: os.environ.get(key) for key in (
            "LLM_TPM_LIMIT", "LLM_RPM_LIMIT", "LLM_MAX_OUTPUT_TOKENS", "LLM_MAX_CONCURRENCY"
        )}
        os.environ.update({"LLM_TPM_LIMIT": "8000", "LLM_RPM_LIMIT": "20",
                           "LLM_MAX_OUTPUT_TOKENS": "256", "LLM_MAX_CONCURRENCY": "1"})

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_context_compaction_preserves_instructions_and_evidence(self):
        text = "MUST keep this instruction.\n\n" + ("low priority filler " * 3000) + "\n\n# Results\nDOI: 10.1/test"
        compact = _compact_context(text, 200)
        self.assertLessEqual(_estimate_tokens(compact), 210)
        self.assertIn("MUST keep", compact)
        self.assertIn("# Results", compact)
        self.assertIn("DOI", compact)

    async def test_identical_request_uses_cache_and_metrics(self):
        client = LLMClient("fake-key-xxxxxxxxxxxxxxxx", "http://fake.local/v1",
                           LLMConfig(model="fake", temperature=0.2, max_tokens=256))
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
                                   usage=SimpleNamespace(completion_tokens=2))
        client.client.chat.completions.create = AsyncMock(return_value=response)
        self.assertEqual(await client.complete("system", "user"), "answer")
        self.assertEqual(await client.complete("system", "user"), "answer")
        self.assertEqual(client.client.chat.completions.create.await_count, 1)
        self.assertEqual(client.metrics_snapshot()["cache_hits"], 1)


if __name__ == "__main__":
    unittest.main()
