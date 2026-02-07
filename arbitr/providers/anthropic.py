from __future__ import annotations

import httpx

from arbitr.api_keys import get_api_key

from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, model: str = "claude-3-5-sonnet-latest"):
        self.name = f"Claude ({model})"
        self.model = model

    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout_s: float = 60.0,
    ) -> str:
        api_key = get_api_key("ANTHROPIC_API_KEY")

        user_content = "\n\n".join([m["content"] for m in messages if m["role"] == "user"])
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_content}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        return data["content"][0]["text"].strip()
