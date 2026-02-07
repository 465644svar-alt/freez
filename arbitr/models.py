from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List


@dataclass
class GenerationConfig:
    temperature: float = 0.3
    max_tokens: int = 1200
    timeout_s: float = 60.0


@dataclass
class Stage1Response:
    model_name: str
    content: str
    error: str | None = None


@dataclass
class Stage2Review:
    reviewer: str
    analysis: str
    ranking: list[str]


@dataclass
class AggregatedResult:
    scores: dict[str, float]
    ranking: list[str]


@dataclass
class RunResult:
    user_query: str
    title: str
    stage1: List[Stage1Response] = field(default_factory=list)
    stage2: List[Stage2Review] = field(default_factory=list)
    aggregated: AggregatedResult | None = None
    final_answer: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


ProgressCallback = Callable[[str], None]
