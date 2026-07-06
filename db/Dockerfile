# Apache AGE 공식 이미지(PostgreSQL 16 + AGE 1.5.0) 위에 pgvector를 추가한다.
# 버전 고정: AGE+pgvector 동시 운용 호환성 리스크 완화 (consensus-plan Risks 참조)
FROM apache/age:release_PG16_1.5.0

# pgvector는 PGDG apt 저장소의 프리빌드 패키지로 설치 (postgres 공식 이미지에 PGDG repo 포함)
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
