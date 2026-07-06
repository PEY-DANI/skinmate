#!/usr/bin/env bash
# DB 스모크 테스트: age·vector 확장이 실제 동작하는지 확인 (로컬·CI 공용)
# 사용 전제: docker compose up -d 로 db 컨테이너가 healthy 상태
set -euo pipefail

PSQL=(docker compose exec -T db psql -U "${POSTGRES_USER:-skinmate}" -d "${POSTGRES_DB:-skinmate}" -v ON_ERROR_STOP=1 -tA)

echo "[1/3] extensions installed"
exts=$("${PSQL[@]}" -c "SELECT count(*) FROM pg_extension WHERE extname IN ('age','vector');")
if [ "$exts" != "2" ]; then
  echo "ERROR: expected 2 extensions (age, vector), found $exts"
  exit 1
fi

echo "[2/3] pgvector distance op"
"${PSQL[@]}" -c "SELECT '[1,2,3]'::vector <-> '[4,5,6]'::vector;" >/dev/null

echo "[3/3] AGE cypher round-trip"
"${PSQL[@]}" -c "SELECT create_graph('ci_smoke');" >/dev/null
"${PSQL[@]}" -c "SELECT * FROM cypher('ci_smoke', \$\$ CREATE (n:SmokeTest {ok: true}) RETURN n \$\$) AS (n agtype);" >/dev/null
"${PSQL[@]}" -c "SELECT drop_graph('ci_smoke', true);" >/dev/null

echo "OK: age + vector smoke test passed"
