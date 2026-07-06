# WBS: 화장품 추천 시스템 2인 작업 분배

**기준 문서**: [deep-interview-cosmetics-recommendation-memory-graph.md](deep-interview-cosmetics-recommendation-memory-graph.md), [cosmetics-recommendation-consensus-plan.md](cosmetics-recommendation-consensus-plan.md)

**역할 분담**
- **작업자 A — 데이터 플레인**: DB · 데이터 수집(Ingest) · 검색(Retrieval)
- **작업자 B — LLM 플레인**: 기억(Memory) · 대화(Chat) · 평가(Eval)

**규칙**: ★ 표시 산출물은 두 사람의 코드가 동시에 의존하는 것 — 완료·변경 시 반드시 상대방과 합의한다. 나머지는 각자 자유 진행.

---

## Phase 0 — 공동 착수 (약 1주)

| 완료 | ID | 할 일 | 주도 | 완료 조건 |
|:---:|---|---|---|---|
| [ ] | 0.1 | 레포 뼈대 + docker-compose(Postgres+AGE+pgvector) + CI | A | 둘 다 로컬에서 DB 뜨는 것 확인 |
| [ ] | 0.2 | **DB 설계도(schema.sql) 확정** ★ | A (memories는 B 작성) | 양쪽 승인 리뷰 |
| [ ] | 0.3 | **임베딩 모델·차원(D, Dm) 벤치마크 후 확정** ★ | 공동 | 모델명+차원을 설계도에 기록 (되돌리기 어려움) |
| [ ] | 0.4 | **coos.kr 법적 게이트**(robots/약관 확인) ★ | A | 허용→진행 / 불허→공개 소스(CosIng·OBF·식약처)로 교체 결정 |
| [ ] | 0.5 | **인터페이스 계약 3종 문서화** ★ | 공동 | 계약 문서 + 가짜 데이터(fixture) 생성 |
| [ ] | 0.6 | LLM 프로바이더 확정(기본 Claude API) | B | 추상화 인터페이스 초안 |

**계약 3종 (0.5)**
1. **ContextBundle** (A→B): `retrieve(user_id, query) → { documents, graph_paths, memories }` — 검색 결과의 모양
2. **MemoryWriteJob** (B→큐): 턴 종료 시 기억 저장 요청 스키마(user_id, turn_id=중복방지 키, 대화 버퍼) + `pending_writes_drained(user_id)` 함수
3. **그래프 검문소** (A 제공, B 소비): 사용자 서브그래프 접근은 `query_user_graph(user_id, ...)` 단일 함수만 허용 — 직접 Cypher 접근 금지 (코드 리뷰로 상호 감시)

---

## Phase 1 — 병렬 개발

### 작업자 A (데이터 플레인)

| 완료 | ID | 할 일 | 선행 | 비고 |
|:---:|---|---|---|---|
| [ ] | A1.1 | 마이그레이션 적용 + 코어 그래프 온톨로지(노드/엣지 라벨) | 0.2 | |
| [ ] | A1.2 | 그래프 검문소 함수(user_scope 강제 주입) | A1.1 | 계약 3의 실물 |
| [ ] | A2.1 | coos.kr 크롤러(rate-limit, 캐시, 출처·수집일시 기록) | 0.4 | |
| [ ] | A2.2 | 성분명 정규화·중복 제거(INCI canonical key + 한글 별칭) | A2.1 | |
| [ ] | A2.3 | 문서 임베딩 생성 → pgvector 적재 | 0.3, A2.2 | |
| [ ] | A2.4 | AGE 그래프 엣지 구축(Product-CONTAINS→Ingredient 등) | A2.2 | 관계형 테이블이 원본(진실원), 그래프는 파생 |
| [ ] | A2.5 | (선택) CosIng INCI 보강 / Open Beauty Facts 제품 적재 | A2.2 | |
| [ ] | A3.1 | 벡터 유사도 검색(vector_search) | A2.3 | |
| [ ] | A3.2 | 그래프 다단계 순회 2~3 hop(graph_traverse) | A1.2, A2.4 | |
| [ ] | A3.3 | 컨텍스트 통합기(context_assembler) — 문서+그래프+기억 묶음 | A3.1, A3.2 | 계약 1의 실물. 기억 순위는 B2.5 함수 호출 |
| [ ] | A3.4 | **속도 벤치마크: 목표 규모에서 p95<300ms** ★ | A3.2 | 미달 시 폴백(materialized-adjacency SQL) 전환을 공동 결정 |
| [ ] | A3.5 | (조건부) materialized-adjacency 폴백 구현 | A3.4 | A3.4 미달 시에만 |
| [ ] | A4.1 | 자료 테스트: AC-D1~D3(적재·조회·출처메타), AC-G1~G2(순회·다단계 추론) | A3.3 | |

### 작업자 B (LLM 플레인)

| 완료 | ID | 할 일 | 선행 | 비고 |
|:---:|---|---|---|---|
| [ ] | B1.1 | LLM 프로바이더 추상화 구현 | 0.6 | |
| [ ] | B2.1 | **memories 테이블 + RLS(사용자 격리) + soft-delete** ★ | 0.2 | A의 마이그레이션에 포함 — 완료 시 A 리뷰 |
| [ ] | B2.2 | 작업 큐(사용자별 순서 보장, idempotency-key, 재시도·dead-letter) | B2.1 | 계약 2의 실물 |
| [ ] | B2.3 | fact 추출기(대화→중요 사실, 일상 정보 필터) | B1.1 | |
| [ ] | B2.4 | CRUD 판정기(add/update/delete/no-op) | B2.3 | delete는 soft-delete + 감사로그 |
| [ ] | B2.5 | 가중치 계산 + 기억 순위 함수(effective_weight = weight × exp(-λ·Δdays), λ=0.02) | B2.1 | A의 통합기(A3.3)가 호출 |
| [ ] | B2.6 | pending_writes_drained(user_id) — 밀린 기억 쓰기 완료 확인 | B2.2 | A의 검색 전에 호출됨 |
| [ ] | B3.1 | 다중 턴 퍼널 상태 관리(조언→좁히기→제품 추천) | B1.1 | 가짜 검색 결과(fixture)로 개발 |
| [ ] | B3.2 | 추천 생성기(컨텍스트+LLM→추천+근거) | B3.1 | 〃 |
| [ ] | B3.3 | **그래프 스키마 확장 승인 플로우(LLM 신규 관계 제안, AC-G3)** ★ | B3.2 | 스키마 변경 기능 — 설계를 A와 합의 |
| [ ] | B4.1 | 기억 시나리오 테스트(AC-M1~M6) | B2.4 | 개발과 병행 권장 (뒤로 몰리지 않게) |
| [ ] | B4.2 | 중요도 분류 평가셋 ~50개 + precision≥0.9 / recall≥0.8 측정 | B2.3 | |
| [ ] | B4.3 | LLM-as-judge 루브릭(정확성·안전성·근거성·톤) + 100개 시나리오 | B3.2 | 평균 ≥ 4.0 목표 |

---

## Phase 2~4 — 통합 (전부 공동 작업)

| 완료 | ID | 할 일 | 선행 | 합의 내용 |
|:---:|---|---|---|---|
| [ ] | I1 ★ | B의 fixture를 A의 진짜 검색으로 교체 | A3.3 + B3.2 | 계약 1 실제 맞물림 확인, 기억 반영도(AC-R4) 첫 확인 |
| [ ] | I2 ★ | 검색 전 pending-drain 연동 | A3.3 + B2.6 | 방금 말한 내용이 다음 턴에 반영되는지 |
| [ ] | I3 ★ | **사용자 격리 테스트: 사용자 A로 사용자 B의 기억/그래프 조회 시 0건** | A1.2 + B2.1 | 보안 핵심(AC-M5) — 둘의 코드가 함께 지켜야 통과 |
| [ ] | I4 ★ | 전체 대화 E2E: N턴 안에 구체 제품+근거 도달(AC-R5) | I1, I2 | |
| [ ] | I5 ★ | 최종 채점: LLM 심사 ≥4.0(AC-R1), 회피 성분 0건(AC-R2), 근거 정합(AC-R3), 전 AC 체크 | I4 | 서로의 영역 교차 리뷰 |

---

## 합의 지점 요약

**시작할 때 (5회)** — 0.2 설계도 · 0.3 임베딩 모델 · 0.4 법적 게이트 · 0.5 계약 3종 · 0.6 프로바이더. 여기서 정한 것은 이후 변경 시 반드시 상대 승인.

**중간에 (3회)** — A3.4 벤치마크 결과(폴백 여부) · B2.1 memories 스키마(A의 DB에 포함) · B3.3 그래프 확장 설계(A의 검문소 경유).

**합칠 때 (5회)** — I1~I5 전부 페어로 진행.

**브랜치 전략**: main + 도메인별 feature 브랜치. 계약 파일(스키마·인터페이스 타입) 변경은 상대방 리뷰 필수, 나머지 자유. 계약별 contract test(스텁과 실물이 같은 스키마를 만족하는지)를 CI에 걸어두면 통합이 가벼워진다.
