"""검색 융합 결과 계약 — retrieve.py(A, ⭐6) 산출 → 근거 생성(B) 입력.

근거: docs/DATA-MODEL.md, PRD.md F3/F4/F7, team-agreement ⭐6/⭐7.
벡터 유사도 + 그래프 순회 + 기억 순위를 하나로 합친 묶음. 하드필터·제형 soft-rank 적용 후의
후보 제품과, 근거로 인용할 그래프 경로·회상된 기억 사실·참고 문서를 담는다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from skinmate.contracts.facts import RankedFact
from skinmate.contracts.graph import GraphPath
from skinmate.contracts.refs import ProductRef


class DocHit(BaseModel):
    """검색으로 찾은 참고 문서 한 조각(RAG 근거, F3). documents 테이블 기반.

    근거 생성이 내용 인용 + 출처 표기(AC-D1)를 봉투만 보고 할 수 있도록 발췌·출처를 함께 담는다.
    """

    doc_id: int
    content: str  # 발췌(스니펫)
    score: float  # 코사인 유사도
    source_meta: dict[str, Any] = Field(default_factory=dict)  # url·kind·crawled_at


class RetrievalContext(BaseModel):
    """한 추천 턴의 융합 검색 결과. 근거 생성은 여기 담긴 경로·기억·문서만 인용한다(AC-R3)."""

    query: str
    products: list[ProductRef] = Field(default_factory=list)  # 하드필터+제형랭킹 후 후보
    graph_paths: list[GraphPath] = Field(default_factory=list)  # 2+hop 근거 경로(AC-G2)
    memory_facts: list[RankedFact] = Field(default_factory=list)  # 회상된 개인 사실(rank_memory)
    doc_hits: list[DocHit] = Field(default_factory=list)  # 참고 문서 유사도 히트(F3, RAG 근거)
