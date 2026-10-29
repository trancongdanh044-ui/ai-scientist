from src.llm import LLMClient


class BaseAgent:
    name: str = "BaseAgent"
    system_prompt: str = "You are a helpful research assistant."

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def run(self, *args, **kwargs):
        raise NotImplementedError
