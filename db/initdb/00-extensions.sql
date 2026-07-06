-- 최초 기동 시 1회 실행 (docker-entrypoint-initdb.d).
-- 이후 스키마/그래프 온톨로지는 /db/migrations에서 관리한다 (WBS A1.1).
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;

-- AGE 사용 세션 편의를 위한 search_path 기본값
ALTER DATABASE skinmate SET search_path = ag_catalog, "$user", public;
