"""대화 총괄(1B.6) — 라우팅→(퍼널 or 근거생성)으로 한 턴을 마무리한다(PRD F6, AC-R1).

실제 검색(1A.7)·저장(1B.4)과의 배선은 2.1 통합의 몫이다 — 여기서는 `RetrievalContext`
계약(⭐7)만 소비하므로, 실물이 없는 지금은 fixture(tests/contracts/stubs.py)로 개발·검증
한다(WBS "fixture로 개발"). fact 추출·CRUD 저장(write_turn)은 이 함수가 호출하지 않는다 —
사용자 발화를 "무엇을 답할지"와 "무엇을 기억할지"는 서로 다른 관심사라 2.1 에서 나란히
배선한다.
"""

from __future__ import annotations

from pydantic import BaseModel

from skinmate.chat.funnel import known_slots_from_memory, next_funnel_question
from skinmate.chat.rationale import FALLBACK_MESSAGE, generate_rationale
from skinmate.chat.route import Route, RouteDecision, classify_route
from skinmate.contracts.facts import RankedFact
from skinmate.contracts.retrieval import RetrievalContext
from skinmate.llm.base import LLMProvider

ACK_MESSAGE = "알려주셔서 감사해요, 기억해 둘게요!"


class TurnResult(BaseModel):
    """한 턴의 응답. route=SPECIFIC 일 때만 cited_* 가 채워질 수 있다(AC-R3 감사용)."""

    route: Route
    message: str
    cited_graph_path_indices: list[int] = []
    cited_memory_ids: list[int] = []


def handle_turn(
    provider: LLMProvider,
    utterance: str,
    *,
    history: list[str] | None = None,
    memory_facts: list[RankedFact] | None = None,
    retrieval_context: RetrievalContext | None = None,
    route_decision: RouteDecision | None = None,
) -> TurnResult:
    """한 턴을 처리한다.

    - STATEMENT: 단순 인지 응답(추천 로직 없음).
    - VAGUE: memory_facts 로 이미 답변된 슬롯을 역산해 다음 좁히기 질문(AC-R1 좁혀가기).
    - SPECIFIC: retrieval_context 로 근거 생성. context 가 없으면(2.1 배선 전) 좁히기로 폴백
      — 억지 추천 금지(PRD F6 예외처리).

    route_decision 을 미리 계산해 주입할 수 있다 — 2.1 배선에서 라우팅 결과에 따라 실제
    retrieval_context 를 조회할지 먼저 결정해야 하므로, classify_route 를 중복 호출(LLM
    쿼터 낭비)하지 않도록 재사용한다. 미제공 시 이 함수가 직접 분류한다(기존 단위테스트 호환).
    """
    memory_facts = memory_facts or []
    decision = route_decision or classify_route(provider, utterance, history=history)

    if decision.route == Route.STATEMENT:
        return TurnResult(route=Route.STATEMENT, message=ACK_MESSAGE)

    if decision.route == Route.VAGUE:
        known = known_slots_from_memory(memory_facts) | decision.known_slots()
        question = next_funnel_question(known) or FALLBACK_MESSAGE
        return TurnResult(route=Route.VAGUE, message=question)

    # SPECIFIC
    if retrieval_context is None:
        return TurnResult(route=Route.VAGUE, message=FALLBACK_MESSAGE)

    rationale = generate_rationale(provider, retrieval_context)
    return TurnResult(
        route=Route.SPECIFIC,
        message=rationale.response,
        cited_graph_path_indices=rationale.cited_graph_path_indices,
        cited_memory_ids=rationale.cited_memory_ids,
    )
