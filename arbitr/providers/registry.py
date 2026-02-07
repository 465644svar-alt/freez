from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import LLMProvider
from .openai_compat import OpenAICompatibleProvider


def default_providers() -> list[LLMProvider]:
    return [
        OpenAICompatibleProvider(
            name="GPT-4o-mini",
            base_url="https://api.openai.com/v1",
            model="gpt-4o-mini",
            api_key_env="OPENAI_API_KEY",
        ),
        OpenAICompatibleProvider(
            name="DeepSeek Chat",
            base_url="https://api.deepseek.com/v1",
            model="deepseek-chat",
            api_key_env="DEEPSEEK_API_KEY",
        ),
        AnthropicProvider(),
        OpenAICompatibleProvider(
            name="Mistral Large",
            base_url="https://api.mistral.ai/v1",
            model="mistral-large-latest",
            api_key_env="MISTRAL_API_KEY",
        ),
        OpenAICompatibleProvider(
            name="Groq Llama 3.1 70B",
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.1-70b-versatile",
            api_key_env="GROQ_API_KEY",
        ),
    ]
