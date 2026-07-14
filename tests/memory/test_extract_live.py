"""라이브 스모크 — 실제 NVIDIA NIM API 호출로 fact 추출기가 의도대로 동작하는지 확인."""

from __future__ import annotations

import time

import pytest

from skinmate.config import settings
from skinmate.contracts.facts import FactType
from skinmate.llm.nvidia import NvidiaProvider
from skinmate.memory.extract import extract_facts

pytestmark = pytest.mark.skipif(
    not settings.openai_api_key, reason="NVIDIA/OPENAI_API_KEY 미설정 — 라이브 스모크 skip"
)


@pytest.fixture(scope="module")
def provider() -> NvidiaProvider:
    return NvidiaProvider(settings.openai_api_key, settings.llm_model)


def test_live_extracts_avoid_ingredient(provider: NvidiaProvider) -> None:
    """구체 회피 성분 발화 → avoid_ingredient 사실이 실제로 추출된다."""
    time.sleep(3)  # Rate Limit 방지
    facts = extract_facts(provider, "저는 레티놀 쓰면 얼굴이 따가워서 못 써요")
    assert facts, "도메인 사실이 최소 1개는 추출돼야 함"
    assert any(f.fact_type == FactType.AVOID_INGREDIENT for f in facts)
    assert any("레티놀" in (f.target_name or f.content) for f in facts)


def test_live_filters_smalltalk(provider: NvidiaProvider) -> None:
    """비도메인 잡담 → 중요도 필터로 걸러져 빈 결과."""
    time.sleep(3)  # Rate Limit 방지
    assert extract_facts(provider, "아 오늘 진짜 피곤하고 졸리다") == []
