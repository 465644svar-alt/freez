from __future__ import annotations

import httpx

from arbitr.api_keys import get_api_key

from .base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, name: str, base_url: str, model: str, api_key_name: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key_name = api_key_name

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout_s: float = 60.0,
    ) -> str:
        api_key = get_api_key(self.api_key_name)

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"].strip()
