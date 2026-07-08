"""계약 스텁 producer — 실물(0.5 stub·1A retrieve)이 나오기 전 계약 형식을 대표하는 유효 인스턴스.

같은 검증 하네스(test_contracts)를 스텁과 실물 producer 가 모두 통과해야 한다
(스텁↔실물, ACCEPTANCE-TESTING §2 계약 계층). 실물이 생기면 아래 RETRIEVAL_PRODUCERS 에 등록한다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from skinmate.contracts import (
    DocHit,
    EdgeRel,
    FactType,
    GraphEdge,
    GraphNode,
    GraphPath,
    IngredientRef,
    NodeKind,
    ProductRef,
    RankedFact,
    RetrievalContext,
)


def stub_ingredient_ref() -> IngredientRef:
    """대표 성분 참조."""
    return IngredientRef(
        ingredient_id=55,
        canonical_key="hyaluronic acid",
        name_ko="히알루론산",
        name_en="Hyaluronic Acid",
        inci_key="hyaluronic acid",
    )


def stub_product_ref() -> ProductRef:
    """대표 제품 참조."""
    return ProductRef(product_id=10, name="수분 에멀전", brand="coos")


def stub_graph_path() -> GraphPath:
    """AC-G2 대표 2+hop 경로(건조←TREATS←히알루론산←CONTAINS←제품 + 개인 HAS_CONCERN)."""
    return GraphPath(
        nodes=[
            GraphNode(kind=NodeKind.USER, key="user:1", label="나"),
            GraphNode(kind=NodeKind.CONCERN, key="dryness", label="건조"),
            GraphNode(kind=NodeKind.INGREDIENT, key="hyaluronic_acid", label="히알루론산"),
            GraphNode(kind=NodeKind.PRODUCT, key="prod:10", label="수분 에멀전"),
        ],
        edges=[
            GraphEdge(rel=EdgeRel.HAS_CONCERN, from_idx=0, to_idx=1, season="가을"),
            GraphEdge(rel=EdgeRel.TREATS, from_idx=2, to_idx=1),
            GraphEdge(rel=EdgeRel.CONTAINS, from_idx=3, to_idx=2),
        ],
    )


def stub_ranked_fact() -> RankedFact:
    """대표 회상 기억: 오일 회피(개인 사실)."""
    return RankedFact(
        memory_id=101,
        fact_type=FactType.AVOID_INGREDIENT,
        content="오일 제형은 안 맞았어요",
        effective_weight=0.82,
        frequency=3,
        last_seen=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        target_ingredient_id=55,
    )


def stub_doc_hit() -> DocHit:
    """대표 참고 문서 히트(출처·유사도 포함)."""
    return DocHit(
        doc_id=7,
        content="가을철 건조에는 히알루론산 계열의 수분 보습이 끈적임 없이 효과적이다.",
        score=0.79,
        source_meta={
            "url": "https://example.com/skincare/autumn",
            "kind": "article",
            "crawled_at": "2026-06-30",
        },
    )


def stub_retrieval_context() -> RetrievalContext:
    """네 소스(벡터·그래프·기억·문서)를 합친 대표 융합 결과."""
    return RetrievalContext(
        query="가을이라 건조한데 끈적한 오일 말고 에멀전으로 보습 확실한 거 추천해줘",
        products=[
            stub_product_ref(),
            ProductRef(product_id=11, name="히알루론 세럼", brand="paulas-choice"),
        ],
        graph_paths=[stub_graph_path()],
        memory_facts=[stub_ranked_fact()],
        doc_hits=[stub_doc_hit()],
    )


# 실물 producer 는 구현되면 여기 등록한다(스텁↔실물 동일 스키마 검증).
# 예: from skinmate.retrieval import retrieve; RETRIEVAL_PRODUCERS.append(lambda: retrieve(...))
RETRIEVAL_PRODUCERS: list[Callable[[], RetrievalContext]] = [stub_retrieval_context]
