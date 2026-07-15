"""scripts/migrate_korean_canonical_keys.py 단위 테스트(한글 canonical_key FK 재연결)."""

from __future__ import annotations

import psycopg
import pytest
from scripts.migrate_korean_canonical_keys import _repoint_product_ingredients


def test_repoint_product_ingredients_per_row_avoids_pk_conflict(
    db_conn: psycopg.Connection,
) -> None:
    """한 제품이 서로 다른 한글 canonical_key 행 2개를 참조하고, 둘 다 같은 영문 행으로
    귀결되는 시나리오를 검증한다.

    이런 경우 집합 UPDATE(WHERE ingredient_id IN (kor_a, kor_b))를 한 번에 실행하면,
    첫 행이 먼저 eng_id 로 갱신된 뒤 두 번째 행도 같은 (product_id, eng_id) 로 갱신을
    시도하면서 복합 PK((product_id, ingredient_id)) 위반이 발생한다 — 실제로 재현해
    확인한다(SAVEPOINT 로 감싸 본 트랜잭션에는 영향이 없도록 한다).

    반면 _repoint_product_ingredients 를 product_id 단위 per-row 로 호출하면, 두 번째
    행 처리 시 이미 eng_id 로 연결되어 있음을 먼저 확인하고 dedup(DELETE)하므로 충돌이
    발생하지 않는다.
    """
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingredients (canonical_key, name_ko)
            VALUES ('test_dedup_eng', '테스트중복성분')
            RETURNING ingredient_id;
            """
        )
        eng_row = cur.fetchone()
        assert eng_row is not None
        eng_id = eng_row[0]

        cur.execute(
            """
            INSERT INTO ingredients (canonical_key, name_ko)
            VALUES ('테스트중복성분한글A', '테스트중복성분'),
                   ('테스트중복성분한글B', '테스트중복성분')
            RETURNING ingredient_id;
            """
        )
        kor_a_id, kor_b_id = (row[0] for row in cur.fetchall())

        cur.execute(
            """
            INSERT INTO products (name, brand, description)
            VALUES ('테스트 중복상품', '테스트브랜드', '')
            RETURNING product_id;
            """
        )
        product_row = cur.fetchone()
        assert product_row is not None
        product_id = product_row[0]

        cur.execute(
            """
            INSERT INTO product_ingredients (product_id, ingredient_id)
            VALUES (%s, %s), (%s, %s);
            """,
            (product_id, kor_a_id, product_id, kor_b_id),
        )

        # 회귀 재현: 집합 UPDATE 는 복합 PK 위반으로 실패해야 한다(SAVEPOINT 로 격리).
        cur.execute("SAVEPOINT batch_update_attempt;")
        with pytest.raises(psycopg.errors.UniqueViolation):
            cur.execute(
                """
                UPDATE product_ingredients SET ingredient_id = %s
                WHERE product_id = %s AND ingredient_id IN (%s, %s);
                """,
                (eng_id, product_id, kor_a_id, kor_b_id),
            )
        cur.execute("ROLLBACK TO SAVEPOINT batch_update_attempt;")

        # per-row 처리: kor_a → eng(UPDATE), kor_b → eng(이미 존재 → dedup DELETE)
        repointed_a, deduped_a = _repoint_product_ingredients(cur, kor_a_id, eng_id)
        assert (repointed_a, deduped_a) == (1, 0)

        repointed_b, deduped_b = _repoint_product_ingredients(cur, kor_b_id, eng_id)
        assert (repointed_b, deduped_b) == (0, 1)

        cur.execute(
            "SELECT ingredient_id FROM product_ingredients WHERE product_id = %s;",
            (product_id,),
        )
        remaining = [row[0] for row in cur.fetchall()]
        assert remaining == [eng_id]
