from __future__ import annotations

import abc


class LLMProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout_s: float = 60.0,
    ) -> str:
        raise NotImplementedError
