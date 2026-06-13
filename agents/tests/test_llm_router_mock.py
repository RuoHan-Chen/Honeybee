import json

import pytest

from honeybee.llm.router import LLMRouter


@pytest.mark.asyncio
async def test_mock_triage_returns_valid_json():
    r = LLMRouter()
    # Force mock by ignoring real keys: easiest is to call with explicit prompts;
    # if keys are configured this test will hit real APIs — gate it:
    import honeybee.config as cfg
    if cfg.CONFIG.has_any_llm:
        pytest.skip("real LLM keys configured; mock path not exercised")
    resp = await r.cheap("triage system", "triage user content")
    data = json.loads(resp.text)
    assert "worth_deep_analysis" in data
    assert 0.0 <= data["quick_fair_price"] <= 1.0
    assert resp.cost_usd == 0.0


@pytest.mark.asyncio
async def test_mock_deep_returns_normalised_prices():
    r = LLMRouter()
    import honeybee.config as cfg
    if cfg.CONFIG.has_any_llm:
        pytest.skip("real LLM keys configured")
    resp = await r.strong("deep system", "deep user content")
    data = json.loads(resp.text)
    s = sum(data["fair_prices"].values())
    assert abs(s - 1.0) < 0.01
