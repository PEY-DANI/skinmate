"""라이브 스모크 — 실제 NVIDIA NIM API로 라우팅·근거생성이 의도대로 동작하는지 확인(AC-R1/R3 정신).

NVIDIA API_KEY 미설정 시 skip.
"""

from __future__ import annotations

import time

import pytest
from tests.contracts.stubs import stub_retrieval_context

from skinmate.chat.orchestrator import ACK_MESSAGE, handle_turn
from skinmate.chat.route import Route
from skinmate.config import settings
from skinmate.llm.nvidia import NvidiaProvider

pytestmark = pytest.mark.skipif(
    not settings.openai_api_key, reason="NVIDIA/OPENAI_API_KEY 미설정 — 라이브 스모크 skip"
)


@pytest.fixture(scope="module")
def provider() -> NvidiaProvider:
    return NvidiaProvider(settings.openai_api_key, settings.llm_model)


def test_live_statement_gets_ack(provider: NvidiaProvider) -> None:
    time.sleep(3)  # Rate Limit 방지
    result = handle_turn(provider, "저는 레티놀 쓰면 자극나요")
    assert result.route == Route.STATEMENT
    assert result.message == ACK_MESSAGE


def test_live_vague_request_asks_narrowing_question(provider: NvidiaProvider) -> None:
    time.sleep(3)  # Rate Limit 방지
    result = handle_turn(provider, "요즘 피부가 별로인데 뭐 쓰면 좋을까?")
    assert result.route == Route.VAGUE
    assert result.message  # 비어있지 않은 좁히기 질문


def test_live_specific_request_produces_grounded_rationale(provider: NvidiaProvider) -> None:
    time.sleep(3)  # Rate Limit 방지
    context = stub_retrieval_context()
    result = handle_turn(
        provider,
        "가을이라 건조한데 끈적한 오일 말고 에멀전으로 보습 확실한 거 추천해줘",
        retrieval_context=context,
    )
    assert result.route == Route.SPECIFIC
    assert result.cited_graph_path_indices or result.cited_memory_ids
