"""기억 사실 계약 — FactType(그래프 투영 축) + RankedFact(rank_memory 산출, ⭐6).

근거: docs/DATA-MODEL.md §1(memories), db/migrations/002_memory_and_rls.sql,
PRD.md F1, ACCEPTANCE AC-M2. FactType 값은 DB `fact_type` ENUM 과 정확히 일치해야 한다
(tests/contracts 의 파리티 테스트가 강제).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class FactType(StrEnum):
    """기억 종류. 그래프 투영 여부를 가르는 축(DATA-MODEL §2)."""

    SKIN_TYPE = "skin_type"  # 관계형만, 그래프 투영 안 함
    AVOID_INGREDIENT = "avoid_ingredient"  # → (:User)-[:AVOIDS]->(:Ingredient)
    PREFER_INGREDIENT = "prefer_ingredient"  # → (:User)-[:PREFERS]->(:Ingredient)
    AVOID_BRAND = "avoid_brand"  # → (:User)-[:AVOIDS]->(:Brand)
    PREFER_BRAND = "prefer_brand"  # → (:User)-[:PREFERS]->(:Brand)
    HAS_CONCERN = "has_concern"  # → (:User)-[:HAS_CONCERN {season?}]->(:Concern)
    OTHER = "other"  # 관계형만, 그래프 투영 안 함


class RankedFact(BaseModel):
    """`rank_memory(user)`(B, ⭐6) 이 반환하는 순위 매겨진 개인 사실. retrieve 가 소비.

    `effective_weight = base_weight × exp(-λ×Δdays)`(λ=0.05/day)는 조회 시 계산된 값이다
    (저장 안 함). 성분 사실은 `target_ingredient_id`, concern/brand 는 `target_name` 으로 다리 연결.
    """

    memory_id: int
    fact_type: FactType
    content: str
    effective_weight: float  # 시간감쇠 반영된 조회-시점 가중치
    frequency: int = 1
    last_seen: datetime
    target_ingredient_id: int | None = None  # 성분 사실의 그래프 다리 참조(FK)
    target_name: str | None = None  # concern/brand 이름(그래프 네이티브 노드 키)
    season: str | None = None  # 계절 맥락(가을/겨울…)
