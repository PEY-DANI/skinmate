"""턴 배선(2.1) — fixture 대신 실물 검색(1A.7)·저장(1B.4)을 대화 총괄(1B.6)에 묶는다.

PRD §1 공통 런타임 흐름을 그대로 구현한다: 라우팅 → [SPECIFIC 이면] 실물 검색 융합 →
근거 생성/응답 → 응답 반환 후 fact 추출·CRUD 판정·원자 저장. 검색·기억조회는 응답 생성에
쓰인 시점의 기억 상태를 반영해야 하므로 반드시 write_turn 이전에 수행한다(AC-M6 최근성
루프가 "다음 턴"부터 반영됨을 보장하는 전제).
"""

from __future__ import annotations

from typing import Any

import psycopg

from skinmate import db
from skinmate.chat.orchestrator import TurnResult, handle_turn
from skinmate.chat.route import Route, classify_route
from skinmate.llm.base import LLMProvider
from skinmate.memory.rank import rank_memory
from skinmate.retrieval.retrieve import retrieve_recommendation_context
from skinmate.write.writer import write_turn


def process_turn(
    conn: psycopg.Connection[Any],
    provider: LLMProvider,
    user_id: int,
    utterance: str,
    *,
    history: list[str] | None = None,
    season: str | None = None,
) -> TurnResult:
    """한 턴 전체(읽기→응답→쓰기)를 처리해 TurnResult 를 반환한다.

    호출자가 연 커넥션을 그대로 쓴다(수명·풀링은 호출자 책임, write_turn 과 동일 관례).
    """
    decision = classify_route(provider, utterance, history=history)

    with db.user_scope(conn, user_id):
        if decision.route == Route.SPECIFIC:
            retrieval_context = retrieve_recommendation_context(
                conn, user_id, utterance, season=season
            )
            memory_facts = retrieval_context.memory_facts
        else:
            retrieval_context = None
            memory_facts = rank_memory(conn, user_id)

    result = handle_turn(
        provider,
        utterance,
        history=history,
        memory_facts=memory_facts,
        retrieval_context=retrieval_context,
        route_decision=decision,
    )

    write_turn(conn, provider, user_id, utterance)

    return result
