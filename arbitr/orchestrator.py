from __future__ import annotations

import asyncio
import re
from collections import defaultdict

from .models import AggregatedResult, GenerationConfig, ProgressCallback, RunResult, Stage1Response, Stage2Review
from .prompts import CHAIRMAN_PROMPT, STAGE2_PROMPT, TITLE_PROMPT
from .providers.base import LLMProvider


def _label_for_index(idx: int) -> str:
    return f"Response {chr(ord('A') + idx)}"


def parse_final_ranking(text: str) -> list[str]:
    marker = "FINAL RANKING:"
    if marker not in text:
        return []
    tail = text.split(marker, 1)[1].strip()
    ranking: list[str] = []
    for line in tail.splitlines():
        line = line.strip()
        match = re.match(r"^\d+\.\s+(Response\s+[A-Z])$", line)
        if match:
            ranking.append(match.group(1))
    return ranking


class ArbitrationOrchestrator:
    def __init__(self, providers: list[LLMProvider], chairman: LLMProvider, config: GenerationConfig):
        self.providers = providers
        self.chairman = chairman
        self.config = config

    async def run(self, user_query: str, on_progress: ProgressCallback | None = None) -> RunResult:
        self._notify(on_progress, "Stage 0: Генерация заголовка")
        title = await self._generate_title(user_query)
        self._notify(on_progress, "Stage 1: Сбор первичных ответов")
        stage1 = await self._run_stage1(user_query)
        self._notify(on_progress, "Stage 2: Взаимное оценивание")
        stage2 = await self._run_stage2(user_query, stage1)
        self._notify(on_progress, "Aggregation: Подсчёт итогового рейтинга")
        aggregated = self._aggregate(stage2)
        self._notify(on_progress, "Stage 3: Chairman synthesis")
        final_answer = await self._run_stage3(user_query, stage1, stage2)
        self._notify(on_progress, "Готово")
        return RunResult(
            user_query=user_query,
            title=title,
            stage1=stage1,
            stage2=stage2,
            aggregated=aggregated,
            final_answer=final_answer,
        )

    @staticmethod
    def _notify(callback: ProgressCallback | None, message: str) -> None:
        if callback:
            callback(message)

    async def _generate_title(self, user_query: str) -> str:
        prompt = TITLE_PROMPT.format(user_query=user_query)
        try:
            return (
                await self.chairman.complete(
                    [{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=20,
                    timeout_s=self.config.timeout_s,
                )
            ).strip()
        except Exception:
            return "New conversation"

    async def _run_stage1(self, user_query: str) -> list[Stage1Response]:
        async def call(provider: LLMProvider) -> Stage1Response:
            try:
                text = await provider.complete(
                    [{"role": "user", "content": user_query}],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    timeout_s=self.config.timeout_s,
                )
                return Stage1Response(model_name=provider.name, content=text)
            except Exception as exc:
                return Stage1Response(model_name=provider.name, content="", error=str(exc))

        return await asyncio.gather(*[call(p) for p in self.providers])

    async def _run_stage2(self, user_query: str, stage1: list[Stage1Response]) -> list[Stage2Review]:
        nonempty = [s for s in stage1 if s.content]
        labeled = [(_label_for_index(i), s) for i, s in enumerate(nonempty)]
        responses_text = "\n\n".join([f"{label}:\n{s.content}" for label, s in labeled])
        prompt = STAGE2_PROMPT.format(user_query=user_query, responses_text=responses_text)

        async def review(provider: LLMProvider) -> Stage2Review:
            text = await provider.complete(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=self.config.max_tokens,
                timeout_s=self.config.timeout_s,
            )
            return Stage2Review(reviewer=provider.name, analysis=text, ranking=parse_final_ranking(text))

        reviews: list[Stage2Review] = []
        for provider in self.providers:
            try:
                reviews.append(await review(provider))
            except Exception as exc:
                reviews.append(Stage2Review(reviewer=provider.name, analysis=f"Review failed: {exc}", ranking=[]))
        return reviews

    def _aggregate(self, stage2: list[Stage2Review]) -> AggregatedResult:
        score_map: dict[str, list[int]] = defaultdict(list)
        for review in stage2:
            n = len(review.ranking)
            for idx, label in enumerate(review.ranking):
                score_map[label].append(n - idx)
        averages = {k: (sum(v) / len(v) if v else 0.0) for k, v in score_map.items()}
        ranking = sorted(averages.keys(), key=lambda x: averages[x], reverse=True)
        return AggregatedResult(scores=averages, ranking=ranking)

    async def _run_stage3(self, user_query: str, stage1: list[Stage1Response], stage2: list[Stage2Review]) -> str:
        stage1_text = "\n\n".join([f"{s.model_name}:\n{s.content or '[ERROR] ' + (s.error or '')}" for s in stage1])
        stage2_text = "\n\n".join([f"{s.reviewer}:\n{s.analysis}" for s in stage2])
        prompt = CHAIRMAN_PROMPT.format(user_query=user_query, stage1_text=stage1_text, stage2_text=stage2_text)
        return await self.chairman.complete(
            [{"role": "user", "content": prompt}],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            timeout_s=self.config.timeout_s,
        )
