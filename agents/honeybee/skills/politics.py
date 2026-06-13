"""Politics skill — placeholder for current-events reasoning."""
from __future__ import annotations


def register(orchestrator) -> None:  # noqa: ANN001
    orchestrator.skill_prompts.setdefault("politics.", (
        "When evaluating political markets, weight: polling aggregates and "
        "their recency, prediction-market consensus across venues, base rates "
        "for similar historical events, and procedural mechanics (who decides, when)."
    ))
