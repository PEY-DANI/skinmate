# Deep Interview Spec: skinmate — 기억·지식·관계그래프 기반 대화형 화장품 추천

> ⚠️ Fresh-start 인터뷰: 사용자 요청에 따라 기존 spec/plan/schema는 참조하지 않고 백지에서 재수행했습니다.
>
> 📌 **사후 변경(인터뷰 이후 사용자 결정, 2026-07-06)** — 아래 트랜스크립트는 인터뷰 시점 기록이며, 합의 계획 단계에서 두 가지가 갱신되었습니다. 구현 기준은 [skinmate-consensus-plan.md](skinmate-consensus-plan.md)가 우선합니다.
> 1. **저장 타이밍: 비동기 → 동기.** R2/AC-S2의 "비동기 백그라운드 잡 + drain"을 철회하고, **동기 원자적 단일 트랜잭션**으로 확정(`write_jobs` 큐/워커/drain/dead-letter 제거). 단일 Postgres가 3-store 원자성을 이미 보장하므로 큐는 불필요 — 대가는 턴당 ~1–3s 지연, 교차턴 staleness 소멸. WriteJob 엔티티도 폐기.
> 2. **데이터 소스 확정.** 크롤 주 소스 = **coos.kr**(성분 canonical+한글명) + **Paula's Choice Beautypedia**(성분 문서+제품 제형 서술). `season_concerns`는 수동 시드.

## Metadata
- Interview ID: skinmate-fresh-001
- Rounds: 11 (+ Round 0 topology gate)
- Final Ambiguity Score: 16.5%
- Type: greenfield (fresh start)
- Generated: 2026-07-06
- Threshold: 0.2
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.82 | 0.40 | 0.328 |
| Constraint Clarity | 0.87 | 0.30 | 0.261 |
| Success Criteria | 0.82 | 0.30 | 0.246 |
| **Total Clarity** | | | **0.835** |
| **Ambiguity** | | | **0.165 (16.5%)** |

## Topology
| Component | Status | Description | Coverage / Note |
|-----------|--------|-------------|-----------------|
| ① Memory (기억) | active | 사용자별 개인 사실(피부상태, 안맞는/선호 성분·제품·제형·브랜드) 저장 + 빈도·최근성 weight 우선순위화 | LLM CRUD(R3), 지수감쇠 weight(R6), 비동기 원자적 쓰기(R2), 다중사용자 격리(R8) — AC-M* |
| ② Structured Knowledge (구조화 지식) | active | 성분(등급·효과·분류)·제품·성분-제품 관계를 관계형 테이블로 저장 | 실제 공개데이터/크롤링(R5), 성분 회피 하드필터(R11) — AC-D*, AC-R2 |
| ③ Document Embeddings (문서 RAG) | active | "피부관리 방식" 등 프로즈 문서를 임베딩으로 저장·유사도 검색 | pgvector, 제형 임베딩 근사(R10) — AC-D1 |
| ④ Relationship Graph (관계 그래프) | active | 계절→문제, 선호/회피, 문제→성분, 성분→성분 등 관계를 그래프 DB에 저장·순회 | Apache AGE, 2+ hop 다단계 순회가 추천 핵심(R4→R6) — AC-G* |
| ⑤ Storage Sync (저장 동기화) | active | 관계형+그래프+벡터 원자적 쓰기, 하나 실패 시 전체 롤백 | 단일 Postgres 단일 트랜잭션(R9), 비동기 백그라운드(R2) — AC-S* |
| ⑥ Chat/Recommendation (대화형 추천) | active | 과거 고민·선호 회상 + 현재 질문 이해 → 검색 → 답변 생성 | 적응형 산출물(R1), 4개 품질 AC(R7) — AC-R* |

*Round 0에서 사용자가 "성분·제품 지식"을 구조화 테이블 지식(②)과 문서 임베딩 RAG(③)로 분리 요청 → 6개 컴포넌트로 확정.*

## Goal
다중 사용자 각각에게 개인화된 **대화형 화장품 추천**을 제공하는 시스템을 구축한다. 시스템은 세 컨텍스트 소스를 결합한다: (1) 실제 공개 데이터/크롤링으로 적재한 **구조화 지식**(성분 등급·효과·분류, 제품, 성분-제품 관계)과 **문서 임베딩**(피부관리 방식 등 프로즈, pgvector 유사도 검색), (2) 사용자별 격리된 **기억**(LLM이 중요 사실만 add/update/delete/no-op으로 관리, `effective_weight = base_weight × exp(-λ × 경과일)`로 빈도·최근성 우선순위화), (3) 사용자별 격리된 **관계 그래프**(Apache AGE, 계절→문제·선호/회피·문제→성분·성분→성분 등, **2-hop 이상 다단계 순회**로 풍부한 근거 생성). 추천 산출물은 **적응형**이다 — 질문이 구체적(제형·보습 명시)이면 바로 구체 제품명 + 근거를 제시하고, 모호하면 성분/방향 조언에서 시작해 대화로 좁혀 최종 제품에 도달한다. 세 저장소 쓰기는 **단일 Postgres 단일 트랜잭션으로 원자적**이며 하나라도 실패하면 전체 롤백한다.

## Constraints
- **스택**: 단일 PostgreSQL 인스턴스 + `vector`(pgvector, 임베딩) + `age`(Apache AGE, 그래프) 확장 공존. (R9)
- **저장소 물리 구성**: 관계형·그래프·벡터가 모두 한 Postgres 안에 존재 → 원자성이 단일 트랜잭션으로 성립(분산 saga 불필요). (R9)
- **저장 원자성**: 3개 저장 영역(관계형·그래프·벡터)에 대한 쓰기는 원자적. 하나라도 실패 시 전체 롤백 + 재시도, N회 초과 시 dead-letter. (R2, 사용자 하드 요구)
- **저장 타이밍**: 기억/관계/문서 쓰기는 **비동기 백그라운드 잡**. 사용자 응답은 즉시 반환(대화형 UX 지연 최소화). 다음 턴 정합성은 다음 검색 전 해당 사용자의 밀린 쓰기 drain으로 보장. (R2)
- **기억 CRUD 정책**: LLM이 중요도 판단 + add(신규)/update(값 변경, 동일 슬롯 재값)/delete(철회·무효, 슬롯 소멸)/no-op(중복) 결정. 일상·비도메인 정보("오늘 피곤해")는 저장 안 함. (R3)
- **weight 공식**: `effective_weight = base_weight × exp(-λ × 경과일)`. `base_weight`는 언급 빈도로 증가, 조회 시 시간감쇠 계산. 파라미터 λ 하나로 시작. (R6)
- **사용자 모델**: 다중 사용자. 모든 memory fact와 사용자 graph edge에 `user_id` 스코프 강제, 사용자 간 기억·그래프 완전 격리. (R8)
- **관계 그래프**: 2-hop 이상 다단계 순회를 추천의 핵심 추론 방식으로 사용(예: 민감성→회피성분→그 성분 포함 제품 제외→대체 성분→대체 제품). 풍부한 근거 콘텐츠 생성 목적. (R4→R6)
- **데이터 출처**: 성분·제품 및 피부관리 문서는 실제 공개 데이터/크롤링 기반(합성/예시 아님). (R5)
- **제형 처리**: 제형(에멀전/오일/크림/젤/끈적임 등)은 별도 구조화 태그 없이 제품 설명 임베딩 유사도로 근사 처리(best-effort). (R10)
- **하드 제약 범위**: 회피 **성분**은 구조화 필터로 절대 0건 보장(하드). 회피 **제형**은 임베딩 랭킹 기반 best-effort(하드 보장 아님). (R11)

## Non-Goals
- 화장품 전자상거래/결제/재고 없음 (추천만).
- 일상·비도메인 대화 기억 저장 없음. (R3)
- 정교한 다요인 weight 모델 없음 — 단일 지수 시간감쇠로 시작. (R6)
- 제형에 대한 하드 0건 보장 없음 — best-effort 랭킹. (R11)
- 분산 트랜잭션/saga 없음 — 단일 Postgres 단일 트랜잭션으로 원자성 확보. (R9)

## Acceptance Criteria
**② Structured Knowledge / Documents**
- [ ] AC-D1: 실제 공개 데이터/크롤링으로 성분·제품·피부관리 문서를 적재하고, 질의 시 pgvector 유사도 상위 문서/제품이 반환된다.
- [ ] AC-D2: 성분-제품 관계가 조회 가능하다(알려진 성분 → 그를 포함하는 제품 목록).

**① Memory**
- [ ] AC-M1: 신규=add, 값 변경=update(동일 슬롯 최신값), 철회/무효=delete, 중복=no-op 정책이 각 케이스에서 올바르게 동작한다. (R3)
- [ ] AC-M2: 자주·최근 언급된 사실이 오래된·드문 사실보다 `effective_weight` 상위에 온다. (R6)
- [ ] AC-M3: 중요도 분류 정확 — 일상·사소 정보는 미저장, 피부·선호 등 중요 사실만 저장. (R3)
- [ ] AC-M4: **기억 반영도** — 같은 질문이라도 기억 있는 사용자와 없는 사용자의 추천 결과가 실제로 다르다. (R7)
- [ ] AC-M5: 모든 fact가 `user_id`로 격리 — 다른 사용자 기억 조회 0건. (R8)

**⑤ Storage Sync**
- [ ] AC-S1: 관계형·그래프·벡터 쓰기가 원자적 — 하나 실패 시 전체 롤백되어 부분 적용이 남지 않는다. (R2/R9)
- [ ] AC-S2: 저장은 비동기 — 사용자 응답 경로가 memory-write보다 먼저 반환된다. 다음 검색 전 밀린 쓰기 drain. (R2)

**④ Graph**
- [ ] AC-G1: 코어 관계가 그래프에 저장되고 Cypher(AGE)로 순회 가능하다.
- [ ] AC-G2: 2-hop 이상 다단계 순회로 추천이 도출되고, 순회 경로가 근거로 제시된다. (R4→R6)
- [ ] AC-G3: 사용자 서브그래프가 `user_id`로 격리 — 크로스유저 누수 0건. (R8)

**⑥ Chat/Recommendation**
- [ ] AC-R1: **적응형 산출물** — 구체 질문은 제품명+근거로 바로, 모호한 질문은 조언→대화 좁힘 퍼널로 최종 제품에 도달. (R1)
- [ ] AC-R2: **제약 준수(하드)** — 사용자가 회피한 **성분**이 추천에 절대 포함되지 않는다(0건, 구조화 필터). 제형은 best-effort. (R7/R11)
- [ ] AC-R3: **근거 정합성** — 추천 이유가 실제 그래프 경로/기억과 일치하고 환각 근거가 없다. (R7)
- [ ] AC-R4: 동기 시나리오("가을 건조, 오일 회피, 에멀전, 보습 확실") 완주 — 과거 고민·선호 회상 + 현재 질문 이해 → 검색 → 근거 기반 답변.

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| "성분·제품 지식"은 단일 컴포넌트 | Round 0 토폴로지 | 구조화 테이블(②)과 문서 임베딩 RAG(③)로 분리 → 6 컴포넌트 |
| "추천" 산출물 형태가 자명 | R1 Goal | 적응형(구체→제품+근거, 모호→조언 퍼널) |
| 저장 타이밍이 자명 | R2 Constraint | 비동기 + 원자적 백그라운드(응답 즉시, 실패 전체 롤백) |
| 모순 사실 처리·기억 판단이 애매 | R3 Goal | LLM add/update/delete/no-op + 중요도 필터 |
| 그래프 DB가 정말 필요한가? | R4 Contrarian: 관계형+벡터로 충분? | (초기 보류 추천) → **R6에서 사용자가 반전**, 2+ hop 순회가 추천 핵심이라 그래프 DB 도입 확정 |
| 데이터는 생성/예시로 충분 | R5 Constraint | 실제 공개 데이터/크롤링 |
| 정교한 weight 필요 | R6 Simplifier: 최소 버전? | 단일 지수 시간감쇠 `exp(-λ×경과일)` |
| 추천 품질 판정 불가(주관적) | R7 Criteria | 4개 테스트 가능 기준(제약준수·기억반영·근거정합·CRUD정확) |
| 단일 사용자로 가정 | R8 Constraint | 다중 사용자 + 완전 격리(누수 0건) |
| 원자적 롤백 = 분산 트랜잭션 필요? | R9 Constraint | 단일 Postgres(pgvector+AGE) → 단일 트랜잭션으로 원자성 |
| 제형이 하드 필터 속성 | R10/R11 | 제형=임베딩 근사(best-effort), 하드 0건은 성분만 |

## Technical Context (greenfield)
- **DB**: 단일 PostgreSQL. 확장: `vector`(pgvector), `age`(Apache AGE). 세 저장 영역이 한 인스턴스 → 단일 트랜잭션 원자성.
- **기억 파이프라인(비동기)**: 작업 큐 + 워커 — fact 추출(LLM) → 유사도 매칭(pgvector) → CRUD 결정(LLM add/update/delete/no-op) → weight/모순 재정리. 사용자별 직렬화, 재시도/dead-letter/idempotency, delete는 soft-delete+감사로그 권장.
- **검색(동기, 읽기 전용)**: pgvector 유사도 + AGE 2+ hop Cypher 순회 + memory `effective_weight` 순위 → 3소스 컨텍스트 통합.
- **격리**: memories 등 관계형은 RLS(`user_id`), AGE 사용자 서브그래프는 choke-point 함수로 `user_scope` 강제(RLS가 AGE에 적용 불가하므로 앱 레벨 불변식) + 크로스유저 누수 0건 테스트.
- **데이터 수집**: 성분·제품·피부관리 문서 실제 공개 소스 크롤링/적재(robots·ToS·rate-limit·캐시·출처메타). 성분 canonical key 정규화·중복제거.
- **미확정(구현 기본값)**: LLM 프로바이더(권장 Claude API, 추상화), 임베딩 모델·차원(다국어 KO+EN, 착수 초기 고정), λ 값, 크롤링 주 소스 확정.

## Ontology (Key Entities) — 최종 라운드
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| User | core domain | user_id, skin_type, concerns, preferences | HAS_CONCERN→Concern, PREFERS/AVOIDS→Ingredient·Formulation·Brand, (owns) Memory/Graph |
| Memory/Fact | core domain | user_id, content, fact_type, base_weight, frequency, last_seen | (belongs to) User |
| Ingredient | core domain | inci_key, name(KO/EN), grade, function, classification, embedding | TREATS/AGGRAVATES→Concern, HELPS/CONFLICTS→Ingredient, (in) Product |
| Product | core domain | name, brand, category, description, embedding | CONTAINS→Ingredient |
| Concern | core domain | name (건조·민감·트러블) | (treated by) Ingredient, (had by) User, (affected by) Season |
| SkinType | core domain | name (지성/건성/복합/민감) | (of) User |
| Season | supporting | name | AFFECTS→Concern |
| Formulation (제형) | supporting | name (에멀전/오일/크림/젤) | (임베딩 근사, 제품 설명에 내재) |
| Brand | supporting | name | (of) Product, PREFERS/AVOIDS by User |
| Relationship (Edge) | core domain | subject, verb, object, user_scope | 엔티티 연결(계절→문제, 문제→성분, 성분→성분 등) |
| Document | core domain | content, embedding, source | (피부관리 방식 등 프로즈 RAG) |
| Recommendation | supporting | products[], rationale, reasoning_path | derived from Graph+Memory+Docs |
| WriteJob | supporting | user_id, turn_id, payload, status, attempts | 비동기 원자적 기억 쓰기 |
| DataSource | external system | url, crawled_at | 성분·제품·문서 출처 |
| Conversation | supporting | turns[], user_id, funnel_state | (produces) Memory/Fact |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 12 | 12 | - | - | N/A |
| 2 | 13 | 1 (WriteJob) | 0 | 12 | 92% |
| 3 | 13 | 0 | 0 | 13 | 100% |
| 4 | 13 | 0 | 0 | 13 | 100% |
| 5 | 14 | 1 (DataSource) | 0 | 13 | 93% |
| 6 | 14 | 0 | 0 | 14 | 100% |
| 7 | 14 | 0 | 0 | 14 | 100% |
| 8 | 14 | 0 | 0 | 14 | 100% |
| 9 | 15 | 1 (Conversation) | 0 | 14 | 93% |
| 10 | 15 | 0 | 0 | 15 | 100% |
| 11 | 15 | 0 | 0 | 15 | 100% |

## Interview Transcript
<details>
<summary>Full Q&A (Round 0 + 11 rounds)</summary>

### Round 0 — Topology
**Q:** 최상위 컴포넌트 5개(기억/구조화지식/그래프/저장동기화/추천)가 맞나?
**A:** "2번인데, 성분·제품 지식을 테이블 저장(등급·효과·분류)과 문서 임베딩(피부관리 방식)으로 분리해줘" → 6 컴포넌트 확정.

### Round 1 — ⑥추천 Goal
**Q:** 추천 산출물이 구체적으로 어떤 모습인가? (한번에 제품명 vs 대화로 좁힘)
**A:** 상황에 따라 둘 다 (적응형).
**Ambiguity:** 75.5%

### Round 2 — ⑤저장 Constraint
**Q:** 3-store 쓰기가 언제 일어나야 하나? (동기 vs 비동기, 원자성 고정)
**A:** 명확히 안 정함 → 추천안(비동기+원자적 백그라운드) 채택.
**Ambiguity:** 69.5%

### Round 3 — ①기억 Goal
**Q:** 모순되는 말("예전엔 레티놀 안맞았는데 지금 괜찮아") 시 기억은? 무엇을 기억할 가치가 있나?
**A:** LLM이 add/update/delete/no-op 판단.
**Ambiguity:** 64%

### Round 4 — ④그래프 (Contrarian)
**Q:** 그래프 DB가 '그래프여야만 가능한 것'을 주나, 관계형+벡터로 충분한가?
**A:** 모르겠음 → 추천안(관계형+벡터 시작, 그래프 보류) 제시.
**Ambiguity:** 58.2%

### Round 5 — ②③ 데이터 출처 Constraint
**Q:** 성분/제품/문서는 어디서? 실제 공개 vs 직접 생성?
**A:** 실제 공개 데이터/크롤링.
**Ambiguity:** 53.4%

### Round 6 — ①weight (Simplifier)
**Q:** weight 최소 버전 공식? (정교 다요인 vs 단순 시간감쇠)
**A:** 단순 지수 시간감쇠. **+ "그래프 DB 넣어줘 — 2-hop 이상 관계까지 보고 풍부한 콘텐츠로 답변"** → R4 추천 반전, 그래프 DB 도입 확정, 저장소 3개 확정.
**Ambiguity:** 49.1%

### Round 7 — ⑥ Success Criteria
**Q:** '잘 동작한다'를 어떻게 확인? (복수 선택)
**A:** 제약준수(하드) + 기억반영도 + 근거정합성 + 기억 CRUD 정확도 (전부).
**Ambiguity:** 36.1%

### Round 8 — ①⑤ 격리 Constraint
**Q:** 단일 vs 다중 사용자? (온톨로지 수렴으로 Ontologist 재정의 생략)
**A:** 다중 사용자 + 완전 격리.
**Ambiguity:** 30.9%

### Round 9 — ⑤저장소 물리구성 Constraint
**Q:** 관계형·그래프·벡터 물리 배치? (단일 트랜잭션 vs 분산 saga)
**A:** 단일 Postgres + pgvector + AGE 확장.
**Ambiguity:** 25%

### Round 10 — ②⑥ 제형 Goal
**Q:** 제형(에멀전/오일/끈적임)을 어떻게 다루나?
**A:** 텍스트/임베딩으로 근사.
**Ambiguity:** 20.9%

### Round 11 — ⑥ 제약 정합 Criteria
**Q:** 제형이 임베딩 근사면 '회피 하드 0건'은 어디까지 적용?
**A:** 성분만 하드, 제형은 best-effort.
**Ambiguity:** 16.5% ✅

</details>
