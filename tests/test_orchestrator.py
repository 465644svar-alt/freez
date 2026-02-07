from __future__ import annotations

import asyncio

from arbitr.models import GenerationConfig
from arbitr.orchestrator import ArbitrationOrchestrator, parse_final_ranking
from arbitr.providers.base import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self, name: str, replies: list[str]):
        self.name = name
        self._replies = replies

    async def complete(
        self,
        messages,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout_s: float = 60.0,
    ) -> str:
        if not self._replies:
            return "fallback"
        return self._replies.pop(0)


def test_parse_final_ranking():
    text = """Analysis text\nFINAL RANKING:\n1. Response C\n2. Response A\n3. Response B\n"""
    assert parse_final_ranking(text) == ["Response C", "Response A", "Response B"]


def test_pipeline_minimal():
    p1 = FakeProvider("M1", ["ans1", "FINAL RANKING:\n1. Response A\n2. Response B"])
    p2 = FakeProvider("M2", ["ans2", "FINAL RANKING:\n1. Response B\n2. Response A"])
    chairman = FakeProvider("Chair", ["Short title", "Final synthesis"])
    orch = ArbitrationOrchestrator([p1, p2], chairman, config=GenerationConfig())

    result = asyncio.run(orch.run("What is X?"))

    assert result.title == "Short title"
    assert len(result.stage1) == 2
    assert len(result.stage2) == 2
    assert result.aggregated is not None
    assert set(result.aggregated.ranking) == {"Response A", "Response B"}
    assert result.final_answer == "Final synthesis"
