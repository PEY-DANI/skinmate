"""오케스트레이터 통합 테스트 — 라우팅→퍼널/근거생성 전체 흐름(AC-R1 적응형).

가짜 프로바이더 + 계약 fixture(stub_retrieval_context)로 개발한다(1A.7/1B.4 배선은 2.1).
"""

from __future__ import annotations

from datetime import UTC, datetime

from tests.contracts.stubs import stub_retrieval_context

from skinmate.chat.orchestrator import ACK_MESSAGE, TurnResult, handle_turn
from skinmate.chat.rationale import FALLBACK_MESSAGE
from skinmate.chat.route import Route
from skinmate.contracts.facts import FactType, RankedFact


class _ScriptedProvider:
    """호출마다 미리 정한 payload 를 순서대로 반환(라우팅→근거생성 2단계 호출 시나리오용)."""

    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self._payloads = list(payloads)

    def complete(self, system: str, prompt: str) -> str:
        return ""

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, object]
    ) -> dict[str, object]:
        return self._payloads.pop(0)


def _fact(fact_type: FactType) -> RankedFact:
    return RankedFact(
        memory_id=1,
        fact_type=fact_type,
        content="x",
        effective_weight=1.0,
        last_seen=datetime(2026, 7, 9, tzinfo=UTC),
    )


def test_statement_route_gives_ack_no_recommendation() -> None:
    provider = _ScriptedProvider([{"intent": "statement"}])
    result = handle_turn(provider, "저는 레티놀 쓰면 자극나요")
    assert result == TurnResult(route=Route.STATEMENT, message=ACK_MESSAGE)


def test_vague_route_asks_concern_first_when_nothing_known() -> None:
    provider = _ScriptedProvider([{"intent": "recommendation"}])
    result = handle_turn(provider, "요즘 피부가 별로인데 뭐 쓰면 좋을까?")
    assert result.route == Route.VAGUE
    assert "고민" in result.message


def test_vague_route_asks_ingredient_when_concern_already_in_memory() -> None:
    """AC-R1 좁혀가기: 고민은 이미 기억에 있으니 다음은 성분을 묻는다."""
    provider = _ScriptedProvider([{"intent": "recommendation"}])
    result = handle_turn(
        provider,
        "그냥 아무거나 좋은 거 추천해줘",
        memory_facts=[_fact(FactType.HAS_CONCERN)],
    )
    assert result.route == Route.VAGUE
    assert "성분" in result.message


def test_specific_route_without_context_falls_back_to_funnel() -> None:
    """2.1 배선 전(retrieval_context 미제공) — 억지 추천 대신 좁히기로 안전 폴백."""
    provider = _ScriptedProvider([{"intent": "recommendation", "has_concern_slot": True}])
    result = handle_turn(provider, "건조에 좋은 에멀전 추천해줘")
    assert result.route == Route.VAGUE
    assert result.message == FALLBACK_MESSAGE


def test_specific_route_with_context_produces_grounded_rationale() -> None:
    """AC-R4 (a)/(d) 근사: 근거에 그래프 경로(계절 포함)와 회상된 기억이 함께 등장."""
    context = stub_retrieval_context()
    provider = _ScriptedProvider(
        [
            {"intent": "recommendation", "has_texture_slot": True, "has_concern_slot": True},
            {
                "response": "수분 에멀전을 추천해요 — 건조 고민에 히알루론산이 도움되고, "
                "오일 회피 기억도 반영했어요.",
                "cited_graph_path_indices": [0],
                "cited_memory_ids": [101],
            },
        ]
    )
    result = handle_turn(
        provider,
        "가을이라 건조한데 오일 말고 에멀전 추천해줘",
        retrieval_context=context,
    )
    assert result.route == Route.SPECIFIC
    assert result.cited_graph_path_indices == [
        0
    ]  # (a) 고민→성분 경로(계절 포함, 시드에 season='가을')
    assert result.cited_memory_ids == [101]  # (d) 회상된 기억(오일 회피) 등장
