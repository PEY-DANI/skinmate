"""퍼널 테스트 — memory_facts 에서 known_slots 역산 + 우선순위대로 다음 질문 고르기(AC-R1)."""

from __future__ import annotations

from datetime import UTC, datetime

from skinmate.chat.funnel import known_slots_from_memory, next_funnel_question
from skinmate.contracts.facts import FactType, RankedFact


def _fact(fact_type: FactType) -> RankedFact:
    return RankedFact(
        memory_id=1,
        fact_type=fact_type,
        content="x",
        effective_weight=1.0,
        last_seen=datetime(2026, 7, 9, tzinfo=UTC),
    )


def test_known_slots_from_memory_concern() -> None:
    assert known_slots_from_memory([_fact(FactType.HAS_CONCERN)]) == {"concern"}


def test_known_slots_from_memory_ingredient() -> None:
    assert known_slots_from_memory([_fact(FactType.AVOID_INGREDIENT)]) == {"ingredient"}
    assert known_slots_from_memory([_fact(FactType.PREFER_INGREDIENT)]) == {"ingredient"}


def test_known_slots_from_memory_unrelated_type_ignored() -> None:
    assert known_slots_from_memory([_fact(FactType.SKIN_TYPE)]) == set()


def test_known_slots_from_memory_empty() -> None:
    assert known_slots_from_memory([]) == set()


def test_next_funnel_question_asks_concern_first() -> None:
    assert next_funnel_question(set()) == next_funnel_question(set())  # 결정적
    q = next_funnel_question(set())
    assert q is not None and "고민" in q


def test_next_funnel_question_asks_ingredient_when_concern_known() -> None:
    q = next_funnel_question({"concern"})
    assert q is not None and "성분" in q


def test_next_funnel_question_none_when_all_known() -> None:
    assert next_funnel_question({"concern", "ingredient"}) is None
