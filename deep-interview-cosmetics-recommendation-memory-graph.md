# Deep Interview Spec: 기억·문서·관계그래프 기반 화장품 추천 대화 시스템

## Metadata
- Interview ID: ci-cosmetics-rec-001
- Rounds: 10 (+ Round 0 topology gate)
- Final Ambiguity Score: 15%
- Type: greenfield
- Generated: 2026-07-02
- Threshold: 0.2
- Threshold Source: default
- Initial Context Summarized: no
- Status: PASSED

## Clarity Breakdown
| Dimension | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Goal Clarity | 0.85 | 0.40 | 0.340 |
| Constraint Clarity | 0.85 | 0.30 | 0.255 |
| Success Criteria | 0.85 | 0.30 | 0.255 |
| **Total Clarity** | | | **0.850** |
| **Ambiguity** | | | **0.150 (15%)** |

## Topology
| Component | Status | Description | Coverage / Deferral Note |
|-----------|--------|-------------|--------------------------|
| Documents (RAG) | active | 성분/제품 문서를 pgvector 임베딩으로 저장·유사도 검색 | 실제 공개 데이터셋 기반, 전역 공유(AC-D1~D2) |
| Memory (기억) | active | LLM 사실 판단 CRUD + 빈도/최근성 weight 우선순위 검색 | add/update/delete/no-op + effective_weight 공식, 비동기 처리(AC-M1~M6) |
| Graph (관계) | active | Apache AGE 엔티티+연결동사, 다단계 추론 | 하이브리드 스키마, 사용자별 격리(AC-G1~G3) |
| Chat/추천 | active | 사용자 대화·화장품 추천 (다중 턴 퍼널) | 성분/조언→구체 제품+근거, 추천 품질 4기준(AC-R1~R4) |

*Round 0에서 별도로 제안됐던 "가중치·검색 엔진"은 사용자 확인에 따라 Memory 컴포넌트의 우선순위 판단 기준으로 병합됨.*

## Goal
로그인한 여러 사용자가 각자 개인화된 대화형 화장품 추천을 받는 시스템을 구축한다. 시스템은 세 가지 컨텍스트 소스를 결합한다: (1) 실제 공개 데이터셋에서 적재한 전역 공유 **문서**(성분·제품, pgvector 유사도 검색), (2) 사용자별로 격리된 **기억**(LLM이 중요 사실만 선별해 add/update/delete/no-op으로 관리하고, 빈도·최근성 기반 effective_weight로 우선순위화), (3) 사용자별로 격리된 **관계 그래프**(Apache AGE, 코어 고정 + LLM 확장 하이브리드 스키마). 추천은 다중 턴 대화 퍼널로, 성분/카테고리 조언에서 시작해 대화로 좁혀 최종적으로 구체 제품명과 근거를 제시하며, 다단계 그래프 순회(예: 민감성→성분 회피→해당 성분 포함 제품 제외→대체 성분 추천)를 추천의 핵심 추론 방식으로 사용한다.

## Constraints
- **스택**: PostgreSQL + Apache AGE(그래프) + pgvector(임베딩). 단일 Postgres 인스턴스에 세 확장 공존.
- **사용자 모델**: 다중 사용자. 모든 memory fact 및 graph edge에 `user_id` 스코핑, 사용자 간 기억/그래프 완전 격리.
- **공유 범위**: 성분·제품 문서 및 성분-제품 관계 지식은 전역 공유. 개인 기억·개인 선호 그래프만 사용자별 격리.
- **문서 출처**: 실제 화장품 성분/제품 데이터 (합성/예시 데이터 아님). 성분은 coos.kr 크롤링 주 소스(robots.txt·ToS 준수, rate-limit, 캐시). 화해·EWG 등 다른 독점 소스는 무단 크롤링 지양.
- **언어/로케일**: 한국어 대화 + INCI 영문명을 canonical key로 저장하고 한글 성분명은 alias로 부착. 다국어 임베딩 모델 사용.
- **기억 CRUD 정책**: 신규 사실→add, 기존 사실의 값 변경→update(동일 슬롯 새 값), 사실 철회/무효→delete(대체값 없이 슬롯 소멸), 중복 사실→no-op. 중요도 판단·CRUD 결정은 LLM이 수행.
- **일상/사소 정보 제외**: "오늘 피곤해" 같은 일상적·비화장품 정보는 기억에 저장하지 않음.
- **weight 공식**: `effective_weight = weight × exp(-λ × days_since_last_seen)`, λ=0.02 기본값(도메인별 조정 가능). base `weight`는 언급 빈도로 증가.
- **기억 쓰기 타이밍**: 응답 직후 **비동기 배치** 처리(권장안 채택). 응답은 즉시 반환, 백그라운드 잡이 fact 추출→유사도 매칭→LLM add/update/delete/no-op→weight·모순 재정리 수행. 다중 사용자 대비 턴별 작업 큐.
- **그래프 스키마**: 하이브리드. 코어 노드(User, Product, Ingredient, Concern, SkinType) + 코어 엣지(CONTAINS, TREATS, AVOIDS, PREFERS, HAS_CONCERN) 고정, LLM이 새 관계 제안 시 점진 확장.

## Non-Goals
- 화장품 전자상거래/결제/재고 기능 없음 (추천만).
- 일상적·비도메인 대화 내용의 기억 저장 없음.
- (초기) 정교한 다요인 weight 모델 없음 — 지수 시간감쇠 단일 공식으로 시작.
- (초기) 완전 개방형 그래프 스키마 아님 — 코어 고정 기반 하이브리드.

## Acceptance Criteria
**Documents (RAG)**
- [ ] AC-D1: 공개 데이터셋을 임포트해 제품·성분 문서가 pgvector 임베딩으로 저장되고, 질의 시 유사도 상위 문서가 반환된다.
- [ ] AC-D2: 성분-제품 관계가 전역 지식으로 조회 가능하다.
- [ ] AC-D3: coos.kr/ingredients 성분 데이터를 (robots.txt·ToS 준수·rate-limit·캐시 하에) 크롤링해 canonical key(INCI 있으면 INCI, 없으면 한글명)로 정규화·중복제거 적재하고, 출처·수집일시 메타가 기록된다.

**Memory (기억)**
- [ ] AC-M1: 같은 속성의 값 변경("피부타입 건성→복합성")은 **update**로 최신 값만 남기고, 사실 자체가 대체값 없이 무효화되는 철회("임신 중 레티놀 회피"→"출산함")는 **delete**로 제거한다. (update=동일 슬롯 재값, delete=슬롯 소멸)
- [ ] AC-M2: 자주·최근 언급된 사실이 오래된·드문 사실보다 effective_weight 검색 상위에 온다(공식 순서와 일치).
- [ ] AC-M3: 중요도 분류가 정확하다 — 일상·사소 정보는 저장 안 하고, 피부·선호 등 중요 사실만 저장한다.
- [ ] AC-M4: 신규=add, 값 변경=update, 철회/무효=delete, 중복=no-op 정책이 각 케이스에서 올바르게 동작한다.
- [ ] AC-M5: 모든 fact가 `user_id`로 격리되어 다른 사용자 기억이 조회되지 않는다.
- [ ] AC-M6: 기억 쓰기가 응답 지연을 유발하지 않는다(비동기 처리 확인).

**Graph (관계)**
- [ ] AC-G1: 코어 노드/엣지 스키마로 엔티티·연결동사가 저장되고 Cypher(AGE)로 순회 가능하다.
- [ ] AC-G2: 다단계 추론 경로(2~3 hop)로 추천이 도출된다(예: 민감성→회피성분→성분포함 제품 제외→대체 추천).
- [ ] AC-G3: LLM이 제안한 신규 관계가 스키마에 점진 추가된다(하이브리드 확장).

**Chat/추천**
- [ ] AC-R1: 사용자 만족도 — LLM-as-judge 답변 평가가 기준선 이상.
- [ ] AC-R2: 제약조건 준수 — 사용자가 회피한 성분/모순된 선호가 추천에 절대 포함되지 않는다.
- [ ] AC-R3: 근거 설명 정합성 — 추천 이유가 실제 그래프 경로/기억과 일치하고 환각 근거가 없다.
- [ ] AC-R4: 기억 반영도 — 저장된 개인 기억이 추천에 실제 반영된다(기억 없는 사용자와 다른 결과).
- [ ] AC-R5: 다중 턴 퍼널 — 성분/조언에서 시작해 대화로 좁혀 구체 제품명+근거에 도달한다.

## Assumptions Exposed & Resolved
| Assumption | Challenge | Resolution |
|------------|-----------|------------|
| 가중치 엔진이 별도 최상위 컴포넌트 | Round 0 토폴로지 확인 | Memory의 우선순위 판단 기준으로 병합(4 컴포넌트) |
| "추천"의 결과물 형태가 자명함 | Round 1 Goal 질문 | 다중 턴 퍼널: 성분/조언→구체 제품+근거 |
| 데이터는 생성/예시로 충분 | Round 2 Constraint 질문 | 실제 공개 데이터셋 사용 |
| Apache AGE 그래프가 반드시 필요 | Round 4 Contrarian: vector+기억으로 충분하지 않나? | 다단계 추론이 핵심 → 그래프 유지 정당화 |
| 단일 사용자로 가정 | Round 5 Constraint 질문 | 다중 사용자 + 개인 기억 격리 |
| 정교한 weight 공식 필요 | Round 6 Simplifier: 최소 버전은? | 지수 시간감쇠 단일 공식(λ=0.02)으로 시작 |
| 기억 쓰기 타이밍 자명 | Round 7 Constraint 질문 | 응답 직후 비동기 배치(권장안 채택) |
| 그래프 스키마 고정 vs 개방 | Round 8 Goal 질문 | 하이브리드(코어 고정 + LLM 확장) |
| 추천 품질 판정이 주관적이라 불가 | Round 9 Criteria 질문 | 4개 테스트 가능 기준(만족도·제약준수·근거정합·기억반영) |

## Technical Context (greenfield)
- **DB**: PostgreSQL 단일 인스턴스. 확장: `age`(그래프), `vector`(pgvector 임베딩).
- **그래프**: Apache AGE의 Cypher로 코어 온톨로지 순회, 다단계 추론.
- **임베딩**: pgvector로 문서(성분/제품) 및 memory fact 유사도 검색. HNSW/IVFFlat 인덱스 검토.
- **기억 파이프라인**: 비동기 워커(작업 큐) — fact 추출(LLM) → 유사도 매칭(pgvector) → CRUD 결정(LLM) → weight/모순 재정리.
- **데이터 수집(Data Acquisition)**:
  - 성분 사전(주 소스): **coos.kr/ingredients** 크롤링 (한글 화장품 성분 사전). 크롤링 전 `robots.txt`·이용약관 확인 필수, 공식 API 있으면 우선, rate-limit(1~2 req/s)+로컬 캐시, 출처·수집일시 메타 저장. 상업적 재배포는 별도 허가 검토.
  - 조인 키: coos.kr이 INCI 영문명을 노출하면 canonical key로 사용, 없으면 한글 성분명을 primary key로 두고 정규화·중복제거.
  - 성분 보강(선택): **CosIng**(INCI·규제) / **PubChem**(화학 속성)로 INCI 매핑 보강.
  - 제품 레벨(선택/후속): **Open Beauty Facts**(ODbL 덤프/API, 한국 제품 포함) 등 공식 소스.
  - ETL: 크롤링/다운로드 → canonical 스키마 정규화 → 성분키 기준 dedup → (다국어) 임베딩 → pgvector 적재 → AGE 그래프 엣지(Product-CONTAINS→Ingredient, Ingredient-TREATS→Concern) 구축.
- **미확정(구현 기본값 처리)**: LLM 프로바이더(권장: Claude API 기본, 교체 가능하도록 추상화). 아키텍처 비블로킹이며 구현 단계 기본값으로 진행.

## Ontology (Key Entities) — 최종 라운드
| Entity | Type | Fields | Relationships |
|--------|------|--------|---------------|
| User | core domain | user_id, skin_type, concerns, preferences | HAS_CONCERN→Concern, PREFERS/AVOIDS→Ingredient, (owns) Memory/Graph |
| Product | core domain | name, category, brand | CONTAINS→Ingredient |
| Ingredient | core domain | name(EN/KO), effect | TREATS→Concern, (contained in) Product |
| Concern | core domain | name (예: 건조, 민감, 트러블) | (treated by) Ingredient, (had by) User |
| SkinType | core domain | name (지성/건성/복합/민감성) | (of) User |
| Memory/Fact | core domain | user_id, content, weight, last_seen, frequency | (belongs to) User |
| Relationship (Edge) | core domain | subject, verb, object, user_scope | 엔티티 연결(코어+확장 동사) |
| Recommendation | supporting | products[], rationale, reasoning_path | derived from Graph+Memory+Docs |
| Conversation | supporting | turns[], user_id, session | (produces) Memory/Fact |

## Ontology Convergence
| Round | Entity Count | New | Changed | Stable | Stability Ratio |
|-------|-------------|-----|---------|--------|----------------|
| 1 | 6 | 6 | - | - | N/A |
| 2 | 6 | 0 | 0 | 6 | 100% |
| 3 | 6 | 0 | 0 | 6 | 100% |
| 4 | 7 | 1 (Relationship) | 0 | 6 | 86% |
| 5 | 7 | 0 | 0 | 7 | 100% |
| 6 | 7 | 0 | 0 | 7 | 100% |
| 7 | 7 | 0 | 0 | 7 | 100% |
| 8 | 9 | 2 (Concern, SkinType) | 0 | 7 | 78% |
| 9 | 9 | 0 | 0 | 9 | 100% |
| 10 | 9 | 0 | 0 | 9 | 100% |

## Interview Transcript
<details>
<summary>Full Q&A (Round 0 + 9 rounds)</summary>

### Round 0 — Topology
**Q:** 5개 최상위 컴포넌트(문서/기억/그래프/가중치엔진/대화)가 맞는가?
**A:** "가중치 판단은 기억 관리에서의 우선 순위 판단 기준이야" → 가중치 엔진을 Memory로 병합, 4 컴포넌트 확정.

### Round 1 — Chat/추천 Goal
**Q:** '추천'의 결과물은 구체적으로 어떤 모습인가? ('건조한 피부 토너 추천해줘' 시 무엇을 반환?)
**A:** 둘 다 (대화로 점진) — 성분/조언에서 시작해 구체 제품명까지.
**Ambiguity:** 73%

### Round 2 — Documents Constraint
**Q:** 성분/제품 문서는 어디서 오나? 실제 카탈로그 vs 생성 데이터?
**A:** 실제 공개 데이터셋.
**Ambiguity:** 65%

### Round 3 — Memory Success Criteria
**Q:** 기억 시스템이 '제대로 동작한다'를 어떻게 확인하나?
**A:** 모순 감지·정리, 가중치 우선순위 정확도, 중요도 분류 정확도, 추천 반영도 (전부).
**Ambiguity:** 53%

### Round 4 — Graph (Contrarian)
**Q:** AGE 그래프 없이 vector+기억 fact로 충분하지 않은가? 그래프 순회가 무엇을 가능하게 하나?
**A:** 다단계 추론이 핵심.
**Ambiguity:** 48%

### Round 5 — 사용자 범위 Constraint
**Q:** 단일/다중 사용자? 기억·그래프가 한 명 귀속인가 사용자별 독립인가?
**A:** 다중 + 개인기억 격리.
**Ambiguity:** 41%

### Round 6 — Memory weight (Simplifier)
**Q:** weight 공식 — 정교한 모델 필요 vs 단순 시작?
**A:** effective_weight = weight × exp(-λ × days_since_last_seen), λ=0.02.
**Ambiguity:** 35%

### Round 7 — 기억쓰기 타이밍 Constraint
**Q:** 기억 쓰기(add/update/delete)는 언제 일어나나?
**A:** 아직 미정 → 권장안(응답 직후 비동기 배치) 채택.
**Ambiguity:** 30%

### Round 8 — Graph 스키마 Goal
**Q:** 그래프 엔티티/연결동사를 고정 vs 개방으로?
**A:** 하이브리드(코어 고정 + 확장).
**Ambiguity:** 26%

### Round 9 — 추천 Success Criteria
**Q:** 추천 '잘 동작했다'를 객관적으로 어떻게 판정?
**A:** 사용자 만족도(LLM 평가), 제약조건 준수, 근거 설명 정합성, 기억 반영도 (전부).
**Ambiguity:** 19%

### Round 10 — 언어/데이터 수집 Constraint
**Q:** 대화 언어와 성분 데이터 로케일을 어떻게? (사용자 역질문: 실제 공개 데이터셋은 어떻게 가져올 건가?)
**A:** 권장안 채택 — Open Beauty Facts(제품, ODbL 덤프/API) + CosIng(성분, INCI) + 식약처/공공데이터포털(한글명) + PubChem(선택). INCI canonical key + 한글 alias, 한국어 대화 + 다국어 임베딩.
**Ambiguity:** 15% ✅

</details>
