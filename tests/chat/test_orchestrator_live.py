"""라이브 스모크 — 실제 Gemini로 라우팅·근거생성이 의도대로 동작하는지 확인(AC-R1/R3 정신).

기본은 녹화/가짜 프로바이더(test_route.py 등)로 돌고, 이 파일은 소량 라이브 확인이다
(ACCEPTANCE §2). GEMINI_API_KEY 미설정 시 skip.
"""

from __future__ import annotations

import pytest
from tests.contracts.stubs import stub_retrieval_context

from skinmate.chat.orchestrator import ACK_MESSAGE, handle_turn
from skinmate.chat.route import Route
from skinmate.config import settings
from skinmate.llm.gemini import GeminiProvider

pytestmark = pytest.mark.skipif(
    not settings.gemini_api_key, reason="GEMINI_API_KEY 미설정 — 라이브 스모크 skip"
)


@pytest.fixture(scope="module")
def provider() -> GeminiProvider:
    return GeminiProvider(settings.gemini_api_key, settings.llm_model)


def test_live_statement_gets_ack(provider: GeminiProvider) -> None:
    result = handle_turn(provider, "저는 레티놀 쓰면 자극나요")
    assert result.route == Route.STATEMENT
    assert result.message == ACK_MESSAGE


def test_live_vague_request_asks_narrowing_question(provider: GeminiProvider) -> None:
    result = handle_turn(provider, "요즘 피부가 별로인데 뭐 쓰면 좋을까?")
    assert result.route == Route.VAGUE
    assert result.message  # 비어있지 않은 좁히기 질문


def test_live_specific_request_produces_grounded_rationale(provider: GeminiProvider) -> None:
    context = stub_retrieval_context()
    result = handle_turn(
        provider,
        "가을이라 건조한데 끈적한 오일 말고 에멀전으로 보습 확실한 거 추천해줘",
        retrieval_context=context,
    )
    assert result.route == Route.SPECIFIC
    # 최소 하나는 실제로 인용해야 함(전무하면 폴백 메시지로 빠졌을 것)
    assert result.cited_graph_path_indices or result.cited_memory_ids
