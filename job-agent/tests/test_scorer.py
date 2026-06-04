"""
tests/test_scorer.py
--------------------
Unit tests for agents/scorer_agent.py.

Run with:
    pytest job-agent/tests/ -v
or (from job-agent/):
    pytest tests/ -v

All tests mock utils.llm.chat_json so no real Anthropic API calls are made.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
# Allow imports from the project root (job-agent/) when running from the repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.scorer_agent import score_job, score_batch  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────────

VALID_LLM_RESPONSE = {
    "score": 0.88,
    "domain": "ai_ml",
    "reasoning": "Strong match for ML engineer role requiring PyTorch and LLM experience.",
    "ats_keywords": ["PyTorch", "LLM", "transformer", "MLOps", "RAG", "NLP", "prompt", "inference"],
    "red_flags": [],
}

BASE_JOB: dict = {
    "id": "abc123",
    "title": "Senior ML Engineer",
    "company": "Acme Corp",
    "url": "https://example.com/jobs/123",
    "platform": "linkedin",
    "description": "We are looking for a Senior ML Engineer with PyTorch experience and LLM expertise.",
    "job_type": "full-time",
    "salary_text": "$130,000 – $160,000",
    "discovered_at": "2026-05-01T12:00:00Z",
}

BASE_PROFILE: dict = {
    "domains": ["artificial intelligence", "machine learning"],
    "experience_level": ["mid", "senior"],
    "salary_min_usd": 80000,
    "job_types": ["full-time", "contract"],
    "remote_preference": "hybrid_or_remote",
    "blacklist_companies": ["BadCorp", "SketchyStartup"],
}


# ── Test: hard filter — blacklisted company ───────────────────────────────────

@pytest.mark.asyncio
async def test_hard_filter_blacklist():
    """Company in blacklist_companies must yield score 0.0 without calling the LLM."""
    job = {**BASE_JOB, "company": "BadCorp"}

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        result = await score_job(job, BASE_PROFILE)

    # LLM must NOT have been called
    mock_llm.assert_not_called()

    assert result["score"] == 0.0
    assert len(result["red_flags"]) > 0
    assert any("blacklist" in flag.lower() or "blacklisted" in flag.lower()
               for flag in result["red_flags"])


@pytest.mark.asyncio
async def test_hard_filter_blacklist_case_insensitive():
    """Blacklist check should be case-insensitive."""
    job = {**BASE_JOB, "company": "BADCORP"}

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        result = await score_job(job, BASE_PROFILE)

    mock_llm.assert_not_called()
    assert result["score"] == 0.0


# ── Test: hard filter — intern in title ───────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_filter_intern():
    """Title containing 'Intern' must yield score 0.0 without calling the LLM."""
    job = {**BASE_JOB, "title": "Software Engineer Intern"}

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        result = await score_job(job, BASE_PROFILE)

    mock_llm.assert_not_called()

    assert result["score"] == 0.0
    assert len(result["red_flags"]) > 0
    assert any("intern" in flag.lower() or "excluded" in flag.lower()
               for flag in result["red_flags"])


@pytest.mark.asyncio
async def test_hard_filter_unpaid():
    """Title containing 'unpaid' must yield score 0.0."""
    job = {**BASE_JOB, "title": "Unpaid Research Assistant"}

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        result = await score_job(job, BASE_PROFILE)

    mock_llm.assert_not_called()
    assert result["score"] == 0.0


@pytest.mark.asyncio
async def test_hard_filter_intern_tutoring_exempt():
    """'Intern' filter must NOT apply to tutoring domain jobs."""
    job = {**BASE_JOB, "title": "Math Tutoring Intern", "domain": "tutoring"}

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {**VALID_LLM_RESPONSE, "domain": "tutoring"}
        result = await score_job(job, BASE_PROFILE)

    # LLM should have been called (tutoring is exempt from intern filter)
    mock_llm.assert_called_once()
    assert result["score"] == pytest.approx(VALID_LLM_RESPONSE["score"])


# ── Test: valid LLM JSON is propagated correctly ──────────────────────────────

@pytest.mark.asyncio
async def test_score_returned_from_llm():
    """When the LLM returns valid JSON, the score must be propagated to the caller."""
    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = VALID_LLM_RESPONSE.copy()
        result = await score_job(BASE_JOB, BASE_PROFILE)

    mock_llm.assert_called_once()

    assert result["score"] == pytest.approx(0.88)
    assert result["domain"] == "ai_ml"
    assert result["reasoning"] == VALID_LLM_RESPONSE["reasoning"]
    assert result["ats_keywords"] == VALID_LLM_RESPONSE["ats_keywords"]
    assert result["red_flags"] == []


@pytest.mark.asyncio
async def test_score_clamped_to_zero_one():
    """Scores outside [0, 1] returned by the LLM must be clamped."""
    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {**VALID_LLM_RESPONSE, "score": 1.5}
        result = await score_job(BASE_JOB, BASE_PROFILE)

    assert result["score"] == pytest.approx(1.0)

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm2:
        mock_llm2.return_value = {**VALID_LLM_RESPONSE, "score": -0.3}
        result2 = await score_job(BASE_JOB, BASE_PROFILE)

    assert result2["score"] == pytest.approx(0.0)


# ── Test: invalid / malformed LLM JSON does not raise ─────────────────────────

@pytest.mark.asyncio
async def test_invalid_llm_json_handled():
    """
    When chat_json raises ValueError (bad JSON), score_job must NOT propagate
    the exception — it must return a safe zero-score result instead.
    """
    with patch(
        "agents.scorer_agent.chat_json",
        new_callable=AsyncMock,
        side_effect=ValueError("LLM returned invalid JSON after 2 attempts."),
    ):
        result = await score_job(BASE_JOB, BASE_PROFILE)

    assert result["score"] == 0.0
    assert len(result["red_flags"]) > 0
    assert any("LLM" in flag or "error" in flag.lower() for flag in result["red_flags"])


@pytest.mark.asyncio
async def test_llm_exception_handled():
    """Any unexpected exception from chat_json must be caught; score must be 0.0."""
    with patch(
        "agents.scorer_agent.chat_json",
        new_callable=AsyncMock,
        side_effect=RuntimeError("network timeout"),
    ):
        # Must not raise
        result = await score_job(BASE_JOB, BASE_PROFILE)

    assert result["score"] == 0.0
    assert result["domain"] == "other"


# ── Test: domain field is always present ─────────────────────────────────────

@pytest.mark.asyncio
async def test_domain_classification():
    """Result dict must always contain a 'domain' key with a non-empty string."""
    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = VALID_LLM_RESPONSE.copy()
        result = await score_job(BASE_JOB, BASE_PROFILE)

    assert "domain" in result
    assert isinstance(result["domain"], str)
    assert len(result["domain"]) > 0


@pytest.mark.asyncio
async def test_domain_present_on_hard_filter():
    """'domain' must be present even when a hard filter is triggered (no LLM call)."""
    job = {**BASE_JOB, "company": "BadCorp"}
    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock):
        result = await score_job(job, BASE_PROFILE)

    assert "domain" in result
    assert isinstance(result["domain"], str)


@pytest.mark.asyncio
async def test_domain_defaults_when_missing_from_llm():
    """
    If the LLM omits 'domain' from the response, score_job must supply
    a default value ('other') rather than raising a KeyError.
    """
    response_without_domain = {k: v for k, v in VALID_LLM_RESPONSE.items() if k != "domain"}
    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = response_without_domain
        result = await score_job(BASE_JOB, BASE_PROFILE)

    assert "domain" in result
    assert result["domain"] == "other"


# ── Test: score_batch ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_score_batch_returns_same_length():
    """score_batch must return exactly one result per input job."""
    jobs = [
        {**BASE_JOB, "id": f"job{i}", "url": f"https://example.com/{i}"}
        for i in range(5)
    ]
    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = VALID_LLM_RESPONSE.copy()
        results = await score_batch(jobs, BASE_PROFILE, batch_size=3)

    assert len(results) == 5
    assert all("score" in r for r in results)


@pytest.mark.asyncio
async def test_score_batch_empty_input():
    """score_batch must handle an empty job list gracefully."""
    results = await score_batch([], BASE_PROFILE)
    assert results == []


@pytest.mark.asyncio
async def test_score_batch_partial_failure():
    """
    If one job raises inside gather(), score_batch must still return a result
    for every job (failed ones get zero score, not raise).
    """
    jobs = [
        {**BASE_JOB, "id": "good1", "url": "https://example.com/good1"},
        {**BASE_JOB, "id": "bad1",  "url": "https://example.com/bad1",
         "company": "BadCorp"},  # will be hard-filtered, no LLM call
        {**BASE_JOB, "id": "good2", "url": "https://example.com/good2"},
    ]

    def _side_effect(*args, **kwargs):
        # Simulate LLM returning valid JSON for non-blacklisted jobs
        return VALID_LLM_RESPONSE.copy()

    with patch(
        "agents.scorer_agent.chat_json",
        new_callable=AsyncMock,
        side_effect=_side_effect,
    ):
        results = await score_batch(jobs, BASE_PROFILE, batch_size=10)

    assert len(results) == 3
    # BadCorp job must have score 0
    assert results[1]["score"] == 0.0
    # Good jobs should have LLM score
    assert results[0]["score"] == pytest.approx(0.88)
    assert results[2]["score"] == pytest.approx(0.88)


# ── Test: salary filter ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_filter_salary_too_low():
    """Job with explicit max salary below profile minimum must get score 0.0."""
    job = {**BASE_JOB, "salary_text": "up to $50,000"}

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        result = await score_job(job, BASE_PROFILE)

    mock_llm.assert_not_called()
    assert result["score"] == 0.0


@pytest.mark.asyncio
async def test_salary_range_acceptable():
    """Job with salary range upper bound above profile minimum must proceed to LLM."""
    job = {**BASE_JOB, "salary_text": "$90,000 – $120,000"}

    with patch("agents.scorer_agent.chat_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = VALID_LLM_RESPONSE.copy()
        result = await score_job(job, BASE_PROFILE)

    mock_llm.assert_called_once()
    assert result["score"] == pytest.approx(0.88)
