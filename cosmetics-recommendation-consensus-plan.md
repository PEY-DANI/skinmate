# Consensus Plan: 기억·문서·관계그래프 기반 화장품 추천 대화 시스템

**Status:** ✅ PENDING APPROVAL (consensus reached: Architect APPROVE-WITH-IMPROVEMENTS → Critic APPROVE-WITH-IMPROVEMENTS, all findings applied)
**Source spec:** `.omc/specs/deep-interview-cosmetics-recommendation-memory-graph.md` (ambiguity 15%, PASSED)
**Mode:** `--consensus --direct` (short RALPLAN-DR)

---

## Requirements Summary
다중 사용자 대상, 개인 기억·관계그래프 격리형 대화 화장품 추천 시스템. PostgreSQL 단일 인스턴스에 pgvector(임베딩)와 Apache AGE(그래프) 확장을 얹고, 세 컨텍스트 소스(전역 공유 문서 RAG / 사용자별 기억 / 사용자별 관계그래프)를 결합해 다중 턴 대화 퍼널로 성분·조언에서 구체 제품+근거까지 추천한다. 기억은 응답 직후 비동기 배치로 LLM이 add/update/delete/no-op 관리하고 `effective_weight = weight × exp(-λ·Δdays)`(λ=0.02)로 우선순위화한다. 다단계 그래프 순회가 추천의 핵심 추론.

## RALPLAN-DR Summary (Short)

### Principles
1. **단일 저장소 진실원(Single source of truth)**: 문서·기억·그래프를 하나의 Postgres에 두어 조인·트랜잭션 일관성을 확보한다.
2. **응답 지연 최소화**: 사용자 대면 경로는 읽기 전용 검색만 동기 수행하고, 모든 쓰기(기억 CRUD)는 비동기로 격리한다.
3. **근거 추적성(Grounded reasoning)**: 모든 추천은 실제 그래프 경로/기억/문서로 역추적 가능해야 하며 환각 근거를 금지한다.
4. **사용자 격리 불변식**: 개인 기억·선호 그래프는 항상 `user_id` 스코프를 강제하고, 전역 지식(성분·제품)과 물리적으로 분리 질의한다.
5. **점진 확장 스키마**: 그래프는 코어 온톨로지 고정 + LLM 제안 관계 점진 승인으로 데이터 품질과 유연성을 양립한다.

### Decision Drivers (Top 3)
1. **추천 정확도/안전성** — 회피 성분 미포함, 근거 정합성(하드 제약).
2. **응답 지연** — 대화형 UX라 턴당 지연이 핵심 품질 지표.
3. **운영 단순성** — 단일 팀/개인 프로젝트 상정, 인프라 최소화.

### Viable Options

**Option A — 단일 Postgres(AGE+pgvector) + 비동기 워커 (권장)**
- Pros: 조인/트랜잭션 일관성, 인프라 최소, 스펙과 정합, 그래프+벡터 동일 트랜잭션 경계.
- Cons: AGE+pgvector 동시 확장 운영 성숙도 부담, 그래프 쿼리 성능 튜닝 필요.

**Option B — Postgres(pgvector) + 별도 그래프DB(Neo4j)**
- Pros: 그래프 쿼리 성능·생태계 성숙.
- Cons: 이중 저장소 동기화·트랜잭션 경계 붕괴, 스펙(AGE 명시) 위배, 운영 복잡도 증가.

**Invalidation rationale (B 기각):** 주 기각 사유는 **기술적** 근거 — 이중 저장소 동기화 비용, 크로스스토어 트랜잭션 상실, 운영 표면 증가가 운영 단순성 driver와 충돌한다. 특히 전역 성분·제품 그래프가 read-mostly 배치 적재라 단일 저장소 일관성 이점이 실질적이다. 스펙의 AGE 명시는 **부차적 tiebreaker**로만 작용(주 근거 아님).

---

## Proposed Architecture & Module Layout
그린필드. 제안 레이아웃(언어 무관 논리 구조; 구현 언어는 후속 결정, 권장 Python/FastAPI 또는 Node):

```
/db
  migrations/                 # CREATE EXTENSION age, vector; 테이블/그래프 초기화
  schema.sql                  # products, ingredients, ingredient_aliases, memories, users
/ingest                       # 배치 ETL (AC-D1~D3)
  coos_crawler.*              # coos.kr/ingredients 크롤러 (robots/ToS 준수, rate-limit, 캐시) → 성분
  cosing_loader.*             # (선택) INCI 매핑 보강
  obf_loader.*                # (선택/후속) Open Beauty Facts 제품 덤프
  normalize.*                 # canonical key(INCI 우선, 없으면 한글명) dedup
  embed.*                     # (다국어) 임베딩 → pgvector
  graph_build.*               # AGE 엣지(Product-CONTAINS->Ingredient 등)
/retrieval                    # 읽기 경로 (동기)
  vector_search.*             # pgvector 유사도
  graph_traverse.*            # AGE Cypher 다단계 순회 (AC-G2)
  memory_rank.*               # effective_weight 순위 (AC-M2)
  context_assembler.*         # 3소스 통합 컨텍스트
/memory                       # 쓰기 경로 (비동기 워커)
  extractor.*                 # 대화→후보 fact (LLM)
  crud_resolver.*             # add/update/delete/no-op (LLM) (AC-M1,M4)
  weight_updater.*            # 빈도/λ 감쇠 재계산
  worker.*                    # 턴별 작업 큐 소비자 (AC-M6)
/chat
  funnel.*                    # 다중 턴 퍼널 상태 (AC-R5)
  recommender.*               # 컨텍스트+LLM → 추천+근거 (AC-R1~R4)
  llm_provider.*              # 프로바이더 추상화 (기본 Claude API)
/eval
  memory_tests.*              # AC-M1~M6
  recommendation_judge.*      # LLM-as-judge (AC-R1), 제약준수(AC-R2)
```

## Data Model (핵심)
- `users(user_id, ...)`
- `ingredients(inci_key PK, function, restrictions, embedding vector(D))` — D = 임베딩 차원(아래 고정 결정)
- `ingredient_aliases(inci_key FK, alias, locale)` — 한글명 등
- `concerns(concern_id PK, name)` / `skin_types(skin_type_id PK, name)` — 관계형 홈 보유(그래프 노드와 미러)
- `products(product_id PK, name, brand, category, embedding vector(D))`
- `product_ingredients(product_id, inci_key)` — **관계형 테이블이 진실원(source of truth)**, AGE CONTAINS 엣지는 이로부터 재빌드되는 파생 프로젝션. 증분 갱신 시 테이블 먼저 커밋 후 엣지 재생성.
- `memories(id, user_id, content, embedding vector(Dm), weight, frequency, last_seen, created_at, deleted_at)` — user_id 인덱스, **RLS 활성화**(memories는 테이블이므로 RLS 적용 가능), soft-delete.
- **임베딩 공간 분리**: 문서(제품/성분) 임베딩과 memory 임베딩은 별도 테이블·별도 인덱스. 모델/차원은 각각 DDL에서 고정(문서 D, memory Dm). 임베딩 모델·차원은 착수 초기 **되돌리기 어려운 결정으로 확정**(변경 시 전량 재임베딩+마이그레이션), LLM 대화 프로바이더 결정과 분리.
- AGE 그래프: 전역 지식 그래프(Product/Ingredient/Concern/SkinType) + 사용자별 서브그래프(User-PREFERS/AVOIDS/HAS_CONCERN). 모든 사용자 엣지에 `user_scope` 프로퍼티 필수.

## Isolation Strategy (AC-M5, 확정)
RLS는 테이블에만 적용되고 **AGE 그래프에는 적용 불가**하므로 이원 전략을 확정한다:
- **`memories` 등 관계형 사용자 데이터**: PostgreSQL RLS 정책으로 `user_id` 강제(DB 백스톱).
- **AGE 사용자 서브그래프**: 모든 사용자 대상 Cypher는 **단일 choke-point 함수**를 통해서만 실행하며, 이 함수가 `user_scope = :user_id` 필터를 주입한다. 앱 레벨 불변식이며 우회 경로를 코드에서 차단.
- (선택 강화) 사용자별 preference 서브그래프를 user별 AGE graph namespace로 물리 분리 → 필터 누락 시 leak 대신 fail-closed.
- **누수 테스트(AC-M5 검증)**: 사용자 A로 사용자 B의 memory/서브그래프 조회를 시도해 **0건**임을 단언하는 테스트를 필수 추가.

## Implementation Steps
1. **DB 부트스트랩**: Postgres + `age`, `vector` 확장, 마이그레이션, 코어 그래프 온톨로지 노드/엣지 라벨 정의. (`/db`)
2. **Ingest ETL**: coos.kr/ingredients 크롤링(robots·ToS 확인, rate-limit, 캐시, 출처메타) → ingredients; (선택) CosIng으로 INCI 보강, OBF로 products; canonical key dedup; 임베딩 적재; AGE 엣지 구축. (`/ingest`, AC-D1~D3)
3. **Retrieval 레이어**: pgvector 유사도 + AGE 다단계 순회 + memory effective_weight 순위 + 컨텍스트 통합. **동기 읽기 경로 지연 예산 p95 < 300ms(그래프 순회 포함) 목표**(Driver #2). (`/retrieval`, AC-G1~G2, AC-M2)
   - **게이팅 스파이크**: 착수 초기, **목표 규모(성분 N·제품 M·엣지 K, coos.kr 실측으로 확정)의 대표 코퍼스**에서 AC-G2의 2~3 hop 쿼리 패턴 믹스로 벤치마크. "현실 규모"=대표 샘플이 아닌 예상 프로덕션 코퍼스 크기로 정의.
   - **폴백 트리거(명시)**: 목표 규모에서 게이팅 p95 > 300ms이면 핫 추천 경로를 관계형 materialized-adjacency(사전계산 인접 테이블) SQL로 전환. 단일 저장소 유지하며 AGE 플래너 우회.
   - **adjacency 재빌드**: 인접 테이블은 AGE 엣지와 동일하게 `product_ingredients` 커밋 시 재생성되는 파생 프로젝션(진실원=관계형 테이블).
4. **Memory 비동기 파이프라인**: 작업 큐 + 워커; extractor→crud_resolver(add/update/delete/no-op)→weight_updater. 일상정보 필터. **큐는 user_id로 파티션(또는 per-user advisory lock)해 사용자별 순서 적용 보장**; 잡 실패 시 재시도·dead-letter·idempotency-key로 부분 적용 방지; delete는 soft-delete+감사로그. 크로스턴 staleness 완화: **retrieval 전 해당 user의 pending write 잡이 drain됐는지 확인**(단일 메커니즘 확정; read-after-write 대안은 채택 안 함). (`/memory`, AC-M1,M3,M4,M6)
5. **사용자 격리(확정)**: memories는 RLS, AGE 서브그래프는 choke-point 함수로 `user_scope` 강제. 크로스유저 누수 0건 테스트 추가. (AC-M5, 위 Isolation Strategy 참조)
6. **Chat 퍼널 + Recommender**: 다중 턴 상태, 컨텍스트+LLM 추천+근거 생성, 프로바이더 추상화. (`/chat`, AC-R1~R5)
7. **Graph 하이브리드 확장**: LLM 신규 관계 제안 → 승인 → 스키마 점진 추가. (AC-G3)
8. **Eval 하니스**: 기억 테스트 + 추천 LLM-judge + 제약준수 자동 검증. (`/eval`, AC-M*, AC-R1~R4)

## Acceptance Criteria
스펙 AC-D1~D3, AC-M1~M6, AC-G1~G3, AC-R1~R5 상속(스펙 파일 참조). 아래 정량 임계값으로 모호 기준을 operationalize:

**Operationalized Thresholds**
- **AC-R1(만족도)**: LLM-as-judge 루브릭(정확성·안전성·근거성·톤 4축, 각 1~5) 정의, 100개 시나리오 평균 ≥ 4.0을 baseline으로 고정. (룩업이 아닌 고정 목표치.)
- **AC-M6(무지연)**: 동기 응답 경로가 memory-write 잡보다 **먼저** 반환됨을 단언 + 동기 경로 p95 ≤ 300ms.
- **AC-M3(중요도 분류)**: 라벨링된 도메인 vs 일상 발화 ~50개 세트에서 저장/미저장 **precision ≥ 0.9, recall ≥ 0.8**.
- **AC-D3/데이터 스케일**: 벤치마크·폴백 판단 기준 목표 규모를 명시(coos.kr 예상 코퍼스 기준: 성분 N개, 제품 M개, 엣지 K개 — 착수 시 실측 확정).

## Risks and Mitigations
| Risk | Mitigation |
|------|-----------|
| AGE+pgvector 동시 확장 운영 미성숙/버전 충돌 | 초기 스파이크로 확장 호환 버전 고정, docker-compose로 재현 가능 환경 |
| 그래프 다단계 순회 성능 저하(AGE 플래너/인덱스 미성숙) | p95<300ms 지연 예산 + 게이팅 벤치마크, 순회 depth 상한, 인덱스/라벨 최적화, 핫패스 캐시, 미달 시 materialized-adjacency SQL 폴백 |
| 비동기 기억 반영 지연(현재 턴+크로스턴) | 현재 턴 대화 버퍼 즉시 포함 + 사용자별 큐 순서 보장 + 직전 턴 pending writes drained 확인/재조정 |
| 사용자별 기억 write 순서/동시성 붕괴 | 큐를 user_id 파티션 또는 per-user advisory lock으로 직렬화, idempotency-key, dead-letter |
| LLM CRUD 오판(잘못된 delete) | delete는 soft-delete + 감사로그, 모순 판정에 근거 사실 인용 요구 |
| AGE 그래프 격리 DB 백스톱 부재 | choke-point 함수 강제 user_scope 필터 + (선택) user별 graph namespace fail-closed + 크로스유저 누수 0건 테스트 |
| coos.kr 크롤링 ToS/법적 리스크(주 소스 단일실패점) | **결정 게이트(빌드 전)**: coos.kr robots/ToS가 자동수집 허용 여부 확인. 불허 시 CosIng(INCI) + Open Beauty Facts(ODbL) + 식약처/공공데이터포털을 (선택)에서 **확약 주 소스로 승격**(스펙 Round 10에서 이미 승인된 공개 소스). rate-limit+캐시, 출처·수집일시 메타 |
| 크롤 소스 구조 변경으로 파서 파손 | 파서 스키마 검증 + 실패 알림, 스냅샷 캐시로 재처리 |
| 성분명 다국어 매칭 오류 | INCI를 canonical key로 강제, alias는 보조 검색만 |

## Verification Steps
1. `db/migrations` 적용 후 `\dx`로 age·vector 확장 존재 확인.
2. Ingest 후 products/ingredients row count > 0, INCI dedup 유효성, alias 매핑 샘플 검증(AC-D3).
3. Retrieval 단위테스트: 알려진 성분→제품 유사도/그래프 경로 반환(AC-G1,G2).
4. Memory 시나리오 테스트: 모순(AC-M1)/중복 no-op·신규 add(AC-M4)/weight 순위(AC-M2)/**크로스유저 누수 0건(AC-M5)**/비동기 무지연·순서보장(AC-M6). AGE 2~3 hop 게이팅 벤치마크 p95<300ms 확인.
6. **AC-D2 검증**: 알려진 성분 1개로 그를 포함하는 제품 목록이 전역 지식(관계형/그래프)에서 반환됨을 단언.
7. **AC-M3 검증**: 라벨링 발화 세트(도메인 vs 일상 ~50개)로 저장/미저장 precision≥0.9, recall≥0.8 측정.
8. **AC-G3 검증**: LLM이 제안한 신규 관계를 승인 플로우에 투입 → 스키마에 실제 추가됨을 단언(하이브리드 확장).
9. **AC-R5 검증**: 스크립트 기반 다중 턴 세션이 N턴 내 구체 제품명+근거로 종료됨을 단언(퍼널 완주).
5. Recommendation eval: 회피성분 0건 포함(AC-R2), 근거-경로 정합(AC-R3), 기억 유/무 사용자 결과 차이(AC-R4), LLM-judge 기준선(AC-R1).

## ADR

**Decision:** 단일 PostgreSQL에 Apache AGE + pgvector를 얹은 Option A(A-hardened)를 채택한다. 세 컨텍스트 소스(문서/기억/그래프)를 한 저장소에 두고, 기억 쓰기는 사용자별 직렬화된 비동기 워커로 처리한다.

**Drivers:** (1) 추천 정확도/안전성(회피성분·근거정합, 하드 제약), (2) 응답 지연(대화형 UX), (3) 운영 단순성(개인/소규모 팀).

**Alternatives considered:**
- Option B — Postgres(pgvector) + 전용 그래프DB(Neo4j): 다단계 순회 성능·생태계 우위. 그러나 이중 저장소 동기화, 크로스스토어 트랜잭션 상실, 스펙의 AGE 명시 위배, 운영 복잡도 증가.

**Why chosen:** 스펙이 AGE를 명시하고, 전역 성분·제품 그래프가 read-mostly 배치 적재라 단일 저장소 일관성 이점이 크다. Architect 안티테제(AGE는 다단계 성능이 약하고 그래프 격리를 DB로 강제 불가)는 (a) 지연 예산+게이팅 벤치+SQL 폴백, (b) choke-point 격리+누수 테스트, (c) 사용자별 큐 직렬화로 무력화한다 → A-hardened.

**Consequences:**
- (+) 인프라·백업 단일 표면, 조인/트랜잭션 일관성.
- (−) AGE 그래프 격리는 앱 레벨 규율 영구 필요(choke-point), 임베딩 차원 DDL 고정으로 모델 교체 비용 큼, 착수 전 성능 스파이크 필요.

**Follow-ups:**
1. 임베딩 모델·차원(D, Dm) 확정(착수 초기, 되돌리기 어려움). 후보: 다국어(KO+INCI-EN) 지원 모델(예: multilingual-e5, BGE-m3 계열) — 착수 시 벤치 후 고정.
2. AGE 2~3 hop 게이팅 벤치마크 수행 후 빌드 진입 판단(목표 규모 실측 확정).
3. LLM 대화 프로바이더 확정(기본 Claude API, 추상화 유지).
4. choke-point 격리 함수 구현 시 `SECURITY DEFINER` 권한 경계 검토(권한 상승 표면) + 크로스유저 누수 테스트.
5. ETL/마이그레이션 실패 복구: 중간 실패 시 롤백/재개 전략(idempotency는 memory 큐뿐 아니라 ETL 로드에도 적용).
6. coos.kr 법적 게이트 통과 여부 확인 후 데이터 소스 확정(불허 시 공개소스 승격).

## Changelog (Architect 반영)
- 격리 전략을 "가능시 RLS"에서 확정(memories RLS + AGE choke-point + 누수 테스트)으로 강화 (Rec 1).
- 기억 큐 사용자별 직렬화 + retry/dead-letter/idempotency + 크로스턴 staleness 완화 추가 (Rec 2).
- AGE 지연 예산(p95<300ms) + 게이팅 벤치 + materialized-adjacency SQL 폴백 추가 (Rec 3).
- 임베딩 모델·차원 조기 고정, 문서/기억 임베딩 공간 분리 명시 (Rec 4).
- product_ingredients↔AGE 이중쓰기 진실원(관계형=truth, AGE=파생) 명시 (Rec 5).
- Concern/SkinType 관계형 홈 추가 (Rec 6).
- ADR를 지금 확정 (Rec 7).
- 성분 데이터 주 소스를 coos.kr 크롤링으로 스왑(ToS/robots·rate-limit·캐시 리스크 완화) — 사용자 지시 반영.

## Changelog (Critic 반영)
- 미검증 AC 4개(D2/M3/G3/R5)에 대응 검증 단계 추가 (Major 1).
- AGE 게이팅 벤치 목표 규모 정량화 + 폴백 트리거(p95>300ms) + adjacency 재빌드 정책 명시 (Major 2).
- coos.kr 법적 단일실패점 → 빌드 전 결정 게이트 + 공개소스 확약 폴백 (Major 3).
- 모호 AC(R1 루브릭+baseline 4.0, M6 동기경로 p95≤300ms, M3 precision≥0.9/recall≥0.8) operationalize (Major 4).
- Option B 기각을 기술 근거 주도로 재서술, 스펙 명시는 tiebreaker로 강등 (Minor 1).
- 임베딩 후보 모델 제시, choke-point SECURITY DEFINER 검토·ETL 롤백 follow-up 추가 (Minor 2/3).
- 크로스턴 staleness 메커니즘을 "pending writes drained" 단일안으로 확정.
