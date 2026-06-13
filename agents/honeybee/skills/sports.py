"""Sports skill — placeholder. Registers vertical-specific prompt hints."""
from __future__ import annotations


TOPIC_PREFIXES = ("sports.",)


def register(orchestrator) -> None:  # noqa: ANN001
    orchestrator.skill_prompts.setdefault("sports.", (
        "When evaluating sports markets, weight: recent form (last 5 games), "
        "injuries to starters, home/away splits, head-to-head history, "
        "and rest days. Beware narrative-driven public bias."
    ))
