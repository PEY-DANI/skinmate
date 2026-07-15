"""한글 canonical_key 성분 행을 영문 canonical_key 행으로 FK 재연결하는 1회성 마이그레이션.

배경: ingest/normalize.py 가 제품 성분표에서 성분명(name_ko)을 해석하지 못하면 한글
canonical_key 로 신규 ingredients 행을 INSERT 해왔다(근본 원인 — 이 스크립트는 건드리지
않는다, 별도 PR 대상). 그 결과 성분사전에 이미 존재하는 "진짜" 영문 canonical_key 행과
같은 실물 성분을 가리키는 한글 키 중복 행이 389개 쌓였고, product_ingredients /
memories.target_ingredient_id 가 한글 키 행을 참조하는 채로 남았다. knowledge_populate.py
의 (구) 파괴적 키 정제(re.sub 로 비ASCII 문자 삭제)와 맞물려 CONTAINS 엣지 다수가 깨진
키 노드("_200" 등)에 붙는 문제로 이어졌다(별도 수정 완료, 이 스크립트와는 독립).

분류(dry-run 에서 항상 출력):
  - 단일 후보: 같은 name_ko 를 가진 영문(canonical_key ~ '^[a-z0-9_]+$') 행이 정확히
    1개 → 자동 병합 대상(--apply 로 FK 재연결)
  - 모호(복수 후보): 영문 후보가 2개 이상 → 자동 병합 금지, 리포트-온리(작업자A 수동
    판정용으로 후보별 ingredient_id/canonical_key/name_en/inci_key/intro 를 출력)
  - 후보 없음: 영문 후보가 0개 → 리포트-온리(ingredient_id/name_ko/매핑 수 출력, 작업자A
    처리 방안 결정 필요)

FK 재연결(--apply)은 반드시 product_id 단위 per-row 로 수행한다. product_ingredients 의
PK 는 (product_id, ingredient_id) 복합키라, 한 제품이 서로 다른 한글 행 2개를 참조하고
같은 영문 행으로 귀결되는 경우 집합 UPDATE(WHERE ingredient_id IN (...))는 복합 PK 위반
으로 트랜잭션 전체가 롤백된다. 이미 같은 제품이 영문 행으로도 연결되어 있으면 한글 행
매핑을 DELETE(dedup), 아니면 UPDATE 로 재연결한다. memories 는 복합 PK 가 없으므로 단순
UPDATE 로 처리한다(현재 한글 키를 참조하는 memories 행은 0건이지만, 향후 발생을 대비해
동일 패턴을 갖춰둔다).

한글 행 자체(ingredients 원본)는 이 스크립트가 삭제하지 않는다 — 작업자A 검토 후 정리
여부를 별도로 결정한다.

--apply 는 재실행 멱등이다: 첫 실행에서 이미 재연결/삭제된 product_ingredients・memories
행은 두 번째 실행에서 더 이상 kor_id 를 참조하지 않으므로 변경 대상이 0건이 된다.

--clean-graph 는 --apply 와 독립된 별도 플래그다(기본 실행에도 포함되지 않는다). 반드시
scripts/populate_graph.py 를 재실행해 CONTAINS 등을 재투영한 *이후* 마지막 단계로
실행한다 — 삭제 대상 산정 자체는 순서와 무관하게 안전하지만(RDB 에 있는 키는 절대
삭제되지 않음), 재투영이 끝난 최종 상태에서 돌려야 잔재를 빠짐없이 정리할 수 있다.
그래프 Ingredient 노드의 canonical_key 전체와 RDB ingredients.canonical_key 전체집합을
파이썬에서 차집합하여, RDB 에 없는 키의 노드만 개별 DETACH DELETE 한다. 이 스크립트가
보장하는 불변식은 "RDB 에 없는 키의 그래프 노드가 0개"이지 "한글 키 그래프 노드가 0개"가
아니다 — 후보없음(리포트-온리) 30행은 RDB 에 한글 키로 그대로 남아있으므로, 향후 memory
bridge 가 그 한글 키로 그래프 노드를 만들 수 있고 그건 정상 동작이다.

이 스크립트는 ingest/ 를 수정하지 않는다. 근본 원인(name_ko 해석 실패 시 한글 키로 신규
INSERT 하는 로직) 수정은 별도 PR 대상이다.

실행:
  dry-run(기본, 변경 없음 — 분류만 출력):
    .venv/Scripts/python.exe scripts/migrate_korean_canonical_keys.py
  FK 재연결 적용(단일 트랜잭션, 재실행 멱등):
    .venv/Scripts/python.exe scripts/migrate_korean_canonical_keys.py --apply
  그래프 잔재 정리(populate_graph.py 재실행 *이후* 마지막 단계로 별도 실행):
    .venv/Scripts/python.exe scripts/migrate_korean_canonical_keys.py --clean-graph
"""

from __future__ import annotations

import argparse
import os
from typing import Any

import psycopg
import structlog

from skinmate.graph import choke

logger = structlog.get_logger()


def _db_url() -> str:
    user = os.getenv("POSTGRES_USER", "skinmate")
    password = os.getenv("POSTGRES_PASSWORD")
    if not password:
        logger.error("POSTGRES_PASSWORD is not set")
        raise SystemExit(1)
    db_name = os.getenv("POSTGRES_DB", "skinmate")
    port = os.getenv("POSTGRES_PORT", "5432")
    host = os.getenv("POSTGRES_HOST", "localhost")  # 기본값 localhost, Docker 컨테이너 내에서는 db
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _classify(
    cur: psycopg.Cursor[Any],
) -> tuple[
    list[tuple[int, str, int, str]],
    list[tuple[int, str, list[tuple[int, str, str, str, str]]]],
    list[tuple[int, str, int]],
]:
    """한글 canonical_key 행을 단일후보(자동 병합) / 모호(리포트-온리) / 후보없음(리포트-온리)
    로 3분류한다.

    반환: (single[(kor_id, name_ko, eng_id, eng_key)],
           ambiguous[(kor_id, name_ko, candidates[(eng_id, eng_key, name_en, inci_key, intro40)])],
           no_candidate[(kor_id, name_ko, mapping_count)])
    """
    cur.execute(
        "SELECT ingredient_id, canonical_key, name_ko FROM ingredients "
        "WHERE canonical_key ~ '[가-힣]' ORDER BY ingredient_id;"
    )
    kor_rows = cur.fetchall()

    single: list[tuple[int, str, int, str]] = []
    ambiguous: list[tuple[int, str, list[tuple[int, str, str, str, str]]]] = []
    no_candidate: list[tuple[int, str, int]] = []

    for kor_id, _kor_key, name_ko in kor_rows:
        cur.execute(
            """
            SELECT ingredient_id, canonical_key, name_en, inci_key, left(coalesce(intro, ''), 40)
            FROM ingredients
            WHERE lower(name_ko) = lower(%s)
              AND canonical_key ~ '^[a-z0-9_]+$'
            ORDER BY ingredient_id;
            """,
            (name_ko,),
        )
        candidates = cur.fetchall()
        if len(candidates) == 1:
            eng_id, eng_key, _name_en, _inci_key, _intro40 = candidates[0]
            single.append((kor_id, name_ko, eng_id, eng_key))
        elif len(candidates) > 1:
            ambiguous.append((kor_id, name_ko, candidates))
        else:
            cur.execute(
                "SELECT count(*) FROM product_ingredients WHERE ingredient_id = %s;",
                (kor_id,),
            )
            count_row = cur.fetchone()
            mapping_count = count_row[0] if count_row is not None else 0
            no_candidate.append((kor_id, name_ko, mapping_count))

    return single, ambiguous, no_candidate


def _report(
    single: list[tuple[int, str, int, str]],
    ambiguous: list[tuple[int, str, list[tuple[int, str, str, str, str]]]],
    no_candidate: list[tuple[int, str, int]],
) -> None:
    logger.info(
        "classification_summary",
        total_korean_rows=len(single) + len(ambiguous) + len(no_candidate),
        single_candidate=len(single),
        ambiguous=len(ambiguous),
        no_candidate=len(no_candidate),
    )
    for kor_id, name_ko, eng_id, eng_key in single:
        logger.info(
            "auto_merge_planned",
            kor_id=kor_id,
            name_ko=name_ko,
            eng_id=eng_id,
            eng_key=eng_key,
        )
    for kor_id, name_ko, candidates in ambiguous:
        logger.warning(
            "ambiguous_manual_review_required",
            kor_id=kor_id,
            name_ko=name_ko,
            candidate_count=len(candidates),
        )
        for eng_id, eng_key, name_en, inci_key, intro40 in candidates:
            logger.warning(
                "ambiguous_candidate",
                kor_id=kor_id,
                ingredient_id=eng_id,
                canonical_key=eng_key,
                name_en=name_en,
                inci_key=inci_key,
                intro=intro40,
            )
    for kor_id, name_ko, mapping_count in no_candidate:
        logger.warning(
            "no_candidate_manual_review_required",
            kor_id=kor_id,
            name_ko=name_ko,
            mapping_count=mapping_count,
        )


def _repoint_product_ingredients(
    cur: psycopg.Cursor[Any], kor_id: int, eng_id: int
) -> tuple[int, int]:
    """kor_id 를 참조하는 product_ingredients 행을 eng_id 로 product_id 단위 per-row 재연결.

    집합 UPDATE 대신 product_id 단위로 순회한다 — 한 제품이 서로 다른 한글 행을 복수
    참조하고 같은 영문 행으로 귀결되면 집합 UPDATE 는 복합 PK((product_id, ingredient_id))
    위반으로 트랜잭션 전체가 롤백되기 때문이다.

    반환: (repointed, deduped) 카운트.
    """
    cur.execute("SELECT product_id FROM product_ingredients WHERE ingredient_id = %s;", (kor_id,))
    product_ids = [row[0] for row in cur.fetchall()]

    repointed = 0
    deduped = 0
    for product_id in product_ids:
        cur.execute(
            "SELECT 1 FROM product_ingredients WHERE product_id = %s AND ingredient_id = %s;",
            (product_id, eng_id),
        )
        if cur.fetchone():
            # 이미 영문 행으로도 연결되어 있으면(둘 다 있던 경우) 한글 행 매핑만 제거
            cur.execute(
                "DELETE FROM product_ingredients WHERE product_id = %s AND ingredient_id = %s;",
                (product_id, kor_id),
            )
            deduped += 1
        else:
            cur.execute(
                "UPDATE product_ingredients SET ingredient_id = %s "
                "WHERE product_id = %s AND ingredient_id = %s;",
                (eng_id, product_id, kor_id),
            )
            repointed += 1
    return repointed, deduped


def _repoint_memories(cur: psycopg.Cursor[Any], kor_id: int, eng_id: int) -> int:
    """kor_id 를 참조하는 memories.target_ingredient_id 를 eng_id 로 재연결.

    memories 는 (product_ingredients 와 달리) 복합 PK 가 없어 충돌 위험이 없으므로
    단순 집합 UPDATE 를 쓴다. 현재 한글 키를 참조하는 memories 행은 0건이지만, 향후
    발생을 대비해 코드를 갖춰둔다.
    """
    cur.execute(
        "UPDATE memories SET target_ingredient_id = %s WHERE target_ingredient_id = %s;",
        (eng_id, kor_id),
    )
    return cur.rowcount


def _apply(conn: psycopg.Connection[Any], single: list[tuple[int, str, int, str]]) -> None:
    """단일 후보(자동 병합 대상) 행만 FK 재연결한다. 모호/후보없음 행은 절대 건드리지 않는다."""
    total_repointed = 0
    total_deduped = 0
    total_memories = 0
    with conn.cursor() as cur:
        for kor_id, _name_ko, eng_id, _eng_key in single:
            repointed, deduped = _repoint_product_ingredients(cur, kor_id, eng_id)
            mem_updated = _repoint_memories(cur, kor_id, eng_id)
            total_repointed += repointed
            total_deduped += deduped
            total_memories += mem_updated
    conn.commit()
    logger.info(
        "apply_completed",
        rows_processed=len(single),
        product_ingredients_repointed=total_repointed,
        product_ingredients_deduped=total_deduped,
        memories_repointed=total_memories,
    )
    logger.info(
        "next_step_required",
        message=(
            "scripts/populate_graph.py 를 재실행해 CONTAINS 등을 재투영한 뒤, "
            "--clean-graph 로 그래프 잔재 노드를 정리하세요."
        ),
    )


def _clean_graph(conn: psycopg.Connection[Any]) -> None:
    """그래프 Ingredient 노드 중 RDB ingredients.canonical_key 집합에 없는 키의 노드를
    개별 DETACH DELETE 한다.

    populate_graph.py 재투영 *이후* 마지막 단계로 실행한다 — 삭제 대상 산정은 순서와
    무관하게 안전하지만(RDB 에 있는 키는 절대 삭제되지 않음), 재투영이 끝난 최종
    상태에서 돌려야 잔재를 빠짐없이 정리할 수 있다. 보장하는 불변식은 "RDB 에 없는
    키의 노드가 0개"이지 "한글 키 노드가 0개"가 아니다(독스트링 상단 참고).
    """
    with conn.cursor() as cur:
        cur.execute("SELECT canonical_key FROM ingredients;")
        rdb_keys = {row[0] for row in cur.fetchall()}

    # 스칼라 반환은 age_exec 의 JSON 디코드 경로에 따라 형태가 흔들릴 수 있어,
    # 코드베이스 관례대로 map 형태로 감싸 dict 키 접근으로 고정한다.
    graph_rows = choke.age_exec(conn, None, "MATCH (i:Ingredient) RETURN {key: i.canonical_key}")
    graph_keys = {str(row["key"]) for row in graph_rows if isinstance(row, dict) and "key" in row}

    stale_keys = graph_keys - rdb_keys
    logger.info(
        "clean_graph_diff",
        graph_keys=len(graph_keys),
        rdb_keys=len(rdb_keys),
        stale_keys=len(stale_keys),
    )
    if not stale_keys:
        logger.info("clean_graph_nothing_to_delete")
        return

    for key in sorted(stale_keys):
        choke.age_exec(
            conn,
            None,
            "MATCH (i:Ingredient {canonical_key: $key}) DETACH DELETE i",
            {"key": key},
        )
        logger.info("stale_ingredient_node_deleted", canonical_key=key)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.traverse_cache;")
    conn.commit()
    logger.info("clean_graph_completed", deleted=len(stale_keys))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="한글 canonical_key 성분 행 → 영문 행 FK 재연결 1회성 마이그레이션"
    )
    parser.add_argument(
        "--apply", action="store_true", help="분류 후 단일 후보 행만 FK 재연결(기본은 dry-run)"
    )
    parser.add_argument(
        "--clean-graph",
        action="store_true",
        help="그래프 잔재 Ingredient 노드 정리. --apply 와 독립 — populate_graph.py 재실행 "
        "이후 마지막 단계로 별도 실행할 것",
    )
    args = parser.parse_args()

    db_url = _db_url()
    logger.info("migration_started", apply=args.apply, clean_graph=args.clean_graph)

    with psycopg.connect(db_url) as conn:
        if args.clean_graph:
            _clean_graph(conn)
            return

        with conn.cursor() as cur:
            single, ambiguous, no_candidate = _classify(cur)
        _report(single, ambiguous, no_candidate)

        if not args.apply:
            logger.info("dry_run_complete_rerun_with_apply_to_migrate")
            return

        _apply(conn, single)


if __name__ == "__main__":
    main()
