"""그래프 전역 지식 적재 단위 테스트 (WBS 1A.4).

db_conn 은 conftest.py 의 superuser(RLS 우회) 피스처를 그대로 재사용한다 — 로컬에서
app-role 접속으로 재정의하면 populate_global_knowledge 의 memories 조회(섹션 7)가
RLS 에 막혀 조용히 0행을 보게 되므로(HAS_CONCERN/AVOIDS/PREFERS 검증이 거짓 통과)
반드시 superuser 접속을 써야 한다(tests/graph/test_traverse.py 와 동일한 패턴).
"""

from __future__ import annotations

from typing import Any

import psycopg

from skinmate import db
from skinmate.graph import choke
from skinmate.graph.knowledge_populate import populate_global_knowledge


def _bootstrap_graph_schema(cur: psycopg.Cursor[Any]) -> None:
    """멱등적 그래프 및 라벨 생성(비파괴적 셋업) — 여러 테스트가 공유하는 셋업 로직."""
    cur.execute("SET LOCAL search_path = ag_catalog, public;")
    cur.execute("""
    DO $$
    DECLARE
        g name := 'skinmate';
        gid oid;
        lbl text;
        vlabels text[] := ARRAY['User','Ingredient','Product','Concern','Brand'];
        elabels text[] := ARRAY['CONTAINS','TREATS','AGGRAVATES','HELPS',
                                 'CONFLICTS','HAS_CONCERN','AVOIDS','PREFERS'];
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM ag_catalog.ag_graph WHERE name = g) THEN
            PERFORM ag_catalog.create_graph(g);
        END IF;
        SELECT graphid INTO gid FROM ag_catalog.ag_graph WHERE name = g;
        FOREACH lbl IN ARRAY vlabels LOOP
            IF NOT EXISTS (
                SELECT 1 FROM ag_catalog.ag_label
                WHERE name = lbl AND graph = gid
            ) THEN
                PERFORM ag_catalog.create_vlabel(g, lbl);
            END IF;
        END LOOP;
        FOREACH lbl IN ARRAY elabels LOOP
            IF NOT EXISTS (
                SELECT 1 FROM ag_catalog.ag_label
                WHERE name = lbl AND graph = gid
            ) THEN
                PERFORM ag_catalog.create_elabel(g, lbl);
            END IF;
        END LOOP;
    END $$;
    """)


def test_populate_global_knowledge_integration(db_conn: psycopg.Connection) -> None:
    """RDB 데이터와 성분 소개문 분석을 통한 전역 지식 엣지 생성 로직을 검증합니다."""
    with db_conn.cursor() as cur:
        # 1. 멱등적 그래프 및 라벨 생성 (비파괴적 셋업)
        _bootstrap_graph_schema(cur)

        # 2. 테스트용 RDB 데이터 삽입
        cur.execute("SET LOCAL search_path = public;")
        cur.execute("""
            INSERT INTO ingredients (canonical_key, name_ko, intro)
            VALUES 
            (
                'test_hyaluronic_acid', 
                '테스트히알루론산', 
                '피부에 강력한 수분을 공급하여 건조함을 예방하고 보습력을 올립니다.'
            ),
            (
                'test_ethanol', 
                '테스트에탄올', 
                '피부에 일시적인 청량감을 주나, 지속 사용 시 자극 유발 및 붉어짐 '
                '문제가 발생할 수 있어 민감한 피부는 주의할 것.'
            ),
            ('retinol', '레티놀', '주름을 개선함.'),
            ('alcohol', '에탄올', '에탄올 용제.')
            ON CONFLICT (canonical_key) DO UPDATE 
            SET name_ko = EXCLUDED.name_ko, intro = EXCLUDED.intro
            RETURNING canonical_key, ingredient_id;
            """)
        ing_map = {row[0]: row[1] for row in cur.fetchall()}
        hyaluronic_id = ing_map["test_hyaluronic_acid"]
        ing_map["test_ethanol"]

        cur.execute("""
            INSERT INTO products (name, brand, description)
            VALUES ('테스트 에멀전', '테스트브랜드', '수분 에멀전')
            RETURNING product_id;
            """)
        emulsion_id = cur.fetchone()[0]

        cur.execute(f"""
            INSERT INTO product_ingredients (product_id, ingredient_id) VALUES
            ({emulsion_id}, {hyaluronic_id});
            """)

    # 3. 전역 지식 적재 스크립트 실행
    populate_global_knowledge(db_conn)

    # 4. Apache AGE 그래프 노드 및 엣지 MERGE 상태 조회 검증 (user_scope=None으로 전역 조회)
    # DatatypeMismatch 방지를 위해 복수 컬럼 대신 Map형태 {key: value}로 리턴합니다.

    # 가. Concern 노드 개수 검증
    concerns = choke.age_exec(
        db_conn,
        None,
        "MATCH (c:Concern) RETURN {name: c.name, label: c.label}",
    )
    concern_names = {c["name"] for c in concerns}
    assert "dryness" in concern_names
    assert "sensitivity" in concern_names
    assert "pores" in concern_names

    # 나. Ingredient 노드 검증
    ingredients_graph = choke.age_exec(
        db_conn,
        None,
        "MATCH (i:Ingredient {canonical_key: 'test_hyaluronic_acid'}) RETURN {name: i.name}",
    )
    assert len(ingredients_graph) >= 1
    assert ingredients_graph[0]["name"] == "테스트히알루론산"

    # 다. Product 노드 검증
    products_graph = choke.age_exec(
        db_conn,
        None,
        f"MATCH (p:Product {{product_id: {emulsion_id}}}) RETURN {{name: p.name, brand: p.brand}}",
    )
    assert len(products_graph) >= 1
    assert products_graph[0]["name"] == "테스트 에멀전"
    assert products_graph[0]["brand"] == "테스트브랜드"

    # 라. CONTAINS 엣지 검증
    contains_edges = choke.age_exec(
        db_conn,
        None,
        f"MATCH (p:Product {{product_id: {emulsion_id}}})-[r:CONTAINS]->(i:Ingredient) "
        "RETURN {key: i.canonical_key}",
    )
    assert len(contains_edges) >= 1
    assert contains_edges[0]["key"] == "test_hyaluronic_acid"

    # 마. TREATS 엣지 검증 (보습 키워드로 인해 dryness와 매칭)
    treats_edges = choke.age_exec(
        db_conn,
        None,
        "MATCH (i:Ingredient {canonical_key: 'test_hyaluronic_acid'})-[r:TREATS]->(c:Concern) "
        "RETURN {name: c.name}",
    )
    assert len(treats_edges) >= 1
    assert treats_edges[0]["name"] == "dryness"

    # 바. AGGRAVATES 엣지 검증 (자극 유발 키워드로 인해 sensitivity와 매칭)
    aggravates_edges = choke.age_exec(
        db_conn,
        None,
        "MATCH (i:Ingredient {canonical_key: 'test_ethanol'})-[r:AGGRAVATES]->(c:Concern) "
        "RETURN {name: c.name}",
    )
    assert len(aggravates_edges) >= 1
    assert aggravates_edges[0]["name"] == "sensitivity"

    # 사. HELPS / CONFLICTS 엣지 검증 (retinol CONFLICTS alcohol 관계 검증)
    conflict_edges = choke.age_exec(
        db_conn,
        None,
        "MATCH (i1:Ingredient {canonical_key: 'retinol'})-[r:CONFLICTS]->(i2:Ingredient) "
        "RETURN {key: i2.canonical_key}",
    )
    assert len(conflict_edges) >= 1
    assert conflict_edges[0]["key"] == "alcohol"


def test_populate_skips_invalid_canonical_keys_without_destructive_cleaning(
    db_conn: psycopg.Connection,
) -> None:
    """한글 등 비ASCII canonical_key 행은 (구 동작인 re.sub 문자 삭제 정제 없이) 그대로
    skip 되어야 하며, 파괴적 정제가 만들어내던 깨진 키("_" 등)로도 노드가 생기면 안 된다."""
    kor_key = "테스트한글깨진키_87654321"
    with db_conn.cursor() as cur:
        _bootstrap_graph_schema(cur)

        cur.execute("SET LOCAL search_path = public;")
        cur.execute(
            """
            INSERT INTO ingredients (canonical_key, name_ko, intro)
            VALUES (%s, '테스트한글깨진키성분', '피부에 보습을 공급합니다.')
            ON CONFLICT (canonical_key) DO UPDATE
            SET name_ko = EXCLUDED.name_ko, intro = EXCLUDED.intro;
            """,
            (kor_key,),
        )

    populate_global_knowledge(db_conn)

    # 원본 한글 키로는 노드가 생성되지 않아야 한다(skip).
    nodes = choke.age_exec(
        db_conn,
        None,
        "MATCH (i:Ingredient {canonical_key: $key}) RETURN {key: i.canonical_key}",
        {"key": kor_key},
    )
    assert nodes == []

    # 구 동작(re.sub(r"[^a-z0-9_]+", "", key.lower()))이었다면 이 값으로 깨진 노드가
    # 생겼을 것이다 — 파괴적 정제가 제거되었으므로 이 키로도 노드가 없어야 한다.
    broken_key = "_87654321"
    broken_nodes = choke.age_exec(
        db_conn,
        None,
        "MATCH (i:Ingredient {canonical_key: $key}) RETURN {key: i.canonical_key}",
        {"key": broken_key},
    )
    assert broken_nodes == []


def test_populate_has_concern_resolves_english_key_and_korean_label(
    db_conn: psycopg.Connection,
) -> None:
    """HAS_CONCERN 의 target_name 이 CONCERN_RULES 영문 키('dryness') 그대로 저장되어
    있든, 한글 라벨('건조')로 저장되어 있든 동일한 Concern 노드로 해석되어야 한다
    (tests/graph/test_traverse.py 는 영문 'dryness', tests/app/test_turn.py 는 한글
    '건조' 를 쓰므로 두 형태 모두 지원해야 함)."""
    uid_en = 990201
    uid_ko = 990202
    with db_conn.cursor() as cur:
        _bootstrap_graph_schema(cur)

    with db.user_scope(db_conn, uid_en), db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memories (user_id, content, fact_type, target_name, season)
            VALUES (%s, '가을철 건조(영문 키 형태)', 'has_concern', 'dryness', '가을');
            """,
            (uid_en,),
        )

    with db.user_scope(db_conn, uid_ko), db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO memories (user_id, content, fact_type, target_name, season)
            VALUES (%s, '가을철 건조(한글 라벨 형태)', 'has_concern', '건조', '가을');
            """,
            (uid_ko,),
        )

    populate_global_knowledge(db_conn)

    for uid in (uid_en, uid_ko):
        edges = choke.age_exec(
            db_conn,
            None,
            "MATCH (u:User {user_id: $uid})-[:HAS_CONCERN]->(c:Concern) RETURN c.name",
            {"uid": uid},
        )
        assert edges == ["dryness"], f"user {uid} 의 HAS_CONCERN 해석 결과: {edges}"
