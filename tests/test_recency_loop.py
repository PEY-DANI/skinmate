"""최근성 루프(AC-M6) — 턴 N 에 쓴 사실이 턴 N+1 조회에서 동급 base_weight 미언급 사실 대비
랭크 상승, drain 호출 없음(ACCEPTANCE-TESTING §3 P0 필수 테스트).

writer(1B.4, write_turn)로 실제로 커밋한 뒤, **별도 커넥션**으로 rank_memory(1B.3)를 즉시
호출해 반영 여부를 본다 — 같은 커넥션이면 미커밋 상태도 보일 수 있어 진짜 커밋 증명이 안 됨
(AC-S2 와 같은 이유). 가짜 프로바이더만 쓰므로 LLM 실호출·API 키 불필요.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from skinmate import db
from skinmate.memory.rank import rank_memory
from skinmate.write.writer import write_turn

_UID = 990601


class _CannedProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def complete(self, system: str, prompt: str) -> str:
        return ""

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, object]
    ) -> dict[str, object]:
        return self._payload


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[object]]:
    try:
        c = db.connect()
    except psycopg.OperationalError as exc:
        pytest.skip(f"DB 미기동 — 통합테스트 skip: {exc}")
    try:
        yield c
        with db.user_scope(c, _UID):
            c.execute("DELETE FROM memory_audit WHERE user_id = %s", (_UID,))
            c.execute("DELETE FROM memories WHERE user_id = %s", (_UID,))
    finally:
        c.close()


def _seed_old_fact(conn: psycopg.Connection[object], *, days_ago: int) -> None:
    """동급 base_weight(1.0)의 오래된 미언급 사실을 직접 심는다(비교 기준선)."""
    with db.user_scope(conn, _UID):
        conn.execute(
            """
            INSERT INTO memories (user_id, content, fact_type, target_name, base_weight, last_seen)
            VALUES (%s, %s, 'has_concern', %s, 1.0, %s)
            """,
            (_UID, "오래된 고민", "old_concern", datetime.now(UTC) - timedelta(days=days_ago)),
        )


def test_write_turn_fact_outranks_older_equal_weight_fact(
    conn: psycopg.Connection[object],
) -> None:
    """턴 N 에 쓴 사실이, 동급 base_weight 지만 오래돼 미언급인 사실보다 랭크 상승(AC-M6)."""
    _seed_old_fact(conn, days_ago=10)

    provider = _CannedProvider(
        {
            "facts": [
                {"fact_type": "avoid_ingredient", "content": "레티놀 회피", "target_name": "레티놀"}
            ]
        }
    )
    write_turn(conn, provider, _UID, "레티놀 쓰면 자극나요")  # 턴 N, 반환 시점에 이미 커밋됨

    # 턴 N+1: 완전히 새 커넥션으로 조회 — drain·flush 없이 즉시 반영되는지 확인(AC-S2 와 동일 원리)
    other_conn = db.connect()
    try:
        with db.user_scope(other_conn, _UID):
            ranked = rank_memory(other_conn, _UID)
    finally:
        other_conn.close()

    assert [r.target_name for r in ranked[:1]] == ["레티놀"]  # 방금 쓴 사실이 최상위
    contents = [r.content for r in ranked]
    assert "오래된 고민" in contents  # 이전 사실도 여전히 존재(비파괴)
    weights = {r.content: r.effective_weight for r in ranked}
    assert weights["레티놀 회피"] > weights["오래된 고민"]  # 신선도 반영, 랭크 상승


def test_write_turn_visible_without_explicit_drain_or_flush(
    conn: psycopg.Connection[object],
) -> None:
    """AC-M6 핵심: write_turn 반환 직후 아무 추가 조작(drain 호출 등) 없이도 즉시 조회된다."""
    provider = _CannedProvider({"facts": [{"fact_type": "skin_type", "content": "지성"}]})
    write_turn(conn, provider, _UID, "저는 지성이에요")

    other_conn = db.connect()
    try:
        with db.user_scope(other_conn, _UID):
            ranked = rank_memory(other_conn, _UID)  # drain/flush 호출 없이 바로 조회
    finally:
        other_conn.close()

    assert len(ranked) == 1
    assert ranked[0].content == "지성"
