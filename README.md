# Arbitr

Desktop arbitration engine (Python + PySide6) with multi-model pipeline:

1. Stage 1: collect raw answers from selected models.
2. Stage 2: peer review with strict `FINAL RANKING:` section.
3. Aggregation: compute mean rank-based score.
4. Stage 3: chairman synthesizes final answer.

## Supported providers

- GPT (OpenAI)
- DeepSeek
- Claude (Anthropic)
- Mistral
- Groq

## MVP UI

- **UserChat**: question input + `Отправить`.
- **Арбитраж**: stage indicator + final answer/chat output.
- **Протокол**: Stage 1 answers, Stage 2 reviews, aggregated ranking.
- **Настройки**: active model checkboxes, chairman selector, `temperature`, `max tokens`, `timeout`.
- **Логи**: pipeline logs and error messages.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Set API keys:

```bash
export OPENAI_API_KEY=...
export DEEPSEEK_API_KEY=...
export ANTHROPIC_API_KEY=...
export MISTRAL_API_KEY=...
export GROQ_API_KEY=...
```

Run app:

```bash
arbitr
```
