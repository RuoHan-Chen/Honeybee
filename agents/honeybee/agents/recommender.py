"""Recommender — turns a (Market, Signal, RiskDecision) into a Recommendation.

The Recommendation is the user-facing artefact (frontend renders it, user
approves it). It is also the payload that gets anchored on Arc via
`ResearchAttestation`. Computed deterministically so two agents producing the
same research → same `research_hash` → cache hit, no recompute.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import CONFIG
from ..venues.base import Market
from .research import ResearchSignal
from .risk import SizingDecision


# Recommendations expire after this — frontend must re-hire to refresh.
RECOMMENDATION_TTL_MIN = 15


def build_recommendation(
    *,
    agent_ens: str,
    user_address: str,
    market: Market,
    signal: ResearchSignal,
    decision: SizingDecision,
) -> dict[str, Any]:
    """Construct the canonical Recommendation dict.

    NOTE: returns a dict (not a dataclass) so it's straight-to-JSON for the API.
    """
    if decision.order is None:
        # Caller should have filtered these out; defensive return.
        raise ValueError("cannot build recommendation from rejected decision")

    rec_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    outcome = decision.order.outcome
    fair = signal.fair_prices.get(outcome, 0.5)
    market_price = market.prices.get(outcome, 0.5)

    body = {
        "rec_id": rec_id,
        "agent_ens": agent_ens,
        "user_address": user_address,
        "venue": market.venue,
        "market_id": market.market_id,
        "market_question": market.question,
        "outcome": outcome,
        "side": decision.order.side,
        "fair_price": round(fair, 4),
        "market_price": round(market_price, 4),
        "edge": round(decision.edge, 4),
        "confidence": round(signal.confidence, 3),
        "suggested_size_usd": round(decision.order.size_usd, 2),
        "rationale": signal.rationale,
        "sources": signal.sources,
        "ts": now.isoformat(),
        "expires_at": (now + timedelta(minutes=RECOMMENDATION_TTL_MIN)).timestamp(),
        "research_attestation_tx": None,
        "status": "pending",
    }
    body["research_hash"] = compute_research_hash(market, signal, body)
    return body


def compute_research_hash(market: Market, signal: ResearchSignal, body: dict[str, Any]) -> str:
    """Deterministic hash of research inputs+outputs.

    Two agents that examine the same market, with the same price snapshot,
    and arrive at the same fair price will produce identical hashes — making
    the on-chain anchor a true cache key for `hasResearch(hash)` lookups.

    Deliberately excludes timestamps, rec_id, user_address — those are
    per-call identifiers, not part of the research itself.
    """
    canonical = {
        "venue": market.venue,
        "market_id": market.market_id,
        "question": market.question,
        "price_snapshot": {k: round(v, 4) for k, v in sorted(market.prices.items())},
        "fair_prices": {k: round(v, 4) for k, v in sorted(signal.fair_prices.items())},
        "confidence_bucket": round(signal.confidence, 1),  # bucketed to widen cache hits
        "outcome": body["outcome"],
        "side": body["side"],
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return "0x" + hashlib.sha256(blob).hexdigest()
