"""pytest 전역 설정 및 비파괴적 테스트 데이터 청소 피스처."""

from __future__ import annotations

import os

from dotenv import load_dotenv
import psycopg
import pytest

# pytest 구동 시 로컬 .env 로드
load_dotenv()

# 개발 DB 오염 방지를 위한 테스트 DB 안전 격리막:
# 테스트 세션 중에는 DATABASE_URL을 무조건 'skinmate_test' 데이터베이스로 강제 변환합니다.
_db_url = os.getenv("DATABASE_URL", "postgresql://skinmate:skinmate-dev-only@localhost:5432/skinmate")
if "skinmate_test" not in _db_url:
    if "@" in _db_url:
        _prefix, _host_part = _db_url.split("@", 1)
        if "/" in _host_part:
            _host_info, _db_name = _host_part.split("/", 1)
            if "?" in _db_name:
                _db_name, _query_params = _db_name.split("?", 1)
                _db_url = f"{_prefix}@{_host_info}/skinmate_test?{_query_params}"
            else:
                _db_url = f"{_prefix}@{_host_info}/skinmate_test"
        else:
            _db_url = f"{_prefix}@{_host_part}/skinmate_test"
    os.environ["DATABASE_URL"] = _db_url



@pytest.fixture(scope="function", autouse=True)
def clean_db_fixtures():
    """테스트용 RDB 데이터 및 User 노드들을 비파괴적으로 청소합니다."""
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql://skinmate:skinmate-dev-only@localhost:5432/skinmate",
    )

    def _clean():
        try:
            with psycopg.connect(db_url) as conn, conn.cursor() as cur:
                # 1. RDB 테스트용 유저 memories 데이터 물리 삭제
                cur.execute("DELETE FROM memories WHERE user_id >= 990000 AND user_id <= 999999;")
                cur.execute(
                    "DELETE FROM memory_audit WHERE user_id >= 990000 AND user_id <= 999999;"
                )

                # 2. RDB 테스트용 junction 및 제품 데이터 물리 삭제
                cur.execute("""
                    DELETE FROM product_ingredients 
                    WHERE product_id IN (
                        SELECT product_id FROM products WHERE name LIKE '테스트 %'
                    );
                    """)
                cur.execute("DELETE FROM products WHERE name LIKE '테스트 %';")

                # 3. RDB 테스트용 성분 데이터 물리 삭제
                cur.execute("DELETE FROM ingredients WHERE canonical_key LIKE 'test_%';")

                # 4. RDB 테스트용 문서 데이터 물리 삭제
                cur.execute("DELETE FROM documents WHERE source_meta->>'url' = 'test_source';")

                # 5. 그래프 내의 테스트용 User 노드들 청소 (비파괴적)
                cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'skinmate';")
                if cur.fetchone():
                    cur.execute("SET search_path = ag_catalog, public;")
                    cur.execute(
                        "SELECT * FROM cypher('skinmate', $$"
                        "MATCH (u:User) "
                        "WHERE u.user_id >= 990000 AND u.user_id <= 999999 "
                        "DETACH DELETE u"
                        "$$) AS (result agtype);"
                    )
                conn.commit()
        except psycopg.OperationalError:
            pass
        except Exception:
            pass

    # 테스트 시작 전 클리닝
    _clean()
    yield
    # 테스트 종료 후 클리닝
    _clean()
