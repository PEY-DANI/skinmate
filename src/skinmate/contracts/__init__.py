"""공유 데이터 형식(⭐7) — 트랙 A(데이터)와 B(대화·기억)가 주고받는 계약. 공동 소유.

변경은 반드시 PR + 상대 리뷰(team-agreement §3). 계약↔실물/DB 정합은 tests/contracts 가 강제.
"""

from skinmate.contracts.facts import FactType, RankedFact
from skinmate.contracts.graph import (
    EdgeRel,
    GraphEdge,
    GraphNode,
    GraphPath,
    NodeKind,
)
from skinmate.contracts.refs import IngredientRef, ProductRef
from skinmate.contracts.retrieval import DocHit, RetrievalContext

__all__ = [
    "FactType",
    "RankedFact",
    "IngredientRef",
    "ProductRef",
    "NodeKind",
    "EdgeRel",
    "GraphNode",
    "GraphEdge",
    "GraphPath",
    "DocHit",
    "RetrievalContext",
]
