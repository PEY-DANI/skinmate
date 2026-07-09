"""CRUD 판정기 테스트 — judge 순수 유닛 + apply_decision DB 통합(AC-M1).

judge 는 DB 없이 결정적으로, apply(감사·soft-delete·비파괴 공존)는 실 DB(RLS)로 검증한다.
DB 미기동 시 통합 케이스만 skip.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from skinmate import db
from skinmate.contracts.facts import FactType
from skinmate.memory import crud, repo
from skinmate.memory.crud import CrudOp
from skinmate.memory.extract import ExtractedFact
from skinmate.memory.repo import ActiveMemory

_UID = 990201
_UID_B = 990202


def _fact(fact_type: FactType, target_name: str, *, retract: bool = False) -> ExtractedFact:
    return ExtractedFact(
        fact_type=fact_type, content=f"{target_name} 관련", target_name=target_name, retract=retract
    )


def _active(memory_id: int, fact_type: FactType, slot_key: str, target_name: str) -> ActiveMemory:
    return ActiveMemory(
        memory_id=memory_id,
        fact_type=fact_type,
        slot_key=slot_key,
        target_name=target_name,
        content=f"{target_name} 관련",
        season=None,
    )


# ── 순수 유닛: judge 4개 op + 비파괴 공존 (DB 불필요) ────────────────────
def test_judge_add_when_new_slot() -> None:
    d = crud.judge([], _fact(FactType.AVOID_INGREDIENT, "레티놀"))
    assert d.op == CrudOp.ADD
    assert d.slot_key == "ingredient:레티놀"
    assert d.target_memory_id is None


def test_judge_noop_on_duplicate() -> None:
    existing = [_active(1, FactType.AVOID_INGREDIENT, "ingredient:레티놀", "레티놀")]
    d = crud.judge(existing, _fact(FactType.AVOID_INGREDIENT, "레티놀"))
    assert d.op == CrudOp.NOOP
    assert d.target_memory_id == 1


def test_judge_update_on_stance_flip() -> None:
    """같은 슬롯(ingredient:레티놀) 회피→선호 = update."""
    existing = [_active(1, FactType.AVOID_INGREDIENT, "ingredient:레티놀", "레티놀")]
    d = crud.judge(existing, _fact(FactType.PREFER_INGREDIENT, "레티놀"))
    assert d.op == CrudOp.UPDATE
    assert d.target_memory_id == 1


def test_judge_delete_on_retract() -> None:
    existing = [_active(1, FactType.AVOID_INGREDIENT, "ingredient:레티놀", "레티놀")]
    d = crud.judge(existing, _fact(FactType.AVOID_INGREDIENT, "레티놀", retract=True))
    assert d.op == CrudOp.DELETE
    assert d.target_memory_id == 1


def test_judge_retract_without_match_is_noop() -> None:
    d = crud.judge([], _fact(FactType.AVOID_INGREDIENT, "레티놀", retract=True))
    assert d.op == CrudOp.NOOP
    assert d.target_memory_id is None


def test_judge_nondestructive_coexist() -> None:
    """다른 슬롯의 새 회피는 기존 회피를 건드리지 않고 add(AC-M1 비파괴)."""
    existing = [_active(1, FactType.AVOID_INGREDIENT, "ingredient:레티놀", "레티놀")]
    d = crud.judge(existing, _fact(FactType.AVOID_INGREDIENT, "향료"))
    assert d.op == CrudOp.ADD


def test_judge_skin_type_update_and_noop() -> None:
    existing = [_active(1, FactType.SKIN_TYPE, "skin_type", "지성")]
    same = crud.judge(existing, _fact(FactType.SKIN_TYPE, "지성"))
    changed = crud.judge(existing, _fact(FactType.SKIN_TYPE, "건성"))
    assert same.op == CrudOp.NOOP
    assert changed.op == CrudOp.UPDATE


def test_judge_other_always_add() -> None:
    d = crud.judge([], ExtractedFact(fact_type=FactType.OTHER, content="루틴 아침만"))
    assert d.op == CrudOp.ADD
    assert d.slot_key is None


# ── 통합: apply_decision + 감사 + soft-delete (실 DB) ────────────────────
@pytest.fixture
def conn() -> Iterator[psycopg.Connection[object]]:
    try:
        c = db.connect()
    except psycopg.OperationalError as exc:
        pytest.skip(f"DB 미기동 — 통합테스트 skip: {exc}")
    try:
        yield c
        for uid in (_UID, _UID_B):
            with db.user_scope(c, uid):
                c.execute("DELETE FROM memory_audit WHERE user_id = %s", (uid,))
                c.execute("DELETE FROM memories WHERE user_id = %s", (uid,))
    finally:
        c.close()


def _process(conn: psycopg.Connection[object], uid: int, fact: ExtractedFact) -> crud.CrudDecision:
    """한 발화 사실을 판정→반영(각 호출이 자체 트랜잭션). 반환: 판정."""
    with db.user_scope(conn, uid):
        decision = crud.judge(repo.list_active(conn, uid), fact)
        crud.apply_decision(conn, uid, decision)
    return decision


def _audit_ops(conn: psycopg.Connection[object], uid: int) -> list[str]:
    with db.user_scope(conn, uid):
        cur = conn.execute(
            "SELECT op FROM memory_audit WHERE user_id = %s ORDER BY audit_id", (uid,)
        )
        return [r[0] for r in cur.fetchall()]


def test_apply_add_then_noop_bumps_frequency(conn: psycopg.Connection[object]) -> None:
    """add 후 동일 언급 → no-op 이 frequency 를 올린다(AC-M1 no-op + 가중치)."""
    _process(conn, _UID, _fact(FactType.AVOID_INGREDIENT, "레티놀"))
    _process(conn, _UID, _fact(FactType.AVOID_INGREDIENT, "레티놀"))

    with db.user_scope(conn, _UID):
        row = conn.execute(
            "SELECT frequency FROM memories WHERE user_id = %s AND deleted_at IS NULL", (_UID,)
        ).fetchone()
    assert row is not None and row[0] == 2
    assert _audit_ops(conn, _UID) == ["add", "no-op"]


def test_apply_update_supersedes_and_audits_old(conn: psycopg.Connection[object]) -> None:
    """회피→선호 전환 시 행은 최신값, 감사에 이전 값 보존(AC-M1 update)."""
    _process(conn, _UID, _fact(FactType.AVOID_INGREDIENT, "레티놀"))
    _process(conn, _UID, _fact(FactType.PREFER_INGREDIENT, "레티놀"))

    with db.user_scope(conn, _UID):
        row = conn.execute(
            "SELECT fact_type FROM memories WHERE user_id = %s AND deleted_at IS NULL", (_UID,)
        ).fetchone()
        aud = conn.execute(
            "SELECT old_val, new_val FROM memory_audit WHERE user_id = %s AND op = 'update'",
            (_UID,),
        ).fetchone()
    assert row is not None and row[0] == "prefer_ingredient"
    assert aud is not None
    assert aud[0]["fact_type"] == "avoid_ingredient"  # old
    assert aud[1]["fact_type"] == "prefer_ingredient"  # new


def test_apply_delete_is_soft_and_audited(conn: psycopg.Connection[object]) -> None:
    """철회 → soft-delete(deleted_at)만, 하드삭제 아님 + 감사 delete(AC-M1 delete)."""
    _process(conn, _UID, _fact(FactType.HAS_CONCERN, "트러블"))
    d = _process(conn, _UID, _fact(FactType.HAS_CONCERN, "트러블", retract=True))
    assert d.op == CrudOp.DELETE

    with db.user_scope(conn, _UID):
        active = repo.list_active(conn, _UID)
        total = conn.execute("SELECT count(*) FROM memories WHERE user_id = %s", (_UID,)).fetchone()
    assert active == []  # 활성 목록엔 없음
    assert total is not None and total[0] == 1  # 행은 남아있음(soft)
    assert _audit_ops(conn, _UID) == ["add", "delete"]


def test_apply_nondestructive_coexist(conn: psycopg.Connection[object]) -> None:
    """서로 다른 슬롯 회피 2건은 공존한다(AC-M1 비파괴 공존)."""
    _process(conn, _UID, _fact(FactType.AVOID_INGREDIENT, "레티놀"))
    _process(conn, _UID, _fact(FactType.AVOID_INGREDIENT, "향료"))

    with db.user_scope(conn, _UID):
        names = {m.target_name for m in repo.list_active(conn, _UID)}
    assert names == {"레티놀", "향료"}


def test_apply_isolation_between_users(conn: psycopg.Connection[object]) -> None:
    """A 가 쓴 기억을 B 는 못 본다(RLS, AC-M5 재확인)."""
    _process(conn, _UID, _fact(FactType.AVOID_INGREDIENT, "레티놀"))
    with db.user_scope(conn, _UID_B):
        assert repo.list_active(conn, _UID_B) == []
