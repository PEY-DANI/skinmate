"""계약(⭐7) 검증 — 스텁↔실물 스키마 일치 + 계약↔DB 진실원 파리티. CI 게이트(ACCEPTANCE §2/§5).

이 테스트가 지키는 것:
  1. 계약 모델이 직렬화 왕복(dump→validate)을 손실 없이 통과.
  2. 스텁 producer 산출물이 스키마를 만족(실물 producer 도 같은 하네스로 검증되도록 등록 지점 제공).
  3. FactType·그래프 라벨이 DB 마이그레이션(진실원)과 일치 — 스키마 드리프트 차단.
  4. 잘못된 형식은 거부.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError
from stubs import (
    RETRIEVAL_PRODUCERS,
    stub_doc_hit,
    stub_graph_path,
    stub_ingredient_ref,
    stub_ranked_fact,
    stub_retrieval_context,
)

from skinmate.contracts import (
    EdgeRel,
    FactType,
    GraphEdge,
    GraphNode,
    GraphPath,
    NodeKind,
    RankedFact,
    RetrievalContext,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _read_migration(name: str) -> str:
    return (_REPO_ROOT / "db" / "migrations" / name).read_text(encoding="utf-8")


# ── 1. 직렬화 왕복 ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "instance",
    [
        stub_ingredient_ref(),
        stub_graph_path(),
        stub_ranked_fact(),
        stub_doc_hit(),
        stub_retrieval_context(),
    ],
    ids=["IngredientRef", "GraphPath", "RankedFact", "DocHit", "RetrievalContext"],
)
def test_model_roundtrip(instance: BaseModel) -> None:
    """dump→validate 왕복이 동등한 인스턴스를 복원한다(직렬화 경계 안전)."""
    restored = type(instance).model_validate(instance.model_dump())
    assert restored == instance


# ── 2. 스텁↔실물 하네스 ───────────────────────────────────────────
@pytest.mark.parametrize("producer", RETRIEVAL_PRODUCERS)
def test_retrieval_producer_satisfies_schema(producer: Callable[[], RetrievalContext]) -> None:
    """등록된 모든 producer(스텁·이후 실물)가 RetrievalContext 스키마를 만족."""
    ctx = producer()
    assert isinstance(ctx, RetrievalContext)
    # JSON 왕복으로 실제 직렬화 가능성까지 확인
    RetrievalContext.model_validate(json.loads(ctx.model_dump_json()))


def test_retrieval_context_json_fixture() -> None:
    """스텁 fixture(JSON)가 RetrievalContext 스키마를 만족하고 왕복 동등."""
    raw = json.loads((_FIXTURES / "retrieval_context.json").read_text(encoding="utf-8"))
    ctx = RetrievalContext.model_validate(raw)
    assert ctx.products and ctx.graph_paths and ctx.memory_facts and ctx.doc_hits
    assert RetrievalContext.model_validate(ctx.model_dump()) == ctx


# ── 3. 계약↔DB 진실원 파리티 ──────────────────────────────────────
def test_fact_type_matches_db_enum() -> None:
    """FactType 값이 002 마이그레이션의 `fact_type` ENUM 과 정확히 일치."""
    sql = _read_migration("002_memory_and_rls.sql")
    body = re.search(r"CREATE TYPE fact_type AS ENUM\s*\((.*?)\);", sql, re.DOTALL)
    assert body, "002 에서 fact_type ENUM 정의를 찾지 못함"
    db_values = set(re.findall(r"'([^']+)'", body.group(1)))
    assert db_values == {ft.value for ft in FactType}


def _array_literals(sql: str, var: str) -> set[str]:
    m = re.search(rf"{var}\s+text\[\]\s*:=\s*ARRAY\[(.*?)\]", sql, re.DOTALL)
    assert m, f"003 에서 {var} 배열을 찾지 못함"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_graph_labels_match_db_ontology() -> None:
    """NodeKind·EdgeRel 이 003 그래프 온톨로지의 vlabels·elabels 와 정확히 일치."""
    sql = _read_migration("003_graph_ontology.sql")
    assert _array_literals(sql, "vlabels") == {nk.value for nk in NodeKind}
    assert _array_literals(sql, "elabels") == {er.value for er in EdgeRel}


# ── 4. 잘못된 형식 거부 ───────────────────────────────────────────
def test_graph_path_rejects_out_of_range_edge() -> None:
    """엣지가 존재하지 않는 노드 인덱스를 가리키면 거부."""
    with pytest.raises(ValidationError):
        GraphPath(
            nodes=[GraphNode(kind=NodeKind.USER, key="user:1")],
            edges=[GraphEdge(rel=EdgeRel.AVOIDS, from_idx=0, to_idx=5)],
        )


def test_graph_path_rejects_empty_nodes() -> None:
    """노드 없는 경로는 거부."""
    with pytest.raises(ValidationError):
        GraphPath(nodes=[], edges=[])


def test_ranked_fact_rejects_unknown_fact_type() -> None:
    """FactType enum 밖의 값은 거부(스키마 밖 사실 유입 차단)."""
    with pytest.raises(ValidationError):
        RankedFact.model_validate(
            {
                "memory_id": 1,
                "fact_type": "not_a_real_type",
                "content": "x",
                "effective_weight": 1.0,
                "last_seen": "2026-07-01T09:00:00Z",
            }
        )
